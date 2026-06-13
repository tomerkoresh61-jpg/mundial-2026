#!/usr/bin/env python3
"""
══════════════════════════════════════════════════════════════════
  FIFA WORLD CUP 2026 — TELEGRAM PREDICTION BOT
  UI: Hebrew, button-driven, minimal free text
  Backend: mundial_2026.py prediction engine
  Auto-sync: auto_sync.py (live events) + news_intel.py (press/articles)
══════════════════════════════════════════════════════════════════

  Setup:
    1. Create bot via @BotFather → get TELEGRAM_BOT_TOKEN
    2. Get your user ID from @userinfobot → set ALLOWED_USER_ID
    3. Set API_FOOTBALL_KEY (api-football.com via RapidAPI)
    4. Set ANTHROPIC_API_KEY (for news intel extraction)
    5. Deploy to Railway (see Procfile)
"""

import os, sys, asyncio, logging, json, threading
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      BotCommand)
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ConversationHandler, filters,
                          ContextTypes)
from telegram.constants import ParseMode
from telegram.error import BadRequest

sys.path.insert(0, os.path.dirname(__file__))
import mundial_2026 as mdl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────
BOT_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER = int(os.environ["ALLOWED_USER_ID"])

# Conversation states
(S_AWAIT_PLAYER, S_AWAIT_FITNESS_CONFIRM,
 S_AWAIT_RESULT_A, S_AWAIT_RESULT_B) = range(4)

# ── Access guard ─────────────────────────────────────────────────
def is_allowed(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == ALLOWED_USER

# ── Keyboards ────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 משחקים קרובים", callback_data="upcoming")],
        [InlineKeyboardButton("⚽ חיזוי ספציפי",  callback_data="pick_group"),
         InlineKeyboardButton("📊 סימולציה",       callback_data="simulate")],
        [InlineKeyboardButton("🔄 עדכון מידע",     callback_data="update_menu"),
         InlineKeyboardButton("🏆 בונוס",          callback_data="bonus")],
        [InlineKeyboardButton("🔍 מה השתנה?",      callback_data="changelog")],
    ])

def kb_time_range():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏰ 24 שעות", callback_data="upc_1"),
         InlineKeyboardButton("📆 3 ימים",  callback_data="upc_3"),
         InlineKeyboardButton("🗓 שבוע",    callback_data="upc_7")],
        [InlineKeyboardButton("🔙 תפריט ראשי", callback_data="main")],
    ])

def kb_groups():
    rows = []
    for i in range(0, 12, 4):
        letters = "ABCDEFGHIJKL"[i:i+4]
        rows.append([InlineKeyboardButton(f"קבוצה {g}", callback_data=f"grp_{g}")
                     for g in letters])
    rows.append([InlineKeyboardButton("🔙 תפריט ראשי", callback_data="main")])
    return InlineKeyboardMarkup(rows)

def kb_update_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏥 כושר / ספק",    callback_data="upd_fitness"),
         InlineKeyboardButton("🟨 כרטיס צהוב",   callback_data="upd_yellow")],
        [InlineKeyboardButton("✅ החלמה",          callback_data="upd_recover"),
         InlineKeyboardButton("⏱️ הארכה (AET)",   callback_data="upd_aet")],
        [InlineKeyboardButton("📋 הרכב אושר",     callback_data="upd_lineup"),
         InlineKeyboardButton("🗑 נקה כרטיסים",   callback_data="upd_clearyellows")],
        [InlineKeyboardButton("📝 הזן תוצאה",     callback_data="upd_result"),
         InlineKeyboardButton("💊 מרכיב",         callback_data="upd_intel")],
        [InlineKeyboardButton("🔙 תפריט ראשי",    callback_data="main")],
    ])

def kb_fitness_values(player: str):
    vals = [60, 70, 75, 80, 85, 90, 95, 100]
    rows = []
    for i in range(0, len(vals), 4):
        rows.append([
            InlineKeyboardButton(f"{v}%", callback_data=f"fit|{player}|{v}")
            for v in vals[i:i+4]
        ])
    rows.append([InlineKeyboardButton("🔙 ביטול", callback_data="update_menu")])
    return InlineKeyboardMarkup(rows)

