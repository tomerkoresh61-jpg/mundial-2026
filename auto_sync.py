"""
auto_sync.py — Live sync engine for Mundial 2026
Polls api-football.com v3 for:
  • Upcoming fixtures (get_upcoming_fixtures)
  • Live match events: yellow/red cards, goals, AET detection
  • Lineup publication (~60–90 min before kickoff)

Called by telegram_bot._start_background_workers() as a daemon thread.
Also exports get_upcoming_fixtures() used by _show_upcoming().
"""

import os
import time
import logging
import unicodedata
import difflib
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [auto_sync] %(levelname)s %(message)s")
log = logging.getLogger("auto_sync")

# ── env ───────────────────────────────────────────────────────────────────────
API_KEY        = os.environ.get("API_FOOTBALL_KEY", "")
BOT_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER   = int(os.environ.get("ALLOWED_USER_ID", "0"))
LEAGUE_ID      = 1          # FIFA World Cup
SEASON         = 2026
LIVE_POLL_SEC  = 60         # poll live fixtures every 60 s
IDLE_POLL_SEC  = 300        # poll upcoming fixtures every 5 min when no live game
LINEUP_WINDOW  = 90         # minutes before KO to start polling for lineups
API_BASE       = "https://v3.football.api-sports.io"

# ── shared state (imported by mundial_2026 functions) ─────────────────────────
# Populated by this module; telegram_bot reads these for display.
_known_fixture_ids: set   = set()   # fixture IDs we've seen
_live_fixture_ids:  set   = set()   # currently live
_lineup_checked:    set   = set()   # fixture IDs where we already synced lineup
_sent_events:       set   = set()   # "fixture_id:event_type:player/team" dedup keys

# ── api-football helpers ──────────────────────────────────────────────────────

def _headers() -> dict:
    return {"x-apisports-key": API_KEY}


def _get(endpoint: str, params: dict) -> Optional[dict]:
    """GET with basic error handling; returns parsed JSON or None."""
    url = f"{API_BASE}/{endpoint}"
    try:
        r = requests.get(url, headers=_headers(), params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            log.warning("API errors: %s", data["errors"])
        return data
    except Exception as exc:
        log.error("API request failed (%s %s): %s", endpoint, params, exc)
        return None


# ── name normalisation ────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Lower-case, strip accents, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_ = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(ascii_.lower().split())


def _fuzzy_team(api_name: str, known_teams: list[str]) -> Optional[str]:
    norm_api = _norm(api_name)
    norm_map = {_norm(t): t for t in known_teams}
    # exact
    if norm_api in norm_map:
        return norm_map[norm_api]
    # close
    matches = difflib.get_close_matches(norm_api, norm_map.keys(), n=1, cutoff=0.75)
    return norm_map[matches[0]] if matches else None


def _fuzzy_player(api_name: str) -> Optional[str]:
    """Match api name against players known to mundial_2026."""
    try:
        from mundial_2026 import find_player
        return find_player(api_name)
    except Exception:
        return None


# ── Telegram notification ─────────────────────────────────────────────────────

def _notify(text: str) -> None:
    """Send a plain-text message to ALLOWED_USER via Bot API."""
    if not BOT_TOKEN or not ALLOWED_USER:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": ALLOWED_USER, "text": text,
                                 "parse_mode": "HTML"}, timeout=10)
    except Exception as exc:
        log.error("Telegram notify failed: %s", exc)


# ── fixture fetching ──────────────────────────────────────────────────────────

