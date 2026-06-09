"""
news_intel.py — News scraper + Claude Haiku intel extractor for Mundial 2026
Scrapes: BBC Sport, Sky Sports, ESPN FC, L'Equipe
Extracts structured intel via Claude claude-haiku-4-5-20251001 API
Sends confidence-tiered notifications via Telegram

Three tiers:
  🟢 HIGH   → auto-apply (confidence ≥ 0.80)
  🟡 MEDIUM → ask user to confirm (confidence 0.55–0.79)
  🔴 LOW    → log only (confidence < 0.55)

Called by telegram_bot._start_background_workers() as a daemon thread.
"""

import os
import time
import json
import logging
import hashlib
import unicodedata
import difflib
import requests
from datetime import datetime, timezone
from typing import Optional

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [news_intel] %(levelname)s %(message)s")
log = logging.getLogger("news_intel")

# ── env ───────────────────────────────────────────────────────────────────────
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BOT_TOKEN     = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER  = int(os.environ.get("ALLOWED_USER_ID", "0"))

# Poll interval between scraper runs (seconds)
SCRAPE_INTERVAL = 900   # 15 min

# ── Sources ───────────────────────────────────────────────────────────────────
SOURCES = [
    {
        "name": "BBC Sport",
        "url":  "https://www.bbc.com/sport/football/world-cup",
        "lang": "en",
    },
    {
        "name": "Sky Sports",
        "url":  "https://www.skysports.com/football/world-cup",
        "lang": "en",
    },
    {
        "name": "ESPN FC",
        "url":  "https://www.espn.com/soccer/league/_/name/fifa.world",
        "lang": "en",
    },
    {
        "name": "L'Equipe",
        "url":  "https://www.lequipe.fr/Football/coupe-du-monde-2026.html",
        "lang": "fr",
    },
]

# Already processed article fingerprints (URL hash + headline hash)
_seen_articles: set = set()

# ── helpers ───────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    nfkd  = unicodedata.normalize("NFKD", s)
    ascii_ = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(ascii_.lower().split())


def _fingerprint(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


def _notify(text: str, parse_mode: str = "HTML") -> None:
    if not BOT_TOKEN or not ALLOWED_USER:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id":    ALLOWED_USER,
            "text":       text,
            "parse_mode": parse_mode,
        }, timeout=10)
    except Exception as exc:
        log.error("Telegram notify failed: %s", exc)


def _notify_with_buttons(text: str, buttons: list[list[dict]]) -> None:
    if not BOT_TOKEN or not ALLOWED_USER:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id":      ALLOWED_USER,
            "text":         text,
            "parse_mode":   "HTML",
            "reply_markup": {"inline_keyboard": buttons},
        }, timeout=10)
    except Exception as exc:
        log.error("Telegram notify (buttons) failed: %s", exc)


# ── scraper ───────────────────────────────────────────────────────────────────