def kb_match(team_a, team_b, venue, stage):
    key = f"{team_a}||{team_b}||{venue}||{stage}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 למה התוצאה הזאת?",
                              callback_data=f"why||{key}")],
        [InlineKeyboardButton("🔍 השווה מודלים",
                              callback_data=f"compare||{key}")],
        [InlineKeyboardButton("📋 הרכב אושר — שניהם",
                              callback_data=f"lineup||{team_a}||{team_b}")],
        [InlineKeyboardButton("🔙 תפריט ראשי", callback_data="main")],
    ])

def kb_confirm_intel(item_json_b64: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ אשר ועדכן",  callback_data=f"intel_yes||{item_json_b64}"),
         InlineKeyboardButton("❌ התעלם",      callback_data="intel_no")],
    ])

# ── Confidence level ─────────────────────────────────────────────
def confidence_info(team_a: str, team_b: str,
                    hours_to_ko: float = 999) -> tuple[str, str]:
    lc = mdl.LINEUP_CONFIRMED
    conf_a = lc.get(team_a, False)
    conf_b = lc.get(team_b, False)

    if conf_a and conf_b:
        return "🟢", "שני ההרכבים אושרו רשמית"
    if conf_a or conf_b:
        who = team_a if conf_a else team_b
        return "🟡", f"הרכב {who} אושר | השני ממתין"
    if hours_to_ko <= 24:
        return "🟠", "הרכבים טרם אושרו | פחות מ-24 שעות למשחק"
    if hours_to_ko <= 72:
        return "🟠", "הרכבים טרם אושרו | 1-3 ימים למשחק"
    return "🔴", "ספקולטיבי | יותר מ-3 ימים למשחק"

# ── Narrative generator ──────────────────────────────────────────
def generate_narrative(team_a: str, team_b: str,
                       lam_a: float, lam_b: float,
                       factors: dict,
                       w: float, d: float, l: float) -> str:
    parts = []

    # Lead
    if w > 0.55:
        parts.append(f"*{team_a}* מועדפת ברורה ({w*100:.0f}% לניצחון).")
    elif l > 0.55:
        parts.append(f"*{team_b}* מועדפת ברורה ({l*100:.0f}% לניצחון).")
    elif w > l:
        parts.append(f"משחק פתוח עם יתרון קל ל*{team_a}* ({w*100:.0f}%).")
    else:
        parts.append(f"משחק פתוח עם יתרון קל ל*{team_b}* ({l*100:.0f}%).")

    # Unavailable players
    out_a = [p for p, d in mdl.TEAMS[team_a]["players"].items()
             if not d["available"]]
    out_b = [p for p, d in mdl.TEAMS[team_b]["players"].items()
             if not d["available"]]
    if out_a:
        parts.append(f"ל{team_a} חסרים: *{', '.join(out_a[:2])}*.")
    if out_b:
        parts.append(f"ל{team_b} חסרים: *{', '.join(out_b[:2])}*.")

    # Partial fitness
    fit_issues = []
    for team in [team_a, team_b]:
        for p, d in mdl.TEAMS[team]["players"].items():
            if d["available"] and d.get("fitness", 1.0) < 0.88:
                fit_issues.append(f"{p} ({d.get('fitness',1)*100:.0f}%)")
    if fit_issues:
        parts.append(f"שחקנים עם ספק כושר: {', '.join(fit_issues[:2])}.")

    # Home crowd
    crowd_a, crowd_b = factors["crowd"]
    if crowd_a > 1.03:
        parts.append(f"{team_a} נהנית מיתרון ביתי עצום (+{(crowd_a-1)*100:.0f}% התקפה).")
    elif crowd_b > 1.03:
        parts.append(f"{team_b} נהנית מיתרון ביתי עצום (+{(crowd_b-1)*100:.0f}% התקפה).")

    # Set pieces
    sp_a, sp_b = factors["setpiece"]
    if sp_a - sp_b > 0.06:
        parts.append(f"{team_a} עדיפה משמעותית בכדורים עצורים (+{(sp_a-1)*100:.0f}%).")
    elif sp_b - sp_a > 0.06:
        parts.append(f"{team_b} עדיפה משמעותית בכדורים עצורים (+{(sp_b-1)*100:.0f}%).")

    # Star form
    for team in [team_a, team_b]:
        for p, d in mdl.TEAMS[team]["players"].items():
            if d["available"] and d.get("form", 0) >= 2:
                parts.append(f"*{p}* ({team}) בפורמה יוצאת דופן 🔥.")
                break

    # H2H
    h2h_a, h2h_b = factors["h2h"]
    if h2h_a > 1.04:
        parts.append(f"היסטוריה בין הקבוצות נוטה לטובת {team_a}.")
    elif h2h_b > 1.04:
        parts.append(f"היסטוריה בין הקבוצות נוטה לטובת {team_b}.")

    # Extra time
    et_a, et_b = factors["extra_time"]
    if et_a < 1.0:
        parts.append(f"⚠️ {team_a} שיחקה הארכה בסיבוב הקודם (−9%).")
    if et_b < 1.0:
        parts.append(f"⚠️ {team_b} שיחקה הארכה בסיבוב הקודם (−9%).")

    # Dead rubber
    dr_a, dr_b = factors["dead_rubber"]
    if dr_a < 1.0:
        parts.append(f"🔄 {team_a}: משחק ניהולי — רוטציה צפויה.")
    if dr_b < 1.0:
        parts.append(f"🔄 {team_b}: משחק ניהולי — רוטציה צפויה.")

    return " ".join(parts)

