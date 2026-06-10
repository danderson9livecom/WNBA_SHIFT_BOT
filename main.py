import os
import time
import json
import csv
import math
import smtplib
import requests
from email.message import EmailMessage
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from twilio.rest import Client

"""
SHIFT WNBA V1.1 — PROFESSIONAL BETTOR MODE

Built from the MLB SHIFT structure, but rebuilt for WNBA live betting.

Primary markets:
    1) WNBA live totals:
       Current score + possession-based projection + foul/pace/efficiency profile.

    2) Favorite buyback spread:
       Target favorite around +4.5 when the favorite is temporarily down because of
       a noisy underdog run, not because the game structure has flipped.

Professional upgrades from V1.0:
    - Separate total model and favorite-buyback model.
    - Quarter-specific gates.
    - Fake-run vs real-run detection.
    - Possession-value scoring for spread.
    - Stronger price discipline.
    - No-bet filters.
    - Cleaner exact spread grading using stored team_side.
    - CLV tracking and nightly summary report like MLB.
    - Profile learning summary by scenario.
    - Optional nightly email + optional SMS daily summary.
    - V1.2 team-strength ratings and pregame context.
    - V1.2 player/star availability impact hooks.
    - V1.2 foul-trouble and bonus-risk logic.
    - V1.2 first-half, halftime, Q3, and Q4-specific buyback rules.
    - V1.2 stricter do-not-chase rules.
    - V1.2 stronger learning recommendations by market/profile/quarter.
    - V1.3 Possession Pressure Index.
    - V1.3 scoring acceleration engine.
    - V1.3 run sustainability engine.
    - V1.3 future-state market predictor.
    - V1.3 model-vs-market mispricing score.

Important:
    This is an automated decision-support tool, not a guaranteed profit system.
    It can only evaluate markets your odds provider returns.
"""

load_dotenv()

# =============================================================================
# Identity / timezone / files
# =============================================================================
APP_VERSION = os.getenv("SHIFT_WNBA_APP_VERSION", "V1.7.0")
APP_MODE = "PROFIT CONTROLS + SIMPLE RESULT TEXTS + UNIT SUMMARY"
APP_BUILD_LABEL = f"SHIFT WNBA {APP_VERSION} {APP_MODE}"
TZ = ZoneInfo("America/Phoenix")

STATE_FILE = os.getenv("WNBA_STATE_FILE", "shift_wnba_state.json")
STRIKE_HISTORY_FILE = os.getenv("WNBA_STRIKE_HISTORY_FILE", "wnba_strike_history.csv")
GRADED_RESULTS_FILE = os.getenv("WNBA_GRADED_RESULTS_FILE", "wnba_graded_results.csv")
NEAR_MISS_FILE = os.getenv("WNBA_NEAR_MISS_FILE", "wnba_near_misses.csv")
LINE_HISTORY_FILE = os.getenv("WNBA_LINE_HISTORY_FILE", "wnba_line_history.csv")
CLV_HISTORY_FILE = os.getenv("WNBA_CLV_HISTORY_FILE", "wnba_clv_history.csv")
DAILY_SUMMARY_FILE = os.getenv("WNBA_DAILY_SUMMARY_FILE", "wnba_daily_summary.csv")
PROFILE_SUMMARY_FILE = os.getenv("WNBA_PROFILE_SUMMARY_FILE", "wnba_profile_summary.csv")
PROFILE_RULES_FILE = os.getenv("WNBA_PROFILE_RULES_FILE", "wnba_profile_rules.json")
MARKET_DISCREPANCY_FILE = os.getenv("WNBA_MARKET_DISCREPANCY_FILE", "wnba_market_discrepancy.csv")
BANKROLL_TRACKER_FILE = os.getenv("WNBA_BANKROLL_TRACKER_FILE", "wnba_bankroll_tracker.csv")

# =============================================================================
# Credentials / providers
# =============================================================================
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_SPORT_KEY = os.getenv("WNBA_ODDS_SPORT_KEY", "basketball_wnba")
ODDS_REGIONS = os.getenv("ODDS_REGIONS", "us")
ODDS_MARKETS = os.getenv("WNBA_ODDS_MARKETS", "totals,spreads,h2h")
ODDS_FORMAT = os.getenv("ODDS_FORMAT", "american")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
ALERT_TO_NUMBER = os.getenv("ALERT_TO_NUMBER", "")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER).strip()
NIGHTLY_EMAIL_TO = os.getenv("WNBA_NIGHTLY_EMAIL_TO", os.getenv("NIGHTLY_EMAIL_TO", "danderson9@live.com")).strip()
NIGHTLY_EMAIL_SUBJECT_PREFIX = os.getenv("WNBA_NIGHTLY_EMAIL_SUBJECT_PREFIX", "SHIFT WNBA Daily Summary").strip()

USER_PLAYABLE_BOOKS = [
    b.strip().lower()
    for b in os.getenv("WNBA_USER_PLAYABLE_BOOKS", os.getenv("USER_PLAYABLE_BOOKS", "betmgm")).split(",")
    if b.strip()
]
MARKET_REFERENCE_BOOKS = [
    b.strip().lower()
    for b in os.getenv("WNBA_MARKET_REFERENCE_BOOKS", "draftkings,fanduel,betmgm,caesars,espnbet,bet365,fanatics").split(",")
    if b.strip()
]
IGNORE_RECOMMENDATION_BOOKS = [
    b.strip().lower()
    for b in os.getenv("IGNORE_RECOMMENDATION_BOOKS", "mybookie,mybookieag,mybookie.ag").split(",")
    if b.strip()
]

# =============================================================================
# Polling / alert behavior
# =============================================================================
SLOW_POLL_SECONDS = int(os.getenv("WNBA_SLOW_POLL_SECONDS", "300"))
ACTIVE_POLL_SECONDS = int(os.getenv("WNBA_ACTIVE_POLL_SECONDS", "45"))
FAST_POLL_SECONDS = int(os.getenv("WNBA_FAST_POLL_SECONDS", "20"))
PREGAME_WINDOW_MINUTES = int(os.getenv("WNBA_PREGAME_WINDOW_MINUTES", "45"))

SEND_ONLY_STRIKE_SMS = os.getenv("SEND_ONLY_STRIKE_SMS", "true").lower() == "true"
MAX_SHORT_SMS_CHARS = int(os.getenv("WNBA_MAX_SHORT_SMS_CHARS", "720"))
ALERT_COOLDOWN_SECONDS = int(os.getenv("WNBA_ALERT_COOLDOWN_SECONDS", "720"))
ONE_STRIKE_PER_GAME_MARKET = os.getenv("WNBA_ONE_STRIKE_PER_GAME_MARKET", "true").lower() == "true"
ALLOW_TRUE_REVERSAL = os.getenv("WNBA_ALLOW_TRUE_REVERSAL", "true").lower() == "true"

# Daily/nightly reporting
ENABLE_DAILY_LEARNING_REPORT = os.getenv("WNBA_ENABLE_DAILY_LEARNING_REPORT", "true").lower() == "true"
SEND_DAILY_LEARNING_REPORT_SMS = os.getenv("WNBA_SEND_DAILY_LEARNING_REPORT_SMS", "true").lower() == "true"
SEND_RESULT_SMS = os.getenv("WNBA_SEND_RESULT_SMS", "true").lower() == "true"
ENABLE_NIGHTLY_EMAIL_REPORT = os.getenv("WNBA_ENABLE_NIGHTLY_EMAIL_REPORT", "true").lower() == "true"
DAILY_LEARNING_REPORT_HOUR = int(os.getenv("WNBA_DAILY_LEARNING_REPORT_HOUR", "22"))
ATTACH_DAILY_CSVS_TO_EMAIL = os.getenv("WNBA_ATTACH_DAILY_CSVS_TO_EMAIL", "true").lower() == "true"
STARTING_BANKROLL_UNITS = float(os.getenv("WNBA_STARTING_BANKROLL_UNITS", "100.0"))
SEND_SIMPLE_RESULT_SMS = os.getenv("WNBA_SEND_SIMPLE_RESULT_SMS", "true").lower() == "true"
SEND_SIMPLE_DAILY_SUMMARY_SMS = os.getenv("WNBA_SEND_SIMPLE_DAILY_SUMMARY_SMS", "true").lower() == "true"

# =============================================================================
# WNBA model thresholds
# =============================================================================
REGULATION_MINUTES = 40.0
PERIOD_MINUTES = 10.0
DEFAULT_GAME_POSSESSIONS = float(os.getenv("WNBA_DEFAULT_GAME_POSSESSIONS", "78.0"))
DEFAULT_POINTS_PER_POSSESSION = float(os.getenv("WNBA_DEFAULT_PPP", "1.02"))

# Wide-net learning mode:
# Start with broader capture, then use graded units + CLV by profile to tighten.
WIDE_NET_LEARNING_MODE = os.getenv("WNBA_WIDE_NET_LEARNING_MODE", "true").lower() == "true"
ENABLE_PROJECTION_REALITY_CAPS = os.getenv("WNBA_ENABLE_PROJECTION_REALITY_CAPS", "true").lower() == "true"

# WNBA reality caps. These stop one hot/cold run from creating fake 25-50 point edges.
WNBA_MIN_EXPECTED_TEAM_PPP = float(os.getenv("WNBA_MIN_EXPECTED_TEAM_PPP", "0.86"))
WNBA_MAX_EXPECTED_TEAM_PPP = float(os.getenv("WNBA_MAX_EXPECTED_TEAM_PPP", "1.20"))
WNBA_MAX_LIVE_TEAM_PPP = float(os.getenv("WNBA_MAX_LIVE_TEAM_PPP", "1.28"))
WNBA_MIN_LIVE_TEAM_PPP = float(os.getenv("WNBA_MIN_LIVE_TEAM_PPP", "0.78"))
WNBA_MIN_PROJECTED_POSSESSIONS = float(os.getenv("WNBA_MIN_PROJECTED_POSSESSIONS", "68.0"))
WNBA_MAX_PROJECTED_POSSESSIONS = float(os.getenv("WNBA_MAX_PROJECTED_POSSESSIONS", "88.0"))
WNBA_SANITY_EDGE_WARN = float(os.getenv("WNBA_SANITY_EDGE_WARN", "16.0"))
WNBA_SANITY_EDGE_HARD_CAP = float(os.getenv("WNBA_SANITY_EDGE_HARD_CAP", "24.0"))

# Tiered staking for learning. This is still a recreational decision-support tool.
UNIT_A_PLUS = float(os.getenv("WNBA_UNIT_A_PLUS", "1.0"))
UNIT_B = float(os.getenv("WNBA_UNIT_B", "0.5"))
UNIT_SMALL = float(os.getenv("WNBA_UNIT_SMALL", "0.25"))

# A-grade market-discrepancy controls.
# These detect whether the user's playable book is stale/off-market versus consensus.
ENABLE_MARKET_DISCREPANCY_ENGINE = os.getenv("WNBA_ENABLE_MARKET_DISCREPANCY_ENGINE", "true").lower() == "true"
ENABLE_ADAPTIVE_PROFILE_RULES = os.getenv("WNBA_ENABLE_ADAPTIVE_PROFILE_RULES", "true").lower() == "true"
STALE_LINE_SECONDS = int(os.getenv("WNBA_STALE_LINE_SECONDS", "180"))
MARKET_CONSENSUS_MIN_BOOKS = int(os.getenv("WNBA_MARKET_CONSENSUS_MIN_BOOKS", "3"))
OFF_MARKET_TOTAL_POINTS = float(os.getenv("WNBA_OFF_MARKET_TOTAL_POINTS", "1.5"))
STRONG_OFF_MARKET_TOTAL_POINTS = float(os.getenv("WNBA_STRONG_OFF_MARKET_TOTAL_POINTS", "2.5"))
BIG_EDGE_CONSENSUS_REQUIRED = float(os.getenv("WNBA_BIG_EDGE_CONSENSUS_REQUIRED", "12.0"))
PROFILE_RULE_MIN_SAMPLE = int(os.getenv("WNBA_PROFILE_RULE_MIN_SAMPLE", "6"))
PROFILE_TIGHTEN_CLV = float(os.getenv("WNBA_PROFILE_TIGHTEN_CLV", "-0.25"))
PROFILE_TRUST_CLV = float(os.getenv("WNBA_PROFILE_TRUST_CLV", "0.25"))

# V1.6 paid-alert controls: learning can stay wide, but paid texts get stricter.
SEND_SMALL_LEAN_SMS = os.getenv("WNBA_SEND_SMALL_LEAN_SMS", "false").lower() == "true"
MIN_PAID_ALERT_TIER = os.getenv("WNBA_MIN_PAID_ALERT_TIER", "B_STRIKE").upper()
REQUIRE_MARKET_CONFIRMATION_FOR_SMALL = os.getenv("WNBA_REQUIRE_MARKET_CONFIRMATION_FOR_SMALL", "true").lower() == "true"
BAD_PROFILE_BLOCK_PAID = os.getenv("WNBA_BAD_PROFILE_BLOCK_PAID", "true").lower() == "true"
SPREAD_OFF_MARKET_POINTS = float(os.getenv("WNBA_SPREAD_OFF_MARKET_POINTS", "1.0"))
SPREAD_STRONG_OFF_MARKET_POINTS = float(os.getenv("WNBA_SPREAD_STRONG_OFF_MARKET_POINTS", "1.5"))
SHORT_VELOCITY_WINDOW_SECONDS = int(os.getenv("WNBA_SHORT_VELOCITY_WINDOW_SECONDS", "180"))
PAID_ALERT_REQUIRE_NON_NEGATIVE_PROFILE = os.getenv("WNBA_PAID_ALERT_REQUIRE_NON_NEGATIVE_PROFILE", "true").lower() == "true"


# Total market gates
MIN_TOTAL_EDGE_POINTS = float(os.getenv("WNBA_MIN_TOTAL_EDGE_POINTS", "3.0"))
MIN_TOTAL_CONFIDENCE = int(os.getenv("WNBA_MIN_TOTAL_CONFIDENCE", "60"))
MIN_TOTAL_VALUE_SCORE = int(os.getenv("WNBA_MIN_TOTAL_VALUE_SCORE", "56"))
MAX_TOTAL_RISK_SCORE = int(os.getenv("WNBA_MAX_TOTAL_RISK_SCORE", "72"))

# Favorite buyback gates
ENABLE_FAVORITE_BUYBACK = os.getenv("WNBA_ENABLE_FAVORITE_BUYBACK", "true").lower() == "true"
FAVORITE_BUYBACK_TARGET = float(os.getenv("WNBA_FAVORITE_BUYBACK_TARGET", "4.5"))
FAVORITE_BUYBACK_MIN_LINE = float(os.getenv("WNBA_FAVORITE_BUYBACK_MIN_LINE", "3.5"))
FAVORITE_BUYBACK_MAX_LINE = float(os.getenv("WNBA_FAVORITE_BUYBACK_MAX_LINE", "6.5"))
FAVORITE_BUYBACK_MIN_CONFIDENCE = int(os.getenv("WNBA_FAVORITE_BUYBACK_MIN_CONFIDENCE", "62"))
FAVORITE_BUYBACK_MIN_VALUE_SCORE = int(os.getenv("WNBA_FAVORITE_BUYBACK_MIN_VALUE_SCORE", "58"))
FAVORITE_BUYBACK_MAX_RISK = int(os.getenv("WNBA_FAVORITE_BUYBACK_MAX_RISK", "72"))
FAVORITE_BUYBACK_MIN_SWING = float(os.getenv("WNBA_FAVORITE_BUYBACK_MIN_SWING", "5.0"))

# Price discipline
MAX_TOTAL_PRICE = int(os.getenv("WNBA_MAX_TOTAL_PRICE", "-130"))
MAX_SPREAD_PRICE = int(os.getenv("WNBA_MAX_SPREAD_PRICE", "-130"))
ELITE_SPREAD_MAX_PRICE = int(os.getenv("WNBA_ELITE_SPREAD_MAX_PRICE", "-140"))
ELITE_SPREAD_MIN_CONFIDENCE = int(os.getenv("WNBA_ELITE_SPREAD_MIN_CONFIDENCE", "84"))
MAX_MONEYLINE_PRICE = int(os.getenv("WNBA_MAX_MONEYLINE_PRICE", "-140"))
MAX_DOG_PRICE = int(os.getenv("WNBA_MAX_DOG_PRICE", "115"))

# Momentum scoring
RUN_WINDOW_MAX_MINUTES = float(os.getenv("WNBA_RUN_WINDOW_MAX_MINUTES", "4.0"))
STRONG_RUN_MARGIN = int(os.getenv("WNBA_STRONG_RUN_MARGIN", "8"))
VERY_STRONG_RUN_MARGIN = int(os.getenv("WNBA_VERY_STRONG_RUN_MARGIN", "12"))

# No-bet filters
MAX_FAVORITE_TURNOVER_GAP = int(os.getenv("WNBA_MAX_FAVORITE_TURNOVER_GAP", "6"))
MAX_FAVORITE_FOUL_GAP = int(os.getenv("WNBA_MAX_FAVORITE_FOUL_GAP", "5"))
MAX_FAVORITE_REBOUND_DEFICIT = int(os.getenv("WNBA_MAX_FAVORITE_REBOUND_DEFICIT", "8"))
MIN_SPREAD_POSSESSIONS_LEFT = float(os.getenv("WNBA_MIN_SPREAD_POSSESSIONS_LEFT", "14"))
MIN_TOTAL_POSSESSIONS_LEFT = float(os.getenv("WNBA_MIN_TOTAL_POSSESSIONS_LEFT", "10"))

# CLV grading
CLV_SNAPSHOT_MIN_MOVE = float(os.getenv("WNBA_CLV_SNAPSHOT_MIN_MOVE", "0.5"))
GOOD_CLV_THRESHOLD = float(os.getenv("WNBA_GOOD_CLV_THRESHOLD", "0.5"))
MIN_PROFILE_SAMPLE_FOR_REPORT = int(os.getenv("WNBA_MIN_PROFILE_SAMPLE_FOR_REPORT", "2"))

