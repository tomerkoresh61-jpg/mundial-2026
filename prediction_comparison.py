"""
prediction_comparison.py — Side-by-side model comparison for WC2026 matches.

Sources:
  1. Our model     — mundial_2026.expected_goals() + score_matrix()   [always live]
  2. Betting odds  — api-football.com /odds endpoint                   [live if API plan allows]
  3. Hicruben      — cup26matches.com                                  [STUB: needs site validation]
  4. PELE cache    — manually maintained dict (FiveThirtyEight PELE    [STUB: no live 2026 feed]
                     has no live 2026 endpoint; update PELE_CACHE below
                     from SilverBulletin.com or the official PELE CSV]

Usage:
    from prediction_comparison import compare_match, format_comparison_table
    result = compare_match("France", "Argentina", venue="MetLife", stage="final")
    print(format_comparison_table(result))
"""

import os
import logging
import requests
from typing import Optional

log = logging.getLogger(__name__)

API_KEY   = os.environ.get("API_FOOTBALL_KEY", "")
API_BASE  = "https://v3.football.api-sports.io"
LEAGUE_ID = 1
SEASON    = 2026

# ── PELE manual cache ─────────────────────────────────────────────────────────
# FiveThirtyEight's PELE model is NOT available as a live feed for 2026.
# Update this dict manually from SilverBulletin.com's tournament model
# (or from the published PELE CSV if Nate Silver releases one).
# Format: (home_team, away_team) → {"w": float, "d": float, "l": float}
# where w/d/l are home win / draw / away win probabilities summing to 1.0.
PELE_CACHE: dict[tuple, dict] = {
    # Example (fill in from SilverBulletin.com once published):
    # ("France", "Argentina"): {"w": 0.42, "d": 0.25, "l": 0.33},
}

# Discrepancy threshold — log a warning if our W% differs by more than this
DISCREPANCY_THRESHOLD = 0.15


# ── Our model ─────────────────────────────────────────────────────────────────

def fetch_our_prediction(home: str, away: str,
                         venue: str = "Neutral",
                         stage: str = "group") -> dict:
    """Run our own Poisson/Dixon-Coles model and return W/D/L + top scores."""
    import mundial_2026 as mdl
    mdl._load_state()
    lam_a, lam_b, _ = mdl.expected_goals(home, away, venue, stage=stage)
    P = mdl.score_matrix(lam_a, lam_b)
    w, d, l = mdl.wdl(P)

    # Knockout: advancement % after extra time + penalties (separate from 90' line).
    if mdl.is_knockout(stage):
        p_adv_home, p_adv_away = mdl._advancement_probs(home, away, lam_a, lam_b, w, d, l)
        p_adv_home, p_adv_away = round(p_adv_home, 3), round(p_adv_away, 3)
    else:
        p_adv_home = p_adv_away = None

    scores = sorted(
        [(i, j, P[i, j]) for i in range(P.shape[0]) for j in range(P.shape[1])],
        key=lambda x: -x[2]
    )
    top3 = [(s[0], s[1], round(s[2] * 100, 1)) for s in scores[:3]]

    return {
        "source": "Our Model",
        "w": round(w, 3),
        "d": round(d, 3),
        "l": round(l, 3),
        "p_adv_home": p_adv_home,
        "p_adv_away": p_adv_away,
        "top3": top3,
        "xg": (round(lam_a, 2), round(lam_b, 2)),
        "available": True,
    }


# ── Betting odds ──────────────────────────────────────────────────────────────