# ── Match card builder ────────────────────────────────────────────
def build_match_card(team_a: str, team_b: str,
                     venue: str = "Neutral", stage: str = "group",
                     match_time: str = "",
                     hours_to_ko: float = 999) -> tuple[str, InlineKeyboardMarkup]:
    mdl._load_state()
    lam_a, lam_b, factors = mdl.expected_goals(team_a, team_b, venue, stage=stage)
    P    = mdl.score_matrix(lam_a, lam_b)
    w, d, l = mdl.wdl(P)

    scores = sorted(
        [(i, j, P[i, j]) for i in range(P.shape[0]) for j in range(P.shape[1])],
        key=lambda x: -x[2]
    )

    conf_emoji, conf_text = confidence_info(team_a, team_b, hours_to_ko)
    top3 = " · ".join(f"{s[0]}-{s[1]} ({s[2]*100:.1f}%)" for s in scores[:3])
    best = scores[0]

    # Tournament Pick — result-aware recommendation
    def _best_for(outcome):
        for a_g, b_g, prob in scores:
            if outcome == 'a'    and a_g > b_g: return (a_g, b_g, prob)
            if outcome == 'draw' and a_g == b_g: return (a_g, b_g, prob)
            if outcome == 'b'    and b_g > a_g: return (a_g, b_g, prob)
        return scores[0]

    if w >= 0.40 and w >= l:
        tp = _best_for('a'); tp_label = f"ניצחון {team_a}"
    elif l >= 0.40 and l > w:
        tp = _best_for('b'); tp_label = f"ניצחון {team_b}"
    elif d >= 0.28:
        tp = _best_for('draw'); tp_label = "תיקו"
    elif w >= l:
        tp = _best_for('a'); tp_label = f"יתרון קל ל{team_a}"
    else:
        tp = _best_for('b'); tp_label = f"יתרון קל ל{team_b}"

    # Yellow card warnings
    yc_warns = []
    for team in [team_a, team_b]:
        for p in mdl.TEAMS[team]["players"]:
            yc = mdl.YELLOW_CARDS.get(p, 0)
            if yc >= 1 and mdl.TEAMS[team]["players"][p]["available"]:
                emoji = "🚨" if yc >= 2 else "🟨"
                yc_warns.append(f"{emoji} {p}: {yc} צהוב")

    yc_block = ("\n" + "\n".join(yc_warns)) if yc_warns else ""
    time_str = f" | {match_time}" if match_time else ""
    city = mdl.VENUES.get(venue, {}).get("city", venue)

    text = (
        f"{conf_emoji} _{conf_text}_\n\n"
        f"⚽ *{team_a}* 🆚 *{team_b}*\n"
        f"📍 {city}{time_str}\n"
        f"{yc_block}\n"
        f"🏆 *המלצת טורניר: {team_a} {tp[0]}–{tp[1]} {team_b}*  _({tp_label})_\n"
        f"💡 תוצאה הכי סבירה: {team_a} {best[0]}–{best[1]} {team_b} ({best[2]*100:.1f}%)\n"
        f"{'─'*28}\n"
        f"🎯 {team_a} *{w*100:.0f}%* | תיקו *{d*100:.0f}%* | {team_b} *{l*100:.0f}%*\n"
        f"📊 {top3}"
    )

    return text, kb_match(team_a, team_b, venue, stage)