# =============================================================================
# V1.2 Professional context layer
# =============================================================================
# These ratings are lightweight defaults so the bot can run today without a paid feed.
# You can override them with WNBA_TEAM_RATINGS_JSON as a JSON string:
# {
#   "Las Vegas Aces": {"strength": 88, "off": 86, "def": 82, "pace": 79, "reb": 78, "tov": 72, "star": 92},
#   ...
# }
#
# strength = overall power rating, off/def/pace/reb/tov/star = 0-100.
# def is "defensive quality" where higher is better.
DEFAULT_TEAM_RATINGS = {
    "New York Liberty":       {"strength": 88, "off": 88, "def": 82, "pace": 78, "reb": 78, "tov": 76, "star": 90},
    "Las Vegas Aces":         {"strength": 87, "off": 89, "def": 79, "pace": 80, "reb": 77, "tov": 74, "star": 95},
    "Minnesota Lynx":         {"strength": 86, "off": 84, "def": 86, "pace": 76, "reb": 80, "tov": 78, "star": 88},
    "Connecticut Sun":        {"strength": 82, "off": 78, "def": 84, "pace": 73, "reb": 82, "tov": 76, "star": 82},
    "Seattle Storm":          {"strength": 80, "off": 80, "def": 79, "pace": 77, "reb": 76, "tov": 74, "star": 84},
    "Phoenix Mercury":        {"strength": 79, "off": 82, "def": 74, "pace": 81, "reb": 72, "tov": 70, "star": 86},
    "Indiana Fever":          {"strength": 78, "off": 82, "def": 72, "pace": 82, "reb": 74, "tov": 68, "star": 88},
    "Atlanta Dream":          {"strength": 77, "off": 77, "def": 77, "pace": 76, "reb": 76, "tov": 72, "star": 78},
    "Dallas Wings":           {"strength": 74, "off": 78, "def": 70, "pace": 83, "reb": 78, "tov": 66, "star": 80},
    "Washington Mystics":     {"strength": 73, "off": 73, "def": 74, "pace": 75, "reb": 73, "tov": 72, "star": 74},
    "Chicago Sky":            {"strength": 72, "off": 70, "def": 73, "pace": 77, "reb": 82, "tov": 66, "star": 76},
    "Los Angeles Sparks":     {"strength": 71, "off": 71, "def": 72, "pace": 76, "reb": 72, "tov": 68, "star": 76},
    "Golden State Valkyries":  {"strength": 70, "off": 70, "def": 71, "pace": 76, "reb": 70, "tov": 68, "star": 72},
}

TEAM_RATINGS_JSON = os.getenv("WNBA_TEAM_RATINGS_JSON", "").strip()
STAR_STATUS_JSON = os.getenv("WNBA_STAR_STATUS_JSON", "").strip()
# STAR_STATUS_JSON example:
# {"Las Vegas Aces": {"star_status": "out", "impact": -10}, "Indiana Fever": {"star_status": "limited", "impact": -5}}
# status values: active, limited, questionable, out.

ENABLE_TEAM_STRENGTH_CONTEXT = os.getenv("WNBA_ENABLE_TEAM_STRENGTH_CONTEXT", "true").lower() == "true"
ENABLE_PLAYER_IMPACT_CONTEXT = os.getenv("WNBA_ENABLE_PLAYER_IMPACT_CONTEXT", "true").lower() == "true"
ENABLE_FOUL_TROUBLE_CONTEXT = os.getenv("WNBA_ENABLE_FOUL_TROUBLE_CONTEXT", "true").lower() == "true"
ENABLE_DO_NOT_CHASE_CONTEXT = os.getenv("WNBA_ENABLE_DO_NOT_CHASE_CONTEXT", "true").lower() == "true"
ENABLE_HALFTIME_Q3_CONTEXT = os.getenv("WNBA_ENABLE_HALFTIME_Q3_CONTEXT", "true").lower() == "true"

MIN_FAVORITE_STRENGTH_EDGE = float(os.getenv("WNBA_MIN_FAVORITE_STRENGTH_EDGE", "3.0"))
STAR_OUT_BUYBACK_BLOCK = os.getenv("WNBA_STAR_OUT_BUYBACK_BLOCK", "true").lower() == "true"
STAR_LIMITED_RISK_BUMP = int(os.getenv("WNBA_STAR_LIMITED_RISK_BUMP", "10"))
STAR_OUT_RISK_BUMP = int(os.getenv("WNBA_STAR_OUT_RISK_BUMP", "24"))
DO_NOT_CHASE_TOTAL_MOVE = float(os.getenv("WNBA_DO_NOT_CHASE_TOTAL_MOVE", "10.0"))
DO_NOT_CHASE_SPREAD_SWING = float(os.getenv("WNBA_DO_NOT_CHASE_SPREAD_SWING", "9.0"))
DO_NOT_CHASE_MIN_CONFIDENCE = int(os.getenv("WNBA_DO_NOT_CHASE_MIN_CONFIDENCE", "84"))
Q3_BUYBACK_BONUS = int(os.getenv("WNBA_Q3_BUYBACK_BONUS", "10"))
HALFTIME_RESET_BONUS = int(os.getenv("WNBA_HALFTIME_RESET_BONUS", "6"))
Q4_LATE_BUYBACK_PENALTY = int(os.getenv("WNBA_Q4_LATE_BUYBACK_PENALTY", "18"))

# =============================================================================
# V1.3 Market Predictor / Future-State Engine
# =============================================================================
ENABLE_MARKET_PREDICTOR_ENGINE = os.getenv("WNBA_ENABLE_MARKET_PREDICTOR_ENGINE", "true").lower() == "true"
ENABLE_POSSESSION_PRESSURE_INDEX = os.getenv("WNBA_ENABLE_POSSESSION_PRESSURE_INDEX", "true").lower() == "true"
ENABLE_SCORING_ACCELERATION = os.getenv("WNBA_ENABLE_SCORING_ACCELERATION", "true").lower() == "true"
ENABLE_RUN_SUSTAINABILITY = os.getenv("WNBA_ENABLE_RUN_SUSTAINABILITY", "true").lower() == "true"

# The bot is no longer just asking, "Can this bet win?"
# It asks, "Is the current live market failing to price the next 3-8 possessions?"
MIN_MARKET_MISPRICE_SCORE = int(os.getenv("WNBA_MIN_MARKET_MISPRICE_SCORE", "55"))
MIN_FUTURE_STATE_SCORE = int(os.getenv("WNBA_MIN_FUTURE_STATE_SCORE", "50"))
MIN_RUN_UNSUSTAINABLE_SCORE = int(os.getenv("WNBA_MIN_RUN_UNSUSTAINABLE_SCORE", "62"))
MIN_ACCELERATION_SCORE = int(os.getenv("WNBA_MIN_ACCELERATION_SCORE", "58"))

# Predictor horizon: how much of the next stretch the model should care about.
PREDICTOR_POSSESSION_HORIZON = float(os.getenv("WNBA_PREDICTOR_POSSESSION_HORIZON", "8.0"))
PREDICTOR_MINUTES_HORIZON = float(os.getenv("WNBA_PREDICTOR_MINUTES_HORIZON", "4.0"))

# Future line estimate controls.
TOTAL_POINT_TO_MARKET_MOVE_RATIO = float(os.getenv("WNBA_TOTAL_POINT_TO_MARKET_MOVE_RATIO", "0.55"))
SPREAD_POINT_TO_MARKET_MOVE_RATIO = float(os.getenv("WNBA_SPREAD_POINT_TO_MARKET_MOVE_RATIO", "0.62"))
STRONG_PPI_THRESHOLD = int(os.getenv("WNBA_STRONG_PPI_THRESHOLD", "70"))
ELITE_PPI_THRESHOLD = int(os.getenv("WNBA_ELITE_PPI_THRESHOLD", "82"))

# =============================================================================
# General helpers
# =============================================================================
def now_local():
    return datetime.now(TZ)

def today():
    return now_local().strftime("%Y-%m-%d")

def clamp(value, low=0, high=100):
    return max(low, min(high, value))

def safe_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default

def safe_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default

def avg(values, default=0.0):
    nums = [safe_float(v, None) for v in values]
    nums = [v for v in nums if v is not None]
    return round(sum(nums) / len(nums), 3) if nums else default

def american_to_prob(price):
    p = safe_float(price, 0)
    if p == 0:
        return None
    if p < 0:
        return abs(p) / (abs(p) + 100.0)
    return 100.0 / (p + 100.0)

def decimal_profit_units(price, stake=1.0):
    p = safe_int(price, -110)
    if p < 0:
        return stake * (100.0 / abs(p))
    return stake * (p / 100.0)

def result_units(result, price, stake=1.0):
    stake = safe_float(stake, 1.0)
    if result == "WIN":
        return round(decimal_profit_units(price, stake=stake), 2)
    if result == "LOSS":
        return round(-1.0 * stake, 2)
    return 0.0

def load_json(path, fallback):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return fallback

def save_json(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)

def append_csv(path, row, fieldnames):
    exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)

