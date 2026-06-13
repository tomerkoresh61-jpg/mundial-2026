#!/usr/bin/env python3
"""
══════════════════════════════════════════════════════════════════════
  FIFA WORLD CUP 2026 — PRO PREDICTION ENGINE
  Resolution: Betting-agency grade
══════════════════════════════════════════════════════════════════════

  Model layers (in order of application):
    1. Base strength       — xG-calibrated attack/defense per team
    2. Squad strength      — per-player ratings × availability × fitness × form
    3. Environmental       — altitude, temperature, humidity by venue
    4. Physical            — rest days, cumulative fatigue, travel stress
    5. Tactical matchup    — style interactions (press vs counter, etc.)
    6. Head-to-head        — psychological/historical edge
    7. Motivation          — stage, rivalry, revenge, must-win pressure
    8. External sources     — Opta/PELE/Klement/market consensus + intel gaps
    9. Dixon-Coles Poisson — corrected exact score probability distribution

  Requirements: pip install numpy

  Usage (interactive):
    python mundial_2026.py

  Usage (CLI):
    python mundial_2026.py predict France Norway --venue Dallas --rest 4 3
    python mundial_2026.py group I --venue Dallas
    python mundial_2026.py simulate
    python mundial_2026.py bonus
    python mundial_2026.py update France Iraq 4 0
    python mundial_2026.py injure Mbappe
    python mundial_2026.py recover Mbappe
    python mundial_2026.py form France +2
    python mundial_2026.py report France Norway
══════════════════════════════════════════════════════════════════════
"""

import numpy as np
import math
import json
import sys
import os
import itertools
from collections import Counter, defaultdict

# ─────────────────────────────────────────────────────────────
# GLOBAL CONSTANTS
# ─────────────────────────────────────────────────────────────
BASE_GOALS  = 1.33    # Average WC goals per team per game (2014–2022 avg)
RHO         = -0.13   # Dixon-Coles low-score correlation
N_SIMS      = 50_000  # Monte Carlo iterations
STATE_FILE  = os.path.join(os.path.dirname(__file__), "wc2026_state.json")

# ══════════════════════════════════════════════════════════════
# 1. GROUP DRAW
# ══════════════════════════════════════════════════════════════
GROUPS = {
    "A": ["Mexico",    "South Africa",          "South Korea",  "Czechia"],
    "B": ["Canada",    "Bosnia and Herzegovina", "Qatar",        "Switzerland"],
    "C": ["Brazil",    "Morocco",               "Haiti",        "Scotland"],
    "D": ["USA",       "Paraguay",              "Australia",    "Turkey"],
    "E": ["Germany",   "Curacao",               "Ivory Coast",  "Ecuador"],
    "F": ["Netherlands","Japan",                "Sweden",       "Tunisia"],
    "G": ["Belgium",   "Egypt",                 "Iran",         "New Zealand"],
    "H": ["Spain",     "Cape Verde",            "Saudi Arabia", "Uruguay"],
    "I": ["France",    "Senegal",               "Iraq",         "Norway"],
    "J": ["Argentina", "Algeria",               "Austria",      "Jordan"],
    "K": ["Portugal",  "DR Congo",              "Uzbekistan",   "Colombia"],
    "L": ["England",   "Croatia",               "Ghana",        "Panama"],
}
TEAM_TO_GROUP = {t: g for g, ts in GROUPS.items() for t in ts}

# ══════════════════════════════════════════════════════════════
# 2. VENUE DATABASE
# ══════════════════════════════════════════════════════════════
# Each venue carries environmental multipliers that adjust expected goals.
# altitude_m : altitude in metres  → oxygen deficit hits non-adapted teams hard
# temp_c     : average June temperature at that city
# humidity   : relative humidity 0–1
# Surface    : grass (all WC venues), but turf type can differ slightly
#
# Altitude effect on non-adapted teams (calibrated from empirical data):
#   Azteca studies show ~10-15% reduction in high-intensity sprints at 2240m
#   for non-altitude-adapted teams. This manifests as reduced effective attack.
VENUES = {
    # ── USA ────────────────────────────────────────────────
    "MetLife":      {"city": "New York",       "altitude_m": 8,    "temp_c": 24, "humidity": 0.65},
    "ATT":          {"city": "Dallas",         "altitude_m": 185,  "temp_c": 35, "humidity": 0.60},
    "SoFi":         {"city": "Los Angeles",    "altitude_m": 30,   "temp_c": 22, "humidity": 0.55},
    "RoseBowl":     {"city": "Pasadena",       "altitude_m": 260,  "temp_c": 28, "humidity": 0.42},
    "Levis":        {"city": "San Francisco",  "altitude_m": 22,   "temp_c": 18, "humidity": 0.72},
    "Arrowhead":    {"city": "Kansas City",    "altitude_m": 320,  "temp_c": 31, "humidity": 0.72},
    "Gillette":     {"city": "Boston",         "altitude_m": 15,   "temp_c": 22, "humidity": 0.68},
    "Lincoln":      {"city": "Philadelphia",   "altitude_m": 11,   "temp_c": 25, "humidity": 0.67},
    "HardRock":     {"city": "Miami",          "altitude_m": 2,    "temp_c": 33, "humidity": 0.82},
    "Lumen":        {"city": "Seattle",        "altitude_m": 17,   "temp_c": 19, "humidity": 0.72},
    "NRG":          {"city": "Houston",        "altitude_m": 15,   "temp_c": 33, "humidity": 0.78},
    "Mercedes":     {"city": "Atlanta",        "altitude_m": 315,  "temp_c": 28, "humidity": 0.65},
    # ── Canada ─────────────────────────────────────────────
    "BMO":          {"city": "Toronto",        "altitude_m": 76,   "temp_c": 23, "humidity": 0.68},
    "BCPlace":      {"city": "Vancouver",      "altitude_m": 4,    "temp_c": 18, "humidity": 0.72},
    # ── Mexico ─────────────────────────────────────────────
    "Azteca":       {"city": "Mexico City",    "altitude_m": 2240, "temp_c": 18, "humidity": 0.43},
    "Akron":        {"city": "Guadalajara",    "altitude_m": 1566, "temp_c": 22, "humidity": 0.50},
    "BBVA":         {"city": "Monterrey",      "altitude_m": 538,  "temp_c": 32, "humidity": 0.55},
    # ── Neutral (default for simulations) ──────────────────
    "Neutral":      {"city": "Neutral",        "altitude_m": 50,   "temp_c": 22, "humidity": 0.60},
}

# Teams naturally adapted to altitude (training/playing at high altitude)
ALTITUDE_ADAPTED = {
    "Ecuador":   2850,  # Quito = 2850m, fully adapted
    "Colombia":  1600,  # Bogotá = 2600m, Medellín = 1500m, well adapted
    "Mexico":    2240,  # Mexico City
    "Bolivia":   3600,  # not in WC but for reference
    "Argentina": 1200,  # Buenos Aires = 25m BUT camp at altitude regularly
    "Morocco":    400,  # some high-altitude training
    "Algeria":    800,  # some high-altitude areas
    "Peru":      1500,  # not in WC but reference
}
# Teams with heat/humidity adaptation (play in hot climates regularly)
HEAT_ADAPTED = {
    "Saudi Arabia": 40, "Egypt": 35, "Iraq": 42, "Qatar": 42,
    "Iran": 35,         "Morocco": 35, "Senegal": 33, "Ghana": 32,
    "Ivory Coast": 30,  "Tunisia": 32, "Cape Verde": 30,
    "Mexico": 30,       "Colombia": 28, "Ecuador": 25, "Paraguay": 30,
    "Uruguay": 25,      "Brazil": 30,   "Australia": 28, "DR Congo": 30,
}

# ══════════════════════════════════════════════════════════════
# 2b. HOME CROWD / SET PIECES / MATCH STATE
# ══════════════════════════════════════════════════════════════

# Maps venue → host nation (crowd boost applies only when that nation plays there)
VENUE_HOME_NATION = {
    "Azteca": "Mexico", "Akron": "Mexico", "BBVA": "Mexico",
    "MetLife": "USA", "ATT": "USA", "SoFi": "USA", "RoseBowl": "USA",
    "Levis": "USA", "Arrowhead": "USA", "Gillette": "USA",
    "Lincoln": "USA", "HardRock": "USA", "Lumen": "USA",
    "NRG": "USA", "Mercedes": "USA",
    "BMO": "Canada", "BCPlace": "Canada",
}

# Set piece attack / defense ratings (sp_att, sp_def) — league average = 0.50
# Calibrated from WC/ECL set-piece goal share + squad aerial profiles
# ~30% of WC goals come from set pieces → max swing ≈ ±9% on lam
SET_PIECE_RATINGS = {
    # (sp_att, sp_def)
    "England":     (0.74, 0.65),  # Bellingham/Gallagher delivery, tall squad
    "Netherlands": (0.72, 0.67),  # van Dijk / Timber aerial dominance
    "Morocco":     (0.67, 0.59),  # En-Nesyri headers, physical backline
    "Germany":     (0.66, 0.68),  # Rüdiger, Havertz aerial; organised defence
    "France":      (0.65, 0.72),  # Griezmann delivery; Saliba/Upamecano in air
    "Portugal":    (0.64, 0.62),  # Ronaldo free-kick, Ruben Dias
    "Norway":      (0.63, 0.54),  # Haaland lethal from corners
    "Belgium":     (0.62, 0.57),  # Vertonghen legacy; Lukaku target
    "Croatia":     (0.60, 0.59),  # Gvardiol + set-piece organisation
    "Argentina":   (0.60, 0.62),  # Messi FK; Romero aerial
    "Serbia":      (0.58, 0.55),
    "Sweden":      (0.57, 0.55),
    "Uruguay":     (0.57, 0.57),  # Gimenez, Godin legacy
    "Senegal":     (0.57, 0.53),  # physically dominant
    "Brazil":      (0.56, 0.60),  # Marquinhos + Militao aerial
    "Spain":       (0.55, 0.58),  # technical but smaller — less aerial threat
    "Colombia":    (0.54, 0.51),
    "USA":         (0.54, 0.52),
    "Austria":     (0.54, 0.55),
    "Switzerland": (0.53, 0.55),
    "Turkey":      (0.53, 0.52),
    "Poland":      (0.53, 0.53),
    "Czechia":     (0.52, 0.53),
    "Canada":      (0.51, 0.50),
    "Mexico":      (0.51, 0.50),
    "Ecuador":     (0.50, 0.50),
    "Scotland":    (0.54, 0.53),
    "Romania":     (0.51, 0.52),
    "South Africa":(0.49, 0.49),
    "Ghana":       (0.49, 0.49),
    "Iran":        (0.49, 0.50),
    "Algeria":     (0.49, 0.50),
    "Panama":      (0.44, 0.46),
    "South Korea": (0.44, 0.47),
    "Australia":   (0.47, 0.48),
    "Japan":       (0.42, 0.46),  # smaller squad, less aerial
    "Saudi Arabia":(0.38, 0.45),
    "Iraq":        (0.40, 0.44),
    "Tunisia":     (0.46, 0.48),
    "Egypt":       (0.48, 0.49),
    "Jordan":      (0.43, 0.45),
    "Uzbekistan":  (0.43, 0.45),
    "DR Congo":    (0.49, 0.49),
    "Ivory Coast": (0.50, 0.49),
    "Bosnia and Herzegovina": (0.54, 0.53),
    "Paraguay":    (0.50, 0.50),
    "Haiti":       (0.43, 0.44),
    "Qatar":       (0.41, 0.43),
    "New Zealand": (0.48, 0.48),
    "Curacao":     (0.42, 0.44),
    "Cape Verde":  (0.46, 0.47),
}

# ══════════════════════════════════════════════════════════════
# 2c. SQUAD MARKET VALUES (Transfermarkt, June 2026, €M)
# ══════════════════════════════════════════════════════════════
# Source: Transfermarkt squad total values as of tournament start.
# Reflects depth + star quality. Used as Layer 12 in expected_goals().
# Update these manually each tournament round if values shift materially.
SQUAD_MARKET_VALUE: dict[str, float] = {
    # Elite tier
    "England":      1100.0,
    "France":        950.0,
    "Spain":        1050.0,
    "Brazil":        900.0,
    "Germany":       850.0,
    "Portugal":      740.0,
    "Netherlands":   620.0,
    "Argentina":     780.0,
    # Strong tier
    "Belgium":       420.0,
    "Norway":        390.0,
    "Colombia":      310.0,
    "Uruguay":       270.0,
    "Switzerland":   280.0,
    "Croatia":       260.0,
    "Turkey":        240.0,
    "USA":           230.0,
    "Austria":       220.0,
    "Denmark":       200.0,
    "Sweden":        180.0,
    "South Korea":   160.0,
    "Japan":         155.0,
    "Mexico":        145.0,
    "Senegal":       135.0,
    "Morocco":       130.0,
    "Canada":        130.0,
    "Ecuador":        90.0,
    "Australia":      88.0,
    "Czechia":        85.0,
    "Serbia":         80.0,
    "Poland":         75.0,
    "Scotland":       70.0,
    "Ivory Coast":    68.0,
    "Algeria":        62.0,
    "Tunisia":        58.0,
    "Ghana":          55.0,
    "DR Congo":       48.0,
    "Iran":           42.0,
    "Paraguay":       40.0,
    "Egypt":          38.0,
    "Bosnia and Herzegovina": 35.0,
    "Jordan":         22.0,
    "Uzbekistan":     20.0,
    "South Africa":   18.0,
    "Saudi Arabia":   16.0,
    "New Zealand":    14.0,
    "Qatar":          13.0,
    "Cape Verde":     12.0,
    "Panama":         11.0,
    "Curacao":         9.0,
    "Haiti":           7.0,
    "Iraq":            6.5,
}

# ══════════════════════════════════════════════════════════════
# 2d. TEAM ELO RATINGS (live — updated after each match)
# ══════════════════════════════════════════════════════════════
# Initial values calibrated from FIFA ranking + recent tournament form.
# Persisted to team_ratings.json and reloaded on startup.
# Updated by auto_sync.update_elo_after_match() after each FT/AET/PEN result.
RATINGS_FILE = os.path.join(os.path.dirname(__file__), "team_ratings.json")

TEAM_RATINGS: dict[str, float] = {
    # Elite (FIFA top 5)
    "France":        1900.0,
    "Argentina":     1890.0,
    "England":       1880.0,
    "Brazil":        1870.0,
    "Spain":         1875.0,
    # Second tier
    "Portugal":      1840.0,
    "Netherlands":   1830.0,
    "Belgium":       1820.0,
    "Germany":       1815.0,
    "Morocco":       1790.0,
    "Norway":        1780.0,
    "USA":           1750.0,
    "Colombia":      1745.0,
    "Uruguay":       1740.0,
    "Switzerland":   1735.0,
    "Croatia":       1730.0,
    "South Korea":   1720.0,
    "Japan":         1715.0,
    "Turkey":        1710.0,
    "Austria":       1700.0,
    "Sweden":        1695.0,
    "Senegal":       1690.0,
    "Mexico":        1685.0,
    "Czechia":       1680.0,
    "Australia":     1670.0,
    "Ecuador":       1665.0,
    "Algeria":       1650.0,
    "Ivory Coast":   1640.0,
    "Canada":        1635.0,
    "Serbia":        1625.0,
    "Poland":        1620.0,
    "Tunisia":       1610.0,
    "Scotland":      1605.0,
    "Denmark":       1600.0,
    "Ghana":         1580.0,
    "Iran":          1570.0,
    "Egypt":         1565.0,
    "Paraguay":      1555.0,
    "DR Congo":      1550.0,
    "South Africa":  1535.0,
    "Bosnia and Herzegovina": 1525.0,
    "Saudi Arabia":  1510.0,
    "Jordan":        1490.0,
    "Uzbekistan":    1480.0,
    "New Zealand":   1460.0,
    "Qatar":         1445.0,
    "Cape Verde":    1430.0,
    "Panama":        1410.0,
    "Curacao":       1390.0,
    "Haiti":         1365.0,
    "Iraq":          1360.0,
}

# Yellow card accumulation per player {player_name: card_count}
# Updated via `yellow <player>` command; reset between stages via `clear-yellows`
YELLOW_CARDS: dict = {}

# Extra time fatigue {team_name: True} — set when a team played 120 min last round
# Cleared automatically when update_result is called for that team's next match
TEAM_EXTRA_TIME: dict = {}

# Official lineup confirmed {team_name: True} — set 75 min before kickoff
# Raises confidence level in bot display; auto-set by auto_sync.py
LINEUP_CONFIRMED: dict = {}

# ══════════════════════════════════════════════════════════════
# 3. TACTICAL PROFILES
# ══════════════════════════════════════════════════════════════
# Each team has a primary style. Tactical interactions create multipliers.
#
# Style options:
#   "high_press"   — intense pressing, high defensive line, risky
#   "possession"   — patient buildup, high technical quality required
#   "counter"      — deep block + rapid transition, efficient
#   "direct"       — vertical, physical, set-piece focused
#   "balanced"     — adapts to opponent
#
# TACTICAL_MATRIX[style_a][style_b] = (attack_mult_a, attack_mult_b)
# A >1.0 means style A is advantaged vs style B in attack terms

TACTICAL_MATRIX = {
    # When A plays against B → attack multiplier for A
    "high_press": {
        "possession":  1.06,   # press disrupts slow buildup
        "counter":     0.93,   # counter beats high line
        "direct":      1.02,
        "high_press":  1.00,
        "balanced":    1.02,
    },
    "possession": {
        "high_press":  0.95,   # press can disrupt possession
        "counter":     0.98,   # counter absorbs possession well
        "direct":      1.05,   # technical quality vs physicality
        "possession":  1.00,
        "balanced":    1.02,
    },
    "counter": {
        "high_press":  1.06,   # exploit space behind high line
        "possession":  1.02,
        "direct":      0.98,
        "counter":     1.00,
        "balanced":    1.01,
    },
    "direct": {
        "high_press":  0.98,
        "possession":  0.96,
        "counter":     1.03,
        "direct":      1.00,
        "balanced":    0.99,
    },
    "balanced": {
        "high_press":  0.99,
        "possession":  0.98,
        "counter":     0.99,
        "direct":      1.01,
        "balanced":    1.00,
    },
}