# ── Handlers ─────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    mdl._load_state()
    await update.message.reply_text(
        "⚽ *מונדיאל 2026 — מנוע חיזוי*\nבחר פעולה:",
        reply_markup=kb_main(),
        parse_mode=ParseMode.MARKDOWN
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    query = update.callback_query
    await query.answer()
    data  = query.data
    mdl._load_state()

    # ── Main menu ──────────────────────────────────────────────
    if data == "main":
        await _edit(query, "⚽ *מונדיאל 2026 — מנוע חיזוי*\nבחר פעולה:",
                    kb_main())
        return

    # ── Upcoming matches ───────────────────────────────────────
    if data == "upcoming":
        await _edit(query, "📅 כמה זמן קדימה?", kb_time_range())
        return

    if data.startswith("upc_"):
        days = int(data[4:])
        await _show_upcoming(query, days)
        return

    # ── Group / match selection ────────────────────────────────
    if data == "pick_group":
        await _edit(query, "בחר קבוצה:", kb_groups())
        return

    if data.startswith("grp_"):
        g = data[4:]
        import itertools
        teams = mdl.GROUPS.get(g, [])
        rows  = []
        for a, b in itertools.combinations(teams, 2):
            rows.append([InlineKeyboardButton(
                f"{a} 🆚 {b}",
                callback_data=f"match||{a}||{b}||Neutral||group"
            )])
        rows.append([InlineKeyboardButton("🔙 בחר קבוצה", callback_data="pick_group")])
        await _edit(query, f"⚽ משחקי קבוצה {g}:", InlineKeyboardMarkup(rows))
        return

    if data.startswith("match||"):
        _, a, b, venue, stage = data.split("||")
        text, kb = build_match_card(a, b, venue, stage)
        await _edit(query, text, kb)
        return

    # ── "Why" explanation ──────────────────────────────────────
    if data.startswith("why||"):
        _, a, b, venue, stage = data.split("||")
        lam_a, lam_b, factors = mdl.expected_goals(a, b, venue, stage=stage)
        P = mdl.score_matrix(lam_a, lam_b)
        w, d, l = mdl.wdl(P)
        narrative = generate_narrative(a, b, lam_a, lam_b, factors, w, d, l)

        def pct(v): return f"{(v-1)*100:+.1f}%"
        sq_a  = factors["squad_a"][0]
        sq_b  = factors["squad_b"][0]
        cr_a, cr_b = factors["crowd"]
        sp_a, sp_b = factors["setpiece"]
        h2_a, h2_b = factors["h2h"]
        rm_a, rm_b = factors["rest"]

        text = (
            f"📖 *ניתוח: {a} 🆚 {b}*\n\n"
            f"{narrative}\n\n"
            f"⚡ *פירוט גורמים (התקפה):*\n"
            f"  סגל:       {a} {pct(sq_a)} | {b} {pct(sq_b)}\n"
            f"  קהל:       {a} {pct(cr_a)} | {b} {pct(cr_b)}\n"
            f"  סט-פיסים: {a} {pct(sp_a)} | {b} {pct(sp_b)}\n"
            f"  היסטוריה:  {a} {pct(h2_a)} | {b} {pct(h2_b)}\n"
            f"  מנוחה:     {a} {pct(rm_a)} | {b} {pct(rm_b)}\n\n"
            f"🎯 xG: *{a} {lam_a:.2f} — {lam_b:.2f} {b}*"
        )
        back_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 חזרה לתחזית",
                                 callback_data=f"match||{a}||{b}||{venue}||{stage}")
        ]])
        await _edit(query, text, back_kb)
        return

    # ── Model comparison ───────────────────────────────────────
    if data.startswith("compare||"):
        _, a, b, venue, stage = data.split("||")
        try:
            from prediction_comparison import compare_match, format_comparison_table
            result = compare_match(a, b, venue=venue, stage=stage)
            text   = format_comparison_table(result)
        except Exception as e:
            log.error("compare_match failed: %s", e)
            text = f"❌ שגיאה בהשוואת מודלים: {e}"
        back_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 חזרה לתחזית",
                                 callback_data=f"match||{a}||{b}||{venue}||{stage}")
        ]])
        await _edit(query, text, back_kb)
        return

    # ── Lineup confirmed ───────────────────────────────────────
    if data.startswith("lineup||"):
        _, a, b = data.split("||")
        mdl.LINEUP_CONFIRMED[a] = True
        mdl.LINEUP_CONFIRMED[b] = True
        mdl._save_state()
        await query.answer("✅ הרכב שתי הקבוצות סומן כמאושר!", show_alert=True)
        return

    # ── Update menu ────────────────────────────────────────────
    if data == "update_menu":
        await _edit(query, "🔄 *עדכון מידע*\nבחר פעולה:", kb_update_menu())
        return

    if data == "upd_clearyellows":
        mdl.clear_yellow_cards()
        await query.answer("✅ כרטיסים צהובים נוקו!", show_alert=True)
        await _edit(query, "🔄 *עדכון מידע*\nבחר פעולה:", kb_update_menu())
        return

    if data in ("upd_fitness", "upd_yellow", "upd_recover", "upd_aet",
                "upd_lineup", "upd_result", "upd_intel"):
        context.user_data["pending"] = data
        prompts = {
            "upd_fitness": "✍️ שם השחקן לעדכון כושר:",
            "upd_yellow":  "✍️ שם השחקן שקיבל כרטיס צהוב:",
            "upd_recover": "✍️ שם השחקן שהחלים:",
            "upd_aet":     "✍️ שם הקבוצה שיחקה הארכה:",
            "upd_lineup":  "✍️ שם הקבוצה שהרכבה אושר:",
            "upd_result":  "✍️ שם קבוצה א׳ (הראשונה):",
            "upd_intel":   "✍️ הזן מידע חופשי (שחקן + פרטים):",
        }
        await _edit(query, prompts[data],
                    InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 ביטול", callback_data="update_menu")
                    ]]))
        return S_AWAIT_PLAYER

    # ── Fitness value selection (inline button) ────────────────
    if data.startswith("fit|"):
        _, pl, val = data.split("|")
        mdl.set_fitness(pl, int(val))
        await _edit(query,
                    f"🏥 *{pl}*: כושר עודכן ל-{val}%\n\n"
                    f"התחזיות הבאות ישקפו שינוי זה.",
                    kb_main())
        context.user_data.clear()
        return ConversationHandler.END

    # ── Intel confirmation ─────────────────────────────────────
    if data.startswith("intel_yes||"):
        import base64
        item = json.loads(base64.b64decode(data.split("||")[1]).decode())
        _apply_intel_item_direct(item)
        await query.answer("✅ הוחל!", show_alert=True)
        await _edit(query, "✅ המידע הוחל על המודל.", kb_main())
        return

    if data == "intel_no":
        await query.answer("❌ התעלמנו מהמידע.", show_alert=True)
        await _edit(query, "🔄 *עדכון מידע*\nבחר פעולה:", kb_update_menu())
        return

    # ── Simulate ───────────────────────────────────────────────
    if data == "simulate":
        await _edit(query, "🎲 מריץ 50,000 סימולציות... (כ-25 שניות)", None)
        probs  = mdl.simulate_tournament()
        ranked = sorted(probs.items(), key=lambda x: -x[1]["champion"])[:10]
        lines  = ["🏆 *סימולציית טורניר — 50K*\n"]
        for i, (t, p) in enumerate(ranked, 1):
            bar = "▓" * int(p["champion"] * 100) + "░" * (20 - int(p["champion"] * 100))
            lines.append(f"{i:>2}. {t:<18} {p['champion']*100:>5.1f}%")
        await _edit(query, "\n".join(lines), kb_main())
        return

    # ── Bonus ──────────────────────────────────────────────────
    if data == "bonus":
        await _edit(query, "🎲 מחשב אלוף + מלך שערים... (כ-35 שניות)", None)
        probs   = mdl.simulate_tournament()
        scorers = mdl.predict_top_scorers(probs)
        ranked  = sorted(probs.items(), key=lambda x: -x[1]["champion"])

        champ        = ranked[0]
        top_scorer   = scorers[0]
        scorer_team  = next(t for t, td in mdl.TEAMS.items()
                            if top_scorer[0] in td["players"])

        top5 = "\n".join(
            f"  {i}. {t} — {p['champion']*100:.1f}%"
            for i, (t, p) in enumerate(ranked[:5], 1)
        )
        text = (
            f"🏆 *ניחוש בונוס*\n\n"
            f"🥇 *אלוף:*  {champ[0]}  ({champ[1]['champion']*100:.1f}%)\n"
            f"🥅 *מלך שערים:*  {top_scorer[0]}  "
            f"({scorer_team}, {top_scorer[1]*100:.1f}%)\n\n"
            f"*טופ 5 אלופות:*\n{top5}"
        )
        await _edit(query, text, kb_main())
        return

    # ── Changelog ─────────────────────────────────────────────
    if data == "changelog":
        await _show_changelog(query)
        return