def _scrape_articles(source: dict) -> list[dict]:
    """
    Fetch source page and extract article snippets heuristically.
    Returns list of dicts: {headline, snippet, url, source_name}
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = requests.get(source["url"], headers=headers, timeout=20)
        r.raise_for_status()
        html = r.text
    except Exception as exc:
        log.warning("Scrape failed (%s): %s", source["name"], exc)
        return []

    # Light HTML parsing — extract <a> tags with non-trivial text as article links
    import re
    articles = []
    # Look for patterns like <a href="...">headline</a> near <p> text
    pattern = re.compile(
        r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]{30,200})\s*</a>',
        re.IGNORECASE | re.DOTALL
    )
    snippet_pattern = re.compile(r'<p[^>]*>\s*([^<]{40,400})\s*</p>',
                                  re.IGNORECASE | re.DOTALL)
    snippets = [m.group(1).strip() for m in snippet_pattern.finditer(html)]

    seen_headlines = set()
    for m in pattern.finditer(html):
        href, headline = m.group(1).strip(), m.group(2).strip()
        # Clean headline
        headline = re.sub(r'\s+', ' ', headline).strip()
        if len(headline) < 30 or headline in seen_headlines:
            continue
        # Filter for WC-relevant content
        hl_norm = _norm(headline)
        wc_keywords = [
            "world cup", "mundial", "coupe du monde",
            "injury", "fit", "suspend", "lineup", "squad", "training",
            "blesse", "forfait", "absent", "blessure",
        ]
        if not any(kw in hl_norm for kw in wc_keywords):
            # might still be relevant — include if from a WC section page
            pass  # include all; Haiku will filter

        fp = _fingerprint(source["name"], headline)
        if fp in _seen_articles:
            continue

        # Find closest snippet
        snippet = next((s for s in snippets if s and s not in seen_headlines), "")
        articles.append({
            "headline":    headline,
            "snippet":     snippet[:400],
            "url":         href if href.startswith("http") else source["url"],
            "source_name": source["name"],
            "lang":        source["lang"],
            "fp":          fp,
        })
        seen_headlines.add(headline)
        if len(articles) >= 20:  # cap per source
            break

    return articles


# ── Claude Haiku extraction ───────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are a football analyst assistant. Given a news headline and snippet about the FIFA World Cup 2026, extract structured player/team intelligence.

Return a JSON object with this exact structure (omit fields that don't apply):
{
  "relevant": true/false,           // is this about fitness, injuries, suspensions, form, or lineup?
  "items": [
    {
      "type": "fitness|injury|suspension|form|lineup|team_note",
      "player": "Full Name or null",
      "team": "Country Name or null",
      "value": number_or_null,      // fitness % (0-100) for fitness type, null otherwise
      "direction": "+1|0|-1|null",  // for form: +1 good, -1 bad, 0 neutral
      "detail": "one-line English explanation",
      "confidence": 0.0-1.0         // how confident you are (explicit news=0.9, rumour=0.5)
    }
  ]
}

Rules:
- Only return items directly stated or strongly implied by the headline/snippet.
- fitness: percentage of match fitness (e.g. "doubtful" ≈ 60, "limited training" ≈ 70, "full training" ≈ 90, "fresh" ≈ 100).
- injury: player is injured; if no fitness known leave value null.
- suspension: player suspended for next match.
- form: team or player form signal; direction +1 or -1.
- team_note: qualitative note about a team, no numeric value.
- lineup: player confirmed in/out of starting lineup.
- If not relevant (transfer news, history, unrelated sport), return {"relevant": false, "items": []}.
- Use canonical English country names (e.g. "France", "Brazil", not abbreviations).
- Player names: full names when possible.

Headline: {headline}
Snippet: {snippet}

Respond with JSON only, no markdown."""