# ══════════════════════════════════════════════════════════════
# 4. TEAM MASTER DATA
# ══════════════════════════════════════════════════════════════
# attack, defense  : xG-calibrated base ratings (1.0 = tournament average)
# rank             : FIFA April 2026 ranking
# style            : tactical profile
# altitude_home    : typical home altitude (for adaptation modelling)
# pressure_index   : 0–1 how well this team historically performs under
#                    tournament pressure (1.0 = excellent big-game mentality)
# depth_score      : 0–1 squad depth quality (how much drop from starters)
# players          : KEY players only → those whose absence materially affects
#                    the team's strength. Each entry:
#                      role       : "attack" | "defense" | "midfield" | "gk"
#                      attack_imp : % by which team ATTACK drops if unavailable
#                      defense_imp: % by which team DEFENSE weakens if unavailable
#                      goals_rate : expected goals per game played (for top scorer model)
#                      available  : True (updated live via `injure` command)
#                      form       : -2 to +2 relative to season average

TEAMS = {

    # ══ GROUP A ════════════════════════════════════════════

    "Mexico": {
        "attack": 1.30, "defense": 1.10, "rank": 15,
        "style": "balanced", "altitude_home": 2240,
        "pressure_index": 0.75, "depth_score": 0.70,
        "players": {
            "Hirving Lozano":   {"role":"attack",  "attack_imp":0.14, "defense_imp":0.01, "goals_rate":0.42, "available":True, "form":0, "fitness":1.0},
            "Raul Jimenez":     {"role":"attack",  "attack_imp":0.16, "defense_imp":0.00, "goals_rate":0.45, "available":True, "form":0, "fitness":1.0},
            "Edson Alvarez":    {"role":"midfield","attack_imp":0.06, "defense_imp":0.10, "goals_rate":0.08, "available":True, "form":0, "fitness":1.0},
            "Andres Guardado":  {"role":"midfield","attack_imp":0.07, "defense_imp":0.06, "goals_rate":0.05, "available":True, "form":0, "fitness":1.0},
            "Guillermo Ochoa":  {"role":"gk",      "attack_imp":0.00, "defense_imp":0.15, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },
    "South Africa": {
        "attack": 0.80, "defense": 1.30, "rank": 58,
        "style": "counter", "altitude_home": 1400,
        "pressure_index": 0.60, "depth_score": 0.45,
        "players": {
            "Percy Tau":        {"role":"attack",  "attack_imp":0.18, "defense_imp":0.01, "goals_rate":0.30, "available":True, "form":0, "fitness":1.0},
            "Lyle Foster":      {"role":"attack",  "attack_imp":0.14, "defense_imp":0.00, "goals_rate":0.25, "available":True, "form":0, "fitness":1.0},
            "Themba Zwane":     {"role":"midfield","attack_imp":0.12, "defense_imp":0.03, "goals_rate":0.18, "available":True, "form":0, "fitness":1.0},
        }
    },
    "South Korea": {
        "attack": 1.25, "defense": 1.05, "rank": 22,
        "style": "high_press", "altitude_home": 50,
        "pressure_index": 0.72, "depth_score": 0.65,
        "players": {
            "Son Heung-min":        {"role":"attack",  "attack_imp":0.28, "defense_imp":0.01, "goals_rate":0.55, "available":True, "form":0, "fitness":1.0},
            "Hwang In-beom":        {"role":"midfield","attack_imp":0.10, "defense_imp":0.08, "goals_rate":0.15, "available":True, "form":0, "fitness":1.0},
            "Lee Jae-sung":         {"role":"midfield","attack_imp":0.08, "defense_imp":0.07, "goals_rate":0.12, "available":True, "form":0, "fitness":1.0},
            "Kim Min-jae":          {"role":"defense", "attack_imp":0.02, "defense_imp":0.18, "goals_rate":0.03, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Czechia": {
        "attack": 1.10, "defense": 1.10, "rank": 34,
        "style": "balanced", "altitude_home": 200,
        "pressure_index": 0.62, "depth_score": 0.55,
        "players": {
            "Patrik Schick":        {"role":"attack",  "attack_imp":0.24, "defense_imp":0.00, "goals_rate":0.48, "available":True, "form":0, "fitness":1.0},
            "Tomas Soucek":         {"role":"midfield","attack_imp":0.10, "defense_imp":0.10, "goals_rate":0.15, "available":True, "form":0, "fitness":1.0},
            "Vladimir Coufal":      {"role":"defense", "attack_imp":0.05, "defense_imp":0.10, "goals_rate":0.02, "available":True, "form":0, "fitness":1.0},
        }
    },

    # ══ GROUP B ════════════════════════════════════════════

    "Canada": {
        "attack": 1.25, "defense": 1.10, "rank": 38,
        "style": "high_press", "altitude_home": 100,
        "pressure_index": 0.65, "depth_score": 0.62,
        "players": {
            "Alphonso Davies":      {"role":"attack",  "attack_imp":0.22, "defense_imp":0.04, "goals_rate":0.38, "available":True, "form":0, "fitness":1.0},
            "Jonathan David":       {"role":"attack",  "attack_imp":0.24, "defense_imp":0.00, "goals_rate":0.52, "available":True, "form":0, "fitness":1.0},
            "Stephen Eustaquio":    {"role":"midfield","attack_imp":0.10, "defense_imp":0.08, "goals_rate":0.10, "available":True, "form":0, "fitness":1.0},
            "Tajon Buchanan":       {"role":"attack",  "attack_imp":0.12, "defense_imp":0.01, "goals_rate":0.20, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Bosnia and Herzegovina": {
        "attack": 1.10, "defense": 1.20, "rank": 55,
        "style": "direct", "altitude_home": 500,
        "pressure_index": 0.60, "depth_score": 0.50,
        "players": {
            "Edin Dzeko":           {"role":"attack",  "attack_imp":0.22, "defense_imp":0.00, "goals_rate":0.40, "available":True, "form":0, "fitness":1.0},
            "Miralem Pjanic":       {"role":"midfield","attack_imp":0.14, "defense_imp":0.08, "goals_rate":0.08, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Qatar": {
        "attack": 0.85, "defense": 1.25, "rank": 37,
        "style": "counter", "altitude_home": 10,
        "pressure_index": 0.55, "depth_score": 0.40,
        "players": {
            "Akram Afif":           {"role":"attack",  "attack_imp":0.26, "defense_imp":0.01, "goals_rate":0.35, "available":True, "form":0, "fitness":1.0},
            "Almoez Ali":           {"role":"attack",  "attack_imp":0.18, "defense_imp":0.00, "goals_rate":0.28, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Switzerland": {
        "attack": 1.25, "defense": 0.95, "rank": 19,
        "style": "balanced", "altitude_home": 600,
        "pressure_index": 0.75, "depth_score": 0.68,
        "players": {
            "Xherdan Shaqiri":      {"role":"attack",  "attack_imp":0.16, "defense_imp":0.01, "goals_rate":0.30, "available":True, "form":0, "fitness":1.0},
            "Granit Xhaka":         {"role":"midfield","attack_imp":0.12, "defense_imp":0.12, "goals_rate":0.10, "available":True, "form":0, "fitness":1.0},
            "Remo Freuler":         {"role":"midfield","attack_imp":0.08, "defense_imp":0.10, "goals_rate":0.08, "available":True, "form":0, "fitness":1.0},
            "Yann Sommer":          {"role":"gk",      "attack_imp":0.00, "defense_imp":0.14, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },

    # ══ GROUP C ════════════════════════════════════════════

    "Brazil": {
        "attack": 1.75, "defense": 0.85, "rank": 5,
        "style": "possession", "altitude_home": 800,
        "pressure_index": 0.72, "depth_score": 0.90,
        "players": {
            "Vinicius Jr":      {"role":"attack",  "attack_imp":0.22, "defense_imp":0.01, "goals_rate":0.62, "available":True, "form":0, "fitness":1.0},
            "Rodrygo":          {"role":"attack",  "attack_imp":0.14, "defense_imp":0.01, "goals_rate":0.40, "available":True, "form":0, "fitness":1.0},
            "Endrick":          {"role":"attack",  "attack_imp":0.16, "defense_imp":0.00, "goals_rate":0.48, "available":True, "form":0, "fitness":1.0},
            "Raphinha":         {"role":"attack",  "attack_imp":0.14, "defense_imp":0.01, "goals_rate":0.45, "available":True, "form":0, "fitness":1.0},
            "Casemiro":         {"role":"midfield","attack_imp":0.04, "defense_imp":0.15, "goals_rate":0.08, "available":True, "form":0, "fitness":1.0},
            "Marquinhos":       {"role":"defense", "attack_imp":0.01, "defense_imp":0.14, "goals_rate":0.02, "available":True, "form":0, "fitness":1.0},
            "Alisson":          {"role":"gk",      "attack_imp":0.00, "defense_imp":0.18, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Morocco": {
        "attack": 1.30, "defense": 0.80, "rank": 14,
        "style": "counter", "altitude_home": 500,
        "pressure_index": 0.85, "depth_score": 0.72,
        "players": {
            "Achraf Hakimi":    {"role":"attack",  "attack_imp":0.15, "defense_imp":0.08, "goals_rate":0.28, "available":True, "form":0, "fitness":1.0},
            "Hakim Ziyech":     {"role":"attack",  "attack_imp":0.18, "defense_imp":0.01, "goals_rate":0.32, "available":True, "form":0, "fitness":1.0},
            "Youssef En-Nesyri":{"role":"attack",  "attack_imp":0.20, "defense_imp":0.00, "goals_rate":0.45, "available":True, "form":0, "fitness":1.0},
            "Sofyan Amrabat":   {"role":"midfield","attack_imp":0.04, "defense_imp":0.15, "goals_rate":0.04, "available":True, "form":0, "fitness":1.0},
            "Romain Saiss":     {"role":"defense", "attack_imp":0.01, "defense_imp":0.14, "goals_rate":0.03, "available":True, "form":0, "fitness":1.0},
            "Yassine Bounou":   {"role":"gk",      "attack_imp":0.00, "defense_imp":0.18, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Haiti": {
        "attack": 0.70, "defense": 1.45, "rank": 88,
        "style": "direct", "altitude_home": 20,
        "pressure_index": 0.50, "depth_score": 0.30,
        "players": {
            "Frantzdy Pierrot":     {"role":"attack",  "attack_imp":0.20, "defense_imp":0.00, "goals_rate":0.20, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Scotland": {
        "attack": 1.10, "defense": 1.15, "rank": 39,
        "style": "direct", "altitude_home": 50,
        "pressure_index": 0.60, "depth_score": 0.55,
        "players": {
            "John McGinn":          {"role":"midfield","attack_imp":0.14, "defense_imp":0.08, "goals_rate":0.20, "available":True, "form":0, "fitness":1.0},
            "Che Adams":            {"role":"attack",  "attack_imp":0.16, "defense_imp":0.00, "goals_rate":0.28, "available":True, "form":0, "fitness":1.0},
            "Scott McTominay":      {"role":"midfield","attack_imp":0.12, "defense_imp":0.10, "goals_rate":0.18, "available":True, "form":0, "fitness":1.0},
        }
    },

    # ══ GROUP D ════════════════════════════════════════════

    "USA": {
        "attack": 1.35, "defense": 1.05, "rank": 11,
        "style": "high_press", "altitude_home": 50,
        "pressure_index": 0.68, "depth_score": 0.70,
        "players": {
            "Christian Pulisic":    {"role":"attack",  "attack_imp":0.24, "defense_imp":0.01, "goals_rate":0.45, "available":True, "form":0, "fitness":1.0},
            "Giovanni Reyna":       {"role":"attack",  "attack_imp":0.16, "defense_imp":0.01, "goals_rate":0.30, "available":True, "form":0, "fitness":1.0},
            "Tim Weah":             {"role":"attack",  "attack_imp":0.12, "defense_imp":0.01, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
            "Weston McKennie":      {"role":"midfield","attack_imp":0.10, "defense_imp":0.08, "goals_rate":0.15, "available":True, "form":0, "fitness":1.0},
            "Tyler Adams":          {"role":"midfield","attack_imp":0.04, "defense_imp":0.14, "goals_rate":0.04, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Paraguay": {
        "attack": 1.00, "defense": 1.20, "rank": 62,
        "style": "counter", "altitude_home": 200,
        "pressure_index": 0.60, "depth_score": 0.48,
        "players": {
            "Miguel Almiron":       {"role":"midfield","attack_imp":0.20, "defense_imp":0.03, "goals_rate":0.25, "available":True, "form":0, "fitness":1.0},
            "Antonio Sanabria":     {"role":"attack",  "attack_imp":0.16, "defense_imp":0.00, "goals_rate":0.28, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Australia": {
        "attack": 1.10, "defense": 1.10, "rank": 25,
        "style": "balanced", "altitude_home": 50,
        "pressure_index": 0.70, "depth_score": 0.58,
        "players": {
            "Ajdin Hrustic":        {"role":"midfield","attack_imp":0.16, "defense_imp":0.05, "goals_rate":0.18, "available":True, "form":0, "fitness":1.0},
            "Tom Rogic":            {"role":"midfield","attack_imp":0.12, "defense_imp":0.06, "goals_rate":0.15, "available":True, "form":0, "fitness":1.0},
            "Mitchell Duke":        {"role":"attack",  "attack_imp":0.14, "defense_imp":0.00, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
            "Mat Ryan":             {"role":"gk",      "attack_imp":0.00, "defense_imp":0.14, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Turkey": {
        "attack": 1.30, "defense": 1.05, "rank": 26,
        "style": "balanced", "altitude_home": 900,
        "pressure_index": 0.68, "depth_score": 0.65,
        "players": {
            "Hakan Calhanoglu":     {"role":"midfield","attack_imp":0.18, "defense_imp":0.08, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
            "Arda Guler":           {"role":"attack",  "attack_imp":0.20, "defense_imp":0.01, "goals_rate":0.35, "available":True, "form":0, "fitness":1.0},
            "Merih Demiral":        {"role":"defense", "attack_imp":0.01, "defense_imp":0.14, "goals_rate":0.03, "available":True, "form":0, "fitness":1.0},
            "Kenan Yildiz":         {"role":"attack",  "attack_imp":0.14, "defense_imp":0.01, "goals_rate":0.28, "available":True, "form":0, "fitness":1.0},
        }
    },

    # ══ GROUP E ════════════════════════════════════════════

    "Germany": {
        "attack": 1.80, "defense": 0.90, "rank": 4,
        "style": "high_press", "altitude_home": 300,
        "pressure_index": 0.80, "depth_score": 0.85,
        "players": {
            "Jamal Musiala":        {"role":"attack",  "attack_imp":0.20, "defense_imp":0.02, "goals_rate":0.50, "available":True, "form":0, "fitness":1.0},
            "Florian Wirtz":        {"role":"attack",  "attack_imp":0.22, "defense_imp":0.02, "goals_rate":0.52, "available":True, "form":0, "fitness":1.0},
            "Kai Havertz":          {"role":"attack",  "attack_imp":0.14, "defense_imp":0.02, "goals_rate":0.40, "available":True, "form":0, "fitness":1.0},
            "Leroy Sane":           {"role":"attack",  "attack_imp":0.12, "defense_imp":0.01, "goals_rate":0.30, "available":True, "form":0, "fitness":1.0},
            "Joshua Kimmich":       {"role":"midfield","attack_imp":0.10, "defense_imp":0.12, "goals_rate":0.12, "available":True, "form":0, "fitness":1.0},
            "Antonio Rudiger":      {"role":"defense", "attack_imp":0.01, "defense_imp":0.14, "goals_rate":0.03, "available":True, "form":0, "fitness":1.0},
            "Manuel Neuer":         {"role":"gk",      "attack_imp":0.00, "defense_imp":0.12, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Curacao": {
        "attack": 0.72, "defense": 1.40, "rank": 93,
        "style": "counter", "altitude_home": 30,
        "pressure_index": 0.48, "depth_score": 0.25,
        "players": {
            "Leandro Bacuna":       {"role":"midfield","attack_imp":0.18, "defense_imp":0.05, "goals_rate":0.15, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Ivory Coast": {
        "attack": 1.20, "defense": 1.10, "rank": 44,
        "style": "direct", "altitude_home": 200,
        "pressure_index": 0.65, "depth_score": 0.60,
        "players": {
            "Sebastien Haller":     {"role":"attack",  "attack_imp":0.22, "defense_imp":0.00, "goals_rate":0.42, "available":True, "form":0, "fitness":1.0},
            "Wilfried Zaha":        {"role":"attack",  "attack_imp":0.18, "defense_imp":0.01, "goals_rate":0.32, "available":True, "form":0, "fitness":1.0},
            "Nicolas Pepe":         {"role":"attack",  "attack_imp":0.12, "defense_imp":0.01, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
            "Serge Aurier":         {"role":"defense", "attack_imp":0.04, "defense_imp":0.10, "goals_rate":0.04, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Ecuador": {
        "attack": 1.15, "defense": 1.15, "rank": 47,
        "style": "balanced", "altitude_home": 2850,
        "pressure_index": 0.65, "depth_score": 0.55,
        "players": {
            "Moises Caicedo":       {"role":"midfield","attack_imp":0.12, "defense_imp":0.12, "goals_rate":0.15, "available":True, "form":0, "fitness":1.0},
            "Enner Valencia":       {"role":"attack",  "attack_imp":0.22, "defense_imp":0.00, "goals_rate":0.42, "available":True, "form":0, "fitness":1.0},
            "Jeremy Sarmiento":     {"role":"attack",  "attack_imp":0.14, "defense_imp":0.01, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
        }
    },

    # ══ GROUP F ════════════════════════════════════════════

    "Netherlands": {
        "attack": 1.65, "defense": 0.90, "rank": 7,
        "style": "possession", "altitude_home": 2,
        "pressure_index": 0.72, "depth_score": 0.78,
        "players": {
            "Virgil van Dijk":      {"role":"defense", "attack_imp":0.04, "defense_imp":0.22, "goals_rate":0.08, "available":True, "form":0, "fitness":1.0},
            "Cody Gakpo":           {"role":"attack",  "attack_imp":0.20, "defense_imp":0.01, "goals_rate":0.48, "available":True, "form":0, "fitness":1.0},
            "Denzel Dumfries":      {"role":"attack",  "attack_imp":0.10, "defense_imp":0.06, "goals_rate":0.15, "available":True, "form":0, "fitness":1.0},
            "Tijjani Reijnders":    {"role":"midfield","attack_imp":0.14, "defense_imp":0.08, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
            "Memphis Depay":        {"role":"attack",  "attack_imp":0.14, "defense_imp":0.01, "goals_rate":0.38, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Japan": {
        "attack": 1.45, "defense": 1.00, "rank": 16,
        "style": "high_press", "altitude_home": 40,
        "pressure_index": 0.78, "depth_score": 0.72,
        "players": {
            "Takefusa Kubo":        {"role":"attack",  "attack_imp":0.22, "defense_imp":0.01, "goals_rate":0.42, "available":True, "form":0, "fitness":1.0},
            "Ritsu Doan":           {"role":"attack",  "attack_imp":0.16, "defense_imp":0.01, "goals_rate":0.30, "available":True, "form":0, "fitness":1.0},
            "Wataru Endo":          {"role":"midfield","attack_imp":0.06, "defense_imp":0.14, "goals_rate":0.06, "available":True, "form":0, "fitness":1.0},
            "Takumi Minamino":      {"role":"attack",  "attack_imp":0.14, "defense_imp":0.02, "goals_rate":0.28, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Sweden": {
        "attack": 1.20, "defense": 1.05, "rank": 23,
        "style": "direct", "altitude_home": 30,
        "pressure_index": 0.68, "depth_score": 0.60,
        "players": {
            "Viktor Gyokeres":      {"role":"attack",  "attack_imp":0.30, "defense_imp":0.00, "goals_rate":0.68, "available":True, "form":0, "fitness":1.0},
            "Emil Forsberg":        {"role":"attack",  "attack_imp":0.16, "defense_imp":0.02, "goals_rate":0.28, "available":True, "form":0, "fitness":1.0},
            "Alexander Isak":       {"role":"attack",  "attack_imp":0.18, "defense_imp":0.00, "goals_rate":0.40, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Tunisia": {
        "attack": 0.95, "defense": 1.20, "rank": 30,
        "style": "counter", "altitude_home": 100,
        "pressure_index": 0.60, "depth_score": 0.45,
        "players": {
            "Seifeddine Jaziri":    {"role":"attack",  "attack_imp":0.16, "defense_imp":0.00, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
            "Wahbi Khazri":         {"role":"attack",  "attack_imp":0.18, "defense_imp":0.01, "goals_rate":0.25, "available":True, "form":0, "fitness":1.0},
        }
    },

    # ══ GROUP G ════════════════════════════════════════════

    "Belgium": {
        "attack": 1.50, "defense": 1.00, "rank": 9,
        "style": "possession", "altitude_home": 100,
        "pressure_index": 0.68, "depth_score": 0.72,
        "players": {
            "Kevin De Bruyne":      {"role":"midfield","attack_imp":0.25, "defense_imp":0.04, "goals_rate":0.32, "available":True, "form":0, "fitness":1.0},
            "Romelu Lukaku":        {"role":"attack",  "attack_imp":0.22, "defense_imp":0.00, "goals_rate":0.52, "available":True, "form":0, "fitness":1.0},
            "Jeremy Doku":          {"role":"attack",  "attack_imp":0.16, "defense_imp":0.01, "goals_rate":0.30, "available":True, "form":0, "fitness":1.0},
            "Lois Openda":          {"role":"attack",  "attack_imp":0.14, "defense_imp":0.00, "goals_rate":0.35, "available":True, "form":0, "fitness":1.0},
            "Thibaut Courtois":     {"role":"gk",      "attack_imp":0.00, "defense_imp":0.20, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Egypt": {
        "attack": 1.10, "defense": 1.05, "rank": 35,
        "style": "counter", "altitude_home": 50,
        "pressure_index": 0.65, "depth_score": 0.55,
        "players": {
            "Mohamed Salah":        {"role":"attack",  "attack_imp":0.35, "defense_imp":0.01, "goals_rate":0.62, "available":True, "form":0, "fitness":1.0},
            "Trezeguet":            {"role":"attack",  "attack_imp":0.12, "defense_imp":0.00, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
            "Mohamed Elneny":       {"role":"midfield","attack_imp":0.06, "defense_imp":0.10, "goals_rate":0.06, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Iran": {
        "attack": 1.00, "defense": 1.05, "rank": 24,
        "style": "counter", "altitude_home": 1200,
        "pressure_index": 0.65, "depth_score": 0.55,
        "players": {
            "Mehdi Taremi":         {"role":"attack",  "attack_imp":0.28, "defense_imp":0.00, "goals_rate":0.48, "available":True, "form":0, "fitness":1.0},
            "Alireza Jahanbakhsh":  {"role":"attack",  "attack_imp":0.16, "defense_imp":0.02, "goals_rate":0.28, "available":True, "form":0, "fitness":1.0},
            "Ali Gholizadeh":       {"role":"attack",  "attack_imp":0.12, "defense_imp":0.01, "goals_rate":0.18, "available":True, "form":0, "fitness":1.0},
        }
    },
    "New Zealand": {
        "attack": 0.78, "defense": 1.30, "rank": 97,
        "style": "direct", "altitude_home": 50,
        "pressure_index": 0.55, "depth_score": 0.28,
        "players": {
            "Chris Wood":           {"role":"attack",  "attack_imp":0.28, "defense_imp":0.00, "goals_rate":0.32, "available":True, "form":0, "fitness":1.0},
            "Elijah Just":          {"role":"midfield","attack_imp":0.12, "defense_imp":0.06, "goals_rate":0.12, "available":True, "form":0, "fitness":1.0},
        }
    },

    # ══ GROUP H ════════════════════════════════════════════

    "Spain": {
        "attack": 2.00, "defense": 0.70, "rank": 2,
        "style": "possession", "altitude_home": 650,
        "pressure_index": 0.90, "depth_score": 0.92,
        "players": {
            "Lamine Yamal":         {"role":"attack",  "attack_imp":0.20, "defense_imp":0.01, "goals_rate":0.55, "available":True, "form":0, "fitness":1.0},
            "Pedri":                {"role":"midfield","attack_imp":0.16, "defense_imp":0.06, "goals_rate":0.30, "available":True, "form":0, "fitness":1.0},
            "Alvaro Morata":        {"role":"attack",  "attack_imp":0.14, "defense_imp":0.00, "goals_rate":0.38, "available":True, "form":0, "fitness":1.0},
            "Nico Williams":        {"role":"attack",  "attack_imp":0.16, "defense_imp":0.01, "goals_rate":0.42, "available":True, "form":0, "fitness":1.0},
            "Rodri":                {"role":"midfield","attack_imp":0.10, "defense_imp":0.15, "goals_rate":0.10, "available":True, "form":0, "fitness":1.0},
            "Dani Carvajal":        {"role":"defense", "attack_imp":0.05, "defense_imp":0.10, "goals_rate":0.03, "available":True, "form":0, "fitness":1.0},
            "David Raya":           {"role":"gk",      "attack_imp":0.00, "defense_imp":0.12, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Cape Verde": {
        "attack": 0.82, "defense": 1.30, "rank": 72,
        "style": "counter", "altitude_home": 500,
        "pressure_index": 0.60, "depth_score": 0.30,
        "players": {
            "Ryan Mendes":          {"role":"attack",  "attack_imp":0.20, "defense_imp":0.01, "goals_rate":0.20, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Saudi Arabia": {
        "attack": 0.95, "defense": 1.25, "rank": 58,
        "style": "counter", "altitude_home": 750,
        "pressure_index": 0.65, "depth_score": 0.45,
        "players": {
            "Salem Al-Dawsari":     {"role":"attack",  "attack_imp":0.24, "defense_imp":0.01, "goals_rate":0.35, "available":True, "form":0, "fitness":1.0},
            "Firas Al-Buraikan":    {"role":"attack",  "attack_imp":0.16, "defense_imp":0.00, "goals_rate":0.25, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Uruguay": {
        "attack": 1.35, "defense": 1.00, "rank": 21,
        "style": "counter", "altitude_home": 30,
        "pressure_index": 0.80, "depth_score": 0.65,
        "players": {
            "Darwin Nunez":         {"role":"attack",  "attack_imp":0.22, "defense_imp":0.00, "goals_rate":0.52, "available":True, "form":0, "fitness":1.0},
            "Federico Valverde":    {"role":"midfield","attack_imp":0.18, "defense_imp":0.08, "goals_rate":0.25, "available":True, "form":0, "fitness":1.0},
            "Rodrigo Bentancur":    {"role":"midfield","attack_imp":0.10, "defense_imp":0.10, "goals_rate":0.10, "available":True, "form":0, "fitness":1.0},
            "Jose Maria Gimenez":   {"role":"defense", "attack_imp":0.02, "defense_imp":0.16, "goals_rate":0.03, "available":True, "form":0, "fitness":1.0},
        }
    },

    # ══ GROUP I ════════════════════════════════════════════

    "France": {
        "attack": 2.00, "defense": 0.75, "rank": 1,
        "style": "balanced", "altitude_home": 150,
        "pressure_index": 0.85, "depth_score": 0.95,
        "players": {
            "Kylian Mbappe":        {"role":"attack",  "attack_imp":0.35, "defense_imp":0.01, "goals_rate":0.88, "available":True, "form":0, "fitness":1.0},
            "Ousmane Dembele":      {"role":"attack",  "attack_imp":0.15, "defense_imp":0.01, "goals_rate":0.35, "available":True, "form":0, "fitness":1.0},
            "Antoine Griezmann":    {"role":"attack",  "attack_imp":0.15, "defense_imp":0.03, "goals_rate":0.38, "available":True, "form":0, "fitness":1.0},
            "Aurelien Tchouameni":  {"role":"midfield","attack_imp":0.05, "defense_imp":0.14, "goals_rate":0.08, "available":True, "form":0, "fitness":1.0},
            "Jules Kounde":         {"role":"defense", "attack_imp":0.05, "defense_imp":0.11, "goals_rate":0.02, "available":True, "form":0, "fitness":1.0},
            "William Saliba":       {"role":"defense", "attack_imp":0.01, "defense_imp":0.18, "goals_rate":0.02, "available":True, "form":0, "fitness":1.0},
            "Dayot Upamecano":      {"role":"defense", "attack_imp":0.01, "defense_imp":0.16, "goals_rate":0.01, "available":True, "form":0, "fitness":1.0},
            "Theo Hernandez":       {"role":"defense", "attack_imp":0.06, "defense_imp":0.10, "goals_rate":0.04, "available":True, "form":0, "fitness":1.0},
            "Mike Maignan":         {"role":"gk",      "attack_imp":0.00, "defense_imp":0.16, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Senegal": {
        "attack": 1.25, "defense": 1.00, "rank": 20,
        "style": "counter", "altitude_home": 25,
        "pressure_index": 0.75, "depth_score": 0.65,
        "players": {
            "Sadio Mane":           {"role":"attack",  "attack_imp":0.28, "defense_imp":0.02, "goals_rate":0.48, "available":True, "form":0, "fitness":1.0},
            "Ismaila Sarr":         {"role":"attack",  "attack_imp":0.14, "defense_imp":0.01, "goals_rate":0.28, "available":True, "form":0, "fitness":1.0},
            "Idrissa Gana Gueye":   {"role":"midfield","attack_imp":0.06, "defense_imp":0.14, "goals_rate":0.05, "available":True, "form":0, "fitness":1.0},
            "Kalidou Koulibaly":    {"role":"defense", "attack_imp":0.01, "defense_imp":0.18, "goals_rate":0.02, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Iraq": {
        "attack": 0.85, "defense": 1.35, "rank": 56,
        "style": "defensive", "altitude_home": 35,
        "pressure_index": 0.55, "depth_score": 0.38,
        "players": {
            "Mohanad Ali":          {"role":"attack",  "attack_imp":0.20, "defense_imp":0.00, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
            "Amjed Attwan":         {"role":"midfield","attack_imp":0.12, "defense_imp":0.08, "goals_rate":0.10, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Norway": {
        "attack": 1.50, "defense": 1.00, "rank": 28,
        "style": "direct", "altitude_home": 30,
        "pressure_index": 0.70, "depth_score": 0.65,
        "players": {
            "Erling Haaland":       {"role":"attack",  "attack_imp":0.38, "defense_imp":0.00, "goals_rate":0.85, "available":True, "form":0, "fitness":1.0},
            "Martin Odegaard":      {"role":"midfield","attack_imp":0.22, "defense_imp":0.04, "goals_rate":0.30, "available":True, "form":0, "fitness":1.0},
            "Alexander Sorloth":    {"role":"attack",  "attack_imp":0.14, "defense_imp":0.00, "goals_rate":0.28, "available":True, "form":0, "fitness":1.0},
            "Sander Berge":         {"role":"midfield","attack_imp":0.08, "defense_imp":0.10, "goals_rate":0.08, "available":True, "form":0, "fitness":1.0},
        }
    },

    # ══ GROUP J ════════════════════════════════════════════

    "Argentina": {
        "attack": 1.90, "defense": 0.82, "rank": 3,
        "style": "balanced", "altitude_home": 25,
        "pressure_index": 0.92, "depth_score": 0.88,
        "players": {
            "Lionel Messi":         {"role":"attack",  "attack_imp":0.30, "defense_imp":0.01, "goals_rate":0.72, "available":True, "form":0, "fitness":1.0},
            "Angel Di Maria":       {"role":"attack",  "attack_imp":0.14, "defense_imp":0.01, "goals_rate":0.32, "available":True, "form":0, "fitness":1.0},
            "Julian Alvarez":       {"role":"attack",  "attack_imp":0.18, "defense_imp":0.01, "goals_rate":0.55, "available":True, "form":0, "fitness":1.0},
            "Alexis Mac Allister":  {"role":"midfield","attack_imp":0.12, "defense_imp":0.08, "goals_rate":0.18, "available":True, "form":0, "fitness":1.0},
            "Rodrigo De Paul":      {"role":"midfield","attack_imp":0.10, "defense_imp":0.08, "goals_rate":0.12, "available":True, "form":0, "fitness":1.0},
            "Cristian Romero":      {"role":"defense", "attack_imp":0.01, "defense_imp":0.16, "goals_rate":0.02, "available":True, "form":0, "fitness":1.0},
            "Emiliano Martinez":    {"role":"gk",      "attack_imp":0.00, "defense_imp":0.16, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Algeria": {
        "attack": 1.10, "defense": 1.15, "rank": 33,
        "style": "counter", "altitude_home": 700,
        "pressure_index": 0.65, "depth_score": 0.58,
        "players": {
            "Riyad Mahrez":         {"role":"attack",  "attack_imp":0.28, "defense_imp":0.01, "goals_rate":0.42, "available":True, "form":0, "fitness":1.0},
            "Ismael Bennacer":      {"role":"midfield","attack_imp":0.12, "defense_imp":0.12, "goals_rate":0.10, "available":True, "form":0, "fitness":1.0},
            "Youcef Atal":          {"role":"attack",  "attack_imp":0.14, "defense_imp":0.04, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Austria": {
        "attack": 1.40, "defense": 0.95, "rank": 18,
        "style": "high_press", "altitude_home": 300,
        "pressure_index": 0.72, "depth_score": 0.68,
        "players": {
            "Marcel Sabitzer":      {"role":"midfield","attack_imp":0.16, "defense_imp":0.08, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
            "Marko Arnautovic":     {"role":"attack",  "attack_imp":0.20, "defense_imp":0.00, "goals_rate":0.38, "available":True, "form":0, "fitness":1.0},
            "Konrad Laimer":        {"role":"midfield","attack_imp":0.10, "defense_imp":0.10, "goals_rate":0.12, "available":True, "form":0, "fitness":1.0},
            "David Alaba":          {"role":"defense", "attack_imp":0.06, "defense_imp":0.16, "goals_rate":0.05, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Jordan": {
        "attack": 0.88, "defense": 1.25, "rank": 70,
        "style": "defensive", "altitude_home": 800,
        "pressure_index": 0.65, "depth_score": 0.38,
        "players": {
            "Yazan Al-Naimat":      {"role":"attack",  "attack_imp":0.22, "defense_imp":0.00, "goals_rate":0.20, "available":True, "form":0, "fitness":1.0},
            "Baha Faisal":          {"role":"midfield","attack_imp":0.12, "defense_imp":0.08, "goals_rate":0.10, "available":True, "form":0, "fitness":1.0},
        }
    },

    # ══ GROUP K ════════════════════════════════════════════

    "Portugal": {
        "attack": 1.85, "defense": 0.85, "rank": 6,
        "style": "balanced", "altitude_home": 100,
        "pressure_index": 0.82, "depth_score": 0.85,
        "players": {
            "Cristiano Ronaldo":    {"role":"attack",  "attack_imp":0.28, "defense_imp":0.00, "goals_rate":0.75, "available":True, "form":0, "fitness":1.0},
            "Joao Felix":           {"role":"attack",  "attack_imp":0.18, "defense_imp":0.01, "goals_rate":0.40, "available":True, "form":0, "fitness":1.0},
            "Rafael Leao":          {"role":"attack",  "attack_imp":0.18, "defense_imp":0.01, "goals_rate":0.42, "available":True, "form":0, "fitness":1.0},
            "Bruno Fernandes":      {"role":"midfield","attack_imp":0.20, "defense_imp":0.04, "goals_rate":0.30, "available":True, "form":0, "fitness":1.0},
            "Vitinha":              {"role":"midfield","attack_imp":0.10, "defense_imp":0.08, "goals_rate":0.12, "available":True, "form":0, "fitness":1.0},
            "Ruben Dias":           {"role":"defense", "attack_imp":0.01, "defense_imp":0.18, "goals_rate":0.02, "available":True, "form":0, "fitness":1.0},
            "Diogo Costa":          {"role":"gk",      "attack_imp":0.00, "defense_imp":0.14, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },
    "DR Congo": {
        "attack": 1.05, "defense": 1.25, "rank": 52,
        "style": "counter", "altitude_home": 320,
        "pressure_index": 0.60, "depth_score": 0.48,
        "players": {
            "Theo Bongonda":        {"role":"attack",  "attack_imp":0.18, "defense_imp":0.01, "goals_rate":0.25, "available":True, "form":0, "fitness":1.0},
            "Chancel Mbemba":       {"role":"defense", "attack_imp":0.02, "defense_imp":0.16, "goals_rate":0.02, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Uzbekistan": {
        "attack": 0.95, "defense": 1.25, "rank": 75,
        "style": "counter", "altitude_home": 500,
        "pressure_index": 0.58, "depth_score": 0.40,
        "players": {
            "Eldor Shomurodov":     {"role":"attack",  "attack_imp":0.26, "defense_imp":0.00, "goals_rate":0.30, "available":True, "form":0, "fitness":1.0},
            "Abbosbek Fayzullaev":  {"role":"attack",  "attack_imp":0.16, "defense_imp":0.01, "goals_rate":0.20, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Colombia": {
        "attack": 1.45, "defense": 0.95, "rank": 12,
        "style": "high_press", "altitude_home": 2600,
        "pressure_index": 0.78, "depth_score": 0.75,
        "players": {
            "Luis Diaz":            {"role":"attack",  "attack_imp":0.22, "defense_imp":0.01, "goals_rate":0.50, "available":True, "form":0, "fitness":1.0},
            "James Rodriguez":      {"role":"midfield","attack_imp":0.20, "defense_imp":0.03, "goals_rate":0.28, "available":True, "form":0, "fitness":1.0},
            "Rafael Santos Borre":  {"role":"attack",  "attack_imp":0.14, "defense_imp":0.00, "goals_rate":0.30, "available":True, "form":0, "fitness":1.0},
            "Davinson Sanchez":     {"role":"defense", "attack_imp":0.01, "defense_imp":0.14, "goals_rate":0.02, "available":True, "form":0, "fitness":1.0},
        }
    },

    # ══ GROUP L ════════════════════════════════════════════

    "England": {
        "attack": 1.80, "defense": 0.85, "rank": 4,
        "style": "balanced", "altitude_home": 50,
        "pressure_index": 0.72, "depth_score": 0.88,
        "players": {
            "Jude Bellingham":      {"role":"midfield","attack_imp":0.22, "defense_imp":0.04, "goals_rate":0.52, "available":True, "form":0, "fitness":1.0},
            "Harry Kane":           {"role":"attack",  "attack_imp":0.24, "defense_imp":0.00, "goals_rate":0.65, "available":True, "form":0, "fitness":1.0},
            "Bukayo Saka":          {"role":"attack",  "attack_imp":0.16, "defense_imp":0.02, "goals_rate":0.38, "available":True, "form":0, "fitness":1.0},
            "Phil Foden":           {"role":"attack",  "attack_imp":0.16, "defense_imp":0.02, "goals_rate":0.35, "available":True, "form":0, "fitness":1.0},
            "Declan Rice":          {"role":"midfield","attack_imp":0.06, "defense_imp":0.14, "goals_rate":0.10, "available":True, "form":0, "fitness":1.0},
            "Kyle Walker":          {"role":"defense", "attack_imp":0.03, "defense_imp":0.10, "goals_rate":0.01, "available":True, "form":0, "fitness":1.0},
            "Jordan Pickford":      {"role":"gk",      "attack_imp":0.00, "defense_imp":0.14, "goals_rate":0.00, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Croatia": {
        "attack": 1.30, "defense": 1.00, "rank": 10,
        "style": "possession", "altitude_home": 120,
        "pressure_index": 0.88, "depth_score": 0.70,
        "players": {
            "Luka Modric":          {"role":"midfield","attack_imp":0.22, "defense_imp":0.08, "goals_rate":0.18, "available":True, "form":0, "fitness":1.0},
            "Josko Gvardiol":       {"role":"defense", "attack_imp":0.05, "defense_imp":0.20, "goals_rate":0.04, "available":True, "form":0, "fitness":1.0},
            "Andrej Kramaric":      {"role":"attack",  "attack_imp":0.20, "defense_imp":0.00, "goals_rate":0.40, "available":True, "form":0, "fitness":1.0},
            "Mateo Kovacic":        {"role":"midfield","attack_imp":0.12, "defense_imp":0.10, "goals_rate":0.10, "available":True, "form":0, "fitness":1.0},
            "Ivan Perisic":         {"role":"attack",  "attack_imp":0.14, "defense_imp":0.02, "goals_rate":0.22, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Ghana": {
        "attack": 1.00, "defense": 1.20, "rank": 65,
        "style": "direct", "altitude_home": 100,
        "pressure_index": 0.60, "depth_score": 0.50,
        "players": {
            "Mohammed Kudus":       {"role":"attack",  "attack_imp":0.24, "defense_imp":0.02, "goals_rate":0.38, "available":True, "form":0, "fitness":1.0},
            "Thomas Partey":        {"role":"midfield","attack_imp":0.08, "defense_imp":0.16, "goals_rate":0.08, "available":True, "form":0, "fitness":1.0},
            "Jordan Ayew":          {"role":"attack",  "attack_imp":0.14, "defense_imp":0.02, "goals_rate":0.20, "available":True, "form":0, "fitness":1.0},
        }
    },
    "Panama": {
        "attack": 0.82, "defense": 1.30, "rank": 80,
        "style": "defensive", "altitude_home": 20,
        "pressure_index": 0.62, "depth_score": 0.32,
        "players": {
            "Rolando Blackburn":    {"role":"attack",  "attack_imp":0.18, "defense_imp":0.00, "goals_rate":0.18, "available":True, "form":0, "fitness":1.0},
            "Edgar Barcenas":       {"role":"midfield","attack_imp":0.14, "defense_imp":0.04, "goals_rate":0.12, "available":True, "form":0, "fitness":1.0},
        }
    },
}

# ══════════════════════════════════════════════════════════════
# 5. HEAD-TO-HEAD PSYCHOLOGICAL EDGES
# ══════════════════════════════════════════════════════════════
# Format: (TeamA, TeamB): (mult_for_A, mult_for_B)
# Captures historical/psychological advantage beyond raw stats.
# Based on recent 5-year H2H record in major tournaments.

H2H_EDGES = {
    # High-confidence edges from recent history
    frozenset(["Germany",    "England"]):     (1.05, 0.96),  # Germany dominates historically
    frozenset(["Argentina",  "France"]):      (1.02, 0.99),  # Argentina recent WC final edge
    frozenset(["Spain",      "France"]):      (1.04, 0.97),  # Spain Nations League 2021
    frozenset(["Morocco",    "Belgium"]):     (1.06, 0.95),  # WC 2022 shock
    frozenset(["Morocco",    "Spain"]):       (1.03, 0.98),  # WC 2022 R16
    frozenset(["Japan",      "Germany"]):     (1.05, 0.96),  # WC 2022
    frozenset(["Japan",      "Spain"]):       (1.04, 0.97),  # WC 2022
    frozenset(["South Korea","Germany"]):     (1.04, 0.97),  # WC 2018
    frozenset(["Saudi Arabia","Argentina"]):  (1.08, 0.93),  # WC 2022 shock
    frozenset(["Croatia",    "Brazil"]):      (1.05, 0.96),  # WC 2022 QF
    frozenset(["Croatia",    "Argentina"]):   (0.96, 1.04),  # Argentina won WC SF 2022
    frozenset(["Uruguay",    "Ghana"]):       (1.04, 0.97),  # WC 2010 QF
    frozenset(["France",     "Morocco"]):     (1.04, 0.97),  # WC 2022 SF
    frozenset(["Iran",       "USA"]):         (1.04, 0.97),  # political + WC 2022 tension
    frozenset(["England",    "USA"]):         (1.02, 0.99),  # WC 2022 group draw
}

# ══════════════════════════════════════════════════════════════
# 6. TEAM FORM (updated in real time)
# ══════════════════════════════════════════════════════════════
# -2 = badly below expectations last match
# -1 = slightly off
#  0 = as expected (default)
# +1 = above expectations
# +2 = outstanding performance

TEAM_FORM = {team: 0 for team in TEAMS}

# ══════════════════════════════════════════════════════════════
# 6b. EXTERNAL SOURCES — pre-loaded intelligence
# ══════════════════════════════════════════════════════════════
#
# Sources ranked by historical accuracy on past tournaments.
# Each source has:
#   track_record  : verified past performance
#   accuracy      : calibration score (0–1; Pinnacle ≈ best achievable)
#   champion_probs: {team: probability} from their latest forecast
#   reasoning     : WHY they picked what they picked (key factors)
#   intel         : information they are using that our base model may miss
#   last_updated  : date of forecast
#
# CRITICAL DESIGN PRINCIPLE:
#   The "intel" field is the most valuable part. It surfaces facts that
#   our model cannot know from parameters alone — injuries mentioned in
#   press conferences, tactical switches, morale reports, form in friendlies.
#   These are flagged as "information gaps" in the sources report.
# ══════════════════════════════════════════════════════════════

EXTERNAL_SOURCES = {

    # ── 1. BETTING MARKET (Pinnacle / sharp money) ──────────────
    # Most accurate predictor over time. Pinnacle is the reference market —
    # they accept sharp money and their lines move accordingly.
    # When sharp money disagrees with public money, sharp money wins ~63% of the time.
    "Market (Sharp Money)": {
        "type":         "market",
        "track_record": "Pinnacle consistently outperforms all published models. "
                        "Sharp handle diverged from public bets: France attracting "
                        "MORE handle than Spain despite fewer bet slips — professional "
                        "money is on France.",
        "accuracy":     0.88,   # most accurate source type in sports prediction
        "last_updated": "2026-06-05",
        "champion_probs": {
            # Converted from decimal odds (Spain +450, France +475, Arg +900...)
            # Overround removed: raw implied probs renormalized
            "Spain":       0.185,
            "France":      0.178,
            "Argentina":   0.098,
            "England":     0.112,
            "Brazil":      0.082,
            "Portugal":    0.072,
            "Germany":     0.058,
            "Netherlands": 0.042,
            "Norway":      0.032,
            "Colombia":    0.022,
            "Morocco":     0.018,
            "Belgium":     0.016,
            "Uruguay":     0.014,
            "Japan":       0.012,
        },
        "reasoning": {
            "France":    "Sharp money favors France over Spain despite Spain having "
                         "more public bet volume. Sharps see France's bracket as "
                         "manageable after Group I and value Mbappe's peak-form upside. "
                         "France attracting higher dollar handle = professional confidence.",
            "Spain":     "Public favorite, possibly overbet. Yamal hamstring is a "
                         "real risk for early games — market is pricing in ~80% fitness "
                         "for first match. Rodri return from injury is a major positive.",
            "Netherlands":"Shorter than expected in sharp markets — Klement's 3/3 "
                           "correct prediction generating unusual attention.",
            "Norway":    "Haaland +Odegaard combo undervalued by public. Market sees "
                         "them as genuine dark horse, not just novelty.",
        },
        "intel": [
            ("Spain",       "Lamine Yamal hamstring doubt for first 1-2 matches",         "fitness",  "Lamine Yamal", 80),
            ("Spain",       "Rodri returned from long injury — unknown if fully match-sharp", "fitness", "Rodri", 88),
            ("Argentina",   "Emiliano Martinez training with hand injury, without gloves", "fitness", "Emiliano Martinez", 82),
            ("France",      "Lost pre-tournament friendly vs Ivory Coast (negative signal)", "team_form", None, -1),
            ("Norway",      "Haaland 16 qualifying goals (record pace) — exceptional form", "player_form", "Erling Haaland", 2),
            ("England",     "Kane European Golden Shoe (61 goals) — peak form",            "player_form", "Harry Kane", 2),
        ],
    },

    # ── 2. OPTA SUPERCOMPUTER ────────────────────────────────────
    # Official FIFA data partner. Uses Opta's full event-level dataset —
    # every pass, shot, duel from every international match. Most data-rich model.
    # 25,000 simulations. Historically very well-calibrated.
    "Opta Supercomputer": {
        "type":         "statistical",
        "track_record": "Official FIFA data partner. Uses full xG, press intensity, "
                        "passing networks. Predicted 2022 finalist correctly (Argentina). "
                        "Best calibrated statistical model publicly available.",
        "accuracy":     0.82,
        "last_updated": "2026-06-01",
        "champion_probs": {
            "Spain":       0.161,
            "France":      0.130,
            "England":     0.112,
            "Argentina":   0.104,
            "Portugal":    0.070,
            "Brazil":      0.066,
            "Germany":     0.051,
            "Netherlands": 0.036,
            "Norway":      0.035,
            "Belgium":     0.024,
            "Colombia":    0.021,
            "Morocco":     0.019,
            "USA":         0.012,
            "Mexico":      0.010,
            "Japan":       0.016,
            "Uruguay":     0.014,
            "Ecuador":     0.014,
            "Croatia":     0.016,
        },
        "reasoning": {
            "Spain":     "Only team >50% to reach QF (52.1%). Won Euro 2024 convincingly. "
                         "Depth exceptional — even without Yamal they have Williams, Pedri, "
                         "Morata. Rodri fit and captaining. Group H easiest of top teams.",
            "France":    "Group I hardest of any top team (Norway + Senegal). Only 60.3% "
                         "to top group vs 73% Argentina, 67.9% England. But once past "
                         "group stage, trajectory improves sharply. Mbappe closing in on "
                         "Klose's all-time WC record (12 goals in 2 tournaments).",
            "England":   "8 wins, 8 clean sheets in qualifying — unprecedented clean sheet "
                         "run. Kane 61 club goals this season (European Golden Shoe). "
                         "Tuchel left out Foden — confident in squad depth.",
            "Argentina": "73% to top Group J (easiest draw of top teams). H2H history "
                         "is positive. Messi: first player to score in all 5 WC rounds "
                         "(group, R16, QF, SF, final) in a single tournament in 2022.",
            "Brazil":    "Carlo Ancelotti hired as coach — tactical upgrade. Neymar "
                         "included in squad alongside Vinicius Jr, Raphinha, Endrick. "
                         "60.4% to win Group C.",
            "Norway":    "37 goals in qualifying — most of any team. Haaland 16 goals "
                         "(matched Lewandowski's record). Odegaard 7 assists (4 for "
                         "Haaland). If they exit group, they are 'extremely dangerous'.",
            "Netherlands":"Klement model (3/3 correct) picks them. Three WC finals without "
                           "a win — historically motivated. Group F viable.",
        },
        "intel": [
            ("Spain",    "Lamine Yamal hamstring — rested for Iraq friendly, 'will be in perfect shape'", "fitness", "Lamine Yamal", 88),
            ("Brazil",   "Carlo Ancelotti as new head coach — tactical sophistication upgrade",            "team_form", None, 1),
            ("Brazil",   "Neymar selected in squad — adds creativity and set-piece threat",                "player_note", "Neymar", None),
            ("England",  "Phil Foden dropped from squad by Tuchel — squad reshaping signal",              "squad_note", None, None),
            ("Portugal", "Won UEFA Nations League pre-tournament — team momentum high",                    "team_form", None, 1),
            ("Norway",   "Odegaard 7 qualifying assists, 4 for Haaland — combination in peak sync",       "player_form", "Martin Odegaard", 1),
        ],
    },

    # ── 3. PELE MODEL (Nate Silver / Silver Bulletin) ────────────
    # 100,000 simulations. Incorporates player market values (Transfermarkt),
    # detailed home-field advantage, and a 'Tilt' rating for attacking/defensive
    # tendency. Updated as tournament progresses. Strong track record.
    "PELE (Nate Silver)": {
        "type":         "statistical",
        "track_record": "Successor to FiveThirtyEight SPI. Adds player market values "
                        "and Tilt rating. 100K sims. SPI correctly had Argentina "
                        "as top team before 2022 WC. Saliba injury scare already "
                        "incorporated and resolved.",
        "accuracy":     0.81,
        "last_updated": "2026-06-05",
        "champion_probs": {
            # PELE has Spain top-rated but Argentina very close; England/France tied for 3rd
            # Precise numbers inferred from article descriptions + market
            "Spain":       0.170,
            "Argentina":   0.165,
            "France":      0.135,
            "England":     0.132,
            "Portugal":    0.072,
            "Brazil":      0.065,
            "Germany":     0.052,
            "Netherlands": 0.038,
            "Norway":      0.036,
            "Senegal":     0.012,
            "Colombia":    0.018,
            "Morocco":     0.016,
        },
        "reasoning": {
            "Spain":     "Top PELE rating — but only barely over Argentina. Player market "
                         "values reflect squad quality. Yamal hamstring is key risk; "
                         "PELE would downgrade Spain further if he misses openers.",
            "Argentina": "Nearly tied with Spain in PELE. 73% to top group. "
                         "Best bracket routing of top teams. Market values boosted "
                         "by Messi + Alvarez + Mac Allister primes.",
            "France":    "France/England essentially tied for #3 in PELE. "
                         "Lost friendly to Ivory Coast — mild negative signal "
                         "(PELE doesn't weight friendlies heavily but notes it). "
                         "Saliba cleared from injury scare.",
            "Mexico":    "Huge home field advantage calculated precisely for each venue. "
                         "Azteca altitude is legitimate multiplier — PELE models this "
                         "more rigorously than most models.",
            "Norway":    "Boosted by Haaland + Odegaard market values. PELE sees "
                         "them as genuine top-8 contender if they exit Group F.",
        },
        "intel": [
            ("France",   "William Saliba injury scare but cleared — was on injury list, now removed", "fitness", "William Saliba", 95),
            ("France",   "France lost pre-WC friendly vs Ivory Coast — mild confidence dent",         "team_note", None, None),
            ("Mexico",   "PELE calculates Mexico Azteca home advantage as among world's largest",      "venue_note", None, None),
            ("Spain",    "Rodri fit after long layoff — key to Spain's midfield control",              "fitness", "Rodri", 88),
            ("Argentina","Lautaro Martinez also in squad alongside Alvarez and Messi",                 "player_note", None, None),
        ],
    },

    # ── 4. KLEMENT MODEL ────────────────────────────────────────
    # Joachim Klement: German economist. Track record: 3/3 (2014 Germany,
    # 2018 France, 2022 Argentina). Uses economic + demographic + statistical
    # variables — NOT purely sporting. Contrarian vs consensus.
    "Klement Model": {
        "type":         "econometric",
        "track_record": "3 consecutive correct World Cup champion predictions "
                        "(2014 Germany, 2018 France, 2022 Argentina). "
                        "Model incorporates non-sporting variables: GDP per capita, "
                        "population size, historical football culture index, "
                        "tournament host region advantage, and long-run squad cycles. "
                        "Warned: model does not guarantee accuracy, luck plays a role.",
        "accuracy":     0.75,   # 3/3 is impressive but small sample + possible luck
        "last_updated": "2026-06-03",
        "champion_probs": {
            # Klement specifically called Netherlands winner, Portugal in final
            # Full probability table not published — we infer from description
            "Netherlands": 0.180,   # his top pick
            "Portugal":    0.140,   # his finalist
            "France":      0.090,
            "Spain":       0.100,
            "Argentina":   0.085,
            "Germany":     0.070,
            "England":     0.080,
            "Brazil":      0.060,
        },
        "reasoning": {
            "Netherlands": "Model factors in squad cycle maturity, economic stability, "
                           "historical near-misses (3 finals without a win = accumulated "
                           "institutional knowledge), and favorable bracket routing. "
                           "Under Koeman, Netherlands has peaked at right moment. "
                           "Demographic model: Netherlands population vs historical "
                           "football investment ratio is at optimal phase.",
            "Portugal":    "Ronaldo 6th World Cup creates historic motivation coefficient. "
                           "Portugal's economic investment in football (Primeira Liga "
                           "transfer market, academy infrastructure) at peak output. "
                           "Nations League win pre-tournament is a validated signal.",
            "France":      "Model had France winning 2018 — similar squad cycle pattern "
                           "now. But Deschamps exit after tournament creates transitional "
                           "uncertainty that lowers their score vs previous WC.",
            "Spain":       "Euro 2024 win slightly overweights Spain in sporting models "
                           "but Klement's economic model sees risk of post-peak cycle.",
        },
        "intel": [
            ("France",      "Deschamps confirmed leaving after tournament — end-of-era motivation", "motivation_note", None, None),
            ("Netherlands", "Koeman's squad at demographic/cycle peak per Klement's model",        "cycle_note", None, None),
            ("Portugal",    "Nations League win is validated pre-tournament form signal",           "team_form", None, 1),
            ("Spain",       "Post-Euro 2024 peak risk — economic/cycle model flags potential dip", "cycle_note", None, None),
        ],
    },
}

# ══════════════════════════════════════════════════════════════
# 6.5 EXTERNAL SOURCES — FUNCTIONS
# ══════════════════════════════════════════════════════════════

def sources_report(our_probs=None):
    """
    Side-by-side comparison of all external sources' champion probabilities vs our model.
    Highlights teams where sources diverge significantly from our prediction.
    our_probs: dict from simulate_tournament(), or None to skip our model column.
    """
    src_names = list(EXTERNAL_SOURCES.keys())
    src_accs  = [EXTERNAL_SOURCES[s]["accuracy"] for s in src_names]

    # All teams that appear in any source
    all_teams = set()
    for sd in EXTERNAL_SOURCES.values():
        all_teams.update(sd["champion_probs"].keys())
    if our_probs:
        all_teams.update(k for k, v in our_probs.items() if v.get("champion", 0) > 0.003)

    def consensus(team):
        total_w, total_p = 0.0, 0.0
        for s, acc in zip(src_names, src_accs):
            p = EXTERNAL_SOURCES[s]["champion_probs"].get(team, 0.0)
            total_p += p * acc; total_w += acc
        return total_p / total_w if total_w else 0.0

    ranked = sorted(all_teams, key=lambda t: -consensus(t))

    W = 96
    cw = 11  # column width
    print(f"\n{'═'*W}")
    print(f"  📊  EXTERNAL SOURCES — CHAMPION PROBABILITY COMPARISON")
    print(f"{'─'*W}")

    # Header
    hdr = f"  {'Team':<22}"
    for s in src_names:
        hdr += f"  {s[:cw]:>{cw}}"
    hdr += f"  {'Consensus':>{cw}}"
    if our_probs:
        hdr += f"  {'OurModel':>{cw}}  {'Δ':>8}"
    print(hdr)

    acc_row = f"  {'(accuracy)':22}"
    for acc in src_accs:
        acc_row += f"  {f'({acc:.0%})':>{cw}}"
    acc_row += f"  {'(wtd avg)':>{cw}}"
    print(acc_row)
    print(f"  {'─'*90}")

    for team in ranked:
        con = consensus(team)
        if con < 0.004 and (not our_probs or our_probs.get(team, {}).get("champion", 0) < 0.004):
            continue
        row = f"  {team:<22}"
        for s in src_names:
            p = EXTERNAL_SOURCES[s]["champion_probs"].get(team, 0.0)
            row += f"  {p*100:>{cw}.1f}%"
        row += f"  {con*100:>{cw}.1f}%"
        if our_probs:
            ours = our_probs.get(team, {}).get("champion", 0.0)
            diff = ours - con
            flag = (" ⬆️" if diff > 0.04 else (" ⬇️" if diff < -0.04 else "  "))
            row += f"  {ours*100:>{cw}.1f}%  {diff*100:>+7.1f}%{flag}"
        print(row)

    print(f"\n  Weights: " + " | ".join(f"{s}: {EXTERNAL_SOURCES[s]['accuracy']:.0%}" for s in src_names))

    # Key reasoning snippets
    print(f"\n  {'─'*90}")
    print(f"  💬  KEY REASONING FROM SOURCES (top 3 teams per source):")
    for src, data in EXTERNAL_SOURCES.items():
        if data.get("reasoning"):
            print(f"\n  ── {src}  (accuracy: {data['accuracy']:.0%}, track record: {data['track_record'][:80]}…)")
            for team, text in list(data["reasoning"].items())[:3]:
                short = text[:110] + ("…" if len(text) > 110 else "")
                print(f"     {team:12}: {short}")
    print(f"{'═'*W}\n")


def intel_gaps():
    """
    Display all actionable intelligence items discovered from external sources —
    things our base model may not have captured.
    """
    W = 82
    print(f"\n{'═'*W}")
    print(f"  🔍  INTELLIGENCE GAPS — Real-World Factors Our Model May Have Missed")
    print(f"{'─'*W}")

    ACTION_LABELS = {
        "fitness":        "🏥 FITNESS",
        "player_form":    "🔥 FORM",
        "team_form":      "📈 TEAM FORM",
        "player_note":    "📋 SQUAD",
        "squad_note":     "📋 SQUAD",
        "venue_note":     "🏟  VENUE",
        "motivation_note":"🎯 MOTIVATION",
        "cycle_note":     "📊 CYCLE",
    }

    # Group by team
    team_intel = defaultdict(list)
    for src_name, src_data in EXTERNAL_SOURCES.items():
        acc = src_data["accuracy"]
        for item in src_data.get("intel", []):
            team, desc, itype, player, value = item
            team_intel[team].append((acc, src_name, desc, itype, player, value))

    team_order = sorted(team_intel.keys(), key=lambda t: -max(x[0] for x in team_intel[t]))

    for team in team_order:
        items = sorted(team_intel[team], key=lambda x: -x[0])
        print(f"\n  {team}:")
        for acc, src, desc, itype, player, value in items:
            label = ACTION_LABELS.get(itype, f"📌 {itype.upper()}")
            ptag  = f" [{player}]" if player else ""
            vtag  = ""
            if   itype == "fitness"     and value is not None: vtag = f" → {value}%"
            elif itype in ("player_form","team_form") and value is not None:
                vtag = f" → {'+' if value>0 else ''}{value}"
            print(f"     {label}{ptag}{vtag}  [{src[:24]} {acc:.0%}]")
            print(f"       {desc}")

    print(f"\n  {'─'*W}")
    print(f"  Run 'apply-intel' to apply all fitness/form updates automatically.")
    print(f"{'═'*W}\n")


def apply_intel(dry_run=False):
    """
    Automatically apply all actionable intel from external sources.

    - fitness     → accuracy-weighted average of all reports for that player
    - player_form → rounded average of all reports
    - team_form   → net signal (sum), damped by 0.5, clamped to [-2,+2]

    dry_run=True: preview without making changes.
    """
    W = 72
    print(f"\n{'═'*W}")
    mode = "DRY RUN — no changes will be made" if dry_run else "APPLYING INTEL"
    print(f"  ⚡  {mode}")
    print(f"{'─'*W}")

    fitness_rpts   = defaultdict(list)   # resolved_player → [(val, acc), ...]
    pform_rpts     = defaultdict(list)   # resolved_player → [val, ...]
    tform_signals  = defaultdict(list)   # resolved_team   → [val, ...]

    for src_name, src_data in EXTERNAL_SOURCES.items():
        acc = src_data["accuracy"]
        for item in src_data.get("intel", []):
            team, desc, itype, player, value = item
            if   itype == "fitness"     and player and value is not None:
                pfull = find_player(player)
                if pfull: fitness_rpts[pfull].append((value, acc))
            elif itype == "player_form" and player and value is not None:
                pfull = find_player(player)
                if pfull: pform_rpts[pfull].append(value)
            elif itype == "team_form"   and value is not None:
                tfull = find_team(team)
                if tfull: tform_signals[tfull].append(value)

    applied = []

    # Fitness: accuracy-weighted average (keys are already resolved player names)
    for pfull, reports in fitness_rpts.items():
        total_w  = sum(w for _, w in reports)
        weighted = sum(f * w for f, w in reports) / total_w
        final    = round(weighted)
        cur = next((td["players"][pfull].get("fitness",1.0)*100
                    for td in TEAMS.values() if pfull in td["players"]), 100)
        srcs = ", ".join(f"{int(r[0])}%@{r[1]:.0%}" for r in reports)
        print(f"  🏥 {pfull}: {cur:.0f}% → {final}%  (sources: {srcs})")
        applied.append(("fitness", pfull, final))
        if not dry_run:
            set_fitness(pfull, final)

    # Player form: rounded average (keys are already resolved)
    for pfull, vals in pform_rpts.items():
        form_val = max(-2, min(2, round(sum(vals)/len(vals))))
        print(f"  🔥 {pfull}: form → {form_val:+d}  (signals: {vals})")
        applied.append(("player_form", pfull, form_val))
        if not dry_run:
            set_player_form(pfull, form_val)

    # Team form: net sum, damped only when signals conflict (keys are already resolved)
    for tfull, vals in tform_signals.items():
        net   = sum(vals)
        signs = set(1 if v > 0 else -1 if v < 0 else 0 for v in vals if v != 0)
        damp  = 0.6 if len(signs) > 1 else 1.0
        form_val = max(-2, min(2, int(math.copysign(1, net) * math.ceil(abs(net) * damp)) if net != 0 else 0))
        print(f"  📈 {tfull}: team form → {form_val:+d}  (signals: {vals})")
        applied.append(("team_form", tfull, form_val))
        if not dry_run:
            set_team_form(tfull, form_val)

    print(f"\n  {'─'*W}")
    if not applied:
        print("  (no actionable items)")
    elif dry_run:
        print(f"  Would apply {len(applied)} updates. Run 'apply-intel' to confirm.")
    else:
        print(f"  ✅ Applied {len(applied)} intel updates.")
    print(f"{'═'*W}\n")


def blend_consensus(our_probs):
    """
    Accuracy-weighted blend of all external sources + our simulation.
    Our model is assigned accuracy=0.80.
    Returns normalized dict {team: blended_champion_prob}.
    """
    OUR_ACCURACY = 0.80
    blended = {}
    for team in TEAMS:
        total_w = OUR_ACCURACY
        total_p = our_probs.get(team, {}).get("champion", 0.0) * OUR_ACCURACY
        for sd in EXTERNAL_SOURCES.values():
            acc = sd["accuracy"]
            total_p += sd["champion_probs"].get(team, 0.0) * acc
            total_w += acc
        blended[team] = total_p / total_w if total_w else 0.0
    total = sum(blended.values())
    return {t: v/total for t, v in blended.items()} if total else blended


def consensus_report(our_probs):
    """
    Blended champion probabilities: our model + all external sources, weighted by accuracy.
    """
    blended = blend_consensus(our_probs)
    ranked  = sorted(blended.items(), key=lambda x: -x[1])
    W = 74
    print(f"\n{'═'*W}")
    print(f"  🎯  CONSENSUS CHAMPION PROBABILITIES  (all sources, accuracy-weighted)")
    print(f"  Our model 80% | Market 88% | Opta 82% | PELE 81% | Klement 75%")
    print(f"{'─'*W}")
    print(f"  {'#':<4} {'Team':<26} {'Consensus':>10}  {'Our Model':>10}  {'Δ':>8}")
    print(f"  {'─'*62}")
    for i, (team, bp) in enumerate(ranked[:20], 1):
        ours = our_probs.get(team, {}).get("champion", 0.0)
        diff = bp - ours
        arrow = ("⬆️ " if diff > 0.02 else ("⬇️ " if diff < -0.02 else "   "))
        print(f"  {i:<4} {team:<26} {bp*100:>9.1f}%  {ours*100:>9.1f}%  {arrow}{diff*100:>+6.1f}%")
    print(f"{'═'*W}\n")


# ══════════════════════════════════════════════════════════════
# 7. PERSISTENCE
# ══════════════════════════════════════════════════════════════

def _load_state():
    """Load all saved state (player availability, form, updated parameters)."""
    if not os.path.exists(STATE_FILE):
        return
    with open(STATE_FILE) as f:
        state = json.load(f)
    for team, params in state.get("teams", {}).items():
        if team in TEAMS:
            TEAMS[team]["attack"]  = params.get("attack",  TEAMS[team]["attack"])
            TEAMS[team]["defense"] = params.get("defense", TEAMS[team]["defense"])
    for player, avail in state.get("availability", {}).items():
        for team in TEAMS.values():
            if player in team["players"]:
                team["players"][player]["available"] = avail
    for player, frm in state.get("player_form", {}).items():
        for team in TEAMS.values():
            if player in team["players"]:
                team["players"][player]["form"] = frm
    for player, fit in state.get("player_fitness", {}).items():
        for team in TEAMS.values():
            if player in team["players"]:
                team["players"][player]["fitness"] = fit
    for team, frm in state.get("team_form", {}).items():
        if team in TEAM_FORM:
            TEAM_FORM[team] = frm
    for player, yc in state.get("yellow_cards", {}).items():
        YELLOW_CARDS[player] = yc
    for team, et in state.get("extra_time", {}).items():
        TEAM_EXTRA_TIME[team] = et
    for team, lc in state.get("lineup_confirmed", {}).items():
        LINEUP_CONFIRMED[team] = lc
    _load_elo_ratings()


def _save_state():
    state = {
        "teams": {t: {"attack": p["attack"], "defense": p["defense"]}
                  for t, p in TEAMS.items()},
        "availability": {pl: data["available"]
                         for t in TEAMS.values()
                         for pl, data in t["players"].items()},
        "player_form":  {pl: data["form"]
                         for t in TEAMS.values()
                         for pl, data in t["players"].items()},
        "player_fitness": {pl: data.get("fitness", 1.0)
                           for t in TEAMS.values()
                           for pl, data in t["players"].items()},
        "team_form":      dict(TEAM_FORM),
        "yellow_cards":     dict(YELLOW_CARDS),
        "extra_time":       dict(TEAM_EXTRA_TIME),
        "lineup_confirmed": dict(LINEUP_CONFIRMED),
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# 8. CORE ADJUSTMENT ENGINE
# ══════════════════════════════════════════════════════════════

def _squad_multiplier(team_name):
    """
    Compute (attack_mult, defense_mult) based on squad availability, fitness and form.

    FITNESS MODEL:
      fitness = 1.0  → full contribution (healthy)
      fitness < 1.0  → playing through injury / physical limitation

    Position-specific degradation exponents:
      The body part affected (e.g. back) hits certain positions harder.
      A defender's role is explosion, dueling, positioning — all back-dependent.
      An attacker's finishing is less affected by a back problem than his pressing is.

      role        att_exp   def_exp   rationale
      ─────────── ─────────────────  ─────────────────────────────────────────
      gk          1.0       1.4       back pain → compromised diving, low shots
      defense     1.1       1.5       explosive headers, tackles — most affected
      midfield    1.2       1.2       pressing, box-to-box running
      attack      1.1       1.0       finishing less affected; pressing/runs more

    So: effective_att_impact = att_imp × fitness^att_exp
        effective_def_impact = def_imp × fitness^def_exp
    """
    ROLE_EXPONENTS = {
        "gk":       (1.0, 1.4),
        "defense":  (1.1, 1.5),
        "midfield": (1.2, 1.2),
        "attack":   (1.1, 1.0),
    }

    players = TEAMS[team_name]["players"]
    attack_reduction  = 0.0
    defense_reduction = 0.0

    for name, data in players.items():
        fitness  = data.get("fitness", 1.0)
        form_mod = 1.0 + data["form"] * 0.06   # ±6% per form level
        att_exp, def_exp = ROLE_EXPONENTS.get(data["role"], (1.1, 1.2))

        if not data["available"]:
            # Fully absent → full impact loss
            attack_reduction  += data["attack_imp"]
            defense_reduction += data["defense_imp"]
        else:
            # Fitness degradation: contribution scales as fitness^exponent
            # At fitness=1.0: no change. At fitness=0.7: defender loses ~38% def contribution.
            fitness_att_loss = data["attack_imp"]  * (1.0 - fitness ** att_exp)
            fitness_def_loss = data["defense_imp"] * (1.0 - fitness ** def_exp)
            attack_reduction  += fitness_att_loss
            defense_reduction += fitness_def_loss

            # Form on top of fitness (form shifts the remaining contribution)
            remaining_att = data["attack_imp"]  * (fitness ** att_exp)
            remaining_def = data["defense_imp"] * (fitness ** def_exp)
            attack_reduction  -= remaining_att * (form_mod - 1.0)
            defense_reduction -= remaining_def * (form_mod - 1.0) * (-1)

    att_mult = max(0.40, 1.0 - attack_reduction)
    def_mult = max(0.60, 1.0 + defense_reduction)  # higher = worse defense
    return att_mult, def_mult


def _venue_multiplier(team_name, venue_name="Neutral"):
    """
    Compute (attack_mult, defense_mult) for this team at this venue.
    Accounts for altitude, heat, and humidity.
    Returns multipliers (1.0 = no effect).
    """
    venue = VENUES.get(venue_name, VENUES["Neutral"])
    alt_m    = venue["altitude_m"]
    temp_c   = venue["temp_c"]
    humidity = venue["humidity"]

    team_home_alt = ALTITUDE_ADAPTED.get(team_name, TEAMS[team_name].get("altitude_home", 50))
    team_heat_tol = HEAT_ADAPTED.get(team_name, 20)

    # ── Altitude effect ───────────────────────────────────
    # At altitude, non-adapted teams lose sprint capacity → reduced attack effectiveness
    # Key thresholds from sports science: meaningful above 1500m
    if alt_m > 1500 and team_home_alt < 1000:
        severity = min((alt_m - 1500) / 1000, 1.0)
        alt_att_penalty  = 0.08 * severity   # up to -8% attack
        alt_def_penalty  = 0.04 * severity   # up to +4% defense instability
    elif alt_m > 800 and team_home_alt < 500:
        severity = (alt_m - 800) / 700
        alt_att_penalty  = 0.04 * severity
        alt_def_penalty  = 0.02 * severity
    else:
        alt_att_penalty = 0.0
        alt_def_penalty = 0.0

    # Teams adapted to higher altitude than venue → no penalty; slight advantage possible
    if team_home_alt > alt_m + 500:
        alt_att_penalty  = -0.03   # slight boost (better aerobic conditioning)
        alt_def_penalty  = -0.02

    # ── Heat / Humidity effect ────────────────────────────
    # High-press teams suffer most in heat (30°C+, humidity 70%+)
    team_style  = TEAMS[team_name]["style"]
    heat_stress = max(0, temp_c - 24) / 20   # 0 at 24°C, 1.0 at 44°C
    humid_stress= max(0, humidity - 0.55) / 0.45

    combined_heat = (heat_stress * 0.7 + humid_stress * 0.3)

    # Heat tolerance (how much the team can handle it)
    team_tol = max(0, (team_heat_tol - 24)) / 20
    net_heat = max(0, combined_heat - team_tol * 0.5)

    # High-press teams lose 1.5× more from heat than counter teams
    style_heat_mult = {"high_press": 1.5, "possession": 1.2, "balanced": 1.0,
                       "counter": 0.8, "direct": 0.9, "defensive": 0.7}
    heat_att_penalty  = net_heat * 0.07 * style_heat_mult.get(team_style, 1.0)
    heat_def_penalty  = net_heat * 0.04 * style_heat_mult.get(team_style, 1.0)

    total_att_penalty  = alt_att_penalty  + heat_att_penalty
    total_def_penalty  = alt_def_penalty  + heat_def_penalty

    att_mult = max(0.60, 1.0 - total_att_penalty)
    def_mult = 1.0 + total_def_penalty   # higher = worse defense under stress

    return att_mult, def_mult


def _tactical_multiplier(team_a, team_b):
    """
    Returns (attack_mult_a, attack_mult_b) from tactical style matchup.
    """
    style_a = TEAMS[team_a]["style"]
    style_b = TEAMS[team_b]["style"]
    mult_a = TACTICAL_MATRIX.get(style_a, {}).get(style_b, 1.0)
    mult_b = TACTICAL_MATRIX.get(style_b, {}).get(style_a, 1.0)
    return mult_a, mult_b


def _h2h_multiplier(team_a, team_b):
    """Returns (mult_a, mult_b) from head-to-head psychological data."""
    key = frozenset([team_a, team_b])
    if key in H2H_EDGES:
        a_first = list(key)[0] == team_a
        m1, m2 = H2H_EDGES[key]
        return (m1, m2) if a_first else (m2, m1)
    return (1.0, 1.0)


def _rest_multiplier(rest_days_a, rest_days_b):
    """
    Penalty/bonus from rest days. Reference: 4 days = neutral (1.0).
    3 days: slight fatigue. 2 days: significant. 5+ days: slight boost.
    """
    def factor(days):
        if   days <= 1: return 0.88
        elif days == 2: return 0.93
        elif days == 3: return 0.97
        elif days == 4: return 1.00
        elif days == 5: return 1.01
        else:           return 1.02
    return factor(rest_days_a), factor(rest_days_b)


def _pressure_multiplier(team_a, team_b, stage="group"):
    """
    Motivation and pressure for each team.
    stage: "group", "r32", "r16", "qf", "sf", "final"
    High pressure_index teams improve; low pressure_index teams may freeze.
    """
    stage_pressure = {
        "group": 0.5, "r32": 0.7, "r16": 0.85,
        "qf": 1.0, "sf": 1.15, "final": 1.3
    }
    p = stage_pressure.get(stage, 0.5)

    def factor(team):
        pi = TEAMS[team]["pressure_index"]
        # Teams with high pressure_index benefit from big games
        # Teams below 0.65 slightly underperform under pressure
        delta = (pi - 0.70) * p * 0.08
        return 1.0 + delta

    return factor(team_a), factor(team_b)


def _form_multiplier(team_a, team_b):
    """Team-level form effect (from real match results)."""
    def factor(team):
        frm = TEAM_FORM.get(team, 0)
        return 1.0 + frm * 0.04   # ±4% per form level
    return factor(team_a), factor(team_b)


def _home_crowd_multiplier(team_a, team_b, venue):
    """
    Host-nation crowd boost at their own stadiums.

    Calibration:
      Mexico at Azteca/Akron/BBVA — one of the world's fiercest home environments.
        → home team +7% attack; opponent −5% attack (crowd noise, intimidation).
        (Altitude effect is already captured separately in _venue_multiplier.)
      USA / Canada at home — modern stadium, partisan crowd but less extreme.
        → home team +5% attack; opponent −4% attack.

    Effect is zero when neither team is the host nation, or when playing at a
    neutral/non-home venue.
    """
    CROWD = {
        "Mexico": (1.07, 0.95),   # (home_att_mult, away_att_mult)
        "USA":    (1.05, 0.96),
        "Canada": (1.05, 0.96),
    }
    home_nation = VENUE_HOME_NATION.get(venue)
    if not home_nation:
        return 1.0, 1.0
    mults = CROWD.get(home_nation)
    if not mults:
        return 1.0, 1.0
    home_m, away_m = mults
    if   team_a == home_nation: return home_m, away_m
    elif team_b == home_nation: return away_m, home_m
    else:                       return 1.0, 1.0   # two visiting teams at host venue


def _market_value_multiplier(team_a, team_b):
    """
    Squad market value edge (Layer 12).

    Calibration: richer squads have deeper benches and costlier stars.
    Effect is deliberately small — market value correlates with quality but
    is already partially captured in attack/defense base ratings.

    Formula: mult = (team_value / avg_value) ** 0.10
      England €1100M vs avg €350M → +11% attack / defense
      Haiti   €7M    vs avg €350M → −11%

    Max swing ≈ ±12%. Dampened exponent prevents over-weighting.
    """
    vals = list(SQUAD_MARKET_VALUE.values())
    avg  = sum(vals) / len(vals)

    def mult(team):
        v = SQUAD_MARKET_VALUE.get(team, avg)
        return max(0.85, min((v / avg) ** 0.10, 1.18))

    return mult(team_a), mult(team_b)


def update_elo_rating(winner: str, loser: str, is_draw: bool = False,
                      k: int = 32) -> tuple[float, float]:
    """
    Apply standard Elo update after a match.

    K=32 is the FIFA/WC standard; pass k=40 for knockout rounds.
    Returns (delta_winner, delta_loser) — positive = gained, negative = lost.
    Persists updated ratings to RATINGS_FILE.
    """
    elo_w = TEAM_RATINGS.get(winner, 1500.0)
    elo_l = TEAM_RATINGS.get(loser,  1500.0)

    expected_w = 1.0 / (1.0 + 10 ** ((elo_l - elo_w) / 400.0))
    expected_l = 1.0 - expected_w

    result_w, result_l = (0.5, 0.5) if is_draw else (1.0, 0.0)

    delta_w = k * (result_w - expected_w)
    delta_l = k * (result_l - expected_l)

    new_w = elo_w + delta_w
    new_l = elo_l + delta_l

    if winner in TEAM_RATINGS:
        TEAM_RATINGS[winner] = round(new_w, 1)
    if loser in TEAM_RATINGS:
        TEAM_RATINGS[loser]  = round(new_l, 1)

    _save_elo_ratings()
    return delta_w, delta_l


def _save_elo_ratings():
    """Persist TEAM_RATINGS to team_ratings.json."""
    try:
        with open(RATINGS_FILE, "w") as f:
            json.dump(TEAM_RATINGS, f, indent=2, ensure_ascii=False)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Failed to save Elo ratings: %s", e)


def _load_elo_ratings():
    """Load TEAM_RATINGS from team_ratings.json if it exists."""
    if not os.path.exists(RATINGS_FILE):
        return
    try:
        with open(RATINGS_FILE) as f:
            saved = json.load(f)
        for team, rating in saved.items():
            if team in TEAM_RATINGS:
                TEAM_RATINGS[team] = float(rating)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Failed to load Elo ratings: %s", e)


def _set_piece_multiplier(team_a, team_b):
    """
    Set piece attack vs defensive solidity from dead balls.

    ~30% of WC goals come from set pieces (corners, free kicks, throw-ins).
    Teams with superior sp_att vs opponent's sp_def gain a meaningful edge.

    Calibration:
      Max positive swing  (England sp_att=0.74 vs Iraq sp_def=0.44):
        → (0.74 − 0.44) × 0.28 = +8.4% on lam_a
      Max negative swing  (Iraq sp_att=0.40 vs France sp_def=0.72):
        → (0.40 − 0.72) × 0.28 = −9.0% on lam_a  (clamped to 0.88 floor)
    """
    sp_att_a, sp_def_a = SET_PIECE_RATINGS.get(team_a, (0.50, 0.50))
    sp_att_b, sp_def_b = SET_PIECE_RATINGS.get(team_b, (0.50, 0.50))
    mult_a = max(0.88, 1.0 + (sp_att_a - sp_def_b) * 0.28)
    mult_b = max(0.88, 1.0 + (sp_att_b - sp_def_a) * 0.28)
    return mult_a, mult_b


def _extra_time_multiplier(team_a, team_b):
    """
    Additional fatigue for teams that played 120 minutes in the previous round.

    Sports science: 120-minute match produces ~33% more lactate accumulation
    than 90 minutes. Recovery is incomplete even with 3-4 rest days.
    Modelled as −9% on both attack output (less pressing, slower breaks)
    and defence (higher defensive line drops, concentration lapses).

    Set via: extra-time <TeamName>
    Auto-cleared when update_result is called for that team.
    """
    mult_a = 0.91 if TEAM_EXTRA_TIME.get(team_a, False) else 1.0
    mult_b = 0.91 if TEAM_EXTRA_TIME.get(team_b, False) else 1.0
    return mult_a, mult_b


def _dead_rubber_multiplier(dead_rubber=None):
    """
    Squad rotation penalty when a team is in a 'dead rubber' match
    (already through or already eliminated before the final group game).

    Coaches rotate ~4–5 starters → effective squad quality drops ~18%.
    dead_rubber: None | 'a' | 'b' | 'both'
    """
    mult_a = 0.82 if dead_rubber in ('a', 'both') else 1.0
    mult_b = 0.82 if dead_rubber in ('b', 'both') else 1.0
    return mult_a, mult_b


# ══════════════════════════════════════════════════════════════
# 9. EXPECTED GOALS CALCULATION (multi-layer)
# ══════════════════════════════════════════════════════════════

def expected_goals(team_a, team_b, venue="Neutral",
                   rest_a=4, rest_b=4, stage="group", dead_rubber=None):
    """
    Full multi-layer expected goals calculation.
    Returns (lam_a, lam_b, factors_dict).

    Layers applied (in order):
      1. Base strength        — xG-calibrated attack × opponent defense
      2. Squad strength       — player fitness, availability, form
      3. Environment          — altitude, heat, humidity
      4. Tactics              — style matchup matrix
      5. H2H psychology       — historical edge
      6. Rest / fatigue       — rest days + extra-time carry-over
      7. Pressure/motivation  — stage pressure × pressure_index
      8. Team form            — recent tournament results
      9. Home crowd           — host-nation stadium boost (new)
     10. Set pieces           — dead-ball attack vs defence (new)
     11. Dead rubber          — squad rotation penalty (new)
    """
    base_att_a = TEAMS[team_a]["attack"]
    base_def_a = TEAMS[team_a]["defense"]
    base_att_b = TEAMS[team_b]["attack"]
    base_def_b = TEAMS[team_b]["defense"]

    # 1 — Squad (fitness / availability / form)
    sq_att_a, sq_def_a = _squad_multiplier(team_a)
    sq_att_b, sq_def_b = _squad_multiplier(team_b)

    # 2 — Environment
    env_att_a, env_def_a = _venue_multiplier(team_a, venue)
    env_att_b, env_def_b = _venue_multiplier(team_b, venue)

    # 3 — Tactics
    tac_a, tac_b = _tactical_multiplier(team_a, team_b)

    # 4 — H2H
    h2h_a, h2h_b = _h2h_multiplier(team_a, team_b)

    # 5 — Rest (includes extra-time carry-over)
    rest_fa, rest_fb = _rest_multiplier(rest_a, rest_b)
    et_a, et_b       = _extra_time_multiplier(team_a, team_b)
    rest_fa *= et_a;  rest_fb *= et_b   # fold ET fatigue into rest factor

    # 6 — Pressure
    pres_a, pres_b = _pressure_multiplier(team_a, team_b, stage)

    # 7 — Team form
    form_a, form_b = _form_multiplier(team_a, team_b)

    # 8 — Home crowd
    crowd_a, crowd_b = _home_crowd_multiplier(team_a, team_b, venue)

    # 9 — Set pieces
    sp_a, sp_b = _set_piece_multiplier(team_a, team_b)

    # 10 — Dead rubber
    dr_a, dr_b = _dead_rubber_multiplier(dead_rubber)

    # 11 — Market value (squad financial depth proxy)
    mv_a, mv_b = _market_value_multiplier(team_a, team_b)

    # Combine: attack of A vs defence of B
    eff_att_a = (base_att_a * sq_att_a * env_att_a
                 * tac_a * h2h_a * rest_fa * pres_a * form_a
                 * crowd_a * sp_a * dr_a * mv_a)
    eff_def_b = base_def_b * sq_def_b * env_def_b

    eff_att_b = (base_att_b * sq_att_b * env_att_b
                 * tac_b * h2h_b * rest_fb * pres_b * form_b
                 * crowd_b * sp_b * dr_b * mv_b)
    eff_def_a = base_def_a * sq_def_a * env_def_a

    lam_a = max(0.15, min(BASE_GOALS * eff_att_a * eff_def_b, 6.0))
    lam_b = max(0.15, min(BASE_GOALS * eff_att_b * eff_def_a, 6.0))

    factors = {
        "squad_a":  (sq_att_a, sq_def_a),  "squad_b":  (sq_att_b, sq_def_b),
        "env_a":    (env_att_a, env_def_a), "env_b":    (env_att_b, env_def_b),
        "tactical": (tac_a, tac_b),         "h2h":      (h2h_a, h2h_b),
        "rest":     (rest_fa, rest_fb),      "pressure": (pres_a, pres_b),
        "form":     (form_a, form_b),
        "crowd":    (crowd_a, crowd_b),      "setpiece": (sp_a, sp_b),
        "dead_rubber": (dr_a, dr_b),         "extra_time": (et_a, et_b),
        "market_value": (mv_a, mv_b),
    }
    return lam_a, lam_b, factors


# ══════════════════════════════════════════════════════════════
# 10. DIXON-COLES SCORE MATRIX
# ══════════════════════════════════════════════════════════════

def _poisson_pmf(k, lam):
    if lam <= 0: return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def _tau(x, y, lam, mu, rho=RHO):
    if   x==0 and y==0: return 1 - lam*mu*rho
    elif x==0 and y==1: return 1 + lam*rho
    elif x==1 and y==0: return 1 + mu*rho
    elif x==1 and y==1: return 1 - rho
    else:               return 1.0

def score_matrix(lam_a, lam_b, max_goals=8):
    P = np.zeros((max_goals+1, max_goals+1))
    for i in range(max_goals+1):
        for j in range(max_goals+1):
            P[i,j] = _poisson_pmf(i, lam_a) * _poisson_pmf(j, lam_b) * _tau(i, j, lam_a, lam_b)
    P /= P.sum()
    return P

def wdl(P):
    w, d, l = 0.0, 0.0, 0.0
    for i in range(P.shape[0]):
        for j in range(P.shape[1]):
            if   i>j: w += P[i,j]
            elif i==j: d += P[i,j]
            else:      l += P[i,j]
    return w, d, l


# ══════════════════════════════════════════════════════════════
# 11. PREDICTION OUTPUT
# ══════════════════════════════════════════════════════════════

def _unavailable_players(team):
    return [p for p, d in TEAMS[team]["players"].items() if not d["available"]]

def _form_report(team):
    notable = [(p, d["form"]) for p, d in TEAMS[team]["players"].items()
               if d["form"] != 0]
    return notable


def predict_match(team_a, team_b, venue="Neutral",
                  rest_a=4, rest_b=4, stage="group", dead_rubber=None,
                  verbose=True, top_n=10):

    if team_a not in TEAMS or team_b not in TEAMS:
        print(f"  ❌ Unknown team(s). Check spelling.")
        return None

    lam_a, lam_b, factors = expected_goals(team_a, team_b, venue, rest_a, rest_b, stage, dead_rubber)
    P = score_matrix(lam_a, lam_b)
    w, d, l = wdl(P)

    scores = sorted(
        [(i, j, P[i,j]) for i in range(P.shape[0]) for j in range(P.shape[1])],
        key=lambda x: -x[2]
    )

    if not verbose:
        return {"lam_a": lam_a, "lam_b": lam_b, "win_a": w, "draw": d, "win_b": l,
                "top_scores": scores[:top_n], "matrix": P}

    W = 68
    grp_a = TEAM_TO_GROUP.get(team_a, "?")
    grp_b = TEAM_TO_GROUP.get(team_b, "?")

    print(f"\n{'═'*W}")
    print(f"  ⚽  {team_a}  vs  {team_b}")
    print(f"     Group {grp_a} | FIFA #{TEAMS[team_a]['rank']} | Style: {TEAMS[team_a]['style']:12s}  "
          f"vs  Group {grp_b} | FIFA #{TEAMS[team_b]['rank']} | Style: {TEAMS[team_b]['style']}")
    print(f"     Venue: {VENUES[venue]['city']} ({VENUES[venue]['altitude_m']}m alt, "
          f"{VENUES[venue]['temp_c']}°C, {int(VENUES[venue]['humidity']*100)}% humidity)")
    print(f"     Rest: {team_a} {rest_a}d | {team_b} {rest_b}d   Stage: {stage.upper()}")
    print(f"{'─'*W}")

    # Squad warnings
    out_a = _unavailable_players(team_a)
    out_b = _unavailable_players(team_b)
    if out_a: print(f"  ⚠️  {team_a} UNAVAILABLE: {', '.join(out_a)}")
    if out_b: print(f"  ⚠️  {team_b} UNAVAILABLE: {', '.join(out_b)}")

    # Yellow card suspension risk
    for team in [team_a, team_b]:
        for p in TEAMS[team]["players"]:
            yc = YELLOW_CARDS.get(p, 0)
            if yc >= 2 and TEAMS[team]["players"][p]["available"]:
                print(f"  🚨 {p} ({team}): {yc} yellows — SUSPENDED next match!")
            elif yc == 1 and TEAMS[team]["players"][p]["available"]:
                print(f"  🟨 {p} ({team}): 1 yellow — one more = suspended")

    # Extra time fatigue
    if TEAM_EXTRA_TIME.get(team_a): print(f"  ⏱️  {team_a} played extra time last round (−9% output)")
    if TEAM_EXTRA_TIME.get(team_b): print(f"  ⏱️  {team_b} played extra time last round (−9% output)")

    # Dead rubber notice
    if dead_rubber in ('a', 'both'): print(f"  🔄 {team_a} DEAD RUBBER — rotation expected (−18% squad quality)")
    if dead_rubber in ('b', 'both'): print(f"  🔄 {team_b} DEAD RUBBER — rotation expected (−18% squad quality)")

    # Form alerts
    form_a = _form_report(team_a)
    form_b = _form_report(team_b)
    for p, f in form_a + form_b:
        arrow = ("🔥" if f > 0 else "❄️")
        team = team_a if (p, f) in form_a else team_b
        print(f"  {arrow} {p} ({team}) form: {'+' if f>0 else ''}{f}")

    print(f"{'─'*W}")

    # Factor breakdown
    sq_a, sq_b   = factors["squad_a"],   factors["squad_b"]
    env_a, env_b = factors["env_a"],     factors["env_b"]
    tac_a, tac_b = factors["tactical"]
    h2h_a, h2h_b = factors["h2h"]
    rest_fa, rest_fb = factors["rest"]
    pres_a, pres_b   = factors["pressure"]
    crowd_a, crowd_b = factors["crowd"]
    sp_a, sp_b       = factors["setpiece"]

    def fmt(v): return f"{(v-1)*100:+.1f}%"

    print(f"  Factor breakdown (attack multipliers):")
    print(f"  {'':2} {'':24} {'Squad':>7} {'Enviro':>7} {'Tactic':>7} "
          f"{'H2H':>6} {'Rest':>6} {'Press':>6} {'Crowd':>7} {'SetPc':>7}")
    for team, sq, env, tac, h2h, rst, prs, crd, sp in [
        (team_a, sq_a[0], env_a[0], tac_a, h2h_a, rest_fa, pres_a, crowd_a, sp_a),
        (team_b, sq_b[0], env_b[0], tac_b, h2h_b, rest_fb, pres_b, crowd_b, sp_b),
    ]:
        print(f"  {'▸':2} {team:<24} {fmt(sq):>7} {fmt(env):>7} {fmt(tac):>7} "
              f"{fmt(h2h):>6} {fmt(rst):>6} {fmt(prs):>6} {fmt(crd):>7} {fmt(sp):>7}")

    print(f"{'─'*W}")
    print(f"  Expected goals :  {team_a} {lam_a:.2f}  –  {lam_b:.2f}  {team_b}")
    print(f"  Win / Draw / Win: {w*100:>5.1f}%  /  {d*100:>5.1f}%  /  {l*100:>5.1f}%")
    print()
    print(f"  {'Top Exact Scores':<20} {'Probability':>11}  {'Cumulative':>11}  Result")
    print(f"  {'─'*60}")

    cumulative = 0.0
    top10 = []
    for a, b, prob in scores[:top_n]:
        cumulative += prob
        if   a > b: label = f"✅ {team_a}"
        elif a == b: label = "➡️  DRAW"
        else:        label = f"❌ {team_b}"
        print(f"  {a}-{b:<5}  {prob*100:>10.2f}%  {cumulative*100:>10.2f}%  {label}")
        top10.append((a, b, prob))

    best = scores[0]
    print()
    print(f"  💡 BEST BET    →  {team_a} {best[0]}-{best[1]} {team_b}  ({best[2]*100:.2f}%)")

    # ── Tournament Pick: result-aware score recommendation ────────────────────
    # For prediction tournaments scored on 90-min result, pick the score that
    # best reflects the *likely outcome* (W/D/L) rather than the raw modal score.
    FAVOR_THRESHOLD = 0.40   # team needs ≥40% win prob to get a "win" pick
    DRAW_THRESHOLD  = 0.28   # draw% ≥28% and no team clearly favored → draw pick

    def _best_score_for_outcome(outcome: str) -> tuple:
        """Return highest-prob score matching outcome: 'a', 'draw', 'b'."""
        for a_g, b_g, prob in scores:
            if outcome == 'a'    and a_g > b_g: return (a_g, b_g, prob)
            if outcome == 'draw' and a_g == b_g: return (a_g, b_g, prob)
            if outcome == 'b'    and b_g > a_g: return (a_g, b_g, prob)
        return scores[0]

    if w >= FAVOR_THRESHOLD and w >= l:
        tp = _best_score_for_outcome('a')
        tp_label = f"{team_a} win"
    elif l >= FAVOR_THRESHOLD and l > w:
        tp = _best_score_for_outcome('b')
        tp_label = f"{team_b} win"
    elif d >= DRAW_THRESHOLD:
        tp = _best_score_for_outcome('draw')
        tp_label = "Draw"
    elif w >= l:
        tp = _best_score_for_outcome('a')
        tp_label = f"{team_a} slight edge"
    else:
        tp = _best_score_for_outcome('b')
        tp_label = f"{team_b} slight edge"

    print(f"  🏆 TOURNAMENT PICK → {team_a} {tp[0]}-{tp[1]} {team_b}"
          f"  [{tp_label}, {tp[2]*100:.2f}%]")

    # Sensitivity: impact of losing key player
    print(f"\n  📊 SENSITIVITY — What if a key player is ruled out?")
    print(f"  {'Player':<26} {'Team':<14} {'New xG A':>9} {'New xG B':>9} {'Swing':>8}")
    print(f"  {'─'*65}")
    all_players = (
        [(p, team_a) for p in TEAMS[team_a]["players"] if TEAMS[team_a]["players"][p]["available"]] +
        [(p, team_b) for p in TEAMS[team_b]["players"] if TEAMS[team_b]["players"][p]["available"]]
    )
    sensitivity = []
    for pl, team in all_players:
        TEAMS[team]["players"][pl]["available"] = False
        nl_a, nl_b, _ = expected_goals(team_a, team_b, venue, rest_a, rest_b, stage)
        TEAMS[team]["players"][pl]["available"] = True
        swing = abs((nl_a - lam_a)) + abs((nl_b - lam_b))
        sensitivity.append((pl, team, nl_a, nl_b, swing))
    sensitivity.sort(key=lambda x: -x[4])
    for pl, team, nl_a, nl_b, swing in sensitivity[:6]:
        print(f"  {pl:<26} {team:<14} {nl_a:>9.2f} {nl_b:>9.2f} {swing:>+8.3f}")

    print(f"{'═'*W}\n")

    return {"lam_a": lam_a, "lam_b": lam_b, "win_a": w, "draw": d, "win_b": l,
            "top_scores": top10, "matrix": P}


def predict_group(group_name, venue="Neutral"):
    group_name = group_name.upper()
    if group_name not in GROUPS:
        print(f"  ❌ Unknown group '{group_name}'")
        return
    teams = GROUPS[group_name]
    print(f"\n{'═'*68}")
    print(f"  GROUP {group_name}: {' | '.join(teams)}")
    print(f"{'═'*68}")
    for a, b in itertools.combinations(teams, 2):
        predict_match(a, b, venue=venue)


# ══════════════════════════════════════════════════════════════
# 12. TOURNAMENT SIMULATION
# ══════════════════════════════════════════════════════════════

def _sim_match(team_a, team_b, venue="Neutral", stage="group", knockout=False):
    lam_a, lam_b, _ = expected_goals(team_a, team_b, venue, 4, 4, stage)
    ga = int(np.random.poisson(lam_a))
    gb = int(np.random.poisson(lam_b))

    if knockout and ga == gb:
        # Extra time: ~33% of normal rate, teams tired
        ga += int(np.random.poisson(lam_a * 0.33))
        gb += int(np.random.poisson(lam_b * 0.33))
        if ga == gb:
            # Penalty shootout: weighted by attack quality + pressure_index
            qi = (TEAMS[team_a]["attack"] * TEAMS[team_a]["pressure_index"])
            qj = (TEAMS[team_b]["attack"] * TEAMS[team_b]["pressure_index"])
            pa = np.clip(0.50 + (qi - qj) / (qi + qj) * 0.18, 0.35, 0.65)
            ga += 1 if np.random.random() < pa else 0
            gb += 0 if ga > gb else 1
    return ga, gb

def _sim_group(group_name):
    teams = GROUPS[group_name]
    stats = {t: {"pts":0,"gf":0,"ga":0,"gd":0} for t in teams}
    for a, b in itertools.combinations(teams, 2):
        ga, gb = _sim_match(a, b)
        stats[a]["gf"]+=ga; stats[a]["ga"]+=gb; stats[a]["gd"]+=ga-gb
        stats[b]["gf"]+=gb; stats[b]["ga"]+=ga; stats[b]["gd"]+=gb-ga
        if ga>gb:   stats[a]["pts"]+=3
        elif ga==gb: stats[a]["pts"]+=1; stats[b]["pts"]+=1
        else:        stats[b]["pts"]+=3
    return sorted(stats.items(), key=lambda x:(-x[1]["pts"],-x[1]["gd"],-x[1]["gf"]))

def _ko_round(pairs, stage="r16"):
    winners = []
    for a, b in pairs:
        ga, gb = _sim_match(a, b, stage=stage, knockout=True)
        winners.append(a if ga > gb else b)
    return winners

def _sim_tournament():
    gw, gr, thirds = {}, {}, []
    for g in "ABCDEFGHIJKL":
        s = _sim_group(g)
        gw[g] = s[0][0]; gr[g] = s[1][0]
        thirds.append((s[2][1]["pts"], s[2][1]["gd"], s[2][1]["gf"], s[2][0]))

    thirds.sort(key=lambda x: (-x[0],-x[1],-x[2]))
    bt = [t[3] for t in thirds[:8]]

    r32 = [
        (gw["A"],gr["B"]), (gw["C"],gr["D"]), (gw["E"],gr["F"]), (gw["G"],gr["H"]),
        (gw["I"],gr["J"]), (gw["K"],gr["L"]), (gw["B"],gr["A"]), (gw["D"],gr["C"]),
        (gw["F"],gr["E"]), (gw["H"],gr["G"]), (gw["J"],gr["I"]), (gw["L"],gr["K"]),
        (bt[0],bt[1]), (bt[2],bt[3]), (bt[4],bt[5]), (bt[6],bt[7]),
    ]
    r16 = _ko_round(r32, "r32")
    qf  = _ko_round([(r16[i],r16[i+1]) for i in range(0,16,2)], "r16")
    sf  = _ko_round([(qf[i], qf[i+1])  for i in range(0,8,2)],  "qf")
    fin = _ko_round([(sf[0],sf[1]), (sf[2],sf[3])],              "sf")
    champ = _ko_round([(fin[0],fin[1])],                          "final")[0]
    return champ, fin, sf

def simulate_tournament(n=N_SIMS):
    print(f"\n  🎲 Running {n:,} tournament simulations...", flush=True)
    cc, fc, sc = Counter(), Counter(), Counter()
    for i in range(n):
        if i%10_000==0 and i>0: print(f"     {i:>6,}/{n:,}", flush=True)
        champ, fin, sf = _sim_tournament()
        cc[champ] += 1
        for t in fin: fc[t] += 1
        for t in sf:  sc[t] += 1
    print(f"     {n:,}/{n:,} ✅\n")
    return {t: {"champion": cc[t]/n,
                "finalist": (fc[t]+cc[t])/n,
                "semifinal":(sc[t]+fc[t]+cc[t])/n}
            for t in TEAMS}


# ══════════════════════════════════════════════════════════════
# 13. TOP SCORER MODEL
# ══════════════════════════════════════════════════════════════

def predict_top_scorers(tournament_probs=None, n=20_000):
    """
    Player-level top scorer simulation.
    Uses individual goals_rate × expected games, adjusted for:
    - Tournament advancement probability
    - Player current form
    - Player availability
    """
    print(f"  🥅 Simulating top scorer ({n:,} runs)...")
    scorer_wins = Counter()

    # Build candidate list from ALL available key players with goals_rate
    candidates = []
    for team, tdata in TEAMS.items():
        for player, pdata in tdata["players"].items():
            if pdata["available"] and pdata["goals_rate"] > 0.10:
                form_bonus = pdata["form"] * 0.08
                rate = pdata["goals_rate"] * (1 + form_bonus)
                candidates.append((player, team, rate))

    for _ in range(n):
        pg = {}
        for player, team, rate in candidates:
            tp = tournament_probs.get(team, {}) if tournament_probs else {}
            p_sf   = tp.get("semifinal", 0.25)
            p_fin  = tp.get("finalist",  0.12)
            p_champ= tp.get("champion",  0.06)
            # Expected games: 3 group + weighted knockout games
            exp_games = 3 + p_sf*1.2 + p_fin*1.0 + p_champ*0.8
            games = int(np.clip(np.random.normal(exp_games, 0.9), 3, 7))
            pg[player] = int(np.random.poisson(rate * games))
        scorer_wins[max(pg, key=pg.get)] += 1

    return sorted([(p, scorer_wins[p]/n) for p, _, _ in candidates],
                  key=lambda x: -x[1])


# ══════════════════════════════════════════════════════════════
# 14. LIVE UPDATE COMMANDS
# ══════════════════════════════════════════════════════════════

def update_result(team_a, team_b, ga, gb, weight=0.32):
    """Bayesian-style parameter update after a real match result."""
    lam_a, lam_b, _ = expected_goals(team_a, team_b)
    ra = ga / max(lam_a, 0.01)
    rb = gb / max(lam_b, 0.01)

    def blend(old, ratio, w):
        return old * ((1-w) + w*ratio)

    TEAMS[team_a]["attack"]  = blend(TEAMS[team_a]["attack"],  ra, weight)
    TEAMS[team_b]["attack"]  = blend(TEAMS[team_b]["attack"],  rb, weight)
    TEAMS[team_b]["defense"] = blend(TEAMS[team_b]["defense"], ra, weight)
    TEAMS[team_a]["defense"] = blend(TEAMS[team_a]["defense"], rb, weight)

    # Auto-update team form based on result vs expectation
    if ra > 1.3:   TEAM_FORM[team_a] = min(2, TEAM_FORM[team_a]+1)
    elif ra < 0.7: TEAM_FORM[team_a] = max(-2, TEAM_FORM[team_a]-1)
    if rb > 1.3:   TEAM_FORM[team_b] = min(2, TEAM_FORM[team_b]+1)
    elif rb < 0.7: TEAM_FORM[team_b] = max(-2, TEAM_FORM[team_b]-1)

    # Auto-apply match wear to injured players (fitness < 0.90)
    apply_match_wear(team_a)
    apply_match_wear(team_b)

    # Clear extra-time flags — these teams have now played their next match
    TEAM_EXTRA_TIME.pop(team_a, None)
    TEAM_EXTRA_TIME.pop(team_b, None)

    _save_state()
    print(f"\n  ✅ Updated after: {team_a} {ga}–{gb} {team_b}")
    print(f"     {team_a}: attack={TEAMS[team_a]['attack']:.3f}  defense={TEAMS[team_a]['defense']:.3f}  form={TEAM_FORM[team_a]:+d}")
    print(f"     {team_b}: attack={TEAMS[team_b]['attack']:.3f}  defense={TEAMS[team_b]['defense']:.3f}  form={TEAM_FORM[team_b]:+d}\n")


def injure_player(player_name):
    """Mark a player as unavailable (injured/suspended)."""
    for team, tdata in TEAMS.items():
        if player_name in tdata["players"]:
            tdata["players"][player_name]["available"] = False
            _save_state()
            imp = tdata["players"][player_name]
            print(f"\n  🚑 {player_name} ({team}) marked UNAVAILABLE")
            print(f"     Attack impact: -{imp['attack_imp']*100:.0f}%  "
                  f"Defense impact: -{imp['defense_imp']*100:.0f}%\n")
            return
    print(f"  ❌ Player '{player_name}' not found.")


def recover_player(player_name):
    """Mark a player as available again."""
    for team, tdata in TEAMS.items():
        if player_name in tdata["players"]:
            tdata["players"][player_name]["available"] = True
            _save_state()
            print(f"\n  ✅ {player_name} ({team}) marked AVAILABLE\n")
            return
    print(f"  ❌ Player '{player_name}' not found.")


def set_player_form(player_name, form_value):
    """Set player form (-2 to +2)."""
    form_value = max(-2, min(2, int(form_value)))
    for team, tdata in TEAMS.items():
        if player_name in tdata["players"]:
            tdata["players"][player_name]["form"] = form_value
            _save_state()
            arrow = "🔥" if form_value > 0 else ("❄️" if form_value < 0 else "〰️")
            print(f"\n  {arrow} {player_name} form set to {form_value:+d}\n")
            return
    print(f"  ❌ Player '{player_name}' not found.")


def set_team_form(team_name, form_value):
    """Set team-level form (-2 to +2)."""
    if team_name not in TEAMS:
        print(f"  ❌ Unknown team '{team_name}'")
        return
    form_value = max(-2, min(2, int(form_value)))
    TEAM_FORM[team_name] = form_value
    _save_state()
    print(f"  Team form {team_name} → {form_value:+d}\n")


def set_fitness(player_name, fitness_pct):
    """
    Set a player's physical fitness level (0–100%).
    This models playing-through-injury scenarios.

    Examples:
      fitness "Upamecano" 70   → back problem, expected surgery post-tournament
      fitness "Mbappe" 85      → minor ankle issue, managed with injections
      fitness "Haaland" 100    → fully fit (default)

    The model applies position-specific degradation:
      - A defender at 70% fitness loses ~38% of his defensive contribution
        (back pain → compromised explosive tackles, aerial duels, positioning)
      - An attacker at 70% loses ~23% of his attack contribution
        (finishing less affected; sprinting, pressing more)

    Unlike `injure`, the player stays in the squad but at reduced capacity.
    """
    player = find_player(player_name) if player_name not in [
        p for t in TEAMS.values() for p in t["players"]
    ] else player_name

    if not player:
        player = find_player(player_name)
    if not player:
        return

    fitness_val = max(0.0, min(1.0, float(fitness_pct) / 100.0))
    for team, tdata in TEAMS.items():
        if player in tdata["players"]:
            old_fit = tdata["players"][player].get("fitness", 1.0)
            tdata["players"][player]["fitness"] = fitness_val
            role = tdata["players"][player]["role"]

            # Position-specific degradation table
            ROLE_EXP = {"gk":(1.0,1.4), "defense":(1.1,1.5), "midfield":(1.2,1.2), "attack":(1.1,1.0)}
            ae, de = ROLE_EXP.get(role, (1.1, 1.2))
            att_retained  = fitness_val ** ae
            def_retained  = fitness_val ** de
            att_lost_pct  = (1 - att_retained) * tdata["players"][player]["attack_imp"]  * 100
            def_lost_pct  = (1 - def_retained) * tdata["players"][player]["defense_imp"] * 100

            _save_state()

            emoji = "🟡" if fitness_val >= 0.80 else ("🟠" if fitness_val >= 0.60 else "🔴")
            print(f"\n  {emoji} {player} ({team}) fitness set to {fitness_val*100:.0f}%  "
                  f"[was {old_fit*100:.0f}%]")
            print(f"     Role: {role}  |  Playing through injury — not ruled out")
            print(f"     Effective contribution retained:")
            print(f"       Attack  : {att_retained*100:>5.1f}%  "
                  f"(−{att_lost_pct:.1f}% off team attack rating)")
            print(f"       Defense : {def_retained*100:>5.1f}%  "
                  f"(−{def_lost_pct:.1f}% off team defense rating)")
            if fitness_val < 0.80:
                print(f"     ⚠️  Significant impact — factor this into predictions.")
            if fitness_val < 0.65:
                print(f"     🔴 Critical — consider whether he should start at all.")
            print()
            return
    print(f"  ❌ Player '{player_name}' not found.")


def add_yellow_card(player_name):
    """
    Record a yellow card for a player.
    At 2 yellow cards in the same stage → automatically marks player UNAVAILABLE.
    At 1 yellow card → flags suspension risk in future predictions.
    """
    pfull = find_player(player_name)
    if not pfull:
        return
    YELLOW_CARDS[pfull] = YELLOW_CARDS.get(pfull, 0) + 1
    count = YELLOW_CARDS[pfull]
    _save_state()
    print(f"\n  🟨 {pfull}: yellow card #{count}")
    if count >= 2:
        print(f"  🚨 2 yellow cards — marking {pfull} SUSPENDED (unavailable)")
        injure_player(pfull)
    else:
        print(f"  ⚠️  One more yellow = suspended for next match\n")


def clear_yellow_cards():
    """
    Clear all yellow card accumulation.
    Call between stages (e.g., after group stage, after Round of 16).
    WC 2026 rules: cards reset before Round of 32, and before QF.
    """
    cleared = list(YELLOW_CARDS.keys())
    YELLOW_CARDS.clear()
    _save_state()
    if cleared:
        print(f"  ✅ Yellow cards cleared for: {', '.join(cleared)}\n")
    else:
        print("  (no yellow cards to clear)\n")


def mark_extra_time(team_name):
    """
    Mark that a team played 120 minutes (AET) in their last match.
    Applies −9% output penalty to their next match prediction.
    Cleared automatically when update_result is called for that team.
    """
    tfull = find_team(team_name)
    if not tfull:
        return
    TEAM_EXTRA_TIME[tfull] = True
    _save_state()
    print(f"\n  ⏱️  {tfull}: flagged as AET last round")
    print(f"     −9% attack & defense output in next match prediction.\n")


def apply_match_wear(team_name, wear_per_match=0.03):
    """
    Apply post-match physical wear to injured players (fitness < 0.90).
    Call this after updating a real result.
    Players managing injuries through a tournament typically decline 2-4% per match.
    """
    affected = []
    for player, data in TEAMS[team_name]["players"].items():
        if data.get("fitness", 1.0) < 0.90 and data["available"]:
            old = data["fitness"]
            data["fitness"] = max(0.30, old - wear_per_match)
            affected.append((player, old, data["fitness"]))
    if affected:
        print(f"  📉 Tournament wear applied to {team_name}:")
        for pl, old, new in affected:
            print(f"     {pl}: {old*100:.0f}% → {new*100:.0f}%")
        _save_state()


def squad_report(team_name):
    """Print full squad status for a team."""
    if team_name not in TEAMS:
        print(f"  ❌ Unknown team '{team_name}'")
        return
    t = TEAMS[team_name]
    print(f"\n{'═'*62}")
    print(f"  SQUAD STATUS: {team_name}  |  FIFA #{t['rank']}  |  Style: {t['style']}")
    print(f"  Base: attack={t['attack']:.2f}  defense={t['defense']:.2f}  "
          f"depth={t['depth_score']:.0%}  pressure_index={t['pressure_index']:.0%}")
    print(f"  Team form: {TEAM_FORM[team_name]:+d}")
    print(f"{'─'*62}")
    print(f"  {'Player':<28} {'Pos':8} {'Fit':5} {'Avail':7} {'Form':5} {'Att Imp':8} {'Def Imp':8}")
    print(f"  {'─'*68}")
    for player, d in t["players"].items():
        status = "✅" if d["available"] else "🚑 OUT"
        form_s = f"{d['form']:+d}" if d["form"] != 0 else "  0"
        fit = d.get("fitness", 1.0)
        if   fit >= 0.95: fit_s = f"{'100%':>5}"
        elif fit >= 0.80: fit_s = f"🟡{fit*100:>3.0f}%"
        elif fit >= 0.60: fit_s = f"🟠{fit*100:>3.0f}%"
        else:             fit_s = f"🔴{fit*100:>3.0f}%"
        print(f"  {player:<28} {d['role']:8} {fit_s:5} {status:7} {form_s:5} "
              f"{d['attack_imp']*100:>6.0f}%  {d['defense_imp']*100:>6.0f}%")
    print(f"{'═'*62}\n")


# ══════════════════════════════════════════════════════════════
# 15. BONUS PREDICTIONS
# ══════════════════════════════════════════════════════════════

def bonus_predictions():
    probs = simulate_tournament()

    # Winner table
    ranked = sorted(probs.items(), key=lambda x: -x[1]["champion"])
    print(f"\n{'═'*68}")
    print(f"  🏆  CHAMPION PREDICTION  ({N_SIMS:,} Monte Carlo simulations)")
    print(f"{'═'*68}")
    print(f"  {'#':<4} {'Team':<26} {'Champion':>9}  {'Finalist':>9}  {'Top 4':>8}")
    print(f"  {'─'*58}")
    for i, (team, p) in enumerate(ranked[:20], 1):
        print(f"  {i:<4} {team:<26} {p['champion']*100:>8.1f}%  "
              f"{p['finalist']*100:>8.1f}%  {p['semifinal']*100:>7.1f}%")

    # Top scorer
    scorer_probs = predict_top_scorers(probs)
    print(f"\n{'═'*55}")
    print(f"  🥅  TOP SCORER PREDICTION")
    print(f"{'═'*55}")
    print(f"  {'#':<4} {'Player':<26} {'Team':<16} {'Prob':>6}")
    print(f"  {'─'*52}")
    for i, (player, prob) in enumerate(scorer_probs[:12], 1):
        team = next(t for t, td in TEAMS.items() if player in td["players"])
        avail = "" if TEAMS[team]["players"][player]["available"] else " 🚑"
        print(f"  {i:<4} {player:<26} {team:<16} {prob*100:>5.1f}%{avail}")

    best_team    = ranked[0]
    best_scorer  = scorer_probs[0]
    scorer_team  = next(t for t, td in TEAMS.items() if best_scorer[0] in td["players"])

    print(f"\n{'═'*68}")
    print(f"  📌  MODEL RECOMMENDATION:")
    print(f"       🏆 Champion    →  {best_team[0]}  ({best_team[1]['champion']*100:.1f}%)")
    print(f"       🥅 Top scorer  →  {best_scorer[0]}  "
          f"({scorer_team}, {best_scorer[1]*100:.1f}%)")
    print(f"{'═'*68}\n")


# ══════════════════════════════════════════════════════════════
# 16. FUZZY TEAM / PLAYER LOOKUP
# ══════════════════════════════════════════════════════════════

def find_team(name):
    nl = name.lower()
    for t in TEAMS:
        if t.lower() == nl: return t
    matches = [t for t in TEAMS if nl in t.lower()]
    if len(matches) == 1: return matches[0]
    if len(matches) > 1:
        print(f"  ⚠️  Ambiguous: {matches}")
        return None
    print(f"  ❌ Team '{name}' not found.")
    return None

def find_player(name):
    nl = name.lower()
    results = []
    for team, tdata in TEAMS.items():
        for player in tdata["players"]:
            if nl in player.lower():
                results.append(player)
    if not results: print(f"  ❌ Player '{name}' not found."); return None
    if len(results) == 1: return results[0]
    exact = [r for r in results if r.lower() == nl]
    if len(exact) == 1: return exact[0]
    print(f"  ⚠️  Matches: {results}")
    return None


# ══════════════════════════════════════════════════════════════
# 17. INTERACTIVE MODE
# ══════════════════════════════════════════════════════════════

HELP_TEXT = """
  ─── MATCH PREDICTION ──────────────────────────────────────────
  predict  <A> <B> [--venue V] [--rest rA rB] [--stage s]
  group    <A-L> [--venue V]
  all-groups

  ─── LIVE UPDATES (run after every real match) ──────────────────
  update   <TeamA> <TeamB> <goalsA> <goalsB>
  injure   <PlayerName>          → mark player unavailable
  recover  <PlayerName>          → mark player available again
  form     <PlayerName> <-2..+2> → set player form
  fitness  <PlayerName> <0-100>  → set physical fitness % (playing through injury)
  teamform <TeamName>   <-2..+2> → set team-level form
  yellow   <PlayerName>          → record yellow card (auto-suspends at 2)
  clear-yellows                  → reset all yellow cards (between stages)
  aet      <TeamName>            → flag team played AET last round (−9% next match)
  dead     <TeamName> [<Team2>]  → flag dead-rubber match (rotation applied)

  ─── REPORTS ────────────────────────────────────────────────────
  squad    <TeamName>             → full squad status
  simulate                        → tournament Monte Carlo
  top-scorers                     → top scorer prediction
  bonus                           → full champion + top scorer
  venues                          → list all venues
  teams                           → list all 48 teams

  ─── EXTERNAL SOURCES ───────────────────────────────────────────
  sources                         → compare all sources vs our model (runs sim first)
  intel                           → list all intelligence gaps discovered
  apply-intel                     → apply all fitness/form intel to model
  dry-intel                       → preview intel updates without applying
  consensus                       → accuracy-weighted blended champion forecast

  ─── MISC ───────────────────────────────────────────────────────
  help | quit
"""

def interactive():
    print(f"\n{'═'*68}")
    print(f"  ⚽  FIFA WORLD CUP 2026 — PRO PREDICTION ENGINE")
    print(f"  Dixon-Coles + Squad Strength + Environment + Tactics + H2H")
    print(f"  Type 'help' for commands. Starts June 11, 2026.")
    print(f"{'═'*68}")

    while True:
        try:
            raw = input("\n  >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Good luck! 🏆"); break
        if not raw: continue

        parts = raw.split()
        cmd   = parts[0].lower()

        def get_opt(flag, default=None):
            try:
                idx = parts.index(flag)
                return parts[idx+1]
            except (ValueError, IndexError):
                return default

        def get_opt2(flag, d1=None, d2=None):
            try:
                idx = parts.index(flag)
                return parts[idx+1], parts[idx+2]
            except (ValueError, IndexError):
                return d1, d2

        if cmd in ("q","quit","exit"):
            print("  Good luck! 🏆"); break

        elif cmd == "help":
            print(HELP_TEXT)

        elif cmd == "teams":
            for g in "ABCDEFGHIJKL":
                print(f"  Group {g}: {' | '.join(GROUPS[g])}")

        elif cmd == "venues":
            print(f"\n  {'Name':<12} {'City':<16} {'Alt (m)':>8} {'Temp°C':>7} {'Humidity':>9}")
            print(f"  {'─'*55}")
            for vk, vd in VENUES.items():
                if vk=="Neutral": continue
                print(f"  {vk:<12} {vd['city']:<16} {vd['altitude_m']:>8} {vd['temp_c']:>7} {int(vd['humidity']*100):>8}%")

        elif cmd in ("p","predict") and len(parts) >= 3:
            a = find_team(parts[1]); b = find_team(parts[2])
            if a and b:
                venue = get_opt("--venue", "Neutral")
                r1, r2 = get_opt2("--rest", "4", "4")
                stage  = get_opt("--stage", "group")
                dead   = get_opt("--dead", None)
                predict_match(a, b, venue=venue, rest_a=int(r1), rest_b=int(r2),
                              stage=stage, dead_rubber=dead)

        elif cmd in ("g","group") and len(parts) >= 2:
            venue = get_opt("--venue", "Neutral")
            predict_group(parts[1], venue=venue)

        elif cmd == "all-groups":
            for g in "ABCDEFGHIJKL":
                predict_group(g)

        elif cmd in ("s","simulate"):
            p = simulate_tournament()
            ranked = sorted(p.items(), key=lambda x:-x[1]["champion"])
            print(f"\n  {'#':<4} {'Team':<26} {'Champion':>9}  {'Finalist':>9}  {'Top 4':>8}")
            for i,(t,v) in enumerate(ranked[:20],1):
                print(f"  {i:<4} {t:<26} {v['champion']*100:>8.1f}%  {v['finalist']*100:>8.1f}%  {v['semifinal']*100:>7.1f}%")

        elif cmd in ("t","top-scorers"):
            sp = predict_top_scorers()
            print(f"\n  {'#':<4} {'Player':<26} {'Team':<16} {'Prob':>6}")
            for i,(player,prob) in enumerate(sp[:12],1):
                team = next(t for t,td in TEAMS.items() if player in td["players"])
                print(f"  {i:<4} {player:<26} {team:<16} {prob*100:>5.1f}%")

        elif cmd in ("b","bonus"):
            bonus_predictions()

        elif cmd in ("u","update") and len(parts) >= 5:
            a = find_team(parts[1]); b = find_team(parts[2])
            if a and b:
                try: update_result(a, b, int(parts[3]), int(parts[4]))
                except ValueError: print("  ❌ Goals must be integers.")

        elif cmd == "injure" and len(parts) >= 2:
            pl = find_player(" ".join(parts[1:]))
            if pl: injure_player(pl)

        elif cmd == "recover" and len(parts) >= 2:
            pl = find_player(" ".join(parts[1:]))
            if pl: recover_player(pl)

        elif cmd == "form" and len(parts) >= 3:
            pl = find_player(" ".join(parts[1:-1]))
            if pl: set_player_form(pl, parts[-1])

        elif cmd == "fitness" and len(parts) >= 3:
            pl = find_player(" ".join(parts[1:-1]))
            if pl: set_fitness(pl, parts[-1])

        elif cmd == "teamform" and len(parts) >= 3:
            t = find_team(parts[1])
            if t: set_team_form(t, parts[2])

        elif cmd == "yellow" and len(parts) >= 2:
            pl = find_player(" ".join(parts[1:]))
            if pl: add_yellow_card(pl)

        elif cmd == "clear-yellows":
            clear_yellow_cards()

        elif cmd == "aet" and len(parts) >= 2:
            t = find_team(" ".join(parts[1:]))
            if t: mark_extra_time(t)

        elif cmd == "dead" and len(parts) >= 2:
            # dead <TeamA> [<TeamB>] — mark as dead rubber
            # Stored temporarily; next predict command reads --dead flag
            ta = find_team(parts[1])
            tb = find_team(parts[2]) if len(parts) >= 3 else None
            if ta and tb:
                print(f"  🔄 Dead rubber: both {ta} and {tb} will rotate.")
                print(f"     Run: predict {ta} {tb} --dead both")
            elif ta:
                print(f"  🔄 {ta} dead rubber — run: predict {ta} <opponent> --dead a")

        elif cmd == "squad" and len(parts) >= 2:
            t = find_team(" ".join(parts[1:]))
            if t: squad_report(t)

        elif cmd == "intel":
            intel_gaps()

        elif cmd == "apply-intel":
            apply_intel(dry_run=False)

        elif cmd == "dry-intel":
            apply_intel(dry_run=True)

        elif cmd == "sources":
            print("  🎲 Running simulation for comparison…")
            our = simulate_tournament()
            sources_report(our)

        elif cmd == "consensus":
            print("  🎲 Running simulation…")
            our = simulate_tournament()
            consensus_report(our)

        else:
            print(f"  ❓ Unknown command. Type 'help'.")


# ══════════════════════════════════════════════════════════════
# 18. CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════

def main():
    _load_state()

    if len(sys.argv) < 2:
        interactive()
        return

    cmd  = sys.argv[1].lower()
    args = sys.argv[2:]

    def opt(flag, default=None):
        try: i=args.index(flag); return args[i+1]
        except: return default

    if cmd == "predict" and len(args) >= 2:
        a = find_team(args[0]); b = find_team(args[1])
        if a and b:
            venue  = opt("--venue","Neutral")
            rest_a = int(opt("--rest-a","4")); rest_b = int(opt("--rest-b","4"))
            stage  = opt("--stage","group")
            dead   = opt("--dead", None)
            predict_match(a, b, venue=venue, rest_a=rest_a, rest_b=rest_b,
                          stage=stage, dead_rubber=dead)

    elif cmd == "group" and args:
        venue = opt("--venue","Neutral")
        predict_group(args[0], venue=venue)

    elif cmd == "all-groups":
        for g in "ABCDEFGHIJKL": predict_group(g)

    elif cmd == "simulate":
        p = simulate_tournament()
        for i,(t,v) in enumerate(sorted(p.items(),key=lambda x:-x[1]["champion"])[:20],1):
            print(f"  {i:<4} {t:<26} Champion: {v['champion']*100:.1f}%")

    elif cmd == "top-scorers":
        for i,(pl,prob) in enumerate(predict_top_scorers()[:12],1):
            team = next(t for t,td in TEAMS.items() if pl in td["players"])
            print(f"  {i:<4} {pl:<26} {team:<16} {prob*100:.1f}%")

    elif cmd == "bonus":
        bonus_predictions()

    elif cmd == "update" and len(args) >= 4:
        a = find_team(args[0]); b = find_team(args[1])
        if a and b: update_result(a, b, int(args[2]), int(args[3]))

    elif cmd == "injure":
        pl = find_player(" ".join(args))
        if pl: injure_player(pl)

    elif cmd == "recover":
        pl = find_player(" ".join(args))
        if pl: recover_player(pl)

    elif cmd == "fitness" and len(args) >= 2:
        pl = find_player(" ".join(args[:-1]))
        if pl: set_fitness(pl, args[-1])

    elif cmd == "squad" and args:
        t = find_team(" ".join(args))
        if t: squad_report(t)

    elif cmd == "yellow" and args:
        pl = find_player(" ".join(args))
        if pl: add_yellow_card(pl)

    elif cmd == "clear-yellows":
        clear_yellow_cards()

    elif cmd == "aet" and args:
        t = find_team(" ".join(args))
        if t: mark_extra_time(t)

    elif cmd == "intel":
        intel_gaps()

    elif cmd == "apply-intel":
        apply_intel(dry_run=False)

    elif cmd == "dry-intel":
        apply_intel(dry_run=True)

    elif cmd == "sources":
        print("  🎲 Running simulation for comparison…")
        our = simulate_tournament()
        sources_report(our)

    elif cmd == "consensus":
        print("  🎲 Running simulation…")
        our = simulate_tournament()
        consensus_report(our)

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