async def _show_upcoming(query, days: int):
    """Fetch upcoming fixtures, predict each, and send all cards in one message."""
    try:
        from auto_sync import get_upcoming_fixtures
        fixtures = get_upcoming_fixtures(days)
    except Exception:
        fixtures = []

    no_matches_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚽ חיזוי ספציפי", callback_data="pick_group"),
        InlineKeyboardButton("🔙 חזרה",         callback_data="main"),
    ]])

    if not fixtures:
        await _edit(query,
                    f"לא נמצאו משחקים ב-{days} הימים הקרובים.\n"
                    f"(ייתכן שה-API אינו מוגדר — נסה חיזוי ספציפי בדרך הידנית)",
                    no_matches_kb)
        return

    label_map = {1: "24 שעות", 3: "3 ימים", 7: "שבוע"}
    range_label = label_map.get(days, f"{days} ימים")

    now = datetime.now(timezone.utc)
    mdl._load_state()

    cards = []
    for f in fixtures[:12]:
        hours    = (f["kickoff"] - now).total_seconds() / 3600
        date_str = f["kickoff"].strftime("%d/%m %H:%M UTC")
        try:
            card_text, _ = build_match_card(
                f["home"], f["away"], f["venue"], f["stage"],
                match_time=date_str, hours_to_ko=hours
            )
            cards.append(card_text)
        except Exception as e:
            log.warning("Card build failed %s vs %s: %s", f["home"], f["away"], e)
            cards.append(f"⚠️ שגיאה בחיזוי: *{f['home']}* 🆚 *{f['away']}*")

    SEP      = "\n\n" + "━" * 28 + "\n\n"
    header   = f"📅 *משחקים ב-{range_label}* — {len(cards)} משחקים\n"
    MAX_LEN  = 4000

    # Build the message, truncating if it would exceed Telegram's limit
    body_parts = []
    for i, card in enumerate(cards):
        chunk = (SEP if i > 0 else "\n\n") + card
        if len(header) + len("".join(body_parts)) + len(chunk) > MAX_LEN:
            remaining = len(cards) - i
            body_parts.append(f"\n\n_...ועוד {remaining} משחקים (טווח קצר יותר לפרטים)_")
            break
        body_parts.append(chunk)

    full_text = header + "".join(body_parts)

    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 תפריט ראשי", callback_data="main")
    ]])
    await _edit(query, full_text, back_kb)