def fetch_betting_odds(fixture_id: Optional[int] = None,
                       home: str = "", away: str = "") -> dict:
    """
    Fetch market consensus odds from api-football.com /odds endpoint.
    Returns implied W/D/L probabilities with overround removed.

    Note: the /odds endpoint requires a paid api-football plan.
    Falls back gracefully if not available.
    """
    if not API_KEY:
        return {"source": "Betting Odds", "available": False, "reason": "No API key"}

    params = {"league": LEAGUE_ID, "season": SEASON, "bet": 1}  # bet=1 = Match Winner
    if fixture_id:
        params["fixture"] = fixture_id

    try:
        r = requests.get(f"{API_BASE}/odds", headers={"x-apisports-key": API_KEY},
                         params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"source": "Betting Odds", "available": False, "reason": str(e)}

    if data.get("errors"):
        return {"source": "Betting Odds", "available": False,
                "reason": str(data["errors"])}

    response = data.get("response", [])
    if not response:
        return {"source": "Betting Odds", "available": False,
                "reason": "No odds data returned"}

    # Find the first bookmaker with Match Winner market
    for item in response:
        for bm in item.get("bookmakers", []):
            for bet in bm.get("bets", []):
                if bet.get("id") == 1:  # Match Winner
                    vals = {v["value"]: float(v["odd"]) for v in bet.get("values", [])}
                    h_odd = vals.get("Home", 0)
                    d_odd = vals.get("Draw", 0)
                    a_odd = vals.get("Away", 0)
                    if h_odd and d_odd and a_odd:
                        raw_w = 1 / h_odd
                        raw_d = 1 / d_odd
                        raw_l = 1 / a_odd
                        total = raw_w + raw_d + raw_l
                        return {
                            "source": "Betting Odds",
                            "bookmaker": bm.get("name", "unknown"),
                            "w": round(raw_w / total, 3),
                            "d": round(raw_d / total, 3),
                            "l": round(raw_l / total, 3),
                            "available": True,
                        }

    return {"source": "Betting Odds", "available": False,
            "reason": "Could not parse odds structure"}


# ── To-qualify market (knockout advancement) ──────────────────────────

_QUALIFY_KEYWORDS = ("qualif", "to advance", "advance", "to reach", "to win the tie")