def get_upcoming_fixtures(days: int = 1) -> list[dict]:
    """
    Return a list of upcoming fixtures within `days` days.
    Each dict has keys: fixture_id, home, away, venue, stage, kickoff (datetime UTC),
                        status, home_score, away_score.
    """
    now   = datetime.now(timezone.utc)
    until = now + timedelta(days=days)
    date_from = now.strftime("%Y-%m-%d")
    date_to   = until.strftime("%Y-%m-%d")

    data = _get("fixtures", {
        "league": LEAGUE_ID,
        "season": SEASON,
        "from":   date_from,
        "to":     date_to,
        "timezone": "UTC",
    })
    if not data:
        return []

    result = []
    for item in data.get("response", []):
        fix  = item.get("fixture", {})
        teams = item.get("teams", {})
        venue = item.get("fixture", {}).get("venue", {}).get("name", "Neutral")
        goals = item.get("goals", {})
        score = item.get("score", {})
        ko_str = fix.get("date", "")
        try:
            ko = datetime.fromisoformat(ko_str.replace("Z", "+00:00"))
        except Exception:
            ko = now

        league_round = item.get("league", {}).get("round", "")
        stage = "group"
        lr = league_round.lower()
        if "round of 32"  in lr: stage = "r32"
        elif "round of 16" in lr: stage = "r16"
        elif "quarter"     in lr: stage = "qf"
        elif "semi"        in lr: stage = "sf"
        elif "final"       in lr: stage = "final"
        elif "third"       in lr: stage = "3rd"

        result.append({
            "fixture_id":  fix.get("id"),
            "home":        teams.get("home", {}).get("name", "?"),
            "away":        teams.get("away", {}).get("name", "?"),
            "venue":       venue,
            "stage":       stage,
            "kickoff":     ko,
            "status":      fix.get("status", {}).get("short", "NS"),
            "home_score":  goals.get("home"),
            "away_score":  goals.get("away"),
            "elapsed":     fix.get("status", {}).get("elapsed"),
        })
    result.sort(key=lambda x: x["kickoff"])
    return result


def _get_live_fixture_ids() -> list[int]:
    """Return IDs of currently live WC fixtures."""
    data = _get("fixtures", {"league": LEAGUE_ID, "season": SEASON, "live": "all"})
    if not data:
        return []
    return [item["fixture"]["id"] for item in data.get("response", [])]


def _get_fixture_events(fixture_id: int) -> list[dict]:
    data = _get("fixtures/events", {"fixture": fixture_id})
    if not data:
        return []
    return data.get("response", [])


def _get_fixture_lineups(fixture_id: int) -> list[dict]:
    data = _get("fixtures/lineups", {"fixture": fixture_id})
    if not data:
        return []
    return data.get("response", [])


# ── event processing ──────────────────────────────────────────────────────────

def _known_teams() -> list[str]:
    try:
        from mundial_2026 import BASE_SQUAD
        return list(BASE_SQUAD.keys())
    except Exception:
        return []


def _process_events(fixture_id: int, home_api: str, away_api: str) -> None:
    """Process live events for a fixture and update mundial_2026 state."""
    from mundial_2026 import (add_yellow_card, injure_player, update_result,
                               YELLOW_CARDS, mark_extra_time)

    events = _get_fixture_events(fixture_id)
    teams  = _known_teams()

    for ev in events:
        etype  = ev.get("type", "")
        detail = ev.get("detail", "")
        player = (ev.get("player") or {}).get("name", "")
        assist = (ev.get("assist") or {}).get("name", "")   # for substitution target
        elapsed = ev.get("time", {}).get("elapsed", 0) or 0
        extra   = ev.get("time", {}).get("extra",   0) or 0

        # dedup key
        key = f"{fixture_id}:{etype}:{detail}:{player}:{elapsed}"
        if key in _sent_events:
            continue

        # ── Yellow card ───────────────────────────────────────────────────────
        if etype == "Card" and detail == "Yellow Card" and player:
            resolved = _fuzzy_player(player)
            if resolved:
                _sent_events.add(key)
                yellows_before = YELLOW_CARDS.get(resolved, 0)
                add_yellow_card(resolved)
                if yellows_before >= 1:
                    msg = (f"🟨 <b>SUSPENSION</b>: {resolved} ha recibido su 2ª amarilla "
                           f"→ suspendido (min {elapsed})")
                else:
                    msg = f"🟨 Amarilla: {resolved} (min {elapsed})"
                _notify(msg)
                log.info("Yellow: %s (min %s)", resolved, elapsed)

        # ── Red card ──────────────────────────────────────────────────────────
        elif etype == "Card" and "Red" in detail and player:
            resolved = _fuzzy_player(player)
            if resolved:
                _sent_events.add(key)
                injure_player(resolved)   # mark unavailable for next match
                _notify(f"🟥 <b>Roja</b>: {resolved} expulsado (min {elapsed}) — suspendido siguiente partido")
                log.info("Red card: %s (min %s)", resolved, elapsed)

        # ── AET detection (extra time elapsed > 90) ───────────────────────────
        elif etype in ("Goal", "subst") and elapsed > 90:
            # Match went to extra time — mark both teams
            home_team = _fuzzy_team(home_api, teams)
            away_team = _fuzzy_team(away_api, teams)
            aet_key   = f"{fixture_id}:AET"
            if aet_key not in _sent_events:
                _sent_events.add(aet_key)
                if home_team:
                    mark_extra_time(home_team)
                if away_team:
                    mark_extra_time(away_team)
                _notify(f"⏱ Prórroga detectada: {home_api} vs {away_api} (min {elapsed})")
                log.info("AET detected: %s vs %s", home_api, away_api)