async def _show_changelog(query):
    """Show what has changed since last session."""
    mdl._load_state()
    lines = ["🔔 *שינויים אחרונים במודל:*\n"]

    # Yellow cards
    yellows = [(p, c) for p, c in mdl.YELLOW_CARDS.items() if c > 0]
    if yellows:
        lines.append("🟨 כרטיסים צהובים:")
        for p, c in yellows:
            lines.append(f"  • {p}: {c}")

    # Fitness < 100%
    low_fit = [(p, d.get("fitness", 1.0), t)
               for t, td in mdl.TEAMS.items()
               for p, d in td["players"].items()
               if d.get("fitness", 1.0) < 0.99]
    if low_fit:
        lines.append("\n🏥 שחקנים עם כושר חלקי:")
        for p, f, t in sorted(low_fit, key=lambda x: x[1])[:6]:
            lines.append(f"  • {p} ({t}): {f*100:.0f}%")

    # Unavailable
    unavail = [(p, t) for t, td in mdl.TEAMS.items()
               for p, d in td["players"].items() if not d["available"]]
    if unavail:
        lines.append("\n🚑 לא זמינים:")
        for p, t in unavail[:5]:
            lines.append(f"  • {p} ({t})")

    # Lineup confirmed
    if mdl.LINEUP_CONFIRMED:
        lines.append(f"\n📋 הרכב אושר: {', '.join(k for k, v in mdl.LINEUP_CONFIRMED.items() if v)}")

    # Extra time
    if mdl.TEAM_EXTRA_TIME:
        lines.append(f"\n⏱️ הארכה: {', '.join(k for k, v in mdl.TEAM_EXTRA_TIME.items() if v)}")

    if len(lines) == 1:
        lines.append("אין שינויים מוגדרים כרגע.")

    await _edit(query, "\n".join(lines), kb_main())