def read_csv_rows(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []

def normalize_team(name):
    text = (name or "").lower()
    repl = {
        "new york liberty": "ny liberty",
        "las vegas aces": "lv aces",
        "golden state valkyries": "gs valkyries",
        "washington mystics": "washington mystics",
        "connecticut sun": "connecticut sun",
        "indiana fever": "indiana fever",
        "chicago sky": "chicago sky",
        "atlanta dream": "atlanta dream",
        "phoenix mercury": "phoenix mercury",
        "seattle storm": "seattle storm",
        "minnesota lynx": "minnesota lynx",
        "dallas wings": "dallas wings",
        "los angeles sparks": "la sparks",
    }
    for k, v in repl.items():
        text = text.replace(k, v)
    return "".join(ch for ch in text if ch.isalnum())


def load_team_ratings():
    if TEAM_RATINGS_JSON:
        try:
            custom = json.loads(TEAM_RATINGS_JSON)
            if isinstance(custom, dict):
                merged = dict(DEFAULT_TEAM_RATINGS)
                for k, v in custom.items():
                    if isinstance(v, dict):
                        merged[k] = {**merged.get(k, {}), **v}
                return merged
        except Exception as e:
            print("TEAM RATINGS JSON ERROR:", repr(e))
    return DEFAULT_TEAM_RATINGS

def load_star_status():
    if STAR_STATUS_JSON:
        try:
            data = json.loads(STAR_STATUS_JSON)
            if isinstance(data, dict):
                return data
        except Exception as e:
            print("STAR STATUS JSON ERROR:", repr(e))
    return {}

TEAM_RATINGS = load_team_ratings()
STAR_STATUS = load_star_status()

def team_rating(name):
    if not ENABLE_TEAM_STRENGTH_CONTEXT:
        return {"strength": 75, "off": 75, "def": 75, "pace": 78, "reb": 75, "tov": 72, "star": 75}
    norm = normalize_team(name)
    for k, v in TEAM_RATINGS.items():
        if normalize_team(k) == norm:
            return {
                "strength": safe_float(v.get("strength"), 75),
                "off": safe_float(v.get("off"), 75),
                "def": safe_float(v.get("def"), 75),
                "pace": safe_float(v.get("pace"), 78),
                "reb": safe_float(v.get("reb"), 75),
                "tov": safe_float(v.get("tov"), 72),
                "star": safe_float(v.get("star"), 75),
            }
    return {"strength": 75, "off": 75, "def": 75, "pace": 78, "reb": 75, "tov": 72, "star": 75}

def star_context(team_name):
    if not ENABLE_PLAYER_IMPACT_CONTEXT:
        return {"star_status": "active", "impact": 0, "note": "player impact disabled"}
    norm = normalize_team(team_name)
    for k, v in STAR_STATUS.items():
        if normalize_team(k) == norm:
            status = str(v.get("star_status", "active")).lower()
            impact = safe_float(v.get("impact"), 0)
            return {"star_status": status, "impact": impact, "note": v.get("note", "")}
    return {"star_status": "active", "impact": 0, "note": ""}

def game_context(info):
    home_rating = team_rating(info.get("home"))
    away_rating = team_rating(info.get("away"))
    home_star = star_context(info.get("home"))
    away_star = star_context(info.get("away"))

    home_strength = home_rating["strength"] + safe_float(home_star.get("impact"), 0)
    away_strength = away_rating["strength"] + safe_float(away_star.get("impact"), 0)

    return {
        "home_rating": home_rating,
        "away_rating": away_rating,
        "home_star": home_star,
        "away_star": away_star,
        "home_strength_adj": round(home_strength, 1),
        "away_strength_adj": round(away_strength, 1),
        "strength_edge_home": round(home_strength - away_strength, 1),
        "total_pace_rating": round((home_rating["pace"] + away_rating["pace"]) / 2, 1),
        "total_off_rating": round((home_rating["off"] + away_rating["off"]) / 2, 1),
        "total_def_rating": round((home_rating["def"] + away_rating["def"]) / 2, 1),
    }

def team_context_for_side(info, side):
    ctx = game_context(info)
    if side == "home":
        return {
            "team": info.get("home"),
            "team_rating": ctx["home_rating"],
            "opp_rating": ctx["away_rating"],
            "star": ctx["home_star"],
            "opp_star": ctx["away_star"],
            "strength_edge": ctx["strength_edge_home"],
        }
    return {
        "team": info.get("away"),
        "team_rating": ctx["away_rating"],
        "opp_rating": ctx["home_rating"],
        "star": ctx["away_star"],
        "opp_star": ctx["home_star"],
        "strength_edge": -ctx["strength_edge_home"],
    }

def is_halftime_or_q3_reset_window(info):
    q = safe_int(info.get("period"), 0)
    clock_left = safe_float(info.get("clock_minutes"), 0)
    if q == 2 and clock_left <= 1.0:
        return True
    if q == 3 and safe_float(info.get("minutes_elapsed"), 0) <= 25:
        return True
    return False

def is_ignored_book(book_key):
    return (book_key or "").lower() in IGNORE_RECOMMENDATION_BOOKS

def market_label(price):
    if price is None:
        return "NO PRICE"
    p = safe_int(price)
    if p <= -141:
        return "EXPENSIVE"
    if -140 <= p <= -121:
        return "PLAYABLE ONLY IF ELITE"
    if -120 <= p <= -105:
        return "GOOD PRICE"
    if -104 <= p <= 110:
        return "FAIR / PLUS"
    return "PLUS MONEY"

def line_age_seconds(last_update):
    if not last_update:
        return None
    try:
        dt = datetime.fromisoformat(str(last_update).replace("Z", "+00:00"))
        return (datetime.now(dt.tzinfo) - dt).total_seconds()
    except Exception:
        return None

# =============================================================================
# ESPN WNBA live data
# =============================================================================
def espn_scoreboard():
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
    params = {"dates": now_local().strftime("%Y%m%d"), "limit": 50}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("events", []) or []
    except Exception as e:
        print("ESPN SCOREBOARD ERROR:", repr(e))
        return []

def espn_summary(event_id):
    url = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"
    try:
        r = requests.get(url, params={"event": event_id}, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"ESPN SUMMARY ERROR {event_id}:", repr(e))
        return {}

def parse_espn_start(comp):
    raw = comp.get("date")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(TZ)
    except Exception:
        return None

def parse_clock_minutes(clock_text):
    if not clock_text:
        return 0.0
    try:
        parts = str(clock_text).split(":")
        if len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60.0
    except Exception:
        pass
    return 0.0

def status_type(comp):
    return (comp.get("status", {}).get("type", {}) or {}).get("name", "")

def is_live_status(comp):
    name = status_type(comp).lower()
    return name in {"status_in_progress", "status_halftime", "status_end_period"}

def is_final_status(comp):
    name = status_type(comp).lower()
    return name in {"status_final", "status_full_time", "status_postponed", "status_canceled"}

def game_label_from_event(event):
    comp = (event.get("competitions") or [{}])[0]
    teams = comp.get("competitors", []) or []
    home = next((t for t in teams if t.get("homeAway") == "home"), {})
    away = next((t for t in teams if t.get("homeAway") == "away"), {})
    return f"{away.get('team', {}).get('displayName', 'Away')} at {home.get('team', {}).get('displayName', 'Home')}"

def parse_made_attempted(value):
    if value is None:
        return 0, 0
    txt = str(value)
    if "-" in txt:
        a, b = txt.split("-", 1)
        return safe_int(a), safe_int(b)
    return 0, 0

def normalize_basketball_stats(stats):
    fgm, fga = parse_made_attempted(stats.get("fieldGoalsMade-fieldGoalsAttempted") or stats.get("fieldGoals"))
    tpm, tpa = parse_made_attempted(stats.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted") or stats.get("threePointFieldGoals"))
    ftm, fta = parse_made_attempted(stats.get("freeThrowsMade-freeThrowsAttempted") or stats.get("freeThrows"))

    turnovers = safe_int(stats.get("turnovers") or stats.get("totalTurnovers"), 0)
    off_reb = safe_int(stats.get("offensiveRebounds"), 0)
    def_reb = safe_int(stats.get("defensiveRebounds"), 0)
    assists = safe_int(stats.get("assists"), 0)
    fouls = safe_int(stats.get("fouls") or stats.get("personalFouls"), 0)
    steals = safe_int(stats.get("steals"), 0)
    blocks = safe_int(stats.get("blocks"), 0)
    fast_break = safe_int(stats.get("fastBreakPoints"), 0)
    points_in_paint = safe_int(stats.get("pointsInPaint"), 0)

    efg = ((fgm + 0.5 * tpm) / fga) if fga else 0
    ftr = (fta / fga) if fga else 0

    return {
        "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa, "ftm": ftm, "fta": fta,
        "turnovers": turnovers, "off_reb": off_reb, "def_reb": def_reb,
        "rebounds": off_reb + def_reb, "assists": assists, "fouls": fouls,
        "steals": steals, "blocks": blocks, "fast_break": fast_break,
        "points_in_paint": points_in_paint, "efg": round(efg, 3), "ftr": round(ftr, 3),
    }

def parse_box_stats(summary, home_name, away_name):
    out = {"home": {}, "away": {}}
    boxscore = summary.get("boxscore", {}) or {}
    teams = boxscore.get("teams", []) or []
    for t in teams:
        team = t.get("team", {}) or {}
        display = team.get("displayName") or team.get("shortDisplayName") or ""
        side = None
        if normalize_team(display) == normalize_team(home_name):
            side = "home"
        elif normalize_team(display) == normalize_team(away_name):
            side = "away"
        if not side:
            continue
        stats = {}
        for s in t.get("statistics", []) or []:
            name = s.get("name") or s.get("label") or ""
            stats[name] = s.get("displayValue") or s.get("value")
        out[side] = normalize_basketball_stats(stats)
    return out

def parse_live_game(event, summary=None):
    summary = summary or {}
    comp = (event.get("competitions") or [{}])[0]
    competitors = comp.get("competitors", []) or []
    home = next((t for t in competitors if t.get("homeAway") == "home"), {})
    away = next((t for t in competitors if t.get("homeAway") == "away"), {})

    home_team = home.get("team", {}) or {}
    away_team = away.get("team", {}) or {}
    home_name = home_team.get("displayName") or home_team.get("shortDisplayName") or "Home"
    away_name = away_team.get("displayName") or away_team.get("shortDisplayName") or "Away"

    period = safe_int(comp.get("status", {}).get("period"), 0)
    clock_text = comp.get("status", {}).get("displayClock") or ""
    clock_minutes = parse_clock_minutes(clock_text)

    home_score = safe_int(home.get("score"), 0)
    away_score = safe_int(away.get("score"), 0)

    line_scores = {"home": [], "away": []}
    for side_name, team_obj in [("home", home), ("away", away)]:
        for ls in team_obj.get("linescores", []) or []:
            line_scores[side_name].append(safe_int(ls.get("value"), 0))

    if period <= 0:
        minutes_elapsed = 0.0
    elif period <= 4:
        minutes_elapsed = (period - 1) * PERIOD_MINUTES + max(0.0, PERIOD_MINUTES - clock_minutes)
    else:
        minutes_elapsed = REGULATION_MINUTES
    minutes_remaining = max(0.0, REGULATION_MINUTES - minutes_elapsed)

    return {
        "event_id": event.get("id"),
        "status": status_type(comp),
        "status_detail": comp.get("status", {}).get("type", {}).get("detail") or comp.get("status", {}).get("type", {}).get("description"),
        "start_time": parse_espn_start(comp),
        "home": home_name, "away": away_name,
        "home_abbrev": home_team.get("abbreviation"), "away_abbrev": away_team.get("abbreviation"),
        "home_score": home_score, "away_score": away_score,
        "total_score": home_score + away_score,
        "score_diff_home": home_score - away_score,
        "period": period, "clock": clock_text, "clock_minutes": clock_minutes,
        "minutes_elapsed": round(minutes_elapsed, 2),
        "minutes_remaining": round(minutes_remaining, 2),
        "line_scores": line_scores,
        "box": parse_box_stats(summary, home_name, away_name),
    }

# =============================================================================
# Odds API
# =============================================================================
def get_odds():
    if not ODDS_API_KEY:
        print("ODDS SKIPPED: Missing ODDS_API_KEY")
        return []
    url = f"https://api.the-odds-api.com/v4/sports/{ODDS_SPORT_KEY}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": ODDS_REGIONS,
        "markets": ODDS_MARKETS,
        "oddsFormat": ODDS_FORMAT,
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        print("ODDS CREDITS REMAINING:", r.headers.get("x-requests-remaining"))
        return r.json() or []
    except Exception as e:
        print("ODDS ERROR:", repr(e))
        return []

def matchup_score(a_home, a_away, b_home, b_away):
    return (
        int(normalize_team(a_home) == normalize_team(b_home)) +
        int(normalize_team(a_away) == normalize_team(b_away))
    )

def find_markets(odds, home, away):
    best_event = None
    best_score = -1
    for ev in odds or []:
        score = matchup_score(home, away, ev.get("home_team"), ev.get("away_team"))
        if score > best_score:
            best_score = score
            best_event = ev

    empty = {"total": None, "spreads": {}, "h2h": {}, "books_seen": 0, "event": best_event}
    if not best_event or best_score <= 0:
        return empty

    markets = dict(empty)
    totals = []
    for book in best_event.get("bookmakers", []) or []:
        key = (book.get("key") or "").lower()
        if is_ignored_book(key):
            continue
        markets["books_seen"] += 1

        for m in book.get("markets", []) or []:
            mk = m.get("key")
            outcomes = m.get("outcomes", []) or []

            if mk == "totals":
                over = next((o for o in outcomes if str(o.get("name", "")).lower() == "over"), None)
                under = next((o for o in outcomes if str(o.get("name", "")).lower() == "under"), None)
                if over and over.get("point") is not None:
                    totals.append({
                        "book": key,
                        "point": safe_float(over.get("point")),
                        "over_price": over.get("price"),
                        "under_price": under.get("price") if under else None,
                        "last_update": book.get("last_update"),
                    })

            elif mk == "spreads":
                for o in outcomes:
                    team = o.get("name", "")
                    side = "home" if normalize_team(team) == normalize_team(home) else "away" if normalize_team(team) == normalize_team(away) else None
                    if side:
                        markets["spreads"].setdefault(side, []).append({
                            "book": key, "team": team, "point": safe_float(o.get("point")),
                            "price": o.get("price"), "last_update": book.get("last_update"),
                        })

            elif mk == "h2h":
                for o in outcomes:
                    team = o.get("name", "")
                    side = "home" if normalize_team(team) == normalize_team(home) else "away" if normalize_team(team) == normalize_team(away) else None
                    if side:
                        markets["h2h"].setdefault(side, []).append({
                            "book": key, "team": team, "price": o.get("price"),
                            "last_update": book.get("last_update"),
                        })

    markets["total"] = choose_playable_total(totals)
    return markets

def choose_playable_total(totals):
    if not totals:
        return None
    playable = [t for t in totals if t["book"] in USER_PLAYABLE_BOOKS]
    ref = playable or [t for t in totals if t["book"] in MARKET_REFERENCE_BOOKS] or totals
    chosen = sorted(ref, key=lambda x: (0 if x["book"] in USER_PLAYABLE_BOOKS else 1, x["book"]))[0]
    points = [t["point"] for t in totals if t.get("point") is not None]
    market_points = [t["point"] for t in totals if t.get("point") is not None and t.get("book") in MARKET_REFERENCE_BOOKS]
    market_points = market_points or points
    chosen = dict(chosen)
    chosen["market_avg"] = round(sum(points) / len(points), 2) if points else chosen["point"]
    chosen["market_consensus_avg"] = round(sum(market_points) / len(market_points), 2) if market_points else chosen["point"]
    chosen["market_high"] = max(points) if points else chosen["point"]
    chosen["market_low"] = min(points) if points else chosen["point"]
    chosen["books"] = len(points)
    chosen["consensus_books"] = len(market_points)
    chosen["book_vs_market"] = round(safe_float(chosen.get("point")) - safe_float(chosen.get("market_consensus_avg")), 2)
    chosen["line_age_seconds"] = line_age_seconds(chosen.get("last_update"))

    # Best available view among playable books only.
    if playable:
        over_best = sorted(playable, key=lambda x: (safe_float(x.get("point")), -safe_int(x.get("over_price"), -999)), reverse=False)[0]
        under_best = sorted(playable, key=lambda x: (-safe_float(x.get("point")), -safe_int(x.get("under_price"), -999)), reverse=False)[0]
        chosen["playable_over_best_point"] = over_best.get("point")
        chosen["playable_over_best_book"] = over_best.get("book")
        chosen["playable_over_best_price"] = over_best.get("over_price")
        chosen["playable_under_best_point"] = under_best.get("point")
        chosen["playable_under_best_book"] = under_best.get("book")
        chosen["playable_under_best_price"] = under_best.get("under_price")
    return chosen

def choose_spread_for_side(markets, side):
    offers = markets.get("spreads", {}).get(side, []) or []
    if not offers:
        return None
    playable = [x for x in offers if x["book"] in USER_PLAYABLE_BOOKS]
    ref = playable or [x for x in offers if x["book"] in MARKET_REFERENCE_BOOKS] or offers
    chosen = sorted(ref, key=lambda x: (-x["point"], 0 if x["book"] in USER_PLAYABLE_BOOKS else 1, safe_int(x.get("price"), 999)))[0]

    # Consensus view: for spreads, the better number for the bettor is the higher point
    # when taking a team against the spread (+4.5 is better than +3.5; -2.5 is better than -3.5).
    points = [safe_float(x.get("point"), None) for x in offers if x.get("point") is not None]
    points = [x for x in points if x is not None]
    market_points = [safe_float(x.get("point"), None) for x in offers if x.get("point") is not None and x.get("book") in MARKET_REFERENCE_BOOKS]
    market_points = [x for x in market_points if x is not None] or points
    out = dict(chosen)
    out["market_avg"] = round(sum(points) / len(points), 2) if points else out.get("point")
    out["market_consensus_avg"] = round(sum(market_points) / len(market_points), 2) if market_points else out.get("point")
    out["market_high"] = max(points) if points else out.get("point")
    out["market_low"] = min(points) if points else out.get("point")
    out["books"] = len(points)
    out["consensus_books"] = len(market_points)
    out["book_vs_market"] = round(safe_float(out.get("point")) - safe_float(out.get("market_consensus_avg")), 2)
    out["line_age_seconds"] = line_age_seconds(out.get("last_update"))
    return out

def choose_moneyline_for_side(markets, side):
    offers = markets.get("h2h", {}).get(side, []) or []
    if not offers:
        return None
    playable = [x for x in offers if x["book"] in USER_PLAYABLE_BOOKS]
    ref = playable or [x for x in offers if x["book"] in MARKET_REFERENCE_BOOKS] or offers
    return sorted(ref, key=lambda x: (0 if x["book"] in USER_PLAYABLE_BOOKS else 1, abs(safe_int(x.get("price"), 9999))))[0]

# =============================================================================
# State / line tracking
# =============================================================================
def initial_state():
    return {"date": today(), "games": {}, "final_locked": {}, "daily_report_sent": False}

def load_state():
    st = load_json(STATE_FILE, initial_state())
    if st.get("date") != today():
        st = initial_state()
    st.setdefault("games", {})
    st.setdefault("final_locked", {})
    st.setdefault("daily_report_sent", False)
    return st

def save_state(st):
    save_json(STATE_FILE, st)

def state_game(st, event_id):
    games = st.setdefault("games", {})
    games.setdefault(str(event_id), {
        "opening_total": None,
        "opening_spreads": {},
        "line_history": [],
        "alerts": [],
        "recent_snapshots": [],
        "last_clv_check": None,
    })
    return games[str(event_id)]

def is_final_locked_today(st, event_id):
    rec = st.get("final_locked", {}).get(str(event_id))
    return bool(rec and rec.get("date") == today())

def mark_final_locked(st, event_id, label, score):
    st.setdefault("final_locked", {})[str(event_id)] = {
        "date": today(), "label": label, "score": score, "locked_at": now_local().isoformat()
    }

def update_line_state(sg, info, markets):
    total = markets.get("total")
    if total and total.get("point") is not None:
        if sg.get("opening_total") is None:
            sg["opening_total"] = total["point"]
        snap = {
            "ts": now_local().isoformat(),
            "period": info.get("period"), "clock": info.get("clock"),
            "score": info.get("total_score"),
            "total": total.get("point"), "market_avg": total.get("market_avg"),
            "book": total.get("book"),
        }
        sg.setdefault("line_history", []).append(snap)
        sg["line_history"] = sg["line_history"][-80:]

        append_csv(LINE_HISTORY_FILE, {
            "date": today(), "time": snap["ts"],
            "game": f"{info['away']} at {info['home']}",
            "period": snap["period"], "clock": snap["clock"], "score": snap["score"],
            "live_total": snap["total"], "market_avg": snap["market_avg"], "book": snap["book"],
        }, ["date","time","game","period","clock","score","live_total","market_avg","book"])

    for side in ["home", "away"]:
        offer = choose_spread_for_side(markets, side)
        if offer:
            sg.setdefault("opening_spreads", {}).setdefault(side, offer["point"])

def line_velocity(sg):
    hist = sg.get("line_history", [])
    if len(hist) < 2:
        return 0.0
    latest = hist[-1]
    target = hist[0]
    try:
        latest_dt = datetime.fromisoformat(latest["ts"])
        for h in reversed(hist[:-1]):
            h_dt = datetime.fromisoformat(h["ts"])
            if (latest_dt - h_dt).total_seconds() >= 600:
                target = h
                break
    except Exception:
        pass
    return round(safe_float(latest.get("total")) - safe_float(target.get("total")), 2)

def short_line_velocity(sg):
    hist = sg.get("line_history", [])
    if len(hist) < 2:
        return 0.0
    latest = hist[-1]
    target = hist[-2]
    try:
        latest_dt = datetime.fromisoformat(latest["ts"])
        for h in reversed(hist[:-1]):
            h_dt = datetime.fromisoformat(h["ts"])
            if (latest_dt - h_dt).total_seconds() >= SHORT_VELOCITY_WINDOW_SECONDS:
                target = h
                break
    except Exception:
        pass
    return round(safe_float(latest.get("total")) - safe_float(target.get("total")), 2)

def recent_game_snapshots(sg, info):
    snaps = sg.setdefault("recent_snapshots", [])
    snaps.append({
        "ts": now_local().isoformat(),
        "minutes_elapsed": info.get("minutes_elapsed"),
        "home_score": info.get("home_score"),
        "away_score": info.get("away_score"),
        "period": info.get("period"),
        "clock": info.get("clock"),
        "home_box": info.get("box", {}).get("home", {}),
        "away_box": info.get("box", {}).get("away", {}),
    })
    sg["recent_snapshots"] = snaps[-50:]

def scoring_run_info(sg, info):
    snaps = sg.get("recent_snapshots", [])
    if len(snaps) < 2:
        return {"window_minutes": 0, "home_run": 0, "away_run": 0, "run_margin_home": 0, "leader": None, "margin": 0}
    current_elapsed = safe_float(info.get("minutes_elapsed"))
    start = snaps[0]
    for s in reversed(snaps[:-1]):
        delta = current_elapsed - safe_float(s.get("minutes_elapsed"))
        if delta >= RUN_WINDOW_MAX_MINUTES:
            start = s
            break
        start = s

    home_run = safe_int(info.get("home_score")) - safe_int(start.get("home_score"))
    away_run = safe_int(info.get("away_score")) - safe_int(start.get("away_score"))
    margin_home = home_run - away_run
    leader = "home" if margin_home > 0 else "away" if margin_home < 0 else None
    return {
        "window_minutes": round(current_elapsed - safe_float(start.get("minutes_elapsed")), 2),
        "home_run": home_run, "away_run": away_run,
        "run_margin_home": margin_home,
        "leader": leader, "margin": abs(margin_home),
    }


# =============================================================================
# V1.3 Future-state / market predictor helpers
# =============================================================================
def snapshot_ppp(snap):
    home = safe_int(snap.get("home_score"))
    away = safe_int(snap.get("away_score"))
    elapsed = max(0.1, safe_float(snap.get("minutes_elapsed"), 0.1))
    # fallback possession estimate for historical snapshots when box possession is not reliable.
    poss = DEFAULT_GAME_POSSESSIONS * elapsed / REGULATION_MINUTES
    return round((home + away) / max(1.0, poss), 3)

def scoring_acceleration_info(sg, info):
    """
    Compares current short-window scoring to longer-window scoring.
    Positive acceleration means the game is heating up faster than full-game pace implies.
    Negative acceleration means the game is slowing down.
    """
    snaps = sg.get("recent_snapshots", [])
    if len(snaps) < 4:
        return {
            "short_ppp": current_ppp(info, game_pace(info)),
            "long_ppp": current_ppp(info, game_pace(info)),
            "accel": 0.0,
            "accel_score_over": 45,
            "accel_score_under": 45,
            "profile": "NO_ACCEL_SAMPLE",
        }

    now_elapsed = safe_float(info.get("minutes_elapsed"), 0)
    current_total = safe_int(info.get("home_score")) + safe_int(info.get("away_score"))

    short_start = snaps[0]
    long_start = snaps[0]
    for s in reversed(snaps[:-1]):
        delta = now_elapsed - safe_float(s.get("minutes_elapsed"), 0)
        if delta >= 2.0:
            short_start = s
            break
        short_start = s
    for s in reversed(snaps[:-1]):
        delta = now_elapsed - safe_float(s.get("minutes_elapsed"), 0)
        if delta >= 6.0:
            long_start = s
            break
        long_start = s

    short_min = max(0.1, now_elapsed - safe_float(short_start.get("minutes_elapsed"), 0))
    long_min = max(0.1, now_elapsed - safe_float(long_start.get("minutes_elapsed"), 0))

    short_pts = current_total - safe_int(short_start.get("home_score")) - safe_int(short_start.get("away_score"))
    long_pts = current_total - safe_int(long_start.get("home_score")) - safe_int(long_start.get("away_score"))

    short_rate = short_pts / short_min
    long_rate = long_pts / long_min
    accel = round(short_rate - long_rate, 3)

    over_score = 45 + accel * 12
    under_score = 45 - accel * 12

    if accel >= 1.2:
        profile = "SCORING_ACCELERATION_UP"
    elif accel <= -1.2:
        profile = "SCORING_ACCELERATION_DOWN"
    else:
        profile = "SCORING_STABLE"

    return {
        "short_points_per_min": round(short_rate, 2),
        "long_points_per_min": round(long_rate, 2),
        "accel": accel,
        "accel_score_over": round(clamp(over_score)),
        "accel_score_under": round(clamp(under_score)),
        "profile": profile,
    }

def possession_pressure_index(info, side=None):
    """
    PPI estimates how much the next few possessions can move the betting market.
    It is not a win probability. It is a volatility/market-repricing pressure score.
    """
    min_left = safe_float(info.get("minutes_remaining"), 0)
    diff = abs(safe_int(info.get("home_score")) - safe_int(info.get("away_score")))
    q = safe_int(info.get("period"), 0)
    eff = efficiency_signals(info)
    pace = game_pace(info)

    score = 35

    # Close games create higher spread/moneyline repricing.
    if diff <= 4:
        score += 22
    elif diff <= 8:
        score += 15
    elif diff <= 12:
        score += 8
    elif diff >= 18:
        score -= 12

    # Time remaining: too early = less urgent, middle/late = more market-sensitive.
    if 6 <= min_left <= 18:
        score += 14
    elif 18 < min_left <= 28:
        score += 8
    elif min_left <= 5:
        score += 8
    elif min_left <= 2:
        score -= 10

    # Quarter context.
    if q == 3:
        score += 10
    elif q == 4:
        score += 8
    elif q <= 1:
        score -= 4

    # Foul/FT state creates rapid total/spread swings.
    if eff.get("ftr", 0) >= 0.34:
        score += 10
    if eff.get("fouls", 0) >= 22:
        score += 8

    # Enough possessions left to matter.
    if pace.get("possessions_left", 0) >= 24:
        score += 8
    elif pace.get("possessions_left", 0) < 10:
        score -= 18

    return round(clamp(score))

def run_sustainability_info(info, sg, favorite_side=None):
    """
    Separates noisy runs from structural runs.
    Unsustainable score is useful for favorite buyback.
    Sustainable score is useful for avoiding the favorite or supporting the dog/under/over depending profile.
    """
    run = scoring_run_info(sg, info)
    if not run.get("leader"):
        return {
            "run": run,
            "profile": "NO_CLEAR_RUN",
            "unsustainable_score": 45,
            "sustainable_score": 45,
            "winner_side": None,
        }

    leader = run["leader"]
    trailer = opponent_side(leader)

    lead_box = team_box(info, leader)
    trail_box = team_box(info, trailer)

    three_gap = safe_float(lead_box.get("tpm")) - safe_float(trail_box.get("tpm"))
    three_rate_gap = safe_float(lead_box.get("tpa")) - safe_float(trail_box.get("tpa"))
    ft_gap = safe_float(lead_box.get("fta")) - safe_float(trail_box.get("fta"))
    tov_gap = safe_float(trail_box.get("turnovers")) - safe_float(lead_box.get("turnovers"))
    paint_gap = safe_float(lead_box.get("points_in_paint")) - safe_float(trail_box.get("points_in_paint"))
    reb_gap = safe_float(lead_box.get("rebounds")) - safe_float(trail_box.get("rebounds"))
    efg_gap = safe_float(lead_box.get("efg")) - safe_float(trail_box.get("efg"))

    unsustainable = 35
    sustainable = 35

    # Hot shooting without structural support tends to be noisy.
    if three_gap >= 3:
        unsustainable += 20
    if efg_gap >= 0.12 and paint_gap < 6 and ft_gap < 5:
        unsustainable += 14

    # Structural control.
    if paint_gap >= 10:
        sustainable += 18
    if reb_gap >= 8:
        sustainable += 14
    if ft_gap >= 7:
        sustainable += 12
    if tov_gap >= 5:
        sustainable += 12

    # Very large run can be either; classify by support.
    if run.get("margin", 0) >= VERY_STRONG_RUN_MARGIN:
        if sustainable >= unsustainable:
            sustainable += 8
        else:
            unsustainable += 8

    # If the team on the run is the underdog against the favorite, this is the key buyback read.
    if favorite_side and leader == opponent_side(favorite_side):
        unsustainable += 5

    unsustainable = round(clamp(unsustainable))
    sustainable = round(clamp(sustainable))

    if unsustainable >= sustainable + 10:
        profile = "RUN_UNSUSTAINABLE_NOISE"
    elif sustainable >= unsustainable + 10:
        profile = "RUN_SUSTAINABLE_CONTROL"
    else:
        profile = "RUN_MIXED"

    return {
        "run": run,
        "profile": profile,
        "unsustainable_score": unsustainable,
        "sustainable_score": sustainable,
        "winner_side": leader,
        "three_gap": three_gap,
        "ft_gap": ft_gap,
        "turnover_gap_created": tov_gap,
        "paint_gap": paint_gap,
        "rebound_gap": reb_gap,
        "efg_gap": round(efg_gap, 3),
    }

def future_state_projection(info, sg):
    """
    Predicts the next market-relevant state, not just the final score.
    This is the core of V1.3.
    """
    proj = projected_total(info, sg)
    pace = proj["pace"]
    eff = proj["eff"]
    accel = scoring_acceleration_info(sg, info) if ENABLE_SCORING_ACCELERATION else {}
    ppi = possession_pressure_index(info) if ENABLE_POSSESSION_PRESSURE_INDEX else 50
    run_sus = run_sustainability_info(info, sg) if ENABLE_RUN_SUSTAINABILITY else {}

    # Expected points over next horizon.
    poss_horizon = min(PREDICTOR_POSSESSION_HORIZON, max(0.0, pace.get("possessions_left", 0)))
    expected_ppp = safe_float(proj.get("expected_remaining_ppp"), DEFAULT_POINTS_PER_POSSESSION)

    accel_adj = 0.0
    if accel:
        accel_adj = max(-0.08, min(0.08, safe_float(accel.get("accel"), 0) / 30.0))

    pressure_adj = 0.0
    if ppi >= ELITE_PPI_THRESHOLD:
        pressure_adj = 0.035
    elif ppi >= STRONG_PPI_THRESHOLD:
        pressure_adj = 0.02
    elif ppi <= 35:
        pressure_adj = -0.025

    future_ppp = max(0.82, min(1.28, expected_ppp + accel_adj + pressure_adj))
    next_points = poss_horizon * future_ppp * 2

    # Future-state score identifies whether the next 3-8 possessions are likely to reprice the market.
    future_state_score = 45
    future_state_score += (ppi - 50) * 0.35
    if accel:
        future_state_score += abs(safe_float(accel.get("accel"), 0)) * 4
    if run_sus:
        future_state_score += abs(safe_float(run_sus.get("unsustainable_score"), 45) - safe_float(run_sus.get("sustainable_score"), 45)) * 0.20
    if eff.get("ftr", 0) >= 0.34:
        future_state_score += 5
    if eff.get("turnovers", 0) >= 18:
        future_state_score += 4

    return {
        "projected_total": proj.get("projected_total"),
        "future_ppp": round(future_ppp, 3),
        "next_points_horizon": round(next_points, 1),
        "future_state_score": round(clamp(future_state_score)),
        "possession_pressure_index": ppi,
        "acceleration": accel,
        "run_sustainability": run_sus,
        "pace": pace,
        "eff": eff,
        "quarter_profile": proj.get("quarter_profile"),
    }

def market_misprice_score_for_total(info, sg, market_scores, side):
    future = future_state_projection(info, sg)
    live_total = safe_float(market_scores.get("live_total"))
    projected = safe_float(market_scores.get("projection", {}).get("projected_total"))
    future_score = safe_float(future.get("future_state_score"), 45)
    ppi = safe_float(future.get("possession_pressure_index"), 50)
    accel = future.get("acceleration", {})
    run_sus = future.get("run_sustainability", {})

    if side == "OVER":
        true_gap = projected - live_total
        predicted_line_move = max(0.0, true_gap * TOTAL_POINT_TO_MARKET_MOVE_RATIO)
        accel_support = safe_float(accel.get("accel_score_over"), 45) - 45
    else:
        true_gap = live_total - projected
        predicted_line_move = max(0.0, true_gap * TOTAL_POINT_TO_MARKET_MOVE_RATIO)
        accel_support = safe_float(accel.get("accel_score_under"), 45) - 45

    # Wide-net but realistic: do not let a massive model gap automatically mean 100/100.
    capped_gap = min(true_gap, WNBA_SANITY_EDGE_HARD_CAP)
    predicted_line_move = min(predicted_line_move, WNBA_SANITY_EDGE_HARD_CAP * TOTAL_POINT_TO_MARKET_MOVE_RATIO)

    misprice = 40
    misprice += capped_gap * 4.0
    misprice += predicted_line_move * 4.5
    misprice += (future_score - 50) * 0.35
    misprice += (ppi - 50) * 0.18
    misprice += accel_support * 0.30

    # If the current run is unsustainable, be careful with over/under depending on direction.
    if run_sus:
        if run_sus.get("profile") == "RUN_UNSUSTAINABLE_NOISE":
            # noisy scoring spike tends to support under/fade; noisy cold run may be caught by acceleration instead.
            if side == "UNDER":
                misprice += 5
        elif run_sus.get("profile") == "RUN_SUSTAINABLE_CONTROL":
            if side == "OVER":
                misprice += 4

    return {
        "market_misprice_score": round(clamp(misprice)),
        "predicted_line_move": round(predicted_line_move, 2),
        "future_state": future,
    }

def market_misprice_score_for_spread(info, sg, opp):
    scores = opp.get("scores", {})
    future = future_state_projection(info, sg)
    ppi = safe_float(future.get("possession_pressure_index"), 50)
    run_sus = run_sustainability_info(info, sg, scores.get("favorite_side"))
    poss_value = safe_float(scores.get("possession_value_score"), 50)
    spread_swing = safe_float(scores.get("spread_swing"), 0)
    strength_edge = safe_float(scores.get("strength_edge"), 0)

    # Predict whether the favorite spread should contract from +4.5 toward +2.5/+1.5.
    predicted_spread_contract = 0.0
    predicted_spread_contract += max(0, poss_value - 55) / 20.0
    predicted_spread_contract += max(0, strength_edge) / 8.0
    predicted_spread_contract += max(0, ppi - 55) / 25.0

    if run_sus.get("profile") == "RUN_UNSUSTAINABLE_NOISE":
        predicted_spread_contract += 1.2
    elif run_sus.get("profile") == "RUN_SUSTAINABLE_CONTROL":
        predicted_spread_contract -= 1.5

    predicted_spread_contract = round(max(0.0, predicted_spread_contract * SPREAD_POINT_TO_MARKET_MOVE_RATIO), 2)

    misprice = 38
    misprice += predicted_spread_contract * 12
    misprice += (poss_value - 50) * 0.28
    misprice += (ppi - 50) * 0.22
    misprice += max(0, strength_edge) * 1.2
    if 4.0 <= safe_float(opp.get("line")) <= 5.5:
        misprice += 8
    if spread_swing >= FAVORITE_BUYBACK_MIN_SWING:
        misprice += 6
    if run_sus.get("profile") == "RUN_UNSUSTAINABLE_NOISE":
        misprice += 12
    elif run_sus.get("profile") == "RUN_SUSTAINABLE_CONTROL":
        misprice -= 18

    return {
        "market_misprice_score": round(clamp(misprice)),
        "predicted_spread_contract": predicted_spread_contract,
        "future_state": future,
        "run_sustainability": run_sus,
    }

# =============================================================================
# WNBA model: pace, possessions, total projection
# =============================================================================
def estimate_possessions_from_box(info):
    box = info.get("box", {})
    poss = {}
    for side in ["home", "away"]:
        s = box.get(side, {}) or {}
        fga = s.get("fga", 0)
        fta = s.get("fta", 0)
        tov = s.get("turnovers", 0)
        orb = s.get("off_reb", 0)
        poss[side] = max(0.0, fga + 0.44 * fta + tov - orb)
    if poss["home"] or poss["away"]:
        return round((poss["home"] + poss["away"]) / 2.0, 2)
    return None

def game_pace(info):
    elapsed = max(0.1, safe_float(info.get("minutes_elapsed"), 0.1))
    current_poss = estimate_possessions_from_box(info)
    if current_poss is None:
        current_poss = DEFAULT_GAME_POSSESSIONS * elapsed / REGULATION_MINUTES
    projected_game_poss = current_poss / elapsed * REGULATION_MINUTES
    poss_left = max(0.0, projected_game_poss - current_poss)
    return {
        "current_possessions": round(current_poss, 2),
        "projected_game_possessions": round(projected_game_poss, 2),
        "possessions_left": round(poss_left, 2),
        "pace_vs_default": round(projected_game_poss - DEFAULT_GAME_POSSESSIONS, 2),
    }

def current_ppp(info, pace):
    """
    Returns PER-TEAM points per possession.

    Important WNBA fix:
    estimate_possessions_from_box returns average team possessions.
    Total game points divided by average team possessions is combined PPP,
    which is roughly 2.0. For projection we need per-team PPP, roughly 1.0.
    """
    current_poss = max(1.0, pace.get("current_possessions", 1.0))
    per_team_ppp = safe_float(info.get("total_score")) / (current_poss * 2.0)
    if ENABLE_PROJECTION_REALITY_CAPS:
        per_team_ppp = max(WNBA_MIN_LIVE_TEAM_PPP, min(WNBA_MAX_LIVE_TEAM_PPP, per_team_ppp))
    return round(per_team_ppp, 3)

def team_box(info, side):
    return (info.get("box", {}) or {}).get(side, {}) or {}

def efficiency_signals(info):
    teams = [team_box(info, "home"), team_box(info, "away")]
    fga = sum(s.get("fga", 0) for s in teams)
    fta = sum(s.get("fta", 0) for s in teams)
    tov = sum(s.get("turnovers", 0) for s in teams)
    orb = sum(s.get("off_reb", 0) for s in teams)
    reb = sum(s.get("rebounds", 0) for s in teams)
    tpa = sum(s.get("tpa", 0) for s in teams)
    tpm = sum(s.get("tpm", 0) for s in teams)
    fouls = sum(s.get("fouls", 0) for s in teams)
    fast_break = sum(s.get("fast_break", 0) for s in teams)
    paint = sum(s.get("points_in_paint", 0) for s in teams)
    efgs = [s.get("efg", 0) for s in teams if s.get("fga", 0)]
    return {
        "efg": round(avg(efgs), 3) if efgs else 0,
        "ftr": round(fta / fga, 3) if fga else 0,
        "turnovers": tov, "off_reb": orb, "rebounds": reb,
        "three_rate": round(tpa / fga, 3) if fga else 0,
        "three_pct": round(tpm / tpa, 3) if tpa else 0,
        "fouls": fouls, "fast_break": fast_break, "points_in_paint": paint,
    }

def quarter_profile(info):
    q = safe_int(info.get("period"), 0)
    left = safe_float(info.get("minutes_remaining"), 0)
    if q <= 1:
        return "Q1_EARLY_SAMPLE"
    if q == 2:
        return "Q2_FIRST_HALF_PROFILE"
    if q == 3:
        return "Q3_ADJUSTMENT_WINDOW"
    if q >= 4 and left > 5:
        return "Q4_EARLY_LIVE"
    return "Q4_LATE_HIGH_VARIANCE"

def live_weight_by_quarter(info):
    """
    WNBA live totals are fragile because a few empty possessions, a timeout,
    or a bench rotation can kill pace. Trust live stats differently by quarter.
    """
    qprof = quarter_profile(info)
    if qprof == "Q1_EARLY_SAMPLE":
        return 0.35
    if qprof == "Q2_FIRST_HALF_PROFILE":
        return 0.50
    if qprof == "Q3_ADJUSTMENT_WINDOW":
        return 0.58
    if qprof == "Q4_EARLY_LIVE":
        return 0.48
    return 0.38

def cap_projected_possessions(value):
    if not ENABLE_PROJECTION_REALITY_CAPS:
        return value
    return max(WNBA_MIN_PROJECTED_POSSESSIONS, min(WNBA_MAX_PROJECTED_POSSESSIONS, value))

def cap_expected_team_ppp(value):
    if not ENABLE_PROJECTION_REALITY_CAPS:
        return value
    return max(WNBA_MIN_EXPECTED_TEAM_PPP, min(WNBA_MAX_EXPECTED_TEAM_PPP, value))

def score_state_adjustment(info, expected_ppp):
    """
    WNBA-specific game-state adjustment:
    - blowouts reduce late pace/quality because of clock, bench, and dead possessions
    - close late games can add FT points
    """
    diff = abs(info.get("home_score", 0) - info.get("away_score", 0))
    min_left = safe_float(info.get("minutes_remaining"), 0)
    q = safe_int(info.get("period"), 0)

    late_close_bonus = 0.0
    if min_left <= 5 and diff <= 6:
        late_close_bonus = 4.0
    elif min_left <= 3 and diff <= 10:
        late_close_bonus = 2.0

    if q >= 4 and diff >= 16:
        expected_ppp -= 0.045
    elif q >= 3 and diff >= 22:
        expected_ppp -= 0.035

    return cap_expected_team_ppp(expected_ppp), late_close_bonus

def sanity_edge_tag(edge):
    ae = abs(safe_float(edge, 0))
    if ae >= WNBA_SANITY_EDGE_HARD_CAP:
        return "HARD_SANITY_CHECK"
    if ae >= WNBA_SANITY_EDGE_WARN:
        return "SANITY_CHECK"
    return "NORMAL_EDGE"


def projected_total(info, sg):
    pace = game_pace(info)
    ppp = current_ppp(info, pace)
    eff = efficiency_signals(info)
    ctx = game_context(info)
    qprof = quarter_profile(info)

    live_weight = live_weight_by_quarter(info)
    baseline_weight = 1.0 - live_weight

    expected_ppp = live_weight * ppp + baseline_weight * DEFAULT_POINTS_PER_POSSESSION

    # Pregame/team style context.
    if ENABLE_TEAM_STRENGTH_CONTEXT:
        if ctx["total_pace_rating"] >= 81:
            expected_ppp += 0.012
        elif ctx["total_pace_rating"] <= 74:
            expected_ppp -= 0.012

        if ctx["total_off_rating"] >= 83:
            expected_ppp += 0.014
        elif ctx["total_off_rating"] <= 72:
            expected_ppp -= 0.014

        if ctx["total_def_rating"] >= 83:
            expected_ppp -= 0.012
        elif ctx["total_def_rating"] <= 72:
            expected_ppp += 0.012

    if ENABLE_PLAYER_IMPACT_CONTEXT:
        star_impact = safe_float(ctx["home_star"].get("impact"), 0) + safe_float(ctx["away_star"].get("impact"), 0)
        expected_ppp += max(-0.04, min(0.035, star_impact / 275.0))

    # WNBA live-style adjustments.
    # Fouls/bonus and free throws are more reliable than raw hot shooting.
    if eff["ftr"] >= 0.32 or eff["fouls"] >= 20:
        expected_ppp += 0.026
    if eff["ftr"] >= 0.40:
        expected_ppp += 0.012

    # Offensive rebounding/extra possessions are real. Hot 3PT alone is fragile.
    if eff["off_reb"] >= 12:
        expected_ppp += 0.018
    if eff["fast_break"] >= 16:
        expected_ppp += 0.014

    # Turnovers and empty trips matter in WNBA because possessions are lower.
    if eff["turnovers"] >= 18 and safe_float(info.get("minutes_elapsed")) <= 30:
        expected_ppp -= 0.028
    if eff["efg"] <= 0.42 and eff["ftr"] < 0.24 and safe_float(info.get("minutes_elapsed")) >= 8:
        expected_ppp -= 0.018
    elif eff["efg"] >= 0.58 and eff["three_pct"] >= 0.42:
        # Do not fully chase hot shooting.
        expected_ppp += 0.010

    expected_ppp, late_close_bonus = score_state_adjustment(info, expected_ppp)
    expected_ppp = cap_expected_team_ppp(expected_ppp)

    current_poss = max(1.0, safe_float(pace.get("current_possessions"), 1.0))
    raw_projected_poss = safe_float(pace.get("projected_game_possessions"), DEFAULT_GAME_POSSESSIONS)
    projected_poss_capped = cap_projected_possessions(raw_projected_poss)
    possessions_left = max(0.0, projected_poss_capped - current_poss)

    remaining_points = possessions_left * expected_ppp * 2.0
    proj = safe_float(info.get("total_score")) + remaining_points + late_close_bonus

    return {
        "projected_total": round(proj, 1),
        "pace": {
            **pace,
            "projected_game_possessions_raw": pace.get("projected_game_possessions"),
            "projected_game_possessions": round(projected_poss_capped, 2),
            "possessions_left": round(possessions_left, 2),
            "pace_vs_default": round(projected_poss_capped - DEFAULT_GAME_POSSESSIONS, 2),
        },
        "ppp": ppp,
        "expected_remaining_ppp": round(expected_ppp, 3),
        "eff": eff,
        "late_close_bonus": late_close_bonus,
        "quarter_profile": qprof,
        "game_context": ctx,
        "live_weight": round(live_weight, 2),
        "projection_caps": ENABLE_PROJECTION_REALITY_CAPS,
    }

def classify_total_market(info, sg, live_total, proj, velocity, move_from_open):
    edge_over = round(proj["projected_total"] - live_total, 1)
    edge_under = round(live_total - proj["projected_total"], 1)

    if move_from_open >= 8 and edge_under >= MIN_TOTAL_EDGE_POINTS:
        return "INFLATED_UNDER"
    if move_from_open <= -8 and edge_over >= MIN_TOTAL_EDGE_POINTS:
        return "DISCOUNTED_OVER"
    if velocity >= 4 and edge_under >= MIN_TOTAL_EDGE_POINTS:
        return "FAST_SPIKE_FADE_UNDER"
    if velocity <= -4 and edge_over >= MIN_TOTAL_EDGE_POINTS:
        return "FAST_DROP_BUY_OVER"
    if proj["pace"]["pace_vs_default"] >= 4 and edge_over >= MIN_TOTAL_EDGE_POINTS:
        return "PACE_CONTINUATION_OVER"
    if proj["pace"]["pace_vs_default"] <= -4 and edge_under >= MIN_TOTAL_EDGE_POINTS:
        return "PACE_SUPPRESSION_UNDER"
    return "NEUTRAL_TOTAL"

def total_scores(info, sg, markets):
    proj = projected_total(info, sg)
    total = markets.get("total") or {}
    live_total = safe_float(total.get("point"), None)
    opening_total = safe_float(sg.get("opening_total"), live_total)
    if live_total is None:
        return None

    edge_over = round(proj["projected_total"] - live_total, 1)
    edge_under = round(live_total - proj["projected_total"], 1)
    velocity = line_velocity(sg)
    short_velocity = short_line_velocity(sg)
    move_from_open = round(live_total - opening_total, 1) if opening_total is not None else 0
    eff = proj["eff"]
    pace = proj["pace"]
    ppp = proj["ppp"]
    qprof = proj["quarter_profile"]

    over_confirm = 0
    under_confirm = 0

    if pace["pace_vs_default"] >= 3:
        over_confirm += 16
    elif pace["pace_vs_default"] <= -3:
        under_confirm += 14

    if pace["possessions_left"] >= 34:
        over_confirm += 10
    elif pace["possessions_left"] <= 18:
        under_confirm += 10

    if ppp >= 1.08:
        over_confirm += 14
    elif ppp <= 0.94 and info["minutes_elapsed"] >= 8:
        under_confirm += 14

    if eff["ftr"] >= 0.32:
        over_confirm += 14
    if eff["fouls"] >= 22:
        over_confirm += 12
    if eff["turnovers"] >= 18:
        under_confirm += 14
    if eff["efg"] <= 0.42 and eff["ftr"] < 0.24:
        under_confirm += 16
    if eff["off_reb"] >= 12:
        over_confirm += 10

    market_profile = classify_total_market(info, sg, live_total, proj, velocity, move_from_open)
    if market_profile in {"INFLATED_UNDER", "FAST_SPIKE_FADE_UNDER"}:
        under_confirm += 14
    if market_profile in {"DISCOUNTED_OVER", "FAST_DROP_BUY_OVER", "PACE_CONTINUATION_OVER"}:
        over_confirm += 14

    # Quarter adjustments.
    if qprof == "Q1_EARLY_SAMPLE":
        over_confirm -= 4
        under_confirm -= 4
    elif qprof == "Q3_ADJUSTMENT_WINDOW":
        over_confirm += 4 if edge_over > edge_under else 0
        under_confirm += 4 if edge_under > edge_over else 0
    elif qprof == "Q4_LATE_HIGH_VARIANCE":
        over_confirm -= 6
        under_confirm -= 4

    risk_over = 20
    risk_under = 20
    if info["minutes_remaining"] <= 6:
        risk_over += 10
        risk_under += 8
    if pace["possessions_left"] < MIN_TOTAL_POSSESSIONS_LEFT:
        risk_over += 15
        risk_under += 12
    if abs(info["score_diff_home"]) >= 18 and info["minutes_remaining"] <= 10:
        risk_over += 18
    if eff["ftr"] >= 0.36 and info["minutes_remaining"] <= 8:
        risk_under += 18
    if eff["three_pct"] >= 0.43 and eff["three_rate"] >= 0.34:
        risk_under += 10
    if qprof == "Q4_LATE_HIGH_VARIANCE":
        risk_over += 10
        risk_under += 8

    over_value = clamp(45 + over_confirm + edge_over * 4 - risk_over * 0.35)
    under_value = clamp(45 + under_confirm + edge_under * 4 - risk_under * 0.35)

    return {
        "projection": proj, "live_total": live_total, "opening_total": opening_total,
        "move_from_open": move_from_open, "velocity": velocity, "short_velocity": short_velocity,
        "edge_over": edge_over, "edge_under": edge_under,
        "over_confirm": clamp(over_confirm), "under_confirm": clamp(under_confirm),
        "risk_over": clamp(risk_over), "risk_under": clamp(risk_under),
        "over_value": round(over_value), "under_value": round(under_value),
        "market_profile": market_profile,
        "book": total.get("book"), "over_price": total.get("over_price"), "under_price": total.get("under_price"),
        "market_avg": total.get("market_avg"), "market_consensus_avg": total.get("market_consensus_avg"),
        "market_high": total.get("market_high"), "market_low": total.get("market_low"),
        "book_vs_market": total.get("book_vs_market"), "line_age_seconds": total.get("line_age_seconds"),
        "last_update": total.get("last_update"), "books": total.get("books"), "consensus_books": total.get("consensus_books"),
    }

def profile_key_parts(market_type, scenario, quarter_profile, side, alert_tier=None):
    return "|".join([
        str(market_type or "UNKNOWN"),
        str(scenario or "UNKNOWN"),
        str(quarter_profile or "UNKNOWN"),
        str(side or "UNKNOWN").upper(),
        str(alert_tier or "ANY"),
    ])

def profile_key_for_opp(opp, include_tier=False):
    if not opp:
        return "UNKNOWN"
    return profile_key_parts(
        opp.get("market_type"),
        opp.get("scenario"),
        opp.get("quarter_profile"),
        opp.get("side"),
        opp.get("alert_tier") if include_tier else None,
    )

def profile_key_from_row(row, include_tier=True):
    return profile_key_parts(
        row.get("market_type"),
        row.get("scenario"),
        row.get("quarter_profile"),
        row.get("side"),
        row.get("alert_tier") if include_tier else None,
    )

def load_profile_rules():
    data = load_json(PROFILE_RULES_FILE, {})
    return data if isinstance(data, dict) else {}

def save_profile_rules(data):
    if ENABLE_ADAPTIVE_PROFILE_RULES:
        save_json(PROFILE_RULES_FILE, data)

def profile_rule_for(profile):
    if not ENABLE_ADAPTIVE_PROFILE_RULES or not profile:
        return {}
    rules = load_profile_rules()
    return rules.get(profile, {}) or {}

def profile_rule_for_opp(opp):
    if not ENABLE_ADAPTIVE_PROFILE_RULES or not opp:
        return {}
    rules = load_profile_rules()
    # Prefer the precise market/scenario/quarter/side key, then fall back to scenario-only legacy keys.
    key = profile_key_for_opp(opp, include_tier=False)
    return rules.get(key, {}) or rules.get(opp.get("scenario"), {}) or {}

def apply_profile_rule_adjustment(opp):
    if not opp or not ENABLE_ADAPTIVE_PROFILE_RULES:
        return opp
    rule = profile_rule_for_opp(opp)
    action = rule.get("action", "MONITOR")
    if action == "TIGHTEN":
        opp["confidence"] = round(clamp(safe_float(opp.get("confidence")) - 6))
        opp["value_score"] = round(clamp(safe_float(opp.get("value_score")) - 5))
        opp["risk_score"] = round(clamp(safe_float(opp.get("risk_score")) + 8))
    elif action == "TRUST":
        opp["confidence"] = round(clamp(safe_float(opp.get("confidence")) + 3))
        opp["value_score"] = round(clamp(safe_float(opp.get("value_score")) + 3))
    opp["profile_rule"] = action
    return opp

def market_discrepancy_for_total(scores, side):
    total = scores or {}
    book_line = safe_float(total.get("live_total"), None)
    market_avg = safe_float(total.get("market_consensus_avg"), safe_float(total.get("market_avg"), None))
    books = safe_int(total.get("consensus_books", total.get("books", 0)), 0)
    age = total.get("line_age_seconds")
    if book_line is None or market_avg is None:
        return {"status": "NO_MARKET", "score": 0, "book_vs_market": 0, "books": books, "line_age_seconds": age, "reason": "missing market consensus"}

    book_vs_market = round(book_line - market_avg, 2)
    if side == "OVER":
        # Lower playable line than the market is favorable for over.
        advantage = round(market_avg - book_line, 2)
    else:
        # Higher playable line than the market is favorable for under.
        advantage = round(book_line - market_avg, 2)

    score = 0
    if books >= MARKET_CONSENSUS_MIN_BOOKS:
        score += 15
    if advantage >= STRONG_OFF_MARKET_TOTAL_POINTS:
        score += 35
    elif advantage >= OFF_MARKET_TOTAL_POINTS:
        score += 22
    elif advantage >= 0.5:
        score += 10
    elif advantage <= -1.0:
        score -= 18

    stale = age is not None and safe_float(age, 0) >= STALE_LINE_SECONDS
    if stale and advantage >= OFF_MARKET_TOTAL_POINTS:
        score += 12
    elif stale and advantage <= -0.5:
        score -= 8

    status = "OFF_MARKET_EDGE" if advantage >= OFF_MARKET_TOTAL_POINTS and books >= MARKET_CONSENSUS_MIN_BOOKS else \
             "STRONG_OFF_MARKET_EDGE" if advantage >= STRONG_OFF_MARKET_TOTAL_POINTS and books >= MARKET_CONSENSUS_MIN_BOOKS else \
             "AGAINST_CONSENSUS" if advantage <= -1.0 else "MARKET_ALIGNED"
    if advantage >= STRONG_OFF_MARKET_TOTAL_POINTS and books >= MARKET_CONSENSUS_MIN_BOOKS:
        status = "STRONG_OFF_MARKET_EDGE"

    return {
        "status": status,
        "score": round(clamp(score, -30, 70)),
        "book_vs_market": book_vs_market,
        "advantage_points": advantage,
        "books": books,
        "line_age_seconds": age,
        "stale_line": bool(stale),
        "reason": f"{side} advantage {advantage} vs consensus avg {market_avg} from playable {book_line}",
    }

def market_discrepancy_for_spread(offer):
    if not offer:
        return {"status": "NO_MARKET", "score": 0, "advantage_points": 0, "reason": "missing spread offer"}
    book_line = safe_float(offer.get("point"), None)
    market_avg = safe_float(offer.get("market_consensus_avg"), safe_float(offer.get("market_avg"), None))
    books = safe_int(offer.get("consensus_books", offer.get("books", 0)), 0)
    age = offer.get("line_age_seconds")
    if book_line is None or market_avg is None:
        return {"status": "NO_MARKET", "score": 0, "advantage_points": 0, "books": books, "line_age_seconds": age, "reason": "missing spread consensus"}

    # For any spread side we are taking, a higher point is a better line.
    advantage = round(book_line - market_avg, 2)
    score = 0
    if books >= MARKET_CONSENSUS_MIN_BOOKS:
        score += 15
    if advantage >= SPREAD_STRONG_OFF_MARKET_POINTS:
        score += 35
    elif advantage >= SPREAD_OFF_MARKET_POINTS:
        score += 22
    elif advantage >= 0.5:
        score += 10
    elif advantage <= -0.75:
        score -= 18

    stale = age is not None and safe_float(age, 0) >= STALE_LINE_SECONDS
    if stale and advantage >= SPREAD_OFF_MARKET_POINTS:
        score += 12
    elif stale and advantage <= -0.5:
        score -= 8

    if advantage >= SPREAD_STRONG_OFF_MARKET_POINTS and books >= MARKET_CONSENSUS_MIN_BOOKS:
        status = "STRONG_OFF_MARKET_EDGE"
    elif advantage >= SPREAD_OFF_MARKET_POINTS and books >= MARKET_CONSENSUS_MIN_BOOKS:
        status = "OFF_MARKET_EDGE"
    elif advantage <= -0.75:
        status = "AGAINST_CONSENSUS"
    else:
        status = "MARKET_ALIGNED"

    return {
        "status": status,
        "score": round(clamp(score, -30, 70)),
        "book_vs_market": round(book_line - market_avg, 2),
        "advantage_points": advantage,
        "books": books,
        "line_age_seconds": age,
        "stale_line": bool(stale),
        "reason": f"spread advantage {advantage} vs consensus avg {market_avg} from playable {book_line}",
    }

def log_market_discrepancy(info, label, opp):
    md = (opp or {}).get("market_discrepancy") or {}
    if not md:
        return
    append_csv(MARKET_DISCREPANCY_FILE, {
        "date": today(), "time": now_local().isoformat(), "event_id": info.get("event_id"),
        "game": label, "market_type": opp.get("market_type"), "side": opp.get("side"),
        "line": opp.get("line"), "book": opp.get("book"), "status": md.get("status"),
        "score": md.get("score"), "advantage_points": md.get("advantage_points"),
        "book_vs_market": md.get("book_vs_market"), "books": md.get("books"),
        "line_age_seconds": md.get("line_age_seconds"), "stale_line": md.get("stale_line"),
        "reason": md.get("reason"),
    }, ["date","time","event_id","game","market_type","side","line","book","status","score","advantage_points","book_vs_market","books","line_age_seconds","stale_line","reason"])

def price_ok(price, max_price, elite=False):
    if price is None:
        return True
    p = safe_int(price)
    return p >= max_price

def build_total_opportunity(info, sg, markets):
    s = total_scores(info, sg, markets)
    if not s:
        return None

    if s["edge_over"] >= s["edge_under"]:
        side = "OVER"
        edge = s["edge_over"]
        confidence = round(clamp(45 + s["over_confirm"] * 0.55 + edge * 4 - s["risk_over"] * 0.20))
        value = s["over_value"]
        risk = s["risk_over"]
        price = s["over_price"]
    else:
        side = "UNDER"
        edge = s["edge_under"]
        confidence = round(clamp(45 + s["under_confirm"] * 0.55 + edge * 4 - s["risk_under"] * 0.20))
        value = s["under_value"]
        risk = s["risk_under"]
        price = s["under_price"]

    predictor = market_misprice_score_for_total(info, sg, s, side) if ENABLE_MARKET_PREDICTOR_ENGINE else {
        "market_misprice_score": 50,
        "predicted_line_move": 0,
        "future_state": {},
    }
    market_discrepancy = market_discrepancy_for_total(s, side) if ENABLE_MARKET_DISCREPANCY_ENGINE else {"status": "DISABLED", "score": 0}

    # V1.5: true market deficiency gets rewarded; against-consensus model edges get downgraded.
    confidence = round(clamp(confidence + max(0, predictor.get("market_misprice_score", 50) - 65) * 0.22))
    value = round(clamp(value + max(0, predictor.get("market_misprice_score", 50) - 65) * 0.18))
    confidence = round(clamp(confidence + safe_float(market_discrepancy.get("score"), 0) * 0.18))
    value = round(clamp(value + safe_float(market_discrepancy.get("score"), 0) * 0.16))
    if market_discrepancy.get("status") == "AGAINST_CONSENSUS":
        risk = round(clamp(risk + 10))

    block_reason = ""
    action = "WATCH"

    if s["projection"]["pace"]["possessions_left"] < MIN_TOTAL_POSSESSIONS_LEFT:
        block_reason = "possessions left too low for total entry"
    elif ENABLE_MARKET_PREDICTOR_ENGINE and not WIDE_NET_LEARNING_MODE and predictor.get("market_misprice_score", 0) < MIN_MARKET_MISPRICE_SCORE:
        block_reason = f"predictor miss: market misprice {predictor.get('market_misprice_score')} below {MIN_MARKET_MISPRICE_SCORE}"
    elif ENABLE_MARKET_PREDICTOR_ENGINE and not WIDE_NET_LEARNING_MODE and predictor.get("future_state", {}).get("future_state_score", 0) < MIN_FUTURE_STATE_SCORE:
        block_reason = f"future-state miss: {predictor.get('future_state', {}).get('future_state_score')} below {MIN_FUTURE_STATE_SCORE}"
    elif ENABLE_DO_NOT_CHASE_CONTEXT and abs(s.get("move_from_open", 0)) >= DO_NOT_CHASE_TOTAL_MOVE and confidence < DO_NOT_CHASE_MIN_CONFIDENCE:
        block_reason = f"NO CHASE: total already moved {s.get('move_from_open')} from open"
    elif abs(edge) >= BIG_EDGE_CONSENSUS_REQUIRED and market_discrepancy.get("status") in {"AGAINST_CONSENSUS", "MARKET_ALIGNED", "NO_MARKET"} and confidence < 82:
        block_reason = f"big model edge without market confirmation: {market_discrepancy.get('status')}"
    elif s["market_profile"] == "NEUTRAL_TOTAL":
        block_reason = "neutral total profile; no market overreaction/underreaction"
    elif not price_ok(price, MAX_TOTAL_PRICE) and confidence < 82:
        block_reason = f"total price too expensive: {price}"
    elif edge >= MIN_TOTAL_EDGE_POINTS and confidence >= MIN_TOTAL_CONFIDENCE and value >= MIN_TOTAL_VALUE_SCORE and risk <= MAX_TOTAL_RISK_SCORE:
        action = "STRIKE"
    elif wide_net_strike_ok(edge, confidence, value, risk, predictor, s["market_profile"]):
        action = "STRIKE"
        block_reason = ""
    else:
        block_reason = f"gate miss: edge {edge}, conf {confidence}, value {value}, risk {risk}"

    return assign_alert_tier(apply_profile_rule_adjustment({
        "market_type": "TOTAL", "side": side, "team_side": "",
        "line": s["live_total"], "price": price, "book": s["book"],
        "edge": edge, "projected_total": s["projection"]["projected_total"],
        "confidence": confidence, "value_score": value, "risk_score": risk,
        "action": action, "block_reason": block_reason,
        "scenario": s["market_profile"], "quarter_profile": s["projection"]["quarter_profile"],
        "scores": s,
        "predictor": predictor,
        "market_misprice_score": predictor.get("market_misprice_score"),
        "predicted_line_move": predictor.get("predicted_line_move"),
        "future_state_score": predictor.get("future_state", {}).get("future_state_score"),
        "market_discrepancy": market_discrepancy,
        "market_discrepancy_status": market_discrepancy.get("status"),
        "market_discrepancy_score": market_discrepancy.get("score"),
    }))

# =============================================================================
# Favorite buyback professional model
# =============================================================================
def pregame_favorite_side(sg, markets, info):
    opens = sg.get("opening_spreads", {}) or {}
    home_open = opens.get("home")
    away_open = opens.get("away")
    if home_open is not None and away_open is not None:
        if safe_float(home_open) < safe_float(away_open):
            return "home"
        if safe_float(away_open) < safe_float(home_open):
            return "away"

    home_ml = choose_moneyline_for_side(markets, "home")
    away_ml = choose_moneyline_for_side(markets, "away")
    if home_ml and away_ml:
        hp = safe_int(home_ml.get("price"), 9999)
        ap = safe_int(away_ml.get("price"), 9999)
        if hp < ap:
            return "home"
        if ap < hp:
            return "away"
    return None

def team_side_name(info, side):
    return info.get("home") if side == "home" else info.get("away")

def side_score(info, side):
    return info["home_score"] if side == "home" else info["away_score"]

def opponent_side(side):
    return "away" if side == "home" else "home"

def team_stat_gap(info, side, stat):
    fav = team_box(info, side)
    dog = team_box(info, opponent_side(side))
    return safe_float(fav.get(stat), 0) - safe_float(dog.get(stat), 0)

def possession_value_score(info, live_spread, pace):
    # +4.5 is much more valuable when enough possessions remain.
    left = safe_float(pace.get("possessions_left"), 0)
    if left <= 0:
        return 0
    spread_per_poss = abs(live_spread) / max(left, 1)
    score = 100 - spread_per_poss * 180
    if left >= 24:
        score += 12
    elif left < 14:
        score -= 18
    return round(clamp(score))

def classify_run_quality(info, sg, fav_side):
    run = scoring_run_info(sg, info)
    dog_side = opponent_side(fav_side)
    dog_is_on_run = run["leader"] == dog_side and run["margin"] >= STRONG_RUN_MARGIN

    fav = team_box(info, fav_side)
    dog = team_box(info, dog_side)

    three_gap = safe_float(dog.get("tpm")) - safe_float(fav.get("tpm"))
    ft_gap = safe_float(dog.get("fta")) - safe_float(fav.get("fta"))
    tov_gap = safe_float(fav.get("turnovers")) - safe_float(dog.get("turnovers"))
    paint_gap = safe_float(dog.get("points_in_paint")) - safe_float(fav.get("points_in_paint"))
    reb_gap = safe_float(dog.get("rebounds")) - safe_float(fav.get("rebounds"))

    if not dog_is_on_run:
        return "NOISY_OR_NO_CLEAR_RUN", run, 0, 0

    fake_score = 0
    real_score = 0

    # Fake/noisy: unsustainable shooting spike, small structure edge.
    if three_gap >= 3:
        fake_score += 18
    if run["margin"] >= VERY_STRONG_RUN_MARGIN and three_gap >= 2:
        fake_score += 8
    if ft_gap >= 6:
        real_score += 10
    if tov_gap >= 5:
        real_score += 14
    if paint_gap >= 8:
        real_score += 14
    if reb_gap >= 8:
        real_score += 12

    if fake_score >= real_score + 6:
        quality = "FAKE_UNDERDOG_RUN_SHOOTING_SPIKE"
    elif real_score >= fake_score + 6:
        quality = "REAL_UNDERDOG_CONTROL_RUN"
    else:
        quality = "MIXED_UNDERDOG_RUN"

    return quality, run, fake_score, real_score

def favorite_no_bet_filters(info, fav_side, pace):
    reasons = []
    dog_side = opponent_side(fav_side)

    fav = team_box(info, fav_side)
    dog = team_box(info, dog_side)

    turnover_gap = safe_int(fav.get("turnovers")) - safe_int(dog.get("turnovers"))
    foul_gap = safe_int(fav.get("fouls")) - safe_int(dog.get("fouls"))
    rebound_gap = safe_int(fav.get("rebounds")) - safe_int(dog.get("rebounds"))
    paint_gap = safe_int(dog.get("points_in_paint")) - safe_int(fav.get("points_in_paint"))
    ftr_gap = safe_float(dog.get("ftr")) - safe_float(fav.get("ftr"))

    if safe_float(pace.get("possessions_left")) < MIN_SPREAD_POSSESSIONS_LEFT:
        reasons.append("not enough possessions left")
    if turnover_gap >= MAX_FAVORITE_TURNOVER_GAP:
        reasons.append(f"favorite turnover gap too high: +{turnover_gap}")
    if foul_gap >= MAX_FAVORITE_FOUL_GAP:
        reasons.append(f"favorite foul gap too high: +{foul_gap}")
    if rebound_gap <= -MAX_FAVORITE_REBOUND_DEFICIT:
        reasons.append(f"favorite losing rebounds badly: {rebound_gap}")
    if paint_gap >= 12:
        reasons.append(f"underdog controlling paint: +{paint_gap}")
    if ftr_gap >= 0.18:
        reasons.append(f"underdog FT-rate control: +{round(ftr_gap, 2)}")
    if safe_float(info.get("minutes_remaining")) <= 4:
        reasons.append("late Q4 spread variance too high")
    return reasons

def favorite_buyback_scores(info, sg, markets):
    fav = pregame_favorite_side(sg, markets, info)
    if not fav:
        return None

    spread = choose_spread_for_side(markets, fav)
    if not spread:
        return None

    live_spread = safe_float(spread.get("point"))
    price = spread.get("price")

    if live_spread < FAVORITE_BUYBACK_MIN_LINE or live_spread > FAVORITE_BUYBACK_MAX_LINE:
        return None

    opening = safe_float((sg.get("opening_spreads", {}) or {}).get(fav), None)
    swing = abs(live_spread - opening) if opening is not None else abs(live_spread)

    fav_score = side_score(info, fav)
    dog_score = side_score(info, opponent_side(fav))
    fav_margin = fav_score - dog_score

    proj = projected_total(info, sg)
    pace = proj["pace"]
    eff = proj["eff"]
    qprof = proj["quarter_profile"]
    side_ctx = team_context_for_side(info, fav)
    star = side_ctx.get("star", {})
    strength_edge = safe_float(side_ctx.get("strength_edge"), 0)

    run_quality, run, fake_score, real_score = classify_run_quality(info, sg, fav)
    poss_value = possession_value_score(info, live_spread, pace)
    no_bet_reasons = favorite_no_bet_filters(info, fav, pace)

    comeback_score = 40

    # V1.2 team quality: buybacks are stronger when the pregame favorite still grades better.
    if ENABLE_TEAM_STRENGTH_CONTEXT:
        if strength_edge >= MIN_FAVORITE_STRENGTH_EDGE:
            comeback_score += 12
        elif strength_edge <= -2:
            comeback_score -= 14

    # V1.2 player impact: star limited/out changes the entire favorite buyback profile.
    if ENABLE_PLAYER_IMPACT_CONTEXT:
        if star.get("star_status") in {"limited", "questionable"}:
            comeback_score -= 5
        elif star.get("star_status") == "out":
            comeback_score -= 18

    if run_quality == "FAKE_UNDERDOG_RUN_SHOOTING_SPIKE":
        comeback_score += 22
    elif run_quality == "MIXED_UNDERDOG_RUN":
        comeback_score += 10
    elif run_quality == "REAL_UNDERDOG_CONTROL_RUN":
        comeback_score -= 18

    if swing >= FAVORITE_BUYBACK_MIN_SWING:
        comeback_score += 16
    if 4.0 <= live_spread <= 5.5:
        comeback_score += 12
    if info["minutes_remaining"] >= 12:
        comeback_score += 10
    elif info["minutes_remaining"] >= 6:
        comeback_score += 5
    if abs(fav_margin) <= 9:
        comeback_score += 8
    if poss_value >= 70:
        comeback_score += 10
    elif poss_value <= 45:
        comeback_score -= 10

    # Q3/halftime is the best WNBA favorite buyback correction window.
    if ENABLE_HALFTIME_Q3_CONTEXT and is_halftime_or_q3_reset_window(info):
        comeback_score += HALFTIME_RESET_BONUS
    if qprof == "Q3_ADJUSTMENT_WINDOW":
        comeback_score += Q3_BUYBACK_BONUS
    elif qprof == "Q4_LATE_HIGH_VARIANCE":
        comeback_score -= Q4_LATE_BUYBACK_PENALTY
    elif qprof == "Q1_EARLY_SAMPLE":
        comeback_score -= 4

    risk = 20

    if ENABLE_PLAYER_IMPACT_CONTEXT:
        if star.get("star_status") in {"limited", "questionable"}:
            risk += STAR_LIMITED_RISK_BUMP
        elif star.get("star_status") == "out":
            risk += STAR_OUT_RISK_BUMP

    if info["minutes_remaining"] <= 5:
        risk += 16
    if fav_margin <= -12:
        risk += 14
    if real_score > fake_score:
        risk += 12
    if swing < FAVORITE_BUYBACK_MIN_SWING:
        risk += 12
    if no_bet_reasons:
        risk += min(24, 8 * len(no_bet_reasons))

    value = clamp(45 + comeback_score * 0.48 + poss_value * 0.16 - risk * 0.32)
    confidence = round(clamp(42 + comeback_score * 0.52 + poss_value * 0.12 - risk * 0.30))

    scenario = "FAVORITE_BUYBACK_PLUS_4_5_FAKE_RUN" if run_quality == "FAKE_UNDERDOG_RUN_SHOOTING_SPIKE" and 4.0 <= live_spread <= 5.5 else \
               "FAVORITE_BUYBACK_PLUS_4_5_MIXED_RUN" if run_quality == "MIXED_UNDERDOG_RUN" and 4.0 <= live_spread <= 5.5 else \
               "FAVORITE_BUYBACK_REAL_RUN_BLOCK" if run_quality == "REAL_UNDERDOG_CONTROL_RUN" else \
               "FAVORITE_BUYBACK_PLUS_SPREAD"

    confidence = round(clamp(confidence))
    value = round(clamp(value))
    risk = round(clamp(risk))

    temp_opp_for_predictor = {
        "line": live_spread,
        "scores": {
            "favorite_side": fav,
            "possession_value_score": poss_value,
            "spread_swing": round(swing, 1),
            "strength_edge": strength_edge,
        }
    }
    predictor = market_misprice_score_for_spread(info, sg, temp_opp_for_predictor) if ENABLE_MARKET_PREDICTOR_ENGINE else {
        "market_misprice_score": 50,
        "predicted_spread_contract": 0,
        "future_state": {},
        "run_sustainability": {},
    }

    market_discrepancy = market_discrepancy_for_spread(spread) if ENABLE_MARKET_DISCREPANCY_ENGINE else {"status": "DISABLED", "score": 0}

    confidence = round(clamp(confidence + max(0, predictor.get("market_misprice_score", 50) - 65) * 0.25))
    value = round(clamp(value + max(0, predictor.get("market_misprice_score", 50) - 65) * 0.20))
    confidence = round(clamp(confidence + safe_float(market_discrepancy.get("score"), 0) * 0.16))
    value = round(clamp(value + safe_float(market_discrepancy.get("score"), 0) * 0.14))
    if market_discrepancy.get("status") == "AGAINST_CONSENSUS":
        risk = round(clamp(risk + 10))

    block_reason = ""
    action = "WATCH"

    if STAR_OUT_BUYBACK_BLOCK and star.get("star_status") == "out":
        block_reason = "NO BET: favorite star marked out"
    elif ENABLE_MARKET_PREDICTOR_ENGINE and not WIDE_NET_LEARNING_MODE and predictor.get("market_misprice_score", 0) < MIN_MARKET_MISPRICE_SCORE:
        block_reason = f"predictor miss: market misprice {predictor.get('market_misprice_score')} below {MIN_MARKET_MISPRICE_SCORE}"
    elif ENABLE_MARKET_PREDICTOR_ENGINE and not WIDE_NET_LEARNING_MODE and predictor.get("future_state", {}).get("future_state_score", 0) < MIN_FUTURE_STATE_SCORE:
        block_reason = f"future-state miss: {predictor.get('future_state', {}).get('future_state_score')} below {MIN_FUTURE_STATE_SCORE}"
    elif ENABLE_TEAM_STRENGTH_CONTEXT and strength_edge < -2:
        block_reason = f"NO BET: favorite no longer rates better after context edge {strength_edge}"
    elif ENABLE_DO_NOT_CHASE_CONTEXT and swing >= DO_NOT_CHASE_SPREAD_SWING and confidence < DO_NOT_CHASE_MIN_CONFIDENCE:
        block_reason = f"NO CHASE: spread swing already {round(swing,1)}"
    elif no_bet_reasons:
        block_reason = "NO BET: " + "; ".join(no_bet_reasons[:3])
    elif run_quality == "REAL_UNDERDOG_CONTROL_RUN":
        block_reason = "NO BET: underdog run looks structural, not noisy"
    elif market_discrepancy.get("status") == "AGAINST_CONSENSUS" and confidence < 82:
        block_reason = f"spread against market consensus: {market_discrepancy.get('reason')}"
    elif not price_ok(price, MAX_SPREAD_PRICE):
        if not (safe_int(price) >= ELITE_SPREAD_MAX_PRICE and confidence >= ELITE_SPREAD_MIN_CONFIDENCE):
            block_reason = f"spread price too expensive: {price}"
    if not block_reason:
        if confidence >= FAVORITE_BUYBACK_MIN_CONFIDENCE and value >= FAVORITE_BUYBACK_MIN_VALUE_SCORE and risk <= FAVORITE_BUYBACK_MAX_RISK:
            action = "STRIKE"
        elif wide_net_spread_ok(confidence, value, risk, predictor, block_reason):
            action = "STRIKE"
        else:
            block_reason = f"gate miss: conf {confidence}, value {value}, risk {risk}"

    return assign_alert_tier(apply_profile_rule_adjustment({
        "market_type": "SPREAD",
        "side": team_side_name(info, fav),
        "team_side": fav,
        "line": live_spread,
        "price": price,
        "book": spread.get("book"),
        "edge": round(poss_value / 20.0, 1),
        "projected_total": proj["projected_total"],
        "confidence": confidence,
        "value_score": value,
        "risk_score": risk,
        "action": action,
        "block_reason": block_reason,
        "scenario": scenario,
        "quarter_profile": qprof,
        "scores": {
            "favorite_side": fav, "favorite_margin": fav_margin,
            "opening_spread": opening, "live_spread": live_spread,
            "spread_swing": round(swing, 1), "run_quality": run_quality,
            "fake_run_score": fake_score, "real_run_score": real_score,
            "run": run, "pace": pace, "eff": eff,
            "possession_value_score": poss_value,
            "comeback_score": round(clamp(comeback_score)),
            "strength_edge": strength_edge,
            "star_status": star.get("star_status"),
            "star_impact": star.get("impact"),
            "team_rating": side_ctx.get("team_rating"),
            "no_bet_reasons": no_bet_reasons,
        },
        "predictor": predictor,
        "market_misprice_score": predictor.get("market_misprice_score"),
        "predicted_spread_contract": predictor.get("predicted_spread_contract"),
        "future_state_score": predictor.get("future_state", {}).get("future_state_score"),
        "market_discrepancy": market_discrepancy,
        "market_discrepancy_status": market_discrepancy.get("status"),
        "market_discrepancy_score": market_discrepancy.get("score"),
        "profile_rule": "MONITOR",
    }))

# =============================================================================
# Decision, SMS, logging
# =============================================================================
def assign_alert_tier(opp):
    """
    Wide-net learning tiers:
    A+ = strongest profile
    B = normal playable
    SMALL = data collection / lower unit
    """
    if not opp:
        return opp
    confidence = safe_float(opp.get("confidence"), 0)
    value = safe_float(opp.get("value_score"), 0)
    risk = safe_float(opp.get("risk_score"), 100)
    misprice = safe_float(opp.get("market_misprice_score"), 50)
    future = safe_float(opp.get("future_state_score"), 50)
    edge = safe_float(opp.get("edge"), 0)
    sanity = sanity_edge_tag(edge)

    discrepancy = safe_float(opp.get("market_discrepancy_score"), 0)
    profile_rule = opp.get("profile_rule", "MONITOR")
    score = confidence * 0.30 + value * 0.26 + misprice * 0.20 + future * 0.09 + discrepancy * 0.16 - risk * 0.17
    if opp.get("market_type") == "TOTAL":
        score += min(edge, 12) * 0.9
    else:
        score += min(edge, 6) * 1.2

    if sanity == "HARD_SANITY_CHECK":
        score -= 12
    elif sanity == "SANITY_CHECK":
        score -= 6
    if profile_rule == "TIGHTEN":
        score -= 6
    elif profile_rule == "TRUST":
        score += 3

    if score >= 64 and confidence >= 76 and value >= 72 and risk <= 48 and sanity == "NORMAL_EDGE":
        tier, units = "A_PLUS", UNIT_A_PLUS
    elif score >= 52 and confidence >= 66 and value >= 62 and risk <= 62:
        tier, units = "B_STRIKE", UNIT_B
    else:
        tier, units = "SMALL_LEAN", UNIT_SMALL

    opp["alert_tier"] = tier
    opp["unit_size"] = units
    opp["sanity_tag"] = sanity
    opp["learning_score"] = round(score, 1)

    # Learning can remain wide, but paid alerts should be controlled.
    paid_alert = tier in {"A_PLUS", "B_STRIKE"}
    if tier == "SMALL_LEAN" and SEND_SMALL_LEAN_SMS:
        paid_alert = True
    if BAD_PROFILE_BLOCK_PAID and profile_rule == "TIGHTEN" and tier != "A_PLUS":
        paid_alert = False
    if REQUIRE_MARKET_CONFIRMATION_FOR_SMALL and tier == "SMALL_LEAN" and opp.get("market_discrepancy_status") not in {"OFF_MARKET_EDGE", "STRONG_OFF_MARKET_EDGE"}:
        paid_alert = False
    opp["paid_alert"] = paid_alert
    return opp

def wide_net_strike_ok(edge, confidence, value, risk, predictor, scenario):
    if not WIDE_NET_LEARNING_MODE:
        return False
    if scenario == "NEUTRAL_TOTAL":
        return False
    return (
        safe_float(edge) >= 2.0
        and safe_float(confidence) >= 54
        and safe_float(value) >= 52
        and safe_float(risk) <= 78
        and safe_float(predictor.get("market_misprice_score", 0)) >= 48
        and safe_float(predictor.get("future_state", {}).get("future_state_score", 0)) >= 42
    )

def wide_net_spread_ok(confidence, value, risk, predictor, block_reason):
    if not WIDE_NET_LEARNING_MODE:
        return False
    hard_blocks = ["star marked out", "structural", "not enough possessions", "late Q4"]
    if any(x in (block_reason or "").lower() for x in hard_blocks):
        return False
    return (
        safe_float(confidence) >= 54
        and safe_float(value) >= 52
        and safe_float(risk) <= 78
        and safe_float(predictor.get("market_misprice_score", 0)) >= 48
        and safe_float(predictor.get("future_state", {}).get("future_state_score", 0)) >= 42
    )


def opportunity_key(opp):
    if not opp:
        return ""
    if opp["market_type"] == "TOTAL":
        return f"TOTAL:{opp['side']}"
    return f"SPREAD:{opp.get('team_side')}"

def already_alerted(sg, opp):
    key = opportunity_key(opp)
    now_ts = time.time()
    for a in sg.get("alerts", []):
        if a.get("key") == key:
            age = now_ts - safe_float(a.get("ts"), 0)
            if ONE_STRIKE_PER_GAME_MARKET:
                return True, "one STRIKE already sent for this game/market"
            if age < ALERT_COOLDOWN_SECONDS:
                return True, "cooldown active"
    return False, ""

def approve_opportunity(sg, opp):
    if not opp or opp.get("action") != "STRIKE":
        return False, opp.get("block_reason", "not STRIKE") if opp else "no opportunity"
    if not opp.get("paid_alert", True):
        return False, f"log-only learning play: tier {opp.get('alert_tier')} | profile {opp.get('profile_rule', 'MONITOR')} | market {opp.get('market_discrepancy_status', 'N/A')}"
    blocked, reason = already_alerted(sg, opp)
    if blocked:
        return False, reason
    return True, "approved WNBA BET NOW"

def mark_alert_sent(sg, opp):
    sg.setdefault("alerts", []).append({
        "ts": time.time(), "time": now_local().isoformat(),
        "key": opportunity_key(opp), "market_type": opp.get("market_type"),
        "side": opp.get("side"), "team_side": opp.get("team_side"),
        "line": opp.get("line"), "price": opp.get("price"),
        "confidence": opp.get("confidence"), "scenario": opp.get("scenario"),
        "alert_tier": opp.get("alert_tier"), "unit_size": opp.get("unit_size"),
    })

def reason_lines(info, opp):
    scores = opp.get("scores", {})
    lines = []
    if opp["market_type"] == "TOTAL":
        proj = scores.get("projection", {})
        pace = proj.get("pace", {})
        eff = proj.get("eff", {})
        lines.append(f"Projected {opp['projected_total']} vs live {opp['line']} = {opp['edge']} pt edge")
        lines.append(f"Pace {pace.get('projected_game_possessions')} poss | left {pace.get('possessions_left')} | team PPP {proj.get('ppp')} | live wt {proj.get('live_weight')}")
        lines.append(f"Profile {opp['scenario']} | open move {scores.get('move_from_open')} | velocity {scores.get('velocity')} | short {scores.get('short_velocity')}")
        lines.append(f"Predictor: misprice {opp.get('market_misprice_score')} | future {opp.get('future_state_score')} | next move {opp.get('predicted_line_move')}")
        md = opp.get("market_discrepancy") or {}
        if md:
            lines.append(f"Market deficiency: {md.get('status')} | adv {md.get('advantage_points')} | books {md.get('books')} | stale {md.get('stale_line')}")
        lines.append(f"eFG {eff.get('efg')} | FTr {eff.get('ftr')} | TO {eff.get('turnovers')} | OREB {eff.get('off_reb')} | Fouls {eff.get('fouls')}")
    else:
        run = scores.get("run", {})
        lines.append(f"Favorite available at +{opp['line']} near +{FAVORITE_BUYBACK_TARGET} target")
        lines.append(f"Run quality: {scores.get('run_quality')} | fake {scores.get('fake_run_score')} / real {scores.get('real_run_score')}")
        lines.append(f"Spread swing {scores.get('spread_swing')} | poss value {scores.get('possession_value_score')}/100")
        lines.append(f"Team strength edge {scores.get('strength_edge')} | star {scores.get('star_status')} ({scores.get('star_impact')})")
        lines.append(f"Predictor: misprice {opp.get('market_misprice_score')} | future {opp.get('future_state_score')} | spread contract {opp.get('predicted_spread_contract')}")
        lines.append(f"Recent run: home {run.get('home_run')}, away {run.get('away_run')} over {run.get('window_minutes')} min")
    return lines[:5]

def format_sms(label, info, opp):
    price = opp.get("price")
    price_text = price if price is not None else "N/A"
    title = "🚨 SHIFT WNBA STRIKE — BET NOW"
    if opp["market_type"] == "TOTAL":
        play = f"{opp['side']} {opp['line']} ({price_text})"
        market = "TOTAL"
    else:
        play = f"{opp['side']} +{opp['line']} ({price_text})"
        market = "FAVORITE BUYBACK SPREAD"

    lines = [
        title,
        label,
        "",
        f"PLAY: {play}",
        f"Book: {opp.get('book') or 'Configured app'} | {market_label(price)}",
        f"Market: {market}",
        f"Scenario: {opp.get('scenario')}",
        f"Quarter Profile: {opp.get('quarter_profile')}",
        f"Tier: {opp.get('alert_tier', 'B_STRIKE')} | Unit: {opp.get('unit_size', UNIT_B)}u | Paid: {opp.get('paid_alert', True)} | Sanity: {opp.get('sanity_tag', 'NORMAL_EDGE')}",
        f"Confidence: {opp.get('confidence')}/100 | Value {opp.get('value_score')}/100 | Risk {opp.get('risk_score')}/100",
        f"Predictor: Misprice {opp.get('market_misprice_score')}/100 | Future {opp.get('future_state_score')}/100",
        f"Market Edge: {opp.get('market_discrepancy_status', 'N/A')} | Score {opp.get('market_discrepancy_score', 'N/A')} | Rule {opp.get('profile_rule', 'MONITOR')}",
        f"Score: {info['away_score']}-{info['home_score']} | Q{info['period']} {info['clock']} | Left {info['minutes_remaining']} min",
    ]
    if opp["market_type"] == "TOTAL":
        lines.append(f"Proj: {opp['projected_total']} | Edge: +{opp['edge']} pts")
    else:
        lines.append(f"Target: favorite around +{FAVORITE_BUYBACK_TARGET} | Live: +{opp['line']}")
    lines.append("")
    lines.append("Why:")
    for r in reason_lines(info, opp)[:4]:
        lines.append(f"• {r}")
    lines.append("")
    lines.append("BET NOW")

    text = "\n".join(lines)
    if len(text) > MAX_SHORT_SMS_CHARS:
        text = text[:MAX_SHORT_SMS_CHARS - 20].rstrip() + "\n[Trimmed]"
    return text

def should_send_sms(text, force=False):
    if force:
        return True
    if not SEND_ONLY_STRIKE_SMS:
        return True
    body = (text or "").upper()
    return "BET NOW" in body and "SHIFT WNBA STRIKE" in body

def send_text(text, force=False):
    print("\n" + text + "\n")
    if not should_send_sms(text, force=force):
        print("TEXT NOT SENT: non-BET NOW alert logged only.")
        return False
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, ALERT_TO_NUMBER]):
        print("TEXT NOT SENT: Missing Twilio variables.")
        return False
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(body=text, from_=TWILIO_FROM_NUMBER, to=ALERT_TO_NUMBER)
        print("TEXT SENT SUCCESSFULLY")
        return True
    except Exception as e:
        print("TEXT ERROR:", repr(e))
        return False

