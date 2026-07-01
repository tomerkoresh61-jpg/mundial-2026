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
import json
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
FIXTURES_FILE  = os.path.join(os.path.dirname(__file__), "wc2026_fixtures.json")

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


# api-football uses some country names that differ from our model's names.
# These are checked (accent/case-insensitively) before the fuzzy fallback.
TEAM_ALIASES = {
    "korea republic":     "South Korea",
    "south korea":        "South Korea",
    "cape verde islands": "Cape Verde",
    "ir iran":            "Iran",
    "iran":               "Iran",
    "czech republic":     "Czechia",
    "congo dr":           "DR Congo",
    "dr congo":           "DR Congo",
    "united states":      "USA",
    "cote d'ivoire":      "Ivory Coast",
    "côte d'ivoire":      "Ivory Coast",
}


def _fuzzy_team(api_name: str, known_teams: list[str]) -> Optional[str]:
    norm_api = _norm(api_name)
    norm_map = {_norm(t): t for t in known_teams}
    # exact
    if norm_api in norm_map:
        return norm_map[norm_api]
    # explicit alias map (handles known api-football spellings)
    alias = TEAM_ALIASES.get(norm_api)
    if alias and alias in known_teams:
        return alias
    # close
    matches = difflib.get_close_matches(norm_api, norm_map.keys(), n=1, cutoff=0.75)
    return norm_map[matches[0]] if matches else None


def _fuzzy_player(api_name: str) -> Optional[str]:
    """Match api name against players known to mundial_2026."""
    try:
        from mundial_2026 import find_player
        return find_player(api_name, quiet=True)
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

def _load_hardcoded_fixtures() -> list[dict]:
    """
    Load all fixtures from wc2026_fixtures.json (offline fallback schedule).
    Returns them in the same dict shape as the API path.
    """
    if not os.path.exists(FIXTURES_FILE):
        log.warning("wc2026_fixtures.json not found at %s", FIXTURES_FILE)
        return []
    try:
        with open(FIXTURES_FILE) as f:
            raw = json.load(f)
    except Exception as e:
        log.error("Failed to read wc2026_fixtures.json: %s", e)
        return []

    result = []
    for item in raw:
        ko_str = item.get("kickoff", "")
        try:
            ko = datetime.fromisoformat(ko_str)
        except Exception:
            continue
        result.append({
            "fixture_id": item.get("fixture_id"),
            "home":       item.get("home", "TBD"),
            "away":       item.get("away", "TBD"),
            "venue":      item.get("venue", "Neutral"),
            "stage":      item.get("stage", "group"),
            "kickoff":    ko,
            "status":     item.get("status", "NS"),
            "home_score": item.get("home_score"),
            "away_score": item.get("away_score"),
            "home_winner": item.get("home_winner"),
            "away_winner": item.get("away_winner"),
            "elapsed":    None,
            "source":     "hardcoded",
        })
    result.sort(key=lambda x: x["kickoff"])
    log.debug("Loaded %d hardcoded fixtures from wc2026_fixtures.json", len(result))
    return result