# ── Text input conversation ────────────────────────────────────────
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    mdl._load_state()

    text    = update.message.text.strip()
    pending = context.user_data.get("pending")

    if not pending:
        await update.message.reply_text(
            "בחר פעולה מהתפריט:", reply_markup=kb_main()
        )
        return ConversationHandler.END

    async def reply(msg, kb=None):
        await update.message.reply_text(
            msg, reply_markup=kb or kb_main(), parse_mode=ParseMode.MARKDOWN
        )

    # ── Yellow card ──────────────────────────────────────────
    if pending == "upd_yellow":
        pl = mdl.find_player(text)
        if pl:
            mdl.add_yellow_card(pl)
            await reply(f"🟨 כרטיס צהוב נרשם ל*{pl}*.")
        else:
            await reply(f"❌ לא נמצא שחקן בשם *{text}*.", kb_update_menu())
        context.user_data.clear()
        return ConversationHandler.END

    # ── Recover ──────────────────────────────────────────────
    if pending == "upd_recover":
        pl = mdl.find_player(text)
        if pl:
            mdl.recover_player(pl)
            await reply(f"✅ *{pl}* מסומן כזמין.")
        else:
            await reply(f"❌ לא נמצא שחקן *{text}*.", kb_update_menu())
        context.user_data.clear()
        return ConversationHandler.END

    # ── AET ──────────────────────────────────────────────────
    if pending == "upd_aet":
        t = mdl.find_team(text)
        if t:
            mdl.mark_extra_time(t)
            await reply(f"⏱️ *{t}*: מסומנת עם הארכה (−9% במשחק הבא).")
        else:
            await reply(f"❌ לא נמצאה קבוצה *{text}*.", kb_update_menu())
        context.user_data.clear()
        return ConversationHandler.END

    # ── Lineup confirm ────────────────────────────────────────
    if pending == "upd_lineup":
        t = mdl.find_team(text)
        if t:
            mdl.LINEUP_CONFIRMED[t] = True
            mdl._save_state()
            await reply(f"📋 הרכב *{t}* סומן כמאושר ✅")
        else:
            await reply(f"❌ לא נמצאה קבוצה *{text}*.", kb_update_menu())
        context.user_data.clear()
        return ConversationHandler.END

    # ── Fitness: step 1 — get player name ────────────────────
    if pending == "upd_fitness":
        pl = mdl.find_player(text)
        if pl:
            context.user_data["fit_player"] = pl
            context.user_data["pending"] = "upd_fitness_val"
            await update.message.reply_text(
                f"🏥 *{pl}* — בחר כושר:",
                reply_markup=kb_fitness_values(pl),
                parse_mode=ParseMode.MARKDOWN
            )
            return S_AWAIT_FITNESS_CONFIRM
        else:
            await reply(f"❌ לא נמצא שחקן *{text}*.", kb_update_menu())
            context.user_data.clear()
            return ConversationHandler.END

    # ── Result: step 1 — team A ───────────────────────────────
    if pending == "upd_result":
        t = mdl.find_team(text)
        if t:
            context.user_data["result_a"] = t
            context.user_data["pending"]  = "upd_result_b"
            await reply(f"✍️ שם קבוצה ב׳ (נגד {t}):")
            return S_AWAIT_RESULT_A
        else:
            await reply(f"❌ לא נמצאה קבוצה *{text}*.")
            context.user_data.clear()
            return ConversationHandler.END

    if pending == "upd_result_b":
        t = mdl.find_team(text)
        if t:
            context.user_data["result_b"] = t
            context.user_data["pending"]  = "upd_result_goals"
            ta = context.user_data["result_a"]
            await reply(f"✍️ שערים של {ta}:")
            return S_AWAIT_RESULT_B
        else:
            await reply(f"❌ לא נמצאה קבוצה *{text}*.")
            context.user_data.clear()
            return ConversationHandler.END

    if pending == "upd_result_goals":
        try:
            ga = int(text)
            context.user_data["goals_a"]  = ga
            context.user_data["pending"]  = "upd_result_goals_b"
            tb = context.user_data["result_b"]
            await reply(f"✍️ שערים של {tb}:")
        except ValueError:
            await reply("❌ אנא הזן מספר.")
        return S_AWAIT_RESULT_B

    if pending == "upd_result_goals_b":
        try:
            gb = int(text)
            ta = context.user_data["result_a"]
            tb = context.user_data["result_b"]
            ga = context.user_data["goals_a"]
            mdl.update_result(ta, tb, ga, gb)
            await reply(f"✅ תוצאה עודכנה: *{ta} {ga}–{gb} {tb}*")
        except ValueError:
            await reply("❌ אנא הזן מספר.")
        context.user_data.clear()
        return ConversationHandler.END

    # ── Free-form intel ───────────────────────────────────────
    if pending == "upd_intel":
        await reply(
            f"📝 נרשם: _{text}_\n\n"
            f"(מידע חופשי נשמר ביומן. לעדכון אוטומטי השתמש ב-fitness/injure/form)",
            kb_main()
        )
        context.user_data.clear()
        return ConversationHandler.END

    context.user_data.clear()
    return ConversationHandler.END