def list_odds_markets(fixture_id: int) -> list:
    """
    Probe: list every (bet_id, bet_name) market api-football offers for a fixture.
    Use this once R32 odds go live to discover the real "To Qualify" market id.
    """
    if not API_KEY:
        return []
    try:
        r = requests.get(f"{API_BASE}/odds", headers={"x-apisports-key": API_KEY},
                         params={"fixture": fixture_id}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("list_odds_markets failed: %s", e)
        return []
    seen, out = set(), []
    for item in data.get("response", []):
        for bm in item.get("bookmakers", []):
            for bet in bm.get("bets", []):
                key = (bet.get("id"), bet.get("name"))
                if key not in seen:
                    seen.add(key)
                    out.append({"id": bet.get("id"), "name": bet.get("name")})
    return sorted(out, key=lambda x: (x["id"] is None, x["id"] or 0))


def fetch_qualify_odds(fixture_id: Optional[int] = None,
                       home: str = "", away: str = "") -> dict:
    """
    Fetch the 2-way "to qualify / to advance" market and convert to implied
    advancement probabilities (overround removed). This is the knockout analogue
    of the 90' Match Winner line and is kept SEPARATE from it so the two are
    never compared against each other.
    """
    if not API_KEY:
        return {"source": "To Qualify Odds", "available": False, "reason": "No API key"}
    if not fixture_id:
        return {"source": "To Qualify Odds", "available": False,
                "reason": "fixture id required to locate market"}

    try:
        r = requests.get(f"{API_BASE}/odds", headers={"x-apisports-key": API_KEY},
                         params={"fixture": fixture_id}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"source": "To Qualify Odds", "available": False, "reason": str(e)}

    if data.get("errors"):
        return {"source": "To Qualify Odds", "available": False,
                "reason": str(data["errors"])}

    for item in data.get("response", []):
        for bm in item.get("bookmakers", []):
            for bet in bm.get("bets", []):
                name = (bet.get("name") or "").lower()
                vals = bet.get("values", [])
                if not any(k in name for k in _QUALIFY_KEYWORDS):
                    continue
                if len(vals) != 2:
                    continue
                # Two-way market: map by Home/Away label, else by order.
                lut = {str(v.get("value", "")).lower(): float(v["odd"]) for v in vals}
                h_odd = lut.get("home") or lut.get(home.lower())
                a_odd = lut.get("away") or lut.get(away.lower())
                if not (h_odd and a_odd):
                    odds_in_order = [float(v["odd"]) for v in vals]
                    h_odd, a_odd = odds_in_order[0], odds_in_order[1]
                raw_h, raw_a = 1 / h_odd, 1 / a_odd
                total = raw_h + raw_a
                return {
                    "source": "To Qualify Odds",
                    "bookmaker": bm.get("name", "unknown"),
                    "bet_name": bet.get("name"),
                    "bet_id": bet.get("id"),
                    "p_adv_home": round(raw_h / total, 3),
                    "p_adv_away": round(raw_a / total, 3),
                    "available": True,
                }

    return {"source": "To Qualify Odds", "available": False,
            "reason": "No to-qualify market published yet"}


# ── Hicruben (cup26matches.com) ───────────────────────────────────────────────

def fetch_hicruben_prediction(home: str, away: str) -> dict:
    """
    Fetch Hicruben's prediction from cup26matches.com.

    STUB — site structure not yet validated.
    To implement:
      1. Visit cup26matches.com and inspect the match prediction page HTML.
      2. Find the CSS selectors for home-win%, draw%, away-win%.
      3. Replace the stub below with real BeautifulSoup parsing.

    Requires: pip install beautifulsoup4
    """
    return {
        "source": "Hicruben (cup26matches.com)",
        "available": False,
        "reason": (
            "Stub: cup26matches.com scraping not yet implemented. "
            "See fetch_hicruben_prediction() docstring."
        ),
    }

    # ── Uncomment and adapt once site structure is known: ──────────────────
    # from bs4 import BeautifulSoup
    # slug = f"{home.lower().replace(' ', '-')}-vs-{away.lower().replace(' ', '-')}"
    # url  = f"https://cup26matches.com/predictions/{slug}"
    # try:
    #     r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    #     r.raise_for_status()
    #     soup = BeautifulSoup(r.text, "html.parser")
    #     # TODO: find correct selectors
    #     w = float(soup.select_one(".home-win-pct").text.strip("%")) / 100
    #     d = float(soup.select_one(".draw-pct").text.strip("%")) / 100
    #     l = float(soup.select_one(".away-win-pct").text.strip("%")) / 100
    #     return {"source": "Hicruben", "w": w, "d": d, "l": l, "available": True}
    # except Exception as e:
    #     return {"source": "Hicruben", "available": False, "reason": str(e)}


# ── PELE / FiveThirtyEight ────────────────────────────────────────────────────

def fetch_pele_prediction(home: str, away: str) -> dict:
    """
    Return FiveThirtyEight PELE odds from the manual PELE_CACHE dict.

    FiveThirtyEight was shut down and relaunched as SilverBulletin.com.
    There is no live 2026 World Cup PELE API endpoint.

    To use this:
      1. Visit silverBulletin.com (or wherever Nate Silver publishes 2026 forecasts).
      2. Note the W/D/L% for your match.
      3. Add to PELE_CACHE at the top of this file:
         PELE_CACHE[("France", "Argentina")] = {"w": 0.42, "d": 0.25, "l": 0.33}
    """
    key   = (home, away)
    key_r = (away, home)

    if key in PELE_CACHE:
        e = PELE_CACHE[key]
        return {"source": "PELE (FiveThirtyEight)",
                "w": e["w"], "d": e["d"], "l": e["l"], "available": True}

    if key_r in PELE_CACHE:
        e = PELE_CACHE[key_r]
        return {"source": "PELE (FiveThirtyEight)",
                "w": e["l"], "d": e["d"], "l": e["w"], "available": True}

    return {
        "source": "PELE (FiveThirtyEight)",
        "available": False,
        "reason": "No cached entry. Add to PELE_CACHE in prediction_comparison.py.",
    }


# ── Main comparison function ──────────────────────────────────────────────────

def compare_match(home: str, away: str,
                  venue: str = "Neutral",
                  stage: str = "group",
                  fixture_id: Optional[int] = None) -> dict:
    """
    Gather predictions from all 4 sources and check for discrepancies.

    Returns a dict with keys:
      home, away, venue, stage,
      sources: list of source dicts (w/d/l + metadata),
      warnings: list of discrepancy warning strings.
    """
    import mundial_2026 as mdl
    knockout = mdl.is_knockout(stage)

    our   = fetch_our_prediction(home, away, venue, stage)
    odds  = fetch_betting_odds(fixture_id, home, away)       # 90' Match Winner (1X2)
    hicr  = fetch_hicruben_prediction(home, away)
    pele  = fetch_pele_prediction(home, away)

    sources = [our, odds, hicr, pele]

    # To-qualify market is the advancement analogue, kept separate from 90' lines.
    qualify = fetch_qualify_odds(fixture_id, home, away) if knockout else None

    warnings = []

    # (1) 90'-vs-90' check only: our regulation W% vs 90' sources (bet=1, etc.).
    our_w = our["w"]
    for src in [odds, hicr, pele]:
        if not src.get("available"):
            continue
        diff = abs(our_w - src["w"])
        if diff > DISCREPANCY_THRESHOLD:
            warnings.append(
                f"⚠️ Our 90′ W% ({our_w*100:.0f}%) differs from {src['source']} "
                f"({src['w']*100:.0f}%) by {diff*100:.0f}pp — review model inputs."
            )

    # (2) advancement-vs-advancement check only (never crosses the 90' line).
    if (knockout and qualify and qualify.get("available")
            and our.get("p_adv_home") is not None):
        diff = abs(our["p_adv_home"] - qualify["p_adv_home"])
        if diff > DISCREPANCY_THRESHOLD:
            warnings.append(
                f"⚠️ Our advancement% for {home} ({our['p_adv_home']*100:.0f}%) "
                f"differs from market to-qualify ({qualify['p_adv_home']*100:.0f}%) "
                f"by {diff*100:.0f}pp — review model inputs."
            )

    for w in warnings:
        log.warning(w)

    return {
        "home": home, "away": away, "venue": venue, "stage": stage,
        "knockout": knockout,
        "sources": sources,
        "qualify_odds": qualify,
        "warnings": warnings,
    }


# ── Display formatter ─────────────────────────────────────────────────────────

def format_comparison_table(result: dict) -> str:
    """
    Format the comparison dict as a Telegram-ready Markdown string.

    Example output:
      🔍 France 🆚 Argentina | Final | MetLife

      Source              Home%  Draw%  Away%
      ─────────────────── ─────  ─────  ─────
      Our Model           42%    25%    33%  ✅
      Betting Odds        44%    26%    30%  ✅
      Hicruben            —      —      —   ❌ (stub)
      PELE                —      —      —   ❌ (no cache)
    """
    home    = result["home"]
    away    = result["away"]
    venue   = result["venue"]
    stage   = result["stage"].upper()
    sources = result["sources"]

    lines = [
        f"🔍 *{home}* 🆚 *{away}*  |  {stage}  |  {venue}\n",
        f"{'Source':<22} {'Home%':>5}  {'Draw%':>5}  {'Away%':>5}",
        "─" * 42,
    ]

    for src in sources:
        name = src["source"][:22]
        if src.get("available"):
            w_str = f"{src['w']*100:.0f}%"
            d_str = f"{src['d']*100:.0f}%"
            l_str = f"{src['l']*100:.0f}%"
            lines.append(f"{name:<22} {w_str:>5}  {d_str:>5}  {l_str:>5}  ✅")
        else:
            reason = src.get("reason", "unavailable")[:30]
            lines.append(f"{name:<22} {'—':>5}  {'—':>5}  {'—':>5}  ❌ _{reason}_")

    # Our model top scores
    our = next((s for s in sources if s["source"] == "Our Model"), None)
    if our and our.get("top3"):
        top3_str = "  ·  ".join(f"{a}-{b} ({p}%)" for a, b, p in our["top3"])
        xg_a, xg_b = our["xg"]
        lines.append(f"\n📊 *Top scores:* {top3_str}")
        lines.append(f"⚡ *xG:* {home} {xg_a} — {xg_b} {away}")

    # Knockout: advancement % (our model vs market to-qualify), separate from 90'.
    if result.get("knockout") and our and our.get("p_adv_home") is not None:
        lines.append(
            f"🏆 *Advancement (our):* {home} {our['p_adv_home']*100:.0f}%  "
            f"·  {away} {our['p_adv_away']*100:.0f}%"
        )
        q = result.get("qualify_odds")
        if q and q.get("available"):
            lines.append(
                f"💰 *To-qualify (market):* {home} {q['p_adv_home']*100:.0f}%  "
                f"·  {away} {q['p_adv_away']*100:.0f}%"
            )
        else:
            reason = (q or {}).get("reason", "n/a")
            lines.append(f"💰 *To-qualify (market):* — _{reason}_")

    # Warnings
    for w in result.get("warnings", []):
        lines.append(f"\n{w}")

    return "\n".join(lines)


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    result = compare_match("France", "Norway", venue="MetLife", stage="group")
    print(format_comparison_table(result))
    print()
    print("Raw:", result)