STRIKE_FIELDS = [
    "date","time","event_id","game","market_type","side","team_side","line","price","book","scenario","quarter_profile",
    "confidence","value_score","risk_score","edge","projected_total","market_misprice_score","future_state_score","predicted_market_move","score","period","clock",
    "alert_tier","unit_size","sanity_tag","learning_score","profile_rule","paid_alert","market_discrepancy_status","market_discrepancy_score","market_advantage_points","closing_line","closing_price","clv","final_score","final_total","result","units"
]

def log_strike(info, label, opp):
    append_csv(STRIKE_HISTORY_FILE, {
        "date": today(), "time": now_local().isoformat(),
        "event_id": info.get("event_id"), "game": label,
        "market_type": opp.get("market_type"), "side": opp.get("side"), "team_side": opp.get("team_side"),
        "line": opp.get("line"), "price": opp.get("price"), "book": opp.get("book"),
        "scenario": opp.get("scenario"), "quarter_profile": opp.get("quarter_profile"),
        "confidence": opp.get("confidence"), "value_score": opp.get("value_score"),
        "risk_score": opp.get("risk_score"), "edge": opp.get("edge"),
        "projected_total": opp.get("projected_total"),
        "market_misprice_score": opp.get("market_misprice_score"),
        "future_state_score": opp.get("future_state_score"),
        "predicted_market_move": opp.get("predicted_line_move") if opp.get("market_type") == "TOTAL" else opp.get("predicted_spread_contract"),
        "alert_tier": opp.get("alert_tier"), "unit_size": opp.get("unit_size"),
        "sanity_tag": opp.get("sanity_tag"), "learning_score": opp.get("learning_score"),
        "profile_rule": opp.get("profile_rule"),
        "paid_alert": opp.get("paid_alert"),
        "market_discrepancy_status": opp.get("market_discrepancy_status"),
        "market_discrepancy_score": opp.get("market_discrepancy_score"),
        "market_advantage_points": (opp.get("market_discrepancy") or {}).get("advantage_points"),
        "score": f"{info['away_score']}-{info['home_score']}",
        "period": info.get("period"), "clock": info.get("clock"),
        "closing_line": "", "closing_price": "", "clv": "",
        "final_score": "", "final_total": "", "result": "", "units": "",
    }, STRIKE_FIELDS)