def _extract_intel(article: dict) -> list[dict]:
    """
    Call Claude Haiku to extract structured intel from one article.
    Returns list of intel items (already parsed dicts).
    """
    if not ANTHROPIC_KEY:
        log.warning("ANTHROPIC_API_KEY not set — extraction skipped")
        return []

    prompt = (EXTRACTION_PROMPT
              .replace("{headline}", article["headline"])
              .replace("{snippet}", article["snippet"] or "(no snippet)"))
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 512,
                "messages":   [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()["content"][0]["text"].strip()
        # Strip potential markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        if not data.get("relevant", False):
            return []
        return data.get("items", [])
    except json.JSONDecodeError as exc:
        log.warning("JSON parse error from Haiku: %s", exc)
        return []
    except Exception as exc:
        log.error("Claude extraction failed: %s", exc)
        return []


# ── intel application ─────────────────────────────────────────────────────────

def _apply_item(item: dict) -> str:
    """
    Apply a single intel item to mundial_2026 state.
    Returns a human-readable description of what was changed.
    """
    from mundial_2026 import (set_fitness, injure_player, apply_intel,
                               find_player, SOURCES as M_SOURCES)
    itype  = item.get("type")
    player = item.get("player")
    team   = item.get("team")
    value  = item.get("value")
    detail = item.get("detail", "")
    direc  = item.get("direction")

    # Resolve player name
    resolved_player = None
    if player:
        resolved_player = find_player(player)
        if not resolved_player:
            return f"⚠️ Jugador no encontrado: {player}"

    if itype == "fitness" and resolved_player and value is not None:
        pct = max(60, min(100, int(value)))
        set_fitness(resolved_player, pct)
        return f"💪 Forma física actualizada: {resolved_player} → {pct}%"

    elif itype == "injury" and resolved_player:
        if value is not None:
            pct = max(60, min(100, int(value)))
            set_fitness(resolved_player, pct)
            return f"🤕 Lesión parcial: {resolved_player} → {pct}%"
        else:
            injure_player(resolved_player)
            return f"🤕 Lesión: {resolved_player} marcado como no disponible"

    elif itype == "suspension" and resolved_player:
        injure_player(resolved_player)
        return f"🟥 Suspensión: {resolved_player} marcado como no disponible"

    elif itype == "form" and team and direc is not None:
        try:
            direction = int(direc)
        except (TypeError, ValueError):
            direction = 0
        if direction != 0:
            intel_tuple = ("auto_news", itype, team, direction, detail)
            apply_intel([intel_tuple])
            arrow = "📈" if direction > 0 else "📉"
            return f"{arrow} Forma de equipo actualizada: {team} ({'+1' if direction > 0 else '-1'})"

    elif itype == "team_note" and team:
        return f"📝 Nota: {team} — {detail}"

    return f"ℹ️ {itype}: {detail}"


# ── tier routing ──────────────────────────────────────────────────────────────

def _route_item(item: dict, source_name: str, article_url: str) -> None:
    """Route an intel item through the three-tier confirmation system."""
    confidence = float(item.get("confidence", 0.5))
    itype      = item.get("type", "")
    player     = item.get("player", "")
    team       = item.get("team", "")
    detail     = item.get("detail", "")

    subject = player or team or "?"
    summary = f"[{source_name}] <b>{subject}</b>: {detail}"

    if confidence >= 0.80:
        # 🟢 HIGH — auto-apply
        result = _apply_item(item)
        _notify(f"🟢 <b>Auto-aplicado</b>\n{summary}\n→ {result}\n<a href='{article_url}'>Fuente</a>")
        log.info("AUTO-APPLIED: %s", detail)

    elif confidence >= 0.55:
        # 🟡 MEDIUM — ask for confirmation
        item_json = json.dumps(item, ensure_ascii=False)
        # Store pending in global for telegram_bot to retrieve via callback
        _pending_items[item_json] = item
        buttons = [[
            {"text": "✅ Aplicar",  "callback_data": f"news_apply||{item_json[:200]}"},
            {"text": "❌ Ignorar",  "callback_data": "news_ignore"},
        ]]
        _notify_with_buttons(
            f"🟡 <b>Confirmar intel</b>\n{summary}\n"
            f"Confianza: {confidence:.0%}\n<a href='{article_url}'>Fuente</a>",
            buttons,
        )
        log.info("PENDING CONFIRM: %s (%.0f%%)", detail, confidence * 100)

    else:
        # 🔴 LOW — log only
        log.info("LOW CONFIDENCE (%.0f%%) SKIPPED: %s", confidence * 100, detail)


# Pending medium-confidence items awaiting user confirmation
# Key = truncated JSON string matching callback_data, Value = full item dict
_pending_items: dict = {}


def get_pending_item(key: str) -> Optional[dict]:
    """Called by telegram_bot to retrieve a pending item by its key."""
    return _pending_items.pop(key, None)


def apply_pending_item(key: str) -> str:
    """Apply a pending item (called when user taps ✅). Returns result string."""
    item = _pending_items.pop(key, None)
    if not item:
        return "⚠️ Elemento no encontrado (ya aplicado o expirado)"
    return _apply_item(item)


# ── main news loop ────────────────────────────────────────────────────────────

def run_news_loop() -> None:
    """
    Daemon loop:
    1. Scrape each source for new articles.
    2. Extract intel via Claude Haiku.
    3. Route via three-tier system.
    4. Sleep SCRAPE_INTERVAL seconds.
    """
    log.info("News intel loop starting")
    if not ANTHROPIC_KEY:
        log.error("ANTHROPIC_API_KEY not set — news loop disabled")
        return

    while True:
        try:
            for source in SOURCES:
                articles = _scrape_articles(source)
                log.info("%s: %d new articles", source["name"], len(articles))
                for article in articles:
                    items = _extract_intel(article)
                    for item in items:
                        _route_item(item, source["name"], article["url"])
                    # Mark as seen regardless of extraction result
                    _seen_articles.add(article["fp"])
                    time.sleep(1)   # be polite to Claude API rate limits
        except Exception as exc:
            log.error("News loop error: %s", exc, exc_info=True)

        time.sleep(SCRAPE_INTERVAL)


# ── standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Test extraction on a sample headline
    test_article = {
        "headline": "Kylian Mbappe returns to full training ahead of France vs Germany",
        "snippet":  "The PSG forward has been nursing a knee injury but completed the full "
                    "session on Thursday, putting him on track to start Saturday's quarter-final.",
        "url":      "https://example.com/test",
        "source_name": "Test",
        "lang":     "en",
        "fp":       "test",
    }
    print("Testing extraction...")
    items = _extract_intel(test_article)
    print(json.dumps(items, indent=2, ensure_ascii=False))