# ── Helpers ───────────────────────────────────────────────────────
async def _edit(query, text: str, keyboard):
    try:
        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
    except BadRequest:
        pass  # message not modified


def _apply_intel_item_direct(item: dict):
    """Apply a single intel item (from news_intel confirmation)."""
    mdl._load_state()
    itype  = item.get("type", "")
    player = mdl.find_player(item["player"]) if item.get("player") else None
    team   = mdl.find_team(item["team"])     if item.get("team")   else None
    value  = item.get("value")
    if itype == "fitness" and player and value:
        mdl.set_fitness(player, int(value))
    elif itype == "injury" and player:
        mdl.injure_player(player)
    elif itype == "form" and player and value:
        mdl.set_player_form(player, int(value))
    elif itype == "team_form" and team and value:
        mdl.set_team_form(team, int(value))


# ── Notification sender (called from auto_sync / news_intel) ──────
async def send_notification(bot, text: str, keyboard=None):
    await bot.send_message(
        chat_id=ALLOWED_USER,
        text=text,
        reply_markup=keyboard or kb_main(),
        parse_mode=ParseMode.MARKDOWN
    )


# ── Background threads ────────────────────────────────────────────
def _start_background_workers():
    """Launch auto_sync and news_intel in background threads."""
    try:
        from auto_sync  import run_sync_loop
        from news_intel import run_news_loop
        threading.Thread(target=run_sync_loop,  daemon=True, name="sync").start()
        threading.Thread(target=run_news_loop,  daemon=True, name="news").start()
        log.info("Background workers started.")
    except ImportError as e:
        log.warning(f"Background workers not started: {e}")


# ── Main ─────────────────────────────────────────────────────────
def main():
    mdl._load_state()

    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler for multi-step text inputs
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(on_button)],
        states={
            S_AWAIT_PLAYER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_text),
                CallbackQueryHandler(on_button),
            ],
            S_AWAIT_FITNESS_CONFIRM: [
                CallbackQueryHandler(on_button, pattern=r"^fit\|"),
                CallbackQueryHandler(on_button),
            ],
            S_AWAIT_RESULT_A: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_text),
            ],
            S_AWAIT_RESULT_B: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_text),
            ],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(on_button, pattern="^main$"),
        ],
        per_message=False,
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(on_button))   # fallback

    # Set bot commands
    async def post_init(app):
        await app.bot.set_my_commands([
            BotCommand("start", "פתח תפריט ראשי"),
        ])

    app.post_init = post_init

    _start_background_workers()

    log.info("⚽ WC2026 Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