def log_near_miss(info, label, opp, reason):
    if not opp:
        return
    append_csv(NEAR_MISS_FILE, {
        "date": today(), "time": now_local().isoformat(), "event_id": info.get("event_id"),
        "game": label, "market_type": opp.get("market_type"), "side": opp.get("side"),
        "team_side": opp.get("team_side"), "line": opp.get("line"), "price": opp.get("price"),
        "book": opp.get("book"), "scenario": opp.get("scenario"), "quarter_profile": opp.get("quarter_profile"),
        "confidence": opp.get("confidence"), "value_score": opp.get("value_score"),
        "risk_score": opp.get("risk_score"), "edge": opp.get("edge"),
        "market_misprice_score": opp.get("market_misprice_score"),
        "future_state_score": opp.get("future_state_score"),
        "predicted_market_move": opp.get("predicted_line_move") if opp.get("market_type") == "TOTAL" else opp.get("predicted_spread_contract"),
        "reason": reason or opp.get("block_reason"),
    }, [
        "date","time","event_id","game","market_type","side","team_side","line","price","book","scenario","quarter_profile",
        "confidence","value_score","risk_score","edge","market_misprice_score","future_state_score","predicted_market_move","reason"
    ])

def result_lesson(row):
    result = row.get("result")
    scenario = row.get("scenario") or "UNKNOWN"
    market = row.get("market_type")
    side = str(row.get("side", "")).upper()
    line = safe_float(row.get("line"))
    final_total = safe_float(row.get("final_total"))
    clv = safe_float(row.get("clv"), None) if row.get("clv") not in (None, "") else None

    if market == "TOTAL":
        margin = round(final_total - line, 1) if side == "OVER" else round(line - final_total, 1)
        if result == "WIN":
            base = f"Won by {margin}; profile held."
        elif result == "LOSS":
            base = f"Lost by {abs(margin)}; profile failed or market corrected."
        else:
            base = "Push; number was efficient."
    else:
        base = "Spread result graded by cover margin."

    if clv is not None:
        if clv >= GOOD_CLV_THRESHOLD:
            base += " Good CLV."
        elif clv <= -GOOD_CLV_THRESHOLD:
            base += " Bad CLV; tighten this bucket."
        else:
            base += " Neutral CLV."

    if "PACE_CONTINUATION_OVER" in scenario and result == "LOSS":
        base += " Watch for late pace collapse."
    elif "FAST_DROP_BUY_OVER" in scenario and result == "LOSS":
        base += " Market drop may have been right, not a discount."
    elif "FAST_SPIKE_FADE_UNDER" in scenario and result == "LOSS":
        base += " Hot scoring did not regress."
    elif "FAVORITE_BUYBACK" in scenario and result == "LOSS":
        base += " Buyback failed; run may have been structural."

    return base