def _process_lineups(fixture_id: int) -> None:
    """Sync confirmed lineups into mundial_2026 LINEUP_CONFIRMED."""
    from mundial_2026 import LINEUP_CONFIRMED, injure_player, find_player, BASE_SQUAD

    lineups = _get_fixture_lineups(fixture_id)
    if not lineups:
        return

    teams = _known_teams()
    for side in lineups:
        api_team = side.get("team", {}).get("name", "")
        team     = _fuzzy_team(api_team, teams)
        if not team:
            continue

        starters = [p["player"]["name"] for p in side.get("startXI", []) if p.get("player")]
        bench    = [p["player"]["name"] for p in side.get("substitutes", []) if p.get("player")]

        # Mark lineup as confirmed
        LINEUP_CONFIRMED[team] = True

        # Cross-check: squad players not in starting XI or bench = absent
        if team in BASE_SQUAD:
            known = set(BASE_SQUAD[team].keys())
            all_api_players = set(starters + bench)
            resolved_present = set()
            for api_p in all_api_players:
                r = find_player(api_p)
                if r:
                    resolved_present.add(r)
            for known_p in known:
                if known_p not in resolved_present:
                    # Not in any squad list → likely absent/injured
                    log.info("Lineup: %s not in %s squad list → may be absent", known_p, team)
                    # Don't auto-injure — could be a lineup API mismatch
                    # Just log; human review via bot if needed

        key = f"{fixture_id}:lineup:{team}"
        if key not in _sent_events:
            _sent_events.add(key)
            starters_str = " · ".join(starters[:11])
            _notify(f"📋 <b>Alineación confirmada — {team}</b>\n{starters_str}")
            log.info("Lineup synced for %s", team)


def _check_upcoming_lineups(upcoming: list[dict]) -> None:
    """For fixtures starting within LINEUP_WINDOW minutes, poll for lineups."""
    now = datetime.now(timezone.utc)
    for fix in upcoming:
        fid = fix["fixture_id"]
        if fid in _lineup_checked:
            continue
        mins_to_ko = (fix["kickoff"] - now).total_seconds() / 60
        if 0 <= mins_to_ko <= LINEUP_WINDOW:
            _process_lineups(fid)
            _lineup_checked.add(fid)


def update_elo_after_match(home_team: str, away_team: str,
                           home_goals: int, away_goals: int,
                           stage: str = "group") -> None:
    """
    Update Elo ratings after a finished match.

    K-factor: 40 for knockout rounds (higher variance), 32 for group stage.
    Formula:
      expected = 1 / (1 + 10^((opponent_elo - team_elo) / 400))
      delta    = K * (result - expected)
      result   = 1.0 win / 0.5 draw / 0.0 loss

    Ratings are persisted to team_ratings.json immediately.
    """
    try:
        from mundial_2026 import update_elo_rating, TEAM_RATINGS
    except ImportError:
        log.error("update_elo_after_match: could not import mundial_2026")
        return

    if home_team not in TEAM_RATINGS or away_team not in TEAM_RATINGS:
        log.warning("Elo update skipped: unknown team(s) %s / %s", home_team, away_team)
        return

    k = 40 if stage in ("r32", "r16", "qf", "sf", "final", "3rd") else 32

    is_draw = home_goals == away_goals
    if is_draw:
        winner, loser = home_team, away_team
    elif home_goals > away_goals:
        winner, loser = home_team, away_team
    else:
        winner, loser = away_team, home_team

    old_w = TEAM_RATINGS[winner]
    old_l = TEAM_RATINGS[loser]
    delta_w, delta_l = update_elo_rating(winner, loser, is_draw=is_draw, k=k)

    sign  = "=" if is_draw else "def"
    score = f"{home_goals}–{away_goals}"
    log.info(
        "Elo Update: %s %.0f→%.0f (%+.0f)  %s  %s %.0f→%.0f (%+.0f)",
        winner, old_w, old_w + delta_w, delta_w,
        sign,
        loser,  old_l, old_l + delta_l, delta_l,
    )
    _notify(
        f"📈 <b>Elo Update</b>  {score}\n"
        f"  {winner}: {old_w:.0f} → {old_w + delta_w:.0f} ({delta_w:+.0f})\n"
        f"  {loser}:  {old_l:.0f} → {old_l + delta_l:.0f} ({delta_l:+.0f})"
    )