def get_upcoming_fixtures(days: int = 1) -> list[dict]:
    """
    Return upcoming fixtures within `days` days from now.

    Priority:
      1. api-football.com (live data, requires paid plan for 2026 season)
      2. wc2026_fixtures.json (hardcoded fallback — always available)

    Each returned dict has keys:
      fixture_id, home, away, venue, stage, kickoff (datetime UTC),
      status, home_score, away_score, elapsed, [source]
    """
    now   = datetime.now(timezone.utc)
    until = now + timedelta(days=days)

    # ── 1. Try the API ────────────────────────────────────────
    api_result = None
    if API_KEY:
        data = _get("fixtures", {
            "league":   LEAGUE_ID,
            "season":   SEASON,
            "from":     now.strftime("%Y-%m-%d"),
            "to":       until.strftime("%Y-%m-%d"),
            "timezone": "UTC",
        })
        if data and not data.get("errors") and data.get("response"):
            api_result = []
            for item in data["response"]:
                fix    = item.get("fixture", {})
                teams  = item.get("teams", {})
                venue  = fix.get("venue", {}).get("name", "Neutral")
                goals  = item.get("goals", {})
                ko_str = fix.get("date", "")
                try:
                    ko = datetime.fromisoformat(ko_str.replace("Z", "+00:00"))
                except Exception:
                    ko = now

                lr    = item.get("league", {}).get("round", "").lower()
                stage = "group"
                if "round of 32"  in lr: stage = "r32"
                elif "round of 16" in lr: stage = "r16"
                elif "quarter"     in lr: stage = "qf"
                elif "semi"        in lr: stage = "sf"
                elif "final"       in lr: stage = "final"
                elif "third"       in lr: stage = "3rd"

                api_result.append({
                    "fixture_id": fix.get("id"),
                    "home":       teams.get("home", {}).get("name", "?"),
                    "away":       teams.get("away", {}).get("name", "?"),
                    "venue":      venue,
                    "stage":      stage,
                    "kickoff":    ko,
                    "status":     fix.get("status", {}).get("short", "NS"),
                    "home_score": goals.get("home"),
                    "away_score": goals.get("away"),
                    "home_winner": teams.get("home", {}).get("winner"),
                    "away_winner": teams.get("away", {}).get("winner"),
                    "elapsed":    fix.get("status", {}).get("elapsed"),
                    "source":     "api",
                })
            api_result.sort(key=lambda x: x["kickoff"])

    if api_result:
        return api_result

    # ── 2. Fallback: hardcoded schedule ───────────────────────
    log.info("API unavailable or no data — using hardcoded wc2026_fixtures.json")
    all_fixtures = _load_hardcoded_fixtures()
    return [f for f in all_fixtures if now <= f["kickoff"] <= until]


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
        from mundial_2026 import TEAMS
        return list(TEAMS.keys())
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


def _process_lineups(fixture_id: int) -> bool:
    """
    Sync confirmed lineups into mundial_2026 LINEUP_CONFIRMED.

    Returns True if at least one side's lineup was confirmed, False otherwise
    (e.g. lineups not yet published). Callers use this to decide whether the
    fixture has been fully handled or should be retried later.
    """
    from mundial_2026 import LINEUP_CONFIRMED, injure_player, find_player, TEAMS

    lineups = _get_fixture_lineups(fixture_id)
    if not lineups:
        return False

    confirmed_any = False
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
        confirmed_any = True

        # Cross-check: squad players not in starting XI or bench = absent
        if team in TEAMS:
            known = set(TEAMS[team]["players"].keys())
            all_api_players = set(starters + bench)
            resolved_present = set()
            for api_p in all_api_players:
                r = find_player(api_p, quiet=True)
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

    return confirmed_any


def sync_lineups(fixture_id: int) -> bool:
    """
    On-demand lineup fetch (used by the bot just before kickoff, and safe to
    call from any thread). Wraps _process_lineups with error handling so a
    failed network call never breaks the caller. Returns True if confirmed.
    """
    try:
        return _process_lineups(fixture_id)
    except Exception as exc:
        log.warning("sync_lineups failed for %s: %s", fixture_id, exc)
        return False


def _check_upcoming_lineups(upcoming: list[dict]) -> None:
    """For fixtures starting within LINEUP_WINDOW minutes, poll for lineups."""
    now = datetime.now(timezone.utc)
    for fix in upcoming:
        fid = fix["fixture_id"]
        if fid in _lineup_checked:
            continue
        mins_to_ko = (fix["kickoff"] - now).total_seconds() / 60
        if 0 <= mins_to_ko <= LINEUP_WINDOW:
            # Only mark as handled once a lineup is actually confirmed; otherwise
            # retry on the next poll (lineups may not be published yet).
            if _process_lineups(fid):
                _lineup_checked.add(fid)