def historical_rows_through_today():
    return [r for r in read_csv_rows(GRADED_RESULTS_FILE) if r.get("date") <= today()]

def rows_for_date(date_text):
    return [r for r in read_csv_rows(GRADED_RESULTS_FILE) if r.get("date") == date_text]

def summarize_rows(rows):
    wins = sum(1 for r in rows if r.get("result") == "WIN")
    losses = sum(1 for r in rows if r.get("result") == "LOSS")
    pushes = sum(1 for r in rows if r.get("result") == "PUSH")
    units = round(sum(safe_float(r.get("units"), 0) for r in rows), 2)
    risked = round(sum(safe_float(r.get("unit_size"), 0) for r in rows if r.get("result") in {"WIN", "LOSS", "PUSH"}), 2)
    roi = round((units / risked) * 100, 1) if risked else 0.0
    win_pct = round((wins / max(1, wins + losses)) * 100, 1) if (wins + losses) else 0.0
    return {"wins": wins, "losses": losses, "pushes": pushes, "units": units, "risked": risked, "roi": roi, "win_pct": win_pct}

def best_worst_profile(rows):
    buckets = {}
    for r in rows:
        key = profile_key_from_row(r, include_tier=False)
        rec = buckets.setdefault(key, {"w": 0, "l": 0, "p": 0, "u": 0.0})
        if r.get("result") == "WIN":
            rec["w"] += 1
        elif r.get("result") == "LOSS":
            rec["l"] += 1
        else:
            rec["p"] += 1
        rec["u"] += safe_float(r.get("units"), 0)
    if not buckets:
        return None, None
    ranked = sorted(buckets.items(), key=lambda kv: kv[1]["u"], reverse=True)
    def fmt(item):
        key, rec = item
        return f"{key} | {rec['w']}-{rec['l']}-{rec['p']} | {round(rec['u'],2)}u"
    return fmt(ranked[0]), fmt(ranked[-1])