def _check_finished_matches(upcoming: list[dict]) -> None:
    """Detect matches that just finished; update Elo and notify."""
    for fix in upcoming:
        fid    = fix["fixture_id"]
        status = fix.get("status", "NS")
        if status in ("FT", "AET", "PEN") and fid not in _known_fixture_ids:
            _known_fixture_ids.add(fid)
            hs  = fix.get("home_score")
            as_ = fix.get("away_score")
            hs_str  = str(hs)  if hs  is not None else "?"
            as_str  = str(as_) if as_ is not None else "?"
            _notify(
                f"🏁 Partido finalizado: <b>{fix['home']} {hs_str}–{as_str} {fix['away']}</b>\n"
                f"Registra el resultado con el botón Actualizar en el bot."
            )
            # Auto-update Elo if we have a clean result
            if hs is not None and as_ is not None:
                update_elo_after_match(
                    fix["home"], fix["away"], int(hs), int(as_),
                    stage=fix.get("stage", "group"),
                )


# ── main sync loop ────────────────────────────────────────────────────────────

def run_sync_loop() -> None:
    """
    Daemon loop. Polls api-football.com continuously:
    - Every LIVE_POLL_SEC when there are live games.
    - Every IDLE_POLL_SEC otherwise.
    """
    log.info("Sync loop starting (league=%s season=%s)", LEAGUE_ID, SEASON)
    if not API_KEY:
        log.error("API_FOOTBALL_KEY not set — sync loop disabled")
        return

    # Quick check: verify the API plan supports this season
    test = _get("fixtures", {"league": LEAGUE_ID, "season": SEASON, "next": 1})
    if test and test.get("errors"):
        err = str(test["errors"])
        if "plan" in err.lower() or "season" in err.lower():
            log.warning("api-football free plan does not cover season %s yet. "
                        "Auto-sync disabled until the plan is upgraded or the season unlocks.", SEASON)
            return

    while True:
        try:
            live_ids = _get_live_fixture_ids()

            if live_ids:
                _live_fixture_ids.update(live_ids)
                for fid in live_ids:
                    # We need home/away names — fetch from upcoming cache
                    upcoming = get_upcoming_fixtures(days=1)
                    fix_map  = {f["fixture_id"]: f for f in upcoming}
                    if fid in fix_map:
                        f = fix_map[fid]
                        _process_events(fid, f["home"], f["away"])
                    else:
                        # Fetch directly
                        data = _get("fixtures", {"id": fid})
                        if data and data.get("response"):
                            item = data["response"][0]
                            home = item["teams"]["home"]["name"]
                            away = item["teams"]["away"]["name"]
                            _process_events(fid, home, away)
                sleep_sec = LIVE_POLL_SEC
            else:
                # No live games — check upcoming for lineup window and finished matches
                upcoming = get_upcoming_fixtures(days=2)
                _check_upcoming_lineups(upcoming)
                _check_finished_matches(upcoming)
                sleep_sec = IDLE_POLL_SEC

        except Exception as exc:
            log.error("Sync loop error: %s", exc, exc_info=True)
            sleep_sec = IDLE_POLL_SEC

        time.sleep(sleep_sec)


# ── standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    fixtures = get_upcoming_fixtures(days=3)
    print(f"Found {len(fixtures)} fixtures in next 3 days:")
    for f in fixtures:
        ko = f["kickoff"].strftime("%Y-%m-%d %H:%M UTC")
        print(f"  [{f['stage']:6}] {f['home']:20} vs {f['away']:20}  {ko}  {f['venue']}")