def update_elo_after_match(home_team: str, away_team: str,
                           home_goals: int, away_goals: int,
                           stage: str = "group",
                           winner_team: Optional[str] = None) -> None:
    """
    Update Elo ratings after a finished match.

    K-factor: 40 for knockout rounds (higher variance), 32 for group stage.
    Formula:
      expected = 1 / (1 + 10^((opponent_elo - team_elo) / 400))
      delta    = K * (result - expected)
      result   = 1.0 win / 0.5 draw / 0.0 loss

    Ratings are persisted to team_ratings.json immediately.

    For tied knockout scores decided on penalties, pass winner_team from the
    API winner flag so the advancing side is not recorded as an Elo draw.
    """
    try:
        from mundial_2026 import update_elo_rating, TEAM_RATINGS
    except ImportError:
        log.error("update_elo_after_match: could not import mundial_2026")
        return

    teams = list(TEAM_RATINGS.keys())
    home_team = _fuzzy_team(home_team, teams) or home_team
    away_team = _fuzzy_team(away_team, teams) or away_team
    winner_team = _fuzzy_team(winner_team, teams) if winner_team else None

    if home_team not in TEAM_RATINGS or away_team not in TEAM_RATINGS:
        log.warning("Elo update skipped: unknown team(s) %s / %s", home_team, away_team)
        return

    stage = (stage or "group").lower()
    k = 40 if stage in ("r32", "r16", "qf", "sf", "final", "3rd") else 32

    is_draw = home_goals == away_goals
    if is_draw and winner_team in (home_team, away_team):
        is_draw = False
        if winner_team == home_team:
            winner, loser = home_team, away_team
        else:
            winner, loser = away_team, home_team
    elif is_draw:
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
                winner_team = None
                if fix.get("home_winner") is True:
                    winner_team = fix["home"]
                elif fix.get("away_winner") is True:
                    winner_team = fix["away"]
                update_elo_after_match(
                    fix["home"], fix["away"], int(hs), int(as_),
                    stage=fix.get("stage", "group"),
                    winner_team=winner_team,
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
        log.warning("API_FOOTBALL_KEY not set — live event sync disabled; "
                    "upcoming fixtures served from wc2026_fixtures.json")
        # Still run the idle loop so _check_finished_matches / lineups fire
        # against the hardcoded schedule (status updates need manual bot input).
        while True:
            try:
                upcoming = get_upcoming_fixtures(days=2)
                _check_upcoming_lineups(upcoming)
                _check_finished_matches(upcoming)
            except Exception as exc:
                log.error("Idle loop error: %s", exc)
            time.sleep(IDLE_POLL_SEC)
        return  # unreachable but explicit

    # Quick check: verify the API plan supports this season for fixture queries.
    # NOTE: Even if /fixtures is blocked, /fixtures?live=all may still work,
    # and upcoming fixtures fall back to wc2026_fixtures.json — so we do NOT
    # kill the loop on a plan error, we just note it and carry on.
    test = _get("fixtures", {"league": LEAGUE_ID, "season": SEASON, "next": 1})
    if test and test.get("errors"):
        err = str(test["errors"])
        if "plan" in err.lower() or "season" in err.lower():
            log.warning("api-football plan does not cover season %s for fixture queries. "
                        "Upcoming schedule served from wc2026_fixtures.json. "
                        "Live event polling (/fixtures?live=all) will still be attempted.",
                        SEASON)

    while True:
        try:
            live_ids = _get_live_fixture_ids()

            if live_ids:
                _live_fixture_ids.update(live_ids)
                # Build a lookup from our upcoming fixtures (hardcoded IDs: 10001+).
                # Live API IDs (real fixture IDs) won't match hardcoded ones, so
                # we fall through to the direct fetch — that's intentional.
                upcoming = get_upcoming_fixtures(days=1)
                fix_map  = {f["fixture_id"]: f for f in upcoming}
                for fid in live_ids:
                    if fid in fix_map:
                        f = fix_map[fid]
                        _process_events(fid, f["home"], f["away"])
                    else:
                        # API fixture ID not in hardcoded schedule — fetch names directly.
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