def tier_summary(rows, tier):
    tier_rows = [r for r in rows if str(r.get("alert_tier", "")).upper() == tier]
    sm = summarize_rows(tier_rows)
    return f"{tier}: {sm['wins']}-{sm['losses']}-{sm['pushes']} | {sm['units']}u"

def update_bankroll_tracker(summary):
    season_rows = historical_rows_through_today()
    season = summarize_rows(season_rows)
    ending = round(STARTING_BANKROLL_UNITS + season["units"], 2)
    best, worst = best_worst_profile(rows_for_date(today()))
    append_csv(BANKROLL_TRACKER_FILE, {
        "date": today(),
        "starting_bankroll_units": STARTING_BANKROLL_UNITS,
        "ending_bankroll_units": ending,
        "daily_units": summary.get("units", 0),
        "season_units": season.get("units", 0),
        "units_risked_today": summary.get("risked", 0),
        "daily_roi_pct": summary.get("roi", 0),
        "season_record": f"{season['wins']}-{season['losses']}-{season['pushes']}",
        "best_profile": best or "N/A",
        "worst_profile": worst or "N/A",
        "updated_at": now_local().isoformat(),
    }, ["date","starting_bankroll_units","ending_bankroll_units","daily_units","season_units","units_risked_today","daily_roi_pct","season_record","best_profile","worst_profile","updated_at"])
    return ending, season

def format_result_sms(label, graded_rows):
    if not graded_rows:
        return ""
    sm = summarize_rows(graded_rows)
    lines = [
        "✅ SHIFT WNBA RESULT",
        label,
        "",
        f"Game: {sm['wins']}-{sm['losses']}-{sm['pushes']} | {sm['units']}u",
    ]

    for r in graded_rows[:4]:
        market = r.get("market_type")
        side = r.get("side")
        line = r.get("line")
        price = r.get("price")
        result = r.get("result")
        units_row = r.get("units")
        clv = r.get("clv") if r.get("clv") not in (None, "") else "N/A"
        play = f"{side} {line}" if market == "TOTAL" else f"{side} +{line}"
        icon = "✅" if result == "WIN" else "❌" if result == "LOSS" else "➖"
        lines.extend([
            "",
            f"{icon} {play} ({price})",
            f"Result: {result} | Units: {units_row}u | CLV: {clv}",
            f"Final: {r.get('final_score')} | Total: {r.get('final_total')}",
            f"Why: {result_lesson(r)}",
        ])

    return "\n".join(lines[:24])

# =============================================================================
# CLV and grading
# =============================================================================
def find_current_line_for_strike(markets, strike_row):
    market_type = strike_row.get("market_type")
    team_side = strike_row.get("team_side")
    if market_type == "TOTAL":
        total = markets.get("total") or {}
        return total.get("point"), total.get("over_price") if strike_row.get("side") == "OVER" else total.get("under_price"), total.get("book")
    if market_type == "SPREAD" and team_side:
        offer = choose_spread_for_side(markets, team_side)
        if offer:
            return offer.get("point"), offer.get("price"), offer.get("book")
    return None, None, None

def calculate_clv(strike_row, current_line):
    if current_line is None or current_line == "":
        return ""
    entry = safe_float(strike_row.get("line"))
    current = safe_float(current_line)
    market_type = strike_row.get("market_type")
    side = str(strike_row.get("side")).upper()

    if market_type == "TOTAL":
        if side == "OVER":
            return round(current - entry, 2)
        if side == "UNDER":
            return round(entry - current, 2)

    if market_type == "SPREAD":
        # If we got +4.5 and close is +3.5, we beat the line by +1.0.
        return round(entry - current, 2)

    return ""

def update_clv_snapshots(label, info, markets):
    rows = read_csv_rows(STRIKE_HISTORY_FILE)
    if not rows:
        return
    for r in rows:
        if r.get("date") != today() or str(r.get("event_id")) != str(info.get("event_id")):
            continue
        if r.get("final_score"):
            continue
        current_line, current_price, book = find_current_line_for_strike(markets, r)
        clv = calculate_clv(r, current_line)
        if clv == "":
            continue
        append_csv(CLV_HISTORY_FILE, {
            "date": today(), "time": now_local().isoformat(),
            "event_id": info.get("event_id"), "game": label,
            "market_type": r.get("market_type"), "side": r.get("side"),
            "team_side": r.get("team_side"), "entry_line": r.get("line"),
            "current_line": current_line, "entry_price": r.get("price"),
            "current_price": current_price, "book": book,
            "clv": clv, "period": info.get("period"), "clock": info.get("clock"),
        }, [
            "date","time","event_id","game","market_type","side","team_side",
            "entry_line","current_line","entry_price","current_price","book","clv","period","clock"
        ])

def latest_clv_for_strike(row):
    snaps = [
        s for s in read_csv_rows(CLV_HISTORY_FILE)
        if s.get("event_id") == row.get("event_id")
        and s.get("market_type") == row.get("market_type")
        and s.get("side") == row.get("side")
        and s.get("team_side") == row.get("team_side")
        and str(s.get("entry_line")) == str(row.get("line"))
    ]
    if not snaps:
        return "", "", ""
    last = snaps[-1]
    return last.get("current_line"), last.get("current_price"), last.get("clv")

def grade_completed_strikes(event_id, label, final_score):
    rows = read_csv_rows(STRIKE_HISTORY_FILE)
    new_graded = []
    if not rows:
        return new_graded

    graded_keys = set()
    if os.path.exists(GRADED_RESULTS_FILE):
        for r in read_csv_rows(GRADED_RESULTS_FILE):
            graded_keys.add((r.get("event_id"), r.get("time"), r.get("market_type"), r.get("side"), r.get("line")))

    try:
        away, home = [safe_int(x) for x in str(final_score).split("-")]
    except Exception:
        return new_graded
    final_total = away + home
    home_margin = home - away

    for r in rows:
        if str(r.get("event_id")) != str(event_id):
            continue
        key = (r.get("event_id"), r.get("time"), r.get("market_type"), r.get("side"), r.get("line"))
        if key in graded_keys:
            continue

        result = "PUSH"
        market_type = r.get("market_type")
        side = str(r.get("side")).upper()
        team_side = r.get("team_side")
        line = safe_float(r.get("line"))
        price = r.get("price")

        if market_type == "TOTAL":
            if side == "OVER":
                result = "WIN" if final_total > line else "LOSS" if final_total < line else "PUSH"
            elif side == "UNDER":
                result = "WIN" if final_total < line else "LOSS" if final_total > line else "PUSH"
        elif market_type == "SPREAD":
            margin_for_side = home_margin if team_side == "home" else -home_margin
            cover_margin = margin_for_side + line
            result = "WIN" if cover_margin > 0 else "LOSS" if cover_margin < 0 else "PUSH"

        closing_line, closing_price, clv = latest_clv_for_strike(r)
        out = dict(r)
        out["closing_line"] = closing_line
        out["closing_price"] = closing_price
        out["clv"] = clv
        out["final_score"] = final_score
        out["final_total"] = final_total
        out["result"] = result
        out["units"] = result_units(result, price, r.get("unit_size", 1.0))
        out["graded_at"] = now_local().isoformat()
        append_csv(GRADED_RESULTS_FILE, out, list(out.keys()))
        new_graded.append(out)
        print(f"GRADED | {label} | {market_type} {side} {line} | {result} | CLV {clv} | Final {final_score}")

    return new_graded

# =============================================================================
# Daily report / learning summary
# =============================================================================
def summarize_today():
    rows = [r for r in read_csv_rows(GRADED_RESULTS_FILE) if r.get("date") == today()]
    strikes = [r for r in read_csv_rows(STRIKE_HISTORY_FILE) if r.get("date") == today()]
    near = [r for r in read_csv_rows(NEAR_MISS_FILE) if r.get("date") == today()]
    clv_rows = [r for r in read_csv_rows(CLV_HISTORY_FILE) if r.get("date") == today()]

    wins = sum(1 for r in rows if r.get("result") == "WIN")
    losses = sum(1 for r in rows if r.get("result") == "LOSS")
    pushes = sum(1 for r in rows if r.get("result") == "PUSH")
    graded = wins + losses + pushes
    units = round(sum(safe_float(r.get("units"), 0) for r in rows), 2)
    win_pct = round((wins / (wins + losses) * 100), 1) if (wins + losses) else 0.0

    predictor_scores = [safe_float(r.get("market_misprice_score"), None) for r in rows if r.get("market_misprice_score") not in (None, "")]
    predictor_scores = [p for p in predictor_scores if p is not None]
    avg_predictor = round(sum(predictor_scores) / len(predictor_scores), 1) if predictor_scores else 0.0

    clvs = [safe_float(r.get("clv"), None) for r in clv_rows if r.get("clv") not in (None, "")]
    clvs = [c for c in clvs if c is not None]
    avg_clv = round(sum(clvs) / len(clvs), 2) if clvs else 0.0
    positive_clv = sum(1 for c in clvs if c >= GOOD_CLV_THRESHOLD)

    by_profile = {}
    by_market = {}
    by_quarter = {}
    for r in rows:
        market = r.get("market_type") or "UNKNOWN"
        mrec = by_market.setdefault(market, {"w": 0, "l": 0, "p": 0, "u": 0.0, "clv": []})
        if r.get("result") == "WIN":
            mrec["w"] += 1
        elif r.get("result") == "LOSS":
            mrec["l"] += 1
        else:
            mrec["p"] += 1
        mrec["u"] += safe_float(r.get("units"), 0)
        if r.get("clv") not in (None, ""):
            mrec["clv"].append(safe_float(r.get("clv")))

        quarter = r.get("quarter_profile") or "UNKNOWN"
        qrec = by_quarter.setdefault(quarter, {"w": 0, "l": 0, "p": 0, "u": 0.0, "clv": []})
        if r.get("result") == "WIN":
            qrec["w"] += 1
        elif r.get("result") == "LOSS":
            qrec["l"] += 1
        else:
            qrec["p"] += 1
        qrec["u"] += safe_float(r.get("units"), 0)
        if r.get("clv") not in (None, ""):
            qrec["clv"].append(safe_float(r.get("clv")))

        profile = profile_key_from_row(r, include_tier=False)
        rec = by_profile.setdefault(profile, {"w": 0, "l": 0, "p": 0, "u": 0.0, "clv": []})
        if r.get("result") == "WIN":
            rec["w"] += 1
        elif r.get("result") == "LOSS":
            rec["l"] += 1
        else:
            rec["p"] += 1
        rec["u"] += safe_float(r.get("units"), 0)
        if r.get("clv") not in (None, ""):
            rec["clv"].append(safe_float(r.get("clv")))

    profile_lines = []
    for profile, rec in sorted(by_profile.items()):
        sample = rec["w"] + rec["l"] + rec["p"]
        if sample < MIN_PROFILE_SAMPLE_FOR_REPORT:
            continue
        wp = round(rec["w"] / max(1, rec["w"] + rec["l"]) * 100, 1) if (rec["w"] + rec["l"]) else 0.0
        aclv = round(sum(rec["clv"]) / len(rec["clv"]), 2) if rec["clv"] else 0.0
        action = "TRUST" if wp >= 57 and aclv >= 0 else "TIGHTEN" if wp < 52 or aclv < -0.25 else "MONITOR"
        profile_lines.append(f"{profile}: {rec['w']}-{rec['l']}-{rec['p']} | {wp}% | {round(rec['u'],2)}u | CLV {aclv} | {action}")

        append_csv(PROFILE_SUMMARY_FILE, {
            "date": today(), "profile": profile, "wins": rec["w"], "losses": rec["l"], "pushes": rec["p"],
            "win_pct": wp, "units": round(rec["u"], 2), "avg_clv": aclv, "recommendation": action,
        }, ["date","profile","wins","losses","pushes","win_pct","units","avg_clv","recommendation"])

    market_lines = []
    for market, rec in sorted(by_market.items()):
        wp = round(rec["w"] / max(1, rec["w"] + rec["l"]) * 100, 1) if (rec["w"] + rec["l"]) else 0.0
        aclv = round(sum(rec["clv"]) / len(rec["clv"]), 2) if rec["clv"] else 0.0
        market_lines.append(f"{market}: {rec['w']}-{rec['l']}-{rec['p']} | {wp}% | {round(rec['u'],2)}u | CLV {aclv}")

    quarter_lines = []
    for quarter, rec in sorted(by_quarter.items()):
        wp = round(rec["w"] / max(1, rec["w"] + rec["l"]) * 100, 1) if (rec["w"] + rec["l"]) else 0.0
        aclv = round(sum(rec["clv"]) / len(rec["clv"]), 2) if rec["clv"] else 0.0
        quarter_lines.append(f"{quarter}: {rec['w']}-{rec['l']}-{rec['p']} | {wp}% | {round(rec['u'],2)}u | CLV {aclv}")

    summary = {
        "date": today(), "graded": graded, "wins": wins, "losses": losses, "pushes": pushes,
        "win_pct": win_pct, "units": units, "strikes": len(strikes), "near_misses": len(near),
        "avg_clv": avg_clv, "positive_clv_count": positive_clv, "clv_snapshots": len(clv_rows),
        "avg_predictor": avg_predictor,
        "risked": round(sum(safe_float(r.get("unit_size"), 0) for r in rows if r.get("result") in {"WIN", "LOSS", "PUSH"}), 2),
        "roi": 0.0,
        "profile_lines": profile_lines, "market_lines": market_lines, "quarter_lines": quarter_lines,
    }

    adaptive_rules = update_adaptive_profile_rules_from_rows(rows)
    summary["roi"] = round((summary["units"] / summary["risked"]) * 100, 1) if summary.get("risked") else 0.0
    best_profile, worst_profile = best_worst_profile(rows)
    summary["best_profile"] = best_profile or "N/A"
    summary["worst_profile"] = worst_profile or "N/A"
    ending_bankroll, season_summary = update_bankroll_tracker(summary)
    summary["ending_bankroll"] = ending_bankroll
    summary["season_summary"] = season_summary
    summary["adaptive_rules"] = adaptive_rules

    append_csv(DAILY_SUMMARY_FILE, {
        "date": today(), "graded": graded, "wins": wins, "losses": losses, "pushes": pushes,
        "win_pct": win_pct, "units": units, "strikes": len(strikes), "near_misses": len(near),
        "avg_clv": avg_clv, "positive_clv_count": positive_clv, "clv_snapshots": len(clv_rows),
        "avg_predictor": avg_predictor,
    }, ["date","graded","wins","losses","pushes","win_pct","units","strikes","near_misses","avg_clv","positive_clv_count","clv_snapshots"])

    return summary

def update_adaptive_profile_rules_from_rows(rows):
    if not ENABLE_ADAPTIVE_PROFILE_RULES:
        return {}
    by_profile = {}
    for r in rows:
        profile = profile_key_from_row(r, include_tier=False)
        rec = by_profile.setdefault(profile, {"w":0,"l":0,"p":0,"u":0.0,"clv":[]})
        if r.get("result") == "WIN": rec["w"] += 1
        elif r.get("result") == "LOSS": rec["l"] += 1
        else: rec["p"] += 1
        rec["u"] += safe_float(r.get("units"), 0)
        if r.get("clv") not in (None, ""):
            rec["clv"].append(safe_float(r.get("clv"), 0))
    rules = load_profile_rules()
    for profile, rec in by_profile.items():
        sample = rec["w"] + rec["l"] + rec["p"]
        if sample < PROFILE_RULE_MIN_SAMPLE:
            continue
        avg_clv = round(sum(rec["clv"]) / len(rec["clv"]), 2) if rec["clv"] else 0.0
        win_pct = round(rec["w"] / max(1, rec["w"] + rec["l"]) * 100, 1) if (rec["w"] + rec["l"]) else 0.0
        units = round(rec["u"], 2)
        if units > 0 and avg_clv >= PROFILE_TRUST_CLV:
            action = "TRUST"
        elif units < 0 and avg_clv <= PROFILE_TIGHTEN_CLV:
            action = "TIGHTEN"
        elif units < -1.5:
            action = "TIGHTEN"
        else:
            action = "MONITOR"
        rules[profile] = {
            "action": action, "sample": sample, "wins": rec["w"], "losses": rec["l"], "pushes": rec["p"],
            "win_pct": win_pct, "units": units, "avg_clv": avg_clv, "updated_at": now_local().isoformat(),
        }
    save_profile_rules(rules)
    return rules

def format_daily_report(summary):
    season = summary.get("season_summary", {}) or {}
    lines = [
        f"📊 SHIFT WNBA DAILY SUMMARY — {summary['date']}",
        "",
        f"Today: {summary['wins']}-{summary['losses']}-{summary['pushes']} | {summary['units']}u",
        f"Risked: {summary.get('risked', 0)}u | ROI: {summary.get('roi', 0)}%",
        f"Alerts: {summary['strikes']} STRIKE | Near-misses: {summary['near_misses']}",
        f"CLV: avg {summary['avg_clv']} | +CLV {summary['positive_clv_count']}/{summary['clv_snapshots']}",
        "",
        f"Season: {season.get('wins', 0)}-{season.get('losses', 0)}-{season.get('pushes', 0)} | {season.get('units', 0)}u",
        f"Bankroll: {summary.get('ending_bankroll', STARTING_BANKROLL_UNITS)}u",
        "",
        tier_summary(read_csv_rows(GRADED_RESULTS_FILE), "A_PLUS"),
        tier_summary(read_csv_rows(GRADED_RESULTS_FILE), "B_STRIKE"),
        "",
        f"Best Profile: {summary.get('best_profile', 'N/A')}",
        f"Worst Profile: {summary.get('worst_profile', 'N/A')}",
        "",
        "Rule: trust +units/+CLV profiles, tighten -units/-CLV profiles, keep SMALL_LEAN log-only."
    ]
    return "\n".join(lines)

def send_email_report(text):
    if not ENABLE_NIGHTLY_EMAIL_REPORT:
        return
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM, NIGHTLY_EMAIL_TO]):
        print("EMAIL NOT SENT: Missing SMTP variables.")
        return
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_FROM
        msg["To"] = NIGHTLY_EMAIL_TO
        msg["Subject"] = f"{NIGHTLY_EMAIL_SUBJECT_PREFIX} — {today()}"
        msg.set_content(text)

        if ATTACH_DAILY_CSVS_TO_EMAIL:
            for path in [STRIKE_HISTORY_FILE, GRADED_RESULTS_FILE, CLV_HISTORY_FILE, NEAR_MISS_FILE, DAILY_SUMMARY_FILE, PROFILE_SUMMARY_FILE, MARKET_DISCREPANCY_FILE, PROFILE_RULES_FILE, BANKROLL_TRACKER_FILE]:
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        msg.add_attachment(f.read(), maintype="text", subtype="csv", filename=os.path.basename(path))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print("NIGHTLY EMAIL SENT")
    except Exception as e:
        print("EMAIL ERROR:", repr(e))

def maybe_send_daily_report(st, force=False):
    if not ENABLE_DAILY_LEARNING_REPORT:
        return
    if st.get("daily_report_sent") and not force:
        return
    if not force and now_local().hour < DAILY_LEARNING_REPORT_HOUR:
        return
    summary = summarize_today()
    report = format_daily_report(summary)
    print("\n" + report + "\n")
    if SEND_DAILY_LEARNING_REPORT_SMS and SEND_SIMPLE_DAILY_SUMMARY_SMS:
        send_text(report[:MAX_SHORT_SMS_CHARS], force=True)
    send_email_report(report)
    st["daily_report_sent"] = True
    save_state(st)

# =============================================================================
# Main loop
# =============================================================================
def should_fetch_event(start_time):
    if not start_time:
        return True
    minutes_to_start = (start_time - now_local()).total_seconds() / 60.0
    return minutes_to_start <= PREGAME_WINDOW_MINUTES

def event_schedule_line(event):
    comp = (event.get("competitions") or [{}])[0]
    st = parse_espn_start(comp)
    label = game_label_from_event(event)
    if st:
        return f"{label} | Start {st.strftime('%I:%M %p')} AZ"
    return label

def choose_best_opportunity(total_opp, fav_opp):
    candidates = [o for o in [total_opp, fav_opp] if o]
    strikes = [o for o in candidates if o.get("action") == "STRIKE"]
    if strikes:
        def rank(o):
            spread_bonus = 7 if o.get("market_type") == "SPREAD" and "PLUS_4_5" in o.get("scenario", "") else 0
            clv_bonus = 4 if o.get("book") in USER_PLAYABLE_BOOKS else 0
            return o.get("confidence", 0) + o.get("value_score", 0) * 0.45 - o.get("risk_score", 0) * 0.22 + spread_bonus + clv_bonus
        return sorted(strikes, key=rank, reverse=True)[0]
    return None

def run_once():
    st = load_state()
    events = espn_scoreboard()

    needs_odds = False
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        start = parse_espn_start(comp)
        if should_fetch_event(start) and not is_final_locked_today(st, ev.get("id")):
            needs_odds = True
            break

    odds = get_odds() if needs_odds else []
    if not needs_odds:
        print("ODDS SKIPPED: all games outside pregame window or final locked.")

    print(f"\n--- {APP_BUILD_LABEL} CHECK {now_local().strftime('%I:%M:%S %p')} ---")

    active_found = False

    for ev in events:
        event_id = str(ev.get("id"))
        label = game_label_from_event(ev)
        comp = (ev.get("competitions") or [{}])[0]
        start = parse_espn_start(comp)

        if is_final_locked_today(st, event_id):
            print(f"SKIP FINAL | {label} | already final-locked for {today()}")
            continue

        if is_final_status(comp):
            info = parse_live_game(ev, {})
            final_score = f"{info['away_score']}-{info['home_score']}"
            mark_final_locked(st, event_id, label, final_score)
            graded_rows = grade_completed_strikes(event_id, label, final_score)
            if SEND_RESULT_SMS and SEND_SIMPLE_RESULT_SMS and graded_rows:
                result_sms = format_result_sms(label, graded_rows)
                if result_sms:
                    send_text(result_sms[:MAX_SHORT_SMS_CHARS], force=True)
            print(f"FINAL LOCKED | {label} | Score {final_score} | no more tracking today")
            save_state(st)
            continue

        if start and not should_fetch_event(start):
            print(f"DORMANT | {event_schedule_line(ev)} | Too early")
            continue

        summary = espn_summary(event_id) if is_live_status(comp) else {}
        info = parse_live_game(ev, summary)
        sg = state_game(st, event_id)

        markets = find_markets(odds, info["home"], info["away"])
        update_line_state(sg, info, markets)
        recent_game_snapshots(sg, info)
        update_clv_snapshots(label, info, markets)

        mode = "ACTIVE" if is_live_status(comp) else "PREGAME"
        total_line = (markets.get("total") or {}).get("point")
        spread_home = choose_spread_for_side(markets, "home")
        spread_away = choose_spread_for_side(markets, "away")

        print(
            f"{mode} | {label} | Score {info['away_score']}-{info['home_score']} | "
            f"Q{info['period']} {info['clock']} | Total {total_line or 'N/A'} | "
            f"HomeSpr {spread_home.get('point') if spread_home else 'N/A'} | AwaySpr {spread_away.get('point') if spread_away else 'N/A'}"
        )

        if not is_live_status(comp):
            save_state(st)
            continue

        active_found = True
        total_opp = build_total_opportunity(info, sg, markets)
        fav_opp = favorite_buyback_scores(info, sg, markets) if ENABLE_FAVORITE_BUYBACK else None
        best = choose_best_opportunity(total_opp, fav_opp)

        for opp in [total_opp, fav_opp]:
            if opp and opp.get("action") != "STRIKE":
                log_near_miss(info, label, opp, opp.get("block_reason"))

        if best:
            ok, reason = approve_opportunity(sg, best)
            if ok:
                sms = format_sms(label, info, best)
                send_text(sms)
                log_strike(info, label, best)
                log_market_discrepancy(info, label, best)
                mark_alert_sent(sg, best)
                save_state(st)
            else:
                log_near_miss(info, label, best, reason)
                print(f"BET NOW BLOCKED | {label} | {reason}")

    maybe_send_daily_report(st)
    save_state(st)
    return FAST_POLL_SECONDS if active_found else ACTIVE_POLL_SECONDS if needs_odds else SLOW_POLL_SECONDS

def main():
    print(f"BOOT: {APP_BUILD_LABEL}")
    print(f"DATE: {today()} | TZ: America/Phoenix")
    print(f"Playable books: {USER_PLAYABLE_BOOKS}")
    print("Strategy: WNBA Market Predictor — future-state, run sustainability, possession pressure, totals, +4.5 favorite buyback, CLV, and nightly learning.")
    while True:
        try:
            sleep_for = run_once()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print("LOOP ERROR:", repr(e))
            sleep_for = SLOW_POLL_SECONDS
        print(f"SLEEP {sleep_for}s")
        time.sleep(sleep_for)

if __name__ == "__main__":
    main()
