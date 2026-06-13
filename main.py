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
APP_VERSION = os.getenv("SHIFT_WNBA_APP_VERSION", "V3.4.0")
APP_MODE = "BETMGM PRO V3.4 + DECISION LEARNING UPSERT"
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
POST_ALERT_MOVE_FILE = os.getenv("WNBA_POST_ALERT_MOVE_FILE", "wnba_post_alert_movement.csv")
MISSING_TEAM_WARN_FILE = os.getenv("WNBA_MISSING_TEAM_WARN_FILE", "wnba_missing_team_warnings.csv")

# V3.2 Google Sheets / decision database layer.
# Mirrors the MLB business-process structure, but uses WNBA-specific fields and markets.
WNBA_DECISION_LOG_FILE = os.getenv("WNBA_DECISION_LOG_FILE", "wnba_decision_log.csv")
WNBA_FEATURE_LEARNING_FILE = os.getenv("WNBA_FEATURE_LEARNING_FILE", "wnba_feature_learning_summary.csv")
WNBA_ADAPTIVE_CONFIG_FILE = os.getenv("WNBA_ADAPTIVE_CONFIG_FILE", "wnba_adaptive_config.json")
WNBA_TRACKING_WEBHOOK_URL = os.getenv("WNBA_TRACKING_WEBHOOK_URL", os.getenv("TRACKING_WEBHOOK_URL", "")).strip()
WNBA_TRACKING_WEBHOOK_SECRET = os.getenv("WNBA_TRACKING_WEBHOOK_SECRET", os.getenv("TRACKING_WEBHOOK_SECRET", "")).strip()
WNBA_ENABLE_TRACKING_WEBHOOK = os.getenv("WNBA_ENABLE_TRACKING_WEBHOOK", os.getenv("ENABLE_TRACKING_WEBHOOK", "false")).lower() == "true"
WNBA_ENABLE_DECISION_LOG = os.getenv("WNBA_ENABLE_DECISION_LOG", "true").lower() == "true"
WNBA_ENABLE_DECISION_LOG_NO_BETS = os.getenv("WNBA_ENABLE_DECISION_LOG_NO_BETS", "true").lower() == "true"
WNBA_ENABLE_DECISION_LOG_RESEARCH = os.getenv("WNBA_ENABLE_DECISION_LOG_RESEARCH", "true").lower() == "true"
WNBA_DECISION_LOG_REJECT_COOLDOWN_SECONDS = int(os.getenv("WNBA_DECISION_LOG_REJECT_COOLDOWN_SECONDS", "900"))
WNBA_DECISION_LOG_ACCEPT_COOLDOWN_SECONDS = int(os.getenv("WNBA_DECISION_LOG_ACCEPT_COOLDOWN_SECONDS", "300"))
WNBA_ENABLE_ADAPTIVE_CONFIG = os.getenv("WNBA_ENABLE_ADAPTIVE_CONFIG", "true").lower() == "true"
WNBA_MIN_ADAPTIVE_SAMPLE = int(os.getenv("WNBA_MIN_ADAPTIVE_SAMPLE", "40"))
WNBA_ADAPTIVE_STRONG_ROI = float(os.getenv("WNBA_ADAPTIVE_STRONG_ROI", "0.04"))
WNBA_ADAPTIVE_WEAK_ROI = float(os.getenv("WNBA_ADAPTIVE_WEAK_ROI", "-0.03"))
WNBA_ADAPTIVE_STRONG_CLV = float(os.getenv("WNBA_ADAPTIVE_STRONG_CLV", "0.50"))
WNBA_ADAPTIVE_WEAK_CLV = float(os.getenv("WNBA_ADAPTIVE_WEAK_CLV", "-0.50"))
WNBA_ENABLE_SHEETS_UPSERT_HINTS = os.getenv("WNBA_ENABLE_SHEETS_UPSERT_HINTS", "true").lower() == "true"
WNBA_DECISION_UPSERT_KEY = os.getenv("WNBA_DECISION_UPSERT_KEY", "snapshot_id")
WNBA_SNAPSHOT_BUCKET_SECONDS = int(os.getenv("WNBA_SNAPSHOT_BUCKET_SECONDS", "180"))
WNBA_ENABLE_PASSED_PLAY_ADAPTIVE_LEARNING = os.getenv("WNBA_ENABLE_PASSED_PLAY_ADAPTIVE_LEARNING", "true").lower() == "true"
WNBA_PASSED_PLAY_MIN_SAMPLE = int(os.getenv("WNBA_PASSED_PLAY_MIN_SAMPLE", "20"))
WNBA_PASSED_PLAY_LOOSEN_UNITS = float(os.getenv("WNBA_PASSED_PLAY_LOOSEN_UNITS", "2.0"))
WNBA_PASSED_PLAY_TIGHTEN_UNITS = float(os.getenv("WNBA_PASSED_PLAY_TIGHTEN_UNITS", "-2.0"))

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

# V1.9 free live-context layer. This uses ESPN box score + play state only;
# no paid live lineup provider required.
ENABLE_FREE_LIVE_CONTEXT = os.getenv("WNBA_ENABLE_FREE_LIVE_CONTEXT", "true").lower() == "true"
SHOW_LIVE_CONTEXT_IN_ALERTS = os.getenv("WNBA_SHOW_LIVE_CONTEXT_IN_ALERTS", "true").lower() == "true"
STARTER_SIT_BLOWOUT_MARGIN = int(os.getenv("WNBA_STARTER_SIT_BLOWOUT_MARGIN", "18"))
STARTER_SIT_MINUTES_LEFT = float(os.getenv("WNBA_STARTER_SIT_MINUTES_LEFT", "7.0"))
PLAYER_FOUL_TROUBLE_LEVEL = int(os.getenv("WNBA_PLAYER_FOUL_TROUBLE_LEVEL", "4"))
PLAYER_TURNOVER_WARNING_LEVEL = int(os.getenv("WNBA_PLAYER_TURNOVER_WARNING_LEVEL", "4"))
NEAR_MISS_MIN_LEARNING_SCORE = float(os.getenv("WNBA_NEAR_MISS_MIN_LEARNING_SCORE", "48"))

# V2.0 professional decision controls. These make free live context affect paid bets,
# instead of only appearing in the alert text.
ENABLE_LIVE_CONTEXT_GATES = os.getenv("WNBA_ENABLE_LIVE_CONTEXT_GATES", "true").lower() == "true"
BLOCK_OVER_ON_HIGH_STARTER_SIT_RISK = os.getenv("WNBA_BLOCK_OVER_ON_HIGH_STARTER_SIT_RISK", "true").lower() == "true"
BLOCK_FAVORITE_ON_HIGH_STARTER_SIT_RISK = os.getenv("WNBA_BLOCK_FAVORITE_ON_HIGH_STARTER_SIT_RISK", "true").lower() == "true"
FAVORITE_PLAYER_FOUL_BLOCK = os.getenv("WNBA_FAVORITE_PLAYER_FOUL_BLOCK", "true").lower() == "true"
LIVE_CONTEXT_HIGH_RISK_CONF_PENALTY = int(os.getenv("WNBA_LIVE_CONTEXT_HIGH_RISK_CONF_PENALTY", "15"))
LIVE_CONTEXT_HIGH_RISK_VALUE_PENALTY = int(os.getenv("WNBA_LIVE_CONTEXT_HIGH_RISK_VALUE_PENALTY", "10"))
LIVE_CONTEXT_HIGH_RISK_RISK_BUMP = int(os.getenv("WNBA_LIVE_CONTEXT_HIGH_RISK_RISK_BUMP", "20"))
LIVE_CONTEXT_MED_RISK_CONF_PENALTY = int(os.getenv("WNBA_LIVE_CONTEXT_MED_RISK_CONF_PENALTY", "7"))
LIVE_CONTEXT_MED_RISK_RISK_BUMP = int(os.getenv("WNBA_LIVE_CONTEXT_MED_RISK_RISK_BUMP", "9"))

# Anchor discipline: these are the first line snapshots captured before or near tipoff.
# They are never overwritten during the game.
ANCHOR_CAPTURE_WINDOW_MINUTES = int(os.getenv("WNBA_ANCHOR_CAPTURE_WINDOW_MINUTES", "60"))

# Multi-market alert discipline. Allows the bot to evaluate best total, ML, and spread
# separately, while still avoiding SMS spam.
ENABLE_MULTI_MARKET_ALERTS = os.getenv("WNBA_ENABLE_MULTI_MARKET_ALERTS", "true").lower() == "true"
MAX_ALERTS_PER_GAME_CHECK = int(os.getenv("WNBA_MAX_ALERTS_PER_GAME_CHECK", "2"))
REQUIRE_A_PLUS_FOR_SECOND_ALERT = os.getenv("WNBA_REQUIRE_A_PLUS_FOR_SECOND_ALERT", "false").lower() == "true"


# V3.0 professional unit-control and execution layer.
# These improve real-money discipline without killing alert volume.
ENABLE_BETMGM_RECHECK_BEFORE_SMS = os.getenv("WNBA_ENABLE_BETMGM_RECHECK_BEFORE_SMS", "true").lower() == "true"
RECHECK_MAX_TOTAL_LINE_MOVE = float(os.getenv("WNBA_RECHECK_MAX_TOTAL_LINE_MOVE", "0.5"))
RECHECK_MAX_SPREAD_LINE_MOVE = float(os.getenv("WNBA_RECHECK_MAX_SPREAD_LINE_MOVE", "0.5"))
RECHECK_MAX_ML_IMPLIED_MOVE_PCT = float(os.getenv("WNBA_RECHECK_MAX_ML_IMPLIED_MOVE_PCT", "2.5"))

ENABLE_CLOSING_WINDOW_PROTECTION = os.getenv("WNBA_ENABLE_CLOSING_WINDOW_PROTECTION", "true").lower() == "true"
CLOSING_WINDOW_MINUTES_LEFT = float(os.getenv("WNBA_CLOSING_WINDOW_MINUTES_LEFT", "5.0"))
CLOSING_WINDOW_TOTAL_RISK_BUMP = int(os.getenv("WNBA_CLOSING_WINDOW_TOTAL_RISK_BUMP", "10"))
CLOSING_WINDOW_FAVORITE_RISK_BUMP = int(os.getenv("WNBA_CLOSING_WINDOW_FAVORITE_RISK_BUMP", "8"))
CLOSING_WINDOW_FOUL_OVER_FTR = float(os.getenv("WNBA_CLOSING_WINDOW_FOUL_OVER_FTR", "0.34"))
CLOSING_WINDOW_FOUL_OVER_MAX_DIFF = int(os.getenv("WNBA_CLOSING_WINDOW_FOUL_OVER_MAX_DIFF", "8"))

ENABLE_SMART_ML_STAKING = os.getenv("WNBA_ENABLE_SMART_ML_STAKING", "true").lower() == "true"
ML_UNIT_MAX = float(os.getenv("WNBA_ML_UNIT_MAX", "0.75"))
ML_UNIT_MIN = float(os.getenv("WNBA_ML_UNIT_MIN", "0.25"))
ML_EXPENSIVE_CUTOFF = int(os.getenv("WNBA_ML_EXPENSIVE_CUTOFF", "-140"))

ENABLE_EXPOSURE_CAPS = os.getenv("WNBA_ENABLE_EXPOSURE_CAPS", "true").lower() == "true"
MAX_GAME_EXPOSURE_UNITS = float(os.getenv("WNBA_MAX_GAME_EXPOSURE_UNITS", "1.0"))
MAX_DAILY_EXPOSURE_UNITS = float(os.getenv("WNBA_MAX_DAILY_EXPOSURE_UNITS", "1.5"))
MAX_MARKET_EXPOSURE_UNITS = float(os.getenv("WNBA_MAX_MARKET_EXPOSURE_UNITS", "1.0"))
MAX_ML_EXPOSURE_UNITS = float(os.getenv("WNBA_MAX_ML_EXPOSURE_UNITS", "0.5"))

TEAM_RATINGS_FILE = os.getenv("WNBA_TEAM_RATINGS_FILE", "wnba_team_power_ratings.json")
LINEUP_CONTEXT_FILE = os.getenv("WNBA_LINEUP_CONTEXT_FILE", "wnba_live_lineup_context.json")
LINEUP_CONTEXT_JSON = os.getenv("WNBA_LINEUP_CONTEXT_JSON", "").strip()
ENABLE_EXTERNAL_LINEUP_CONTEXT = os.getenv("WNBA_ENABLE_EXTERNAL_LINEUP_CONTEXT", "true").lower() == "true"

ENABLE_EXPECTED_CLOSE_TRACKING = os.getenv("WNBA_ENABLE_EXPECTED_CLOSE_TRACKING", "true").lower() == "true"
EXPECTED_CLOSE_MINUTES_HORIZON = float(os.getenv("WNBA_EXPECTED_CLOSE_MINUTES_HORIZON", "8.0"))

# V3.1 execution/learning refinements.
# These keep the net open, but make the live execution closer to how a real bettor reviews alerts.
ODDS_CACHE_SECONDS = int(os.getenv("WNBA_ODDS_CACHE_SECONDS", "25"))
REQUIRE_PLAYABLE_BOOK_FOR_PAID_ALERT = os.getenv("WNBA_REQUIRE_PLAYABLE_BOOK_FOR_PAID_ALERT", "true").lower() == "true"
POST_ALERT_MOVE_CHECK_MINUTES = float(os.getenv("WNBA_POST_ALERT_MOVE_CHECK_MINUTES", "5.0"))
POST_ALERT_MOVE_TOLERANCE_TOTAL = float(os.getenv("WNBA_POST_ALERT_MOVE_TOLERANCE_TOTAL", "0.5"))
POST_ALERT_MOVE_TOLERANCE_SPREAD = float(os.getenv("WNBA_POST_ALERT_MOVE_TOLERANCE_SPREAD", "0.5"))
POST_ALERT_MOVE_TOLERANCE_ML_PCT = float(os.getenv("WNBA_POST_ALERT_MOVE_TOLERANCE_ML_PCT", "1.5"))
ENABLE_CORRELATED_MARKET_EXPOSURE_CONTROL = os.getenv("WNBA_ENABLE_CORRELATED_MARKET_EXPOSURE_CONTROL", "true").lower() == "true"
CORRELATED_SECOND_ALERT_MIN_SCORE = float(os.getenv("WNBA_CORRELATED_SECOND_ALERT_MIN_SCORE", "70"))
CORRELATED_SECOND_ALERT_REQUIRE_A_PLUS = os.getenv("WNBA_CORRELATED_SECOND_ALERT_REQUIRE_A_PLUS", "false").lower() == "true"
ENABLE_MISSING_TEAM_WARNINGS = os.getenv("WNBA_ENABLE_MISSING_TEAM_WARNINGS", "true").lower() == "true"

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

# V1.8 professional market-predictor controls
# Prevents the bot from firing both OVER and UNDER on the same game unless a true reversal is extreme.
TOTAL_POSITION_LOCK_MODE = os.getenv("WNBA_TOTAL_POSITION_LOCK_MODE", "same_game").lower()
TRUE_REVERSAL_MIN_CONFIDENCE = int(os.getenv("WNBA_TRUE_REVERSAL_MIN_CONFIDENCE", "90"))
TRUE_REVERSAL_MIN_EDGE = float(os.getenv("WNBA_TRUE_REVERSAL_MIN_EDGE", "14.0"))
TRUE_REVERSAL_MIN_MARKET_SCORE = int(os.getenv("WNBA_TRUE_REVERSAL_MIN_MARKET_SCORE", "60"))
TRUE_REVERSAL_MIN_LINE_MOVE = float(os.getenv("WNBA_TRUE_REVERSAL_MIN_LINE_MOVE", "10.0"))

# Keep learning wide, but stop writing 1,000 low-quality near-miss rows every night.
MIN_NEAR_MISS_LOG_SCORE = float(os.getenv("WNBA_MIN_NEAR_MISS_LOG_SCORE", "54"))
LOG_BLOCKED_POSITION_LOCKS = os.getenv("WNBA_LOG_BLOCKED_POSITION_LOCKS", "true").lower() == "true"

# Favorite moneyline buyback: pregame favorite becomes playable live, usually -140 to +100.
ENABLE_FAVORITE_MONEYLINE_BUYBACK = os.getenv("WNBA_ENABLE_FAVORITE_MONEYLINE_BUYBACK", "true").lower() == "true"
FAVORITE_ML_MIN_PRICE = int(os.getenv("WNBA_FAVORITE_ML_MIN_PRICE", "-160"))
FAVORITE_ML_MAX_PRICE = int(os.getenv("WNBA_FAVORITE_ML_MAX_PRICE", "125"))
FAVORITE_ML_MIN_CONFIDENCE = int(os.getenv("WNBA_FAVORITE_ML_MIN_CONFIDENCE", "58"))
FAVORITE_ML_MIN_VALUE = int(os.getenv("WNBA_FAVORITE_ML_MIN_VALUE", "52"))
FAVORITE_ML_MAX_RISK = int(os.getenv("WNBA_FAVORITE_ML_MAX_RISK", "76"))

# Favorite spread drop: pregame favorite -2.5 or stronger becomes live -4.5-ish or better.
ENABLE_FAVORITE_SPREAD_DROP = os.getenv("WNBA_ENABLE_FAVORITE_SPREAD_DROP", "true").lower() == "true"
PREGAME_FAVORITE_MIN_SPREAD = float(os.getenv("WNBA_PREGAME_FAVORITE_MIN_SPREAD", "-2.5"))
FAVORITE_LIVE_SPREAD_TARGET = float(os.getenv("WNBA_FAVORITE_LIVE_SPREAD_TARGET", "-4.5"))
FAVORITE_LIVE_SPREAD_MIN = float(os.getenv("WNBA_FAVORITE_LIVE_SPREAD_MIN", "-6.5"))
FAVORITE_LIVE_SPREAD_MAX = float(os.getenv("WNBA_FAVORITE_LIVE_SPREAD_MAX", "6.5"))
FAVORITE_SPREAD_DROP_MIN_SWING = float(os.getenv("WNBA_FAVORITE_SPREAD_DROP_MIN_SWING", "2.0"))
FAVORITE_SPREAD_DROP_MIN_CONFIDENCE = int(os.getenv("WNBA_FAVORITE_SPREAD_DROP_MIN_CONFIDENCE", "58"))
FAVORITE_SPREAD_DROP_MIN_VALUE = int(os.getenv("WNBA_FAVORITE_SPREAD_DROP_MIN_VALUE", "52"))
FAVORITE_SPREAD_DROP_MAX_RISK = int(os.getenv("WNBA_FAVORITE_SPREAD_DROP_MAX_RISK", "76"))
FAVORITE_MARKET_SOFT_STRIKE = os.getenv("WNBA_FAVORITE_MARKET_SOFT_STRIKE", "true").lower() == "true"
FAVORITE_SOFT_MIN_CONFIDENCE = int(os.getenv("WNBA_FAVORITE_SOFT_MIN_CONFIDENCE", "52"))
FAVORITE_SOFT_MIN_VALUE = int(os.getenv("WNBA_FAVORITE_SOFT_MIN_VALUE", "48"))
FAVORITE_SOFT_MAX_RISK = int(os.getenv("WNBA_FAVORITE_SOFT_MAX_RISK", "82"))
FAVORITE_EARLY_DOWN_MIN_MARGIN = int(os.getenv("WNBA_FAVORITE_EARLY_DOWN_MIN_MARGIN", "5"))
FAVORITE_DOWN_BUYBACK_MAX_MARGIN = int(os.getenv("WNBA_FAVORITE_DOWN_BUYBACK_MAX_MARGIN", "16"))
FAVORITE_MARKET_OVERREACTION_MIN = float(os.getenv("WNBA_FAVORITE_MARKET_OVERREACTION_MIN", "4.0"))
FAVORITE_DOMINANCE_BONUS_THRESHOLD = int(os.getenv("WNBA_FAVORITE_DOMINANCE_BONUS_THRESHOLD", "58"))

# V2.9 cleanup: legacy +4.5 favorite-buyback engine removed. Use MONEYLINE and FAVORITE_SPREAD_DROP engines only.

# V2.8 expected-live-line engine. This creates an internal fair live spread/ML for the
# pregame favorite and compares BetMGM to that fair number. It is a bonus/penalty, not
# a hard blocker, so we keep sample size while improving intelligence.
ENABLE_EXPECTED_LIVE_LINE_ENGINE = os.getenv("WNBA_ENABLE_EXPECTED_LIVE_LINE_ENGINE", "true").lower() == "true"
EXPECTED_LINE_EDGE_BONUS_THRESHOLD = float(os.getenv("WNBA_EXPECTED_LINE_EDGE_BONUS_THRESHOLD", "2.0"))
EXPECTED_LINE_STRONG_EDGE = float(os.getenv("WNBA_EXPECTED_LINE_STRONG_EDGE", "4.0"))
EXPECTED_ML_EDGE_BONUS_THRESHOLD = float(os.getenv("WNBA_EXPECTED_ML_EDGE_BONUS_THRESHOLD", "3.0"))
EXPECTED_ML_STRONG_EDGE = float(os.getenv("WNBA_EXPECTED_ML_STRONG_EDGE", "6.0"))

# V2.8 conflict control: ML and spread can both be good, but one game check should not
# spam two favorite alerts unless both are strong and aligned.
ENABLE_FAVORITE_MARKET_CONFLICT_CONTROL = os.getenv("WNBA_ENABLE_FAVORITE_MARKET_CONFLICT_CONTROL", "true").lower() == "true"
ALLOW_ALIGNED_FAVORITE_ML_AND_SPREAD = os.getenv("WNBA_ALLOW_ALIGNED_FAVORITE_ML_AND_SPREAD", "false").lower() == "true"

# Total market gates
MIN_TOTAL_EDGE_POINTS = float(os.getenv("WNBA_MIN_TOTAL_EDGE_POINTS", "3.0"))
MIN_TOTAL_CONFIDENCE = int(os.getenv("WNBA_MIN_TOTAL_CONFIDENCE", "60"))
MIN_TOTAL_VALUE_SCORE = int(os.getenv("WNBA_MIN_TOTAL_VALUE_SCORE", "56"))
MAX_TOTAL_RISK_SCORE = int(os.getenv("WNBA_MAX_TOTAL_RISK_SCORE", "72"))

# V2.4 separate total engines. OVER and UNDER are intentionally scored differently.
# Opening total is a small reference only; live stats, BetMGM price, and market context drive alerts.
OPENING_TOTAL_REFERENCE_WEIGHT = float(os.getenv("WNBA_OPENING_TOTAL_REFERENCE_WEIGHT", "0.12"))
MIN_OVER_EDGE_POINTS = float(os.getenv("WNBA_MIN_OVER_EDGE_POINTS", "3.0"))
MIN_UNDER_EDGE_POINTS = float(os.getenv("WNBA_MIN_UNDER_EDGE_POINTS", "3.5"))
MIN_OVER_CONFIDENCE = int(os.getenv("WNBA_MIN_OVER_CONFIDENCE", "60"))
MIN_UNDER_CONFIDENCE = int(os.getenv("WNBA_MIN_UNDER_CONFIDENCE", "62"))
MIN_OVER_VALUE_SCORE = int(os.getenv("WNBA_MIN_OVER_VALUE_SCORE", "56"))
MIN_UNDER_VALUE_SCORE = int(os.getenv("WNBA_MIN_UNDER_VALUE_SCORE", "58"))
MAX_OVER_RISK_SCORE = int(os.getenv("WNBA_MAX_OVER_RISK_SCORE", "72"))
MAX_UNDER_RISK_SCORE = int(os.getenv("WNBA_MAX_UNDER_RISK_SCORE", "68"))
MIN_TOTAL_MINUTES_ELAPSED = float(os.getenv("WNBA_MIN_TOTAL_MINUTES_ELAPSED", "2.0"))
MIN_UNDER_LIVE_SAMPLE_MINUTES = float(os.getenv("WNBA_MIN_UNDER_LIVE_SAMPLE_MINUTES", "5.0"))
UNDER_REQUIRE_TWO_SUPPRESSION_SIGNALS = os.getenv("WNBA_UNDER_REQUIRE_TWO_SUPPRESSION_SIGNALS", "true").lower() == "true"
OVER_REQUIRE_REAL_SCORING_SUPPORT = os.getenv("WNBA_OVER_REQUIRE_REAL_SCORING_SUPPORT", "true").lower() == "true"

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
MAX_TOTAL_PRICE = int(os.getenv("WNBA_MAX_TOTAL_PRICE", "-125"))
ELITE_TOTAL_MAX_PRICE = int(os.getenv("WNBA_ELITE_TOTAL_MAX_PRICE", "-140"))
ELITE_TOTAL_MIN_CONFIDENCE = int(os.getenv("WNBA_ELITE_TOTAL_MIN_CONFIDENCE", "92"))
ELITE_TOTAL_ALLOWED_MARKET_STATES = {"OFF_MARKET_EDGE", "STRONG_OFF_MARKET_EDGE"}
MAX_TOTAL_PAID_EDGE_POINTS = float(os.getenv("WNBA_MAX_TOTAL_PAID_EDGE_POINTS", "15.0"))
MIN_Q1_UNDER_MINUTES_ELAPSED = float(os.getenv("WNBA_MIN_Q1_UNDER_MINUTES_ELAPSED", "4.0"))
HARD_TOTAL_LOCK_NO_REVERSALS = os.getenv("WNBA_HARD_TOTAL_LOCK_NO_REVERSALS", "true").lower() == "true"
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

def write_csv_rows(path, fieldnames, rows):
    try:
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
    except Exception as e:
        print(f"CSV WRITE ERROR {path}:", repr(e))


# =============================================================================
# V3.2 Google Sheets / master decision database
# =============================================================================
def tracking_webhook_enabled():
    return bool(WNBA_ENABLE_TRACKING_WEBHOOK and WNBA_TRACKING_WEBHOOK_URL.startswith(("http://", "https://")))

def post_tracking_event(event_type, payload):
    """Optional Google Sheets Apps Script / Zapier / Make mirror. Local CSV always remains primary."""
    if not tracking_webhook_enabled():
        return False
    body = {
        "event_type": event_type,
        "sent_at": now_local().isoformat(),
        "source": "SHIFT_WNBA_V3_4_DECISION_LEARNING_UPSERT",
        "payload": payload,
    }
    if WNBA_ENABLE_SHEETS_UPSERT_HINTS and isinstance(payload, dict):
        # Apps Script can use these hints to route and update rows instead of only appending.
        if event_type in {"wnba_decision", "wnba_decision_market_update", "wnba_decision_result"}:
            body["sheet_tab"] = "Decision_Database"
            body["upsert_key"] = WNBA_DECISION_UPSERT_KEY
            body["upsert_value"] = payload.get(WNBA_DECISION_UPSERT_KEY) or payload.get("decision_id")
        elif event_type == "wnba_alert":
            body["sheet_tab"] = "Alerts"
            body["upsert_key"] = "decision_id"
            body["upsert_value"] = payload.get("decision_id")
        elif event_type == "wnba_profile_summary":
            body["sheet_tab"] = "Daily_Profile_Summary"
        elif event_type == "wnba_feature_learning":
            body["sheet_tab"] = "Feature_Learning"
    headers = {"Content-Type": "application/json"}
    if WNBA_TRACKING_WEBHOOK_SECRET:
        headers["X-SHIFT-SECRET"] = WNBA_TRACKING_WEBHOOK_SECRET
    try:
        r = requests.post(WNBA_TRACKING_WEBHOOK_URL, json=body, headers=headers, timeout=10)
        if 200 <= r.status_code < 300:
            print(f"TRACKING WEBHOOK SENT | {event_type}")
            return True
        print(f"TRACKING WEBHOOK ERROR | {event_type} | {r.status_code} | {r.text[:180]}")
    except Exception as e:
        print(f"TRACKING WEBHOOK EXCEPTION | {event_type}:", repr(e))
    return False

def wnba_decision_log_fieldnames():
    return [
        "decision_id", "opportunity_id", "snapshot_id", "timestamp", "date", "event_id", "game", "action", "decision_type", "reject_reason", "pass_reason_category",
        "market_type", "engine", "side", "team_side", "team", "line", "price", "book",
        "scenario", "quarter_profile", "period", "clock", "minutes_remaining", "score", "score_margin_home",
        "opening_total", "live_total", "projected_total", "edge", "confidence", "value_score", "risk_score",
        "market_misprice_score", "future_state_score", "predicted_market_move", "market_discrepancy_status",
        "market_discrepancy_score", "market_advantage_points", "alert_tier", "unit_size", "paid_alert",
        "learning_score", "sanity_tag", "profile_rule", "alert_timing_quality", "alert_timing_note",
        "pace_projected_possessions", "pace_possessions_left", "team_ppp", "expected_remaining_ppp",
        "efg", "ftr", "three_rate", "three_pct", "turnovers", "off_reb", "rebounds", "fouls",
        "fast_break", "points_in_paint", "possession_pressure_index", "scoring_accel", "run_profile",
        "run_unsustainable_score", "run_sustainable_score", "favorite_dominance_score", "run_regression_score",
        "market_overreaction_score", "expected_live_spread", "expected_live_ml", "expected_line_edge",
        "favorite_margin_at_alert", "spread_swing", "star_status", "starter_sit_risk", "data_quality",
        "closing_line", "closing_price", "clv", "post_5m_line", "post_5m_move", "final_score", "final_total",
        "favorite_final_margin", "favorite_retook_control", "cover_margin", "result", "units", "would_have_units",
        "actual_vs_would_delta", "missed_units", "decision_outcome_bucket", "graded_at", "result_update_key",
    ]

def wnba_decision_action_from_opp(opp, approved=False, reason=""):
    if not opp:
        return "NO_OPPORTUNITY"
    if approved:
        tier = str(opp.get("alert_tier", "")).upper()
        if tier == "SMALL_LEAN":
            return "TEST_UNIT"
        return "BET_NOW"
    action = str(opp.get("action", "")).upper()
    reason_u = str(reason or opp.get("block_reason", "")).upper()
    if action == "STRIKE":
        return "NO_BET"
    if "LOG" in reason_u or "LEARNING" in reason_u or "RESEARCH" in reason_u or "SMALL" in reason_u:
        return "RESEARCH_ONLY"
    return "NO_BET"

def canonical_line_bucket(value):
    try:
        v = float(value)
        return str(round(v * 2) / 2.0)
    except Exception:
        return ""

def wnba_opportunity_id(info, opp):
    """Stable play identity: does not include clock, score, or reject reason."""
    side = str((opp or {}).get("side") or "NONE").upper()
    team_side = str((opp or {}).get("team_side") or "")
    market = str((opp or {}).get("market_type") or "NONE")
    scenario = str((opp or {}).get("scenario") or "UNKNOWN")
    line_bucket = canonical_line_bucket((opp or {}).get("line"))
    return "|".join([today(), str((info or {}).get("event_id") or ""), market, side, team_side, scenario, line_bucket])

def wnba_snapshot_id(info, opp, action):
    bucket = int(time.time() // max(1, WNBA_SNAPSHOT_BUCKET_SECONDS))
    return "|".join([wnba_opportunity_id(info, opp), str(action or ""), str(bucket)])

def wnba_decision_id(info, opp, action, reason=""):
    # Decision id is stable for this logged snapshot. opportunity_id groups all snapshots of the same betting idea.
    return wnba_snapshot_id(info, opp, action)

def pass_reason_category(reason="", decision_type=""):
    text = f"{reason or ''} {decision_type or ''}".upper()
    if "PRICE" in text or "EXPENSIVE" in text or "RECHECK" in text:
        return "PRICE_PASS"
    if "RISK" in text or "FOUL" in text or "STARTER" in text or "BLOWOUT" in text:
        return "RISK_PASS"
    if "DATA" in text or "NO_MARKET" in text or "MISSING" in text or "CONSENSUS" in text:
        return "DATA_QUALITY_PASS"
    if "LOCK" in text or "ONE STRIKE" in text or "EXPOSURE" in text or "COOLDOWN" in text:
        return "EXPOSURE_PASS"
    if "OPPOSITE" in text or "LOG" in text or "LEARNING" in text or "RESEARCH" in text:
        return "RESEARCH_PASS"
    if "GATE MISS" in text or "PREDICTOR" in text or "SAMPLE" in text:
        return "MODEL_THRESHOLD_PASS"
    return "OTHER_PASS"

def should_log_wnba_decision(sg, decision_id, action):
    if not WNBA_ENABLE_DECISION_LOG or not decision_id:
        return False
    cache = sg.setdefault("decision_log_cache", {}) if isinstance(sg, dict) else {}
    last = safe_float(cache.get(decision_id), 0)
    now_ts = time.time()
    cooldown = WNBA_DECISION_LOG_ACCEPT_COOLDOWN_SECONDS if action in {"BET_NOW", "TEST_UNIT"} else WNBA_DECISION_LOG_REJECT_COOLDOWN_SECONDS
    if last and (now_ts - last) < cooldown:
        return False
    cache[decision_id] = now_ts
    return True

def data_quality_label(opp):
    md = opp.get("market_discrepancy") or {}
    scores = opp.get("scores") or {}
    books = safe_int(md.get("books") or scores.get("books") or scores.get("consensus_books"), 0)
    has_live = bool(scores)
    if books >= 3 and has_live:
        return "HIGH"
    if books >= 1 and has_live:
        return "MEDIUM"
    return "LOW"

def wnba_feature_extract(info, opp):
    scores = opp.get("scores") or {}
    projection = scores.get("projection") or {}
    pace = projection.get("pace") or scores.get("pace") or {}
    eff = projection.get("eff") or scores.get("eff") or {}
    predictor = opp.get("predictor") or {}
    future = predictor.get("future_state") or {}
    run_sus = future.get("run_sustainability") or predictor.get("run_sustainability") or {}
    accel = future.get("acceleration") or {}
    fav_scores = scores if opp.get("market_type") in {"MONEYLINE", "FAVORITE_SPREAD_DROP", "SPREAD"} else {}
    fav_ctx = fav_scores.get("favorite_context") or {}
    dominance = fav_ctx.get("dominance") or {}
    regression = fav_ctx.get("run_regression") or {}
    overreaction = fav_scores.get("market_overreaction") or {}
    expected_line = fav_scores.get("expected_line") or {}
    live_context = opp.get("live_context") or scores.get("live_context") or {}
    return {
        "pace_projected_possessions": pace.get("projected_game_possessions"),
        "pace_possessions_left": pace.get("possessions_left"),
        "team_ppp": projection.get("ppp"),
        "expected_remaining_ppp": projection.get("expected_remaining_ppp"),
        "efg": eff.get("efg"), "ftr": eff.get("ftr"), "three_rate": eff.get("three_rate"),
        "three_pct": eff.get("three_pct"), "turnovers": eff.get("turnovers"), "off_reb": eff.get("off_reb"),
        "rebounds": eff.get("rebounds"), "fouls": eff.get("fouls"), "fast_break": eff.get("fast_break"),
        "points_in_paint": eff.get("points_in_paint"),
        "possession_pressure_index": future.get("possession_pressure_index"),
        "scoring_accel": accel.get("accel"),
        "run_profile": run_sus.get("profile"),
        "run_unsustainable_score": run_sus.get("unsustainable_score"),
        "run_sustainable_score": run_sus.get("sustainable_score"),
        "favorite_dominance_score": fav_scores.get("favorite_dominance_score") or fav_scores.get("dominance_score") or dominance.get("dominance_score"),
        "run_regression_score": fav_scores.get("run_regression_score") or regression.get("run_regression_score"),
        "market_overreaction_score": fav_scores.get("market_overreaction_score") or overreaction.get("market_overreaction_score"),
        "expected_live_spread": fav_scores.get("expected_live_spread") or expected_line.get("expected_live_spread"),
        "expected_live_ml": fav_scores.get("expected_live_ml") or expected_line.get("expected_ml_price"),
        "expected_line_edge": fav_scores.get("expected_line_edge") or expected_line.get("expected_spread_edge") or expected_line.get("expected_ml_edge_pct"),
        "favorite_margin_at_alert": fav_scores.get("favorite_margin") or fav_scores.get("favorite_margin_at_alert") or expected_line.get("favorite_margin_now"),
        "spread_swing": fav_scores.get("spread_swing"),
        "star_status": fav_scores.get("star_status"),
        "starter_sit_risk": live_context.get("starter_sit_risk") or fav_scores.get("starter_sit_risk"),
        "data_quality": data_quality_label(opp),
    }

def wnba_decision_row_from_opp(info, label, opp, action, decision_type="", reject_reason=""):
    info = info or {}
    opp = opp or {}
    md = opp.get("market_discrepancy") or {}
    scores = opp.get("scores") or {}
    features = wnba_feature_extract(info, opp)
    opportunity_id = wnba_opportunity_id(info, opp)
    snapshot_id = wnba_snapshot_id(info, opp, action)
    row = {
        "decision_id": snapshot_id,
        "opportunity_id": opportunity_id,
        "snapshot_id": snapshot_id,
        "timestamp": now_local().isoformat(), "date": today(), "event_id": info.get("event_id"), "game": label,
        "action": action, "decision_type": decision_type, "reject_reason": reject_reason, "pass_reason_category": pass_reason_category(reject_reason, decision_type),
        "market_type": opp.get("market_type"), "engine": f"{opp.get('market_type')}|{opp.get('scenario')}",
        "side": opp.get("side"), "team_side": opp.get("team_side"), "team": opp.get("side") if opp.get("market_type") != "TOTAL" else "",
        "line": opp.get("line"), "price": opp.get("price"), "book": opp.get("book"),
        "scenario": opp.get("scenario"), "quarter_profile": opp.get("quarter_profile"),
        "period": info.get("period"), "clock": info.get("clock"), "minutes_remaining": info.get("minutes_remaining"),
        "score": f"{info.get('away_score')}-{info.get('home_score')}", "score_margin_home": info.get("score_diff_home"),
        "opening_total": scores.get("opening_total"), "live_total": scores.get("live_total") or (opp.get("line") if opp.get("market_type") == "TOTAL" else ""),
        "projected_total": opp.get("projected_total"), "edge": opp.get("edge"),
        "confidence": opp.get("confidence"), "value_score": opp.get("value_score"), "risk_score": opp.get("risk_score"),
        "market_misprice_score": opp.get("market_misprice_score"), "future_state_score": opp.get("future_state_score"),
        "predicted_market_move": opp.get("predicted_line_move") if opp.get("market_type") == "TOTAL" else opp.get("predicted_spread_contract"),
        "market_discrepancy_status": opp.get("market_discrepancy_status"), "market_discrepancy_score": opp.get("market_discrepancy_score"),
        "market_advantage_points": md.get("advantage_points"),
        "alert_tier": opp.get("alert_tier"), "unit_size": opp.get("unit_size"), "paid_alert": opp.get("paid_alert"),
        "learning_score": opp.get("learning_score"), "sanity_tag": opp.get("sanity_tag"), "profile_rule": opp.get("profile_rule"),
        "alert_timing_quality": opp.get("alert_timing_quality"), "alert_timing_note": opp.get("alert_timing_note"),
        "closing_line": "", "closing_price": "", "clv": "", "post_5m_line": "", "post_5m_move": "",
        "final_score": "", "final_total": "", "favorite_final_margin": "", "favorite_retook_control": "", "cover_margin": "",
        "result": "PENDING", "units": "", "would_have_units": "", "actual_vs_would_delta": "",
        "missed_units": "", "decision_outcome_bucket": "", "graded_at": "", "result_update_key": snapshot_id,
    }
    row.update(features)
    return row

def log_wnba_decision(sg, info, label, opp, action=None, decision_type="", reject_reason=""):
    if not WNBA_ENABLE_DECISION_LOG or not opp:
        return
    action = action or wnba_decision_action_from_opp(opp, approved=False, reason=reject_reason)
    if action == "NO_BET" and not WNBA_ENABLE_DECISION_LOG_NO_BETS:
        return
    if action == "RESEARCH_ONLY" and not WNBA_ENABLE_DECISION_LOG_RESEARCH:
        return
    row = wnba_decision_row_from_opp(info, label, opp, action, decision_type, reject_reason)
    if not should_log_wnba_decision(sg if isinstance(sg, dict) else {}, row.get("decision_id"), action):
        return
    append_csv(WNBA_DECISION_LOG_FILE, row, wnba_decision_log_fieldnames())
    post_tracking_event("wnba_decision", row)
    print(f"WNBA DECISION LOG | {action} | {label} | {opp.get('market_type')} {opp.get('side')} {opp.get('line')} | {reject_reason or decision_type}")

def grade_completed_wnba_decision_log(event_id, label, final_score):
    rows = read_csv_rows(WNBA_DECISION_LOG_FILE)
    if not rows:
        return
    try:
        away, home = [safe_int(x) for x in str(final_score).split("-")]
    except Exception:
        return
    final_total = away + home
    home_margin = home - away
    changed = False
    for r in rows:
        if str(r.get("event_id")) != str(event_id) or r.get("result") in {"WIN", "LOSS", "PUSH"}:
            continue
        market_type = r.get("market_type")
        side = str(r.get("side", "")).upper()
        team_side = r.get("team_side")
        line = safe_float(r.get("line"), None)
        result = "PUSH"
        favorite_final_margin = ""
        cover_margin = ""
        favorite_retook_control = ""
        if line is None:
            continue
        if market_type == "TOTAL":
            if side == "OVER":
                result = "WIN" if final_total > line else "LOSS" if final_total < line else "PUSH"
            elif side == "UNDER":
                result = "WIN" if final_total < line else "LOSS" if final_total > line else "PUSH"
        elif market_type in {"SPREAD", "FAVORITE_SPREAD_DROP"}:
            margin_for_side = home_margin if team_side == "home" else -home_margin
            favorite_final_margin = margin_for_side
            cover_margin = round(margin_for_side + line, 2)
            favorite_retook_control = "YES" if margin_for_side > 0 else "NO"
            result = "WIN" if cover_margin > 0 else "LOSS" if cover_margin < 0 else "PUSH"
        elif market_type == "MONEYLINE":
            margin_for_side = home_margin if team_side == "home" else -home_margin
            favorite_final_margin = margin_for_side
            favorite_retook_control = "YES" if margin_for_side > 0 else "NO"
            result = "WIN" if margin_for_side > 0 else "LOSS"
        else:
            continue
        r["final_score"] = final_score
        r["final_total"] = final_total
        r["favorite_final_margin"] = favorite_final_margin
        r["favorite_retook_control"] = favorite_retook_control
        r["cover_margin"] = cover_margin
        r["result"] = result
        actual_units, would_have_units, delta, missed_units, outcome_bucket = calculate_decision_outcome_units(
            r.get("action"), result, r.get("price"), r.get("unit_size", UNIT_B), row=r
        )
        r["units"] = actual_units
        r["would_have_units"] = would_have_units
        r["actual_vs_would_delta"] = delta
        r["missed_units"] = missed_units
        r["decision_outcome_bucket"] = outcome_bucket
        r["graded_at"] = now_local().isoformat()
        changed = True
        post_tracking_event("wnba_decision_result", {k: r.get(k, "") for k in wnba_decision_log_fieldnames()})
    if changed:
        write_csv_rows(WNBA_DECISION_LOG_FILE, wnba_decision_log_fieldnames(), rows)
        build_wnba_adaptive_config_from_decisions()
        print(f"WNBA DECISION LOG GRADED | {label} | Final {final_score}")

def build_wnba_adaptive_config_from_decisions():
    if not WNBA_ENABLE_ADAPTIVE_CONFIG:
        return {}
    all_rows = [r for r in read_csv_rows(WNBA_DECISION_LOG_FILE) if r.get("result") in {"WIN", "LOSS", "PUSH"}]
    if not all_rows:
        return {}
    buckets = {}
    for r in all_rows:
        key = f"{r.get('market_type')}|{r.get('scenario')}|{r.get('quarter_profile')}|{str(r.get('side','')).upper()}"
        rec = buckets.setdefault(key, {"accepted": [], "passed": []})
        if r.get("action") in {"BET_NOW", "TEST_UNIT"}:
            rec["accepted"].append(r)
        elif WNBA_ENABLE_PASSED_PLAY_ADAPTIVE_LEARNING and r.get("action") in {"NO_BET", "RESEARCH_ONLY"}:
            rec["passed"].append(r)
    config = {}
    for key, rec in buckets.items():
        accepted = rec["accepted"]
        passed = rec["passed"]
        accepted_sample = len(accepted)
        passed_sample = len(passed)
        wins = sum(1 for r in accepted if r.get("result") == "WIN")
        losses = sum(1 for r in accepted if r.get("result") == "LOSS")
        pushes = sum(1 for r in accepted if r.get("result") == "PUSH")
        units = round(sum(safe_float(r.get("units"), 0) for r in accepted), 2)
        risked = round(sum(safe_float(r.get("unit_size"), 0) or 1.0 for r in accepted), 2)
        roi = round(units / risked, 4) if risked else 0.0
        passed_units = round(sum(safe_float(r.get("would_have_units"), 0) for r in passed), 2)
        passed_wins = sum(1 for r in passed if r.get("result") == "WIN")
        passed_losses = sum(1 for r in passed if r.get("result") == "LOSS")
        clvs = [safe_float(r.get("clv"), None) for r in accepted if r.get("clv") not in (None, "")]
        clvs = [c for c in clvs if c is not None]
        avg_clv = round(sum(clvs) / len(clvs), 2) if clvs else 0.0

        status, adj = "OPEN_TEST", 0
        loosen_reason = ""
        if accepted_sample >= WNBA_MIN_ADAPTIVE_SAMPLE:
            if roi >= WNBA_ADAPTIVE_STRONG_ROI and avg_clv >= WNBA_ADAPTIVE_STRONG_CLV:
                status, adj = "PROVEN", 3
            elif roi <= WNBA_ADAPTIVE_WEAK_ROI or avg_clv <= WNBA_ADAPTIVE_WEAK_CLV:
                status, adj = "TIGHTEN", -4
            else:
                status, adj = "HOLD", 0
        if WNBA_ENABLE_PASSED_PLAY_ADAPTIVE_LEARNING and passed_sample >= WNBA_PASSED_PLAY_MIN_SAMPLE:
            if passed_units >= WNBA_PASSED_PLAY_LOOSEN_UNITS and status not in {"PROVEN"}:
                status = "LOOSEN_CANDIDATE"
                adj = max(adj, 2)
                loosen_reason = "passed plays profitable; review rejected threshold"
            elif passed_units <= WNBA_PASSED_PLAY_TIGHTEN_UNITS and status == "OPEN_TEST":
                status = "GOOD_PASS"
                adj = min(adj, -1)
                loosen_reason = "passed plays losing; rejection filter likely useful"
        config[key] = {
            "accepted_sample": accepted_sample, "passed_sample": passed_sample,
            "wins": wins, "losses": losses, "pushes": pushes, "units": units, "risked": risked, "roi": roi,
            "passed_wins": passed_wins, "passed_losses": passed_losses, "passed_would_units": passed_units,
            "avg_clv": avg_clv, "status": status, "confidence_adjustment": adj,
            "learning_note": loosen_reason, "updated_at": now_local().isoformat(),
        }
    save_json(WNBA_ADAPTIVE_CONFIG_FILE, config)
    post_tracking_event("wnba_adaptive_config", {"date": today(), "profiles": config})
    return config

def wnba_decision_report_lines(report_date=None):
    report_date = report_date or today()
    rows = [r for r in read_csv_rows(WNBA_DECISION_LOG_FILE) if r.get("date") == report_date]
    if not rows:
        return ["Decision Database: no rows logged yet."]
    lines = ["Decision Database / Google Sheets Mirror:"]
    for action in ["BET_NOW", "TEST_UNIT", "RESEARCH_ONLY", "NO_BET"]:
        bucket = [r for r in rows if r.get("action") == action and r.get("result") in {"WIN", "LOSS", "PUSH"}]
        pending = [r for r in rows if r.get("action") == action and r.get("result") not in {"WIN", "LOSS", "PUSH"}]
        if bucket:
            sm = summarize_rows(bucket)
            would_units = round(sum(safe_float(r.get("would_have_units"), 0) for r in bucket), 2)
            missed_units = round(sum(safe_float(r.get("missed_units"), 0) for r in bucket), 2)
            if action in {"BET_NOW", "TEST_UNIT"}:
                lines.append(f"• {action}: {sm['wins']}-{sm['losses']}-{sm['pushes']} | actual {sm['units']}u | pending {len(pending)}")
            else:
                lines.append(f"• {action}: {sm['wins']}-{sm['losses']}-{sm['pushes']} | would-have {would_units}u | missed/avoided {missed_units}u | pending {len(pending)}")
        elif pending:
            lines.append(f"• {action}: {len(pending)} pending")
    passed = [r for r in rows if r.get("action") in {"NO_BET", "RESEARCH_ONLY"} and r.get("result") in {"WIN", "LOSS", "PUSH"}]
    if passed:
        would_wins = sum(1 for r in passed if r.get("result") == "WIN")
        would_losses = sum(1 for r in passed if r.get("result") == "LOSS")
        would_units = round(sum(safe_float(r.get("would_have_units"), 0) for r in passed), 2)
        lines.append(f"• Passed-play audit: would-have {would_wins}-{would_losses} | {would_units}u theoretical; this is the loosen/tighten signal")
    return lines


def wnba_passed_play_learning_lines(report_date=None):
    """Show rejected/research profiles that would have helped or hurt if bet."""
    report_date = report_date or today()
    rows = [r for r in read_csv_rows(WNBA_DECISION_LOG_FILE)
            if r.get("date") == report_date
            and r.get("action") in {"NO_BET", "RESEARCH_ONLY"}
            and r.get("result") in {"WIN", "LOSS", "PUSH"}]
    if not rows:
        return ["Passed Play Learning: building sample."]
    buckets = {}
    for r in rows:
        key = f"{r.get('market_type')}|{r.get('scenario')}|{r.get('quarter_profile')}|{str(r.get('side','')).upper()}"
        buckets.setdefault(key, []).append(r)
    ranked = []
    for key, bucket in buckets.items():
        wins = sum(1 for r in bucket if r.get("result") == "WIN")
        losses = sum(1 for r in bucket if r.get("result") == "LOSS")
        pushes = sum(1 for r in bucket if r.get("result") == "PUSH")
        would_units = round(sum(safe_float(r.get("would_have_units"), 0) for r in bucket), 2)
        avg_clv = avg([r.get("clv") for r in bucket if r.get("clv") not in (None, "")], 0.0)
        ranked.append((would_units, key, wins, losses, pushes, len(bucket), avg_clv))
    lines = ["Passed Play Learning:"]
    for would_units, key, wins, losses, pushes, sample, avg_clv in sorted(ranked, reverse=True)[:6]:
        tag = "LOOSEN_CANDIDATE" if would_units > 0 else "GOOD_PASS" if would_units < 0 else "MONITOR"
        lines.append(f"• {key}: would-have {wins}-{losses}-{pushes} | {would_units}u | CLV {avg_clv} | n={sample} | {tag}")
    return lines

def wnba_feature_learning_lines(report_date=None):
    rows = [r for r in read_csv_rows(WNBA_DECISION_LOG_FILE) if r.get("action") in {"BET_NOW", "TEST_UNIT"} and r.get("result") in {"WIN", "LOSS", "PUSH"}]
    if not rows:
        return ["Feature Learning: building sample."]
    buckets = {}
    def add(label, r):
        buckets.setdefault(label, []).append(r)
    for r in rows:
        add(f"MARKET|{r.get('market_type')}", r)
        add(f"PROFILE|{r.get('market_type')}|{r.get('scenario')}", r)
        add(f"QUARTER|{r.get('quarter_profile')}", r)
        if safe_float(r.get("pace_projected_possessions"), 0) >= 82: add("PACE_82_PLUS", r)
        if safe_float(r.get("pace_projected_possessions"), 0) <= 74: add("PACE_74_MINUS", r)
        if safe_float(r.get("ftr"), 0) >= 0.32: add("FTR_032_PLUS", r)
        if safe_int(r.get("turnovers"), 0) >= 18: add("TURNOVERS_18_PLUS", r)
        if safe_int(r.get("off_reb"), 0) >= 12: add("OREB_12_PLUS", r)
        if safe_float(r.get("market_advantage_points"), 0) >= 1.0: add("BETMGM_OFF_MARKET_1_PLUS", r)
        if safe_float(r.get("favorite_dominance_score"), 0) >= 65: add("FAVORITE_DOMINANCE_65_PLUS", r)
        if safe_float(r.get("run_regression_score"), 0) >= 65: add("RUN_REGRESSION_65_PLUS", r)
    lines = ["Feature Learning:"]
    summary_rows = []
    for label, bucket in sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)[:18]:
        sm = summarize_rows(bucket)
        line = f"• {label}: {sm['wins']}-{sm['losses']}-{sm['pushes']} | {sm['units']}u | ROI {sm['roi']}% | n={len(bucket)}"
        lines.append(line)
        summary_rows.append({"updated_at": now_local().isoformat(), "bucket": label, "sample": len(bucket), "wins": sm['wins'], "losses": sm['losses'], "pushes": sm['pushes'], "units": sm['units'], "roi": sm['roi']})
    if summary_rows:
        append_csv(WNBA_FEATURE_LEARNING_FILE, summary_rows[0], list(summary_rows[0].keys())) if not os.path.exists(WNBA_FEATURE_LEARNING_FILE) else None
        # Rewrite as current snapshot to keep the file readable.
        write_csv_rows(WNBA_FEATURE_LEARNING_FILE, list(summary_rows[0].keys()), summary_rows)
    return lines

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
    merged = dict(DEFAULT_TEAM_RATINGS)

    # V3.0: weekly editable ratings file. This lets us update team strength/style
    # without rewriting or redeploying code when mounted/persisted in Railway.
    if TEAM_RATINGS_FILE and os.path.exists(TEAM_RATINGS_FILE):
        try:
            file_data = load_json(TEAM_RATINGS_FILE, {})
            if isinstance(file_data, dict):
                for k, v in file_data.items():
                    if isinstance(v, dict):
                        merged[k] = {**merged.get(k, {}), **v}
        except Exception as e:
            print("TEAM RATINGS FILE ERROR:", repr(e))

    if TEAM_RATINGS_JSON:
        try:
            custom = json.loads(TEAM_RATINGS_JSON)
            if isinstance(custom, dict):
                for k, v in custom.items():
                    if isinstance(v, dict):
                        merged[k] = {**merged.get(k, {}), **v}
        except Exception as e:
            print("TEAM RATINGS JSON ERROR:", repr(e))
    return merged

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


def stat_value_from_player_row(row, names, default=0):
    """Best-effort parser for ESPN player box score rows."""
    wanted = {str(x).lower() for x in names}
    stats = row.get("stats") or row.get("statistics") or []
    labels = row.get("labels") or row.get("keys") or []
    if isinstance(stats, dict):
        for k, v in stats.items():
            if str(k).lower() in wanted:
                return v
    if isinstance(stats, list) and labels and len(stats) == len(labels):
        for k, v in zip(labels, stats):
            if str(k).lower() in wanted:
                return v
    # ESPN often provides athlete.stats as a positional list. We fall back to zero
    # when we cannot safely identify a column.
    return default

def normalize_player_box_row(row):
    athlete = row.get("athlete") or row.get("player") or {}
    name = athlete.get("displayName") or athlete.get("shortName") or row.get("name") or "Unknown"
    starter = bool(row.get("starter") or row.get("isStarter"))

    # ESPN schemas vary. These fields are best-effort and harmless when absent.
    pts = safe_int(stat_value_from_player_row(row, ["points", "pts"], row.get("points", 0)), 0)
    reb = safe_int(stat_value_from_player_row(row, ["rebounds", "reb"], row.get("rebounds", 0)), 0)
    ast = safe_int(stat_value_from_player_row(row, ["assists", "ast"], row.get("assists", 0)), 0)
    tov = safe_int(stat_value_from_player_row(row, ["turnovers", "to", "tov"], row.get("turnovers", 0)), 0)
    fouls = safe_int(stat_value_from_player_row(row, ["fouls", "pf", "personalFouls"], row.get("fouls", 0)), 0)
    fg_raw = stat_value_from_player_row(row, ["fieldGoals", "fg", "fgm-a"], row.get("fieldGoals", ""))
    tp_raw = stat_value_from_player_row(row, ["threePointFieldGoals", "3pt", "3pm-a"], row.get("threePointFieldGoals", ""))
    fgm, fga = parse_made_attempted(fg_raw)
    tpm, tpa = parse_made_attempted(tp_raw)
    return {
        "name": name, "starter": starter, "points": pts, "rebounds": reb, "assists": ast,
        "turnovers": tov, "fouls": fouls, "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa,
        "fg_pct": round(fgm / fga, 3) if fga else None,
        "three_pct": round(tpm / tpa, 3) if tpa else None,
    }

def parse_player_box_stats(summary, home_name, away_name):
    """Parse player-level box score if ESPN exposes it. Safe fallback is empty lists."""
    out = {"home": [], "away": []}
    boxscore = summary.get("boxscore", {}) or {}
    players = boxscore.get("players", []) or []
    for team_block in players:
        team = team_block.get("team", {}) or {}
        display = team.get("displayName") or team.get("shortDisplayName") or ""
        side = None
        if normalize_team(display) == normalize_team(home_name):
            side = "home"
        elif normalize_team(display) == normalize_team(away_name):
            side = "away"
        if not side:
            continue
        rows = []
        for group in team_block.get("statistics", []) or []:
            labels = group.get("labels") or group.get("keys") or []
            for row in group.get("athletes", []) or []:
                if labels and isinstance(row, dict):
                    row = dict(row)
                    row.setdefault("labels", labels)
                rows.append(normalize_player_box_row(row))
        out[side] = rows
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
        "players": parse_player_box_stats(summary, home_name, away_name),
    }

# =============================================================================
# Odds API
# =============================================================================
ODDS_CACHE = {"ts": 0.0, "data": []}

def get_odds(force=False):
    """Fetch Odds API with a short cache so re-checks do not burn extra credits every alert."""
    if not ODDS_API_KEY:
        print("ODDS SKIPPED: Missing ODDS_API_KEY")
        return []
    now_ts = time.time()
    if not force and ODDS_CACHE.get("data") and (now_ts - safe_float(ODDS_CACHE.get("ts"), 0)) <= ODDS_CACHE_SECONDS:
        print(f"ODDS CACHE HIT: age {round(now_ts - safe_float(ODDS_CACHE.get('ts'), 0), 1)}s")
        return ODDS_CACHE.get("data") or []
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
        data = r.json() or []
        ODDS_CACHE["ts"] = time.time()
        ODDS_CACHE["data"] = data
        print("ODDS CREDITS REMAINING:", r.headers.get("x-requests-remaining"))
        return data
    except Exception as e:
        print("ODDS ERROR:", repr(e))
        return ODDS_CACHE.get("data") or []

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
        "opening_mls": {},
        "pregame_anchor": {},
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

def should_capture_pregame_anchor(info):
    start = info.get("start_time")
    if not start:
        return safe_float(info.get("minutes_elapsed"), 0) <= 0.5
    minutes_to_start = (start - now_local()).total_seconds() / 60.0
    return -2 <= minutes_to_start <= ANCHOR_CAPTURE_WINDOW_MINUTES

def capture_pregame_anchor(sg, info, markets):
    anchor = sg.setdefault("pregame_anchor", {})
    if anchor.get("locked"):
        return anchor
    if not should_capture_pregame_anchor(info):
        return anchor

    total = markets.get("total") or {}
    if total.get("point") is not None and anchor.get("total") is None:
        anchor["total"] = total.get("point")
        anchor["total_book"] = total.get("book")

    for side in ["home", "away"]:
        spread = choose_spread_for_side(markets, side)
        ml = choose_moneyline_for_side(markets, side)
        if spread and spread.get("point") is not None:
            anchor.setdefault("spreads", {}).setdefault(side, spread.get("point"))
            anchor.setdefault("spread_books", {}).setdefault(side, spread.get("book"))
        if ml and ml.get("price") is not None:
            anchor.setdefault("moneylines", {}).setdefault(side, ml.get("price"))
            anchor.setdefault("moneyline_books", {}).setdefault(side, ml.get("book"))

    spreads = anchor.get("spreads", {})
    if "home" in spreads and "away" in spreads:
        anchor["favorite_side"] = "home" if safe_float(spreads.get("home")) < safe_float(spreads.get("away")) else "away"
        anchor["favorite_spread"] = spreads.get(anchor["favorite_side"])
    else:
        mls = anchor.get("moneylines", {})
        if "home" in mls and "away" in mls:
            anchor["favorite_side"] = "home" if safe_int(mls.get("home"), 9999) < safe_int(mls.get("away"), 9999) else "away"
            anchor["favorite_ml"] = mls.get(anchor["favorite_side"])

    if safe_float(info.get("minutes_elapsed"), 0) > 1.0:
        anchor["locked"] = True
        anchor["locked_at"] = now_local().isoformat()
    return anchor

def update_line_state(sg, info, markets):
    capture_pregame_anchor(sg, info, markets)
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
        ml = choose_moneyline_for_side(markets, side)
        if ml and ml.get("price") is not None:
            sg.setdefault("opening_mls", {}).setdefault(side, ml.get("price"))

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


def side_label(info, side):
    return info.get("home") if side == "home" else info.get("away")

def player_context_for_side(info, side):
    players = ((info.get("players") or {}).get(side) or [])
    if not players:
        return {
            "available": False,
            "top_scorers": [],
            "foul_trouble": [],
            "turnover_warnings": [],
            "starter_count": 0,
            "note": "player box unavailable from free feed",
        }
    top = sorted(players, key=lambda x: safe_int(x.get("points"), 0), reverse=True)[:3]
    foul = [p for p in players if safe_int(p.get("fouls"), 0) >= PLAYER_FOUL_TROUBLE_LEVEL]
    tov = [p for p in players if safe_int(p.get("turnovers"), 0) >= PLAYER_TURNOVER_WARNING_LEVEL]
    return {
        "available": True,
        "top_scorers": [f"{p.get('name')} {p.get('points')}p" for p in top if p.get("name")],
        "foul_trouble": [f"{p.get('name')} {p.get('fouls')}F" for p in foul[:3]],
        "turnover_warnings": [f"{p.get('name')} {p.get('turnovers')}TO" for p in tov[:3]],
        "starter_count": sum(1 for p in players if p.get("starter")),
        "note": "player box parsed from free ESPN feed",
    }

def live_context_engine(info, sg=None, favorite_side=None):
    """Free live context layer using current clock, team box, run history, and any player box rows ESPN exposes."""
    if not ENABLE_FREE_LIVE_CONTEXT:
        return {"enabled": False}
    sg = sg or {}
    pace = game_pace(info)
    eff = efficiency_signals(info)
    run = scoring_run_info(sg, info) if sg else {"leader": None, "margin": 0}
    q = safe_int(info.get("period"), 0)
    min_left = safe_float(info.get("minutes_remaining"), 0)
    diff = abs(safe_int(info.get("home_score")) - safe_int(info.get("away_score")))

    home_box = team_box(info, "home")
    away_box = team_box(info, "away")
    home_players = player_context_for_side(info, "home")
    away_players = player_context_for_side(info, "away")
    home_external_lineup = external_lineup_for_team(info.get("home"))
    away_external_lineup = external_lineup_for_team(info.get("away"))

    starter_sit_risk = "LOW"
    starter_sit_notes = []
    if q >= 4 and diff >= STARTER_SIT_BLOWOUT_MARGIN and min_left <= STARTER_SIT_MINUTES_LEFT:
        starter_sit_risk = "HIGH"
        starter_sit_notes.append("late blowout rotation/starter-sit risk")
    elif q >= 3 and diff >= STARTER_SIT_BLOWOUT_MARGIN + 6:
        starter_sit_risk = "MEDIUM"
        starter_sit_notes.append("large second-half margin")

    favorite_context = {}
    if favorite_side in {"home", "away"}:
        dog_side = opponent_side(favorite_side)
        fav_box = team_box(info, favorite_side)
        dog_box = team_box(info, dog_side)
        favorite_context = {
            "favorite_side": favorite_side,
            "favorite_team": side_label(info, favorite_side),
            "opponent_team": side_label(info, dog_side),
            "favorite_turnover_gap": safe_int(fav_box.get("turnovers")) - safe_int(dog_box.get("turnovers")),
            "favorite_foul_gap": safe_int(fav_box.get("fouls")) - safe_int(dog_box.get("fouls")),
            "favorite_rebound_gap": safe_int(fav_box.get("rebounds")) - safe_int(dog_box.get("rebounds")),
            "favorite_paint_gap": safe_int(fav_box.get("points_in_paint")) - safe_int(dog_box.get("points_in_paint")),
            "opponent_run_active": run.get("leader") == dog_side and safe_int(run.get("margin")) >= STRONG_RUN_MARGIN,
            "favorite_player_context": player_context_for_side(info, favorite_side),
            "favorite_external_lineup": external_lineup_for_team(side_label(info, favorite_side)),
        }

    return {
        "enabled": True,
        "clock": f"Q{q} {info.get('clock')}",
        "minutes_remaining": round(min_left, 2),
        "possessions_left": pace.get("possessions_left"),
        "projected_game_possessions": pace.get("projected_game_possessions"),
        "pace_vs_default": pace.get("pace_vs_default"),
        "team_stats": {
            "home": {
                "team": info.get("home"), "fg": f"{home_box.get('fgm',0)}-{home_box.get('fga',0)}",
                "3pt": f"{home_box.get('tpm',0)}-{home_box.get('tpa',0)}", "efg": home_box.get("efg"),
                "fta": home_box.get("fta"), "turnovers": home_box.get("turnovers"), "fouls": home_box.get("fouls"),
                "oreb": home_box.get("off_reb"), "paint": home_box.get("points_in_paint"),
            },
            "away": {
                "team": info.get("away"), "fg": f"{away_box.get('fgm',0)}-{away_box.get('fga',0)}",
                "3pt": f"{away_box.get('tpm',0)}-{away_box.get('tpa',0)}", "efg": away_box.get("efg"),
                "fta": away_box.get("fta"), "turnovers": away_box.get("turnovers"), "fouls": away_box.get("fouls"),
                "oreb": away_box.get("off_reb"), "paint": away_box.get("points_in_paint"),
            },
        },
        "efficiency": eff,
        "run": run,
        "starter_sit_risk": starter_sit_risk,
        "starter_sit_notes": starter_sit_notes,
        "home_player_context": home_players,
        "away_player_context": away_players,
        "home_external_lineup": home_external_lineup,
        "away_external_lineup": away_external_lineup,
        "favorite_context": favorite_context,
    }


def load_external_lineup_context():
    """Optional manual/paid-feed hook for true lineup/star availability.
    Supports either WNBA_LINEUP_CONTEXT_JSON or LINEUP_CONTEXT_FILE.
    Expected shape:
    {"Las Vegas Aces": {"on_court_note":"Wilson active", "risk":"LOW", "star_status":"active"}}
    """
    if not ENABLE_EXTERNAL_LINEUP_CONTEXT:
        return {}
    if LINEUP_CONTEXT_JSON:
        try:
            data = json.loads(LINEUP_CONTEXT_JSON)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print("LINEUP CONTEXT JSON ERROR:", repr(e))
    if LINEUP_CONTEXT_FILE and os.path.exists(LINEUP_CONTEXT_FILE):
        try:
            data = load_json(LINEUP_CONTEXT_FILE, {})
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print("LINEUP CONTEXT FILE ERROR:", repr(e))
    return {}

def external_lineup_for_team(team_name):
    data = load_external_lineup_context()
    norm = normalize_team(team_name)
    for k, v in data.items():
        if normalize_team(k) == norm and isinstance(v, dict):
            return v
    return {}

def live_context_lines(info, sg=None, favorite_side=None, ctx=None):
    ctx = ctx or live_context_engine(info, sg=sg, favorite_side=favorite_side)
    if not ctx.get("enabled"):
        return []
    run = ctx.get("run") or {}
    lines = [
        f"Live context: {ctx.get('clock')} | poss left {ctx.get('possessions_left')} | pace {ctx.get('projected_game_possessions')} ({ctx.get('pace_vs_default'):+} vs base)",
        f"Team stats: Away TO/F/3PT {ctx['team_stats']['away'].get('turnovers')}/{ctx['team_stats']['away'].get('fouls')}/{ctx['team_stats']['away'].get('3pt')} | Home TO/F/3PT {ctx['team_stats']['home'].get('turnovers')}/{ctx['team_stats']['home'].get('fouls')}/{ctx['team_stats']['home'].get('3pt')}",
    ]
    if run.get("leader"):
        lines.append(f"Run check: {run.get('leader')} run margin {run.get('margin')} over {run.get('window_minutes')} min")
    lines.append(f"Rotation risk: {ctx.get('starter_sit_risk')}" + (f" — {', '.join(ctx.get('starter_sit_notes') or [])}" if ctx.get('starter_sit_notes') else ""))
    # Include player notes only when the free feed exposes them.
    pc_notes = []
    for side_name, pc in [("Away", ctx.get("away_player_context") or {}), ("Home", ctx.get("home_player_context") or {})]:
        if pc.get("available"):
            if pc.get("foul_trouble"):
                pc_notes.append(f"{side_name} foul: {', '.join(pc.get('foul_trouble'))}")
            if pc.get("turnover_warnings"):
                pc_notes.append(f"{side_name} TO: {', '.join(pc.get('turnover_warnings'))}")
    ext_notes = []
    for side_name, ext in [("Away", ctx.get("away_external_lineup") or {}), ("Home", ctx.get("home_external_lineup") or {})]:
        if ext:
            note = ext.get("on_court_note") or ext.get("note") or ext.get("risk") or "external lineup context available"
            ext_notes.append(f"{side_name}: {note}")
    if pc_notes or ext_notes:
        lines.append("Player flags: " + " | ".join((pc_notes + ext_notes)[:2]))
    else:
        lines.append("Player flags: free live player box unavailable/clean; paid lineup feed still needed for true on-court detection")
    return lines[:5]

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
        "playable_over_best_point": total.get("playable_over_best_point"),
        "playable_over_best_book": total.get("playable_over_best_book"),
        "playable_over_best_price": total.get("playable_over_best_price"),
        "playable_under_best_point": total.get("playable_under_best_point"),
        "playable_under_best_book": total.get("playable_under_best_book"),
        "playable_under_best_price": total.get("playable_under_best_price"),
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

def live_context_risk_adjustment(info, sg, opp, favorite_side=None):
    """Apply V2.0 live context directly to confidence/value/risk and block weak situations."""
    if not ENABLE_LIVE_CONTEXT_GATES or not opp:
        return opp
    ctx = live_context_engine(info, sg=sg, favorite_side=favorite_side)
    opp["live_context"] = ctx
    block_notes = []

    starter_risk = ctx.get("starter_sit_risk")
    if starter_risk == "HIGH":
        opp["confidence"] = round(clamp(safe_float(opp.get("confidence")) - LIVE_CONTEXT_HIGH_RISK_CONF_PENALTY))
        opp["value_score"] = round(clamp(safe_float(opp.get("value_score")) - LIVE_CONTEXT_HIGH_RISK_VALUE_PENALTY))
        opp["risk_score"] = round(clamp(safe_float(opp.get("risk_score")) + LIVE_CONTEXT_HIGH_RISK_RISK_BUMP))
        if opp.get("market_type") == "TOTAL" and opp.get("side") == "OVER" and BLOCK_OVER_ON_HIGH_STARTER_SIT_RISK:
            block_notes.append("NO BET: high starter-sit/blowout risk blocks OVER")
        if opp.get("market_type") in {"SPREAD", "MONEYLINE", "FAVORITE_SPREAD_DROP"} and BLOCK_FAVORITE_ON_HIGH_STARTER_SIT_RISK:
            block_notes.append("NO BET: high starter-sit/blowout risk blocks favorite buyback")
    elif starter_risk == "MEDIUM":
        opp["confidence"] = round(clamp(safe_float(opp.get("confidence")) - LIVE_CONTEXT_MED_RISK_CONF_PENALTY))
        opp["risk_score"] = round(clamp(safe_float(opp.get("risk_score")) + LIVE_CONTEXT_MED_RISK_RISK_BUMP))

    if opp.get("market_type") in {"SPREAD", "MONEYLINE", "FAVORITE_SPREAD_DROP"}:
        fav_ctx = ctx.get("favorite_context", {}) or {}
        fav_pc = fav_ctx.get("favorite_player_context", {}) or {}
        if FAVORITE_PLAYER_FOUL_BLOCK and fav_pc.get("foul_trouble"):
            opp["confidence"] = round(clamp(safe_float(opp.get("confidence")) - 10))
            opp["risk_score"] = round(clamp(safe_float(opp.get("risk_score")) + 15))
            block_notes.append("NO BET: favorite player foul trouble " + ", ".join(fav_pc.get("foul_trouble")[:2]))
        if fav_pc.get("turnover_warnings"):
            opp["confidence"] = round(clamp(safe_float(opp.get("confidence")) - 5))
            opp["risk_score"] = round(clamp(safe_float(opp.get("risk_score")) + 7))

    if opp.get("market_type") == "TOTAL":
        away_pc = ctx.get("away_player_context", {}) or {}
        home_pc = ctx.get("home_player_context", {}) or {}
        foul_flags = (away_pc.get("foul_trouble") or []) + (home_pc.get("foul_trouble") or [])
        if foul_flags and opp.get("side") == "OVER":
            # Foul trouble to scorers/starters can kill offensive quality; downgrade, don't auto-block.
            opp["confidence"] = round(clamp(safe_float(opp.get("confidence")) - 4))
            opp["risk_score"] = round(clamp(safe_float(opp.get("risk_score")) + 6))

    if block_notes:
        prior = opp.get("block_reason") or ""
        opp["block_reason"] = "; ".join(block_notes + ([prior] if prior else []))
        opp["action"] = "WATCH"
        opp["paid_alert"] = False
    return opp

def closing_window_adjustment(info, opp):
    """Downgrade chaotic late-Q4 plays unless the OVER is clearly foul-game supported."""
    if not ENABLE_CLOSING_WINDOW_PROTECTION or not opp:
        return opp
    if safe_int(info.get("period"), 0) < 4:
        return opp
    min_left = safe_float(info.get("minutes_remaining"), 0)
    if min_left > CLOSING_WINDOW_MINUTES_LEFT:
        return opp

    eff = efficiency_signals(info)
    diff = abs(safe_int(info.get("home_score")) - safe_int(info.get("away_score")))
    foul_game_over = (
        opp.get("market_type") == "TOTAL"
        and str(opp.get("side", "")).upper() == "OVER"
        and eff.get("ftr", 0) >= CLOSING_WINDOW_FOUL_OVER_FTR
        and diff <= CLOSING_WINDOW_FOUL_OVER_MAX_DIFF
    )
    if foul_game_over:
        opp.setdefault("closing_window_note", "late foul-game support keeps OVER live")
        opp["confidence"] = round(clamp(safe_float(opp.get("confidence")) + 3))
        return opp

    bump = CLOSING_WINDOW_TOTAL_RISK_BUMP if opp.get("market_type") == "TOTAL" else CLOSING_WINDOW_FAVORITE_RISK_BUMP
    opp["risk_score"] = round(clamp(safe_float(opp.get("risk_score")) + bump))
    opp["confidence"] = round(clamp(safe_float(opp.get("confidence")) - max(3, bump // 2)))
    opp["closing_window_note"] = f"late Q4 chaos protection: +{bump} risk"
    return opp

def finalize_opportunity(info, sg, opp, favorite_side=None):
    if not opp:
        return opp
    opp = apply_profile_rule_adjustment(opp)
    opp = live_context_risk_adjustment(info, sg, opp, favorite_side=favorite_side)
    opp = closing_window_adjustment(info, opp)
    return assign_alert_tier(opp)


def total_engine_market_context(side, s):
    """Side-specific total line context. Uses BetMGM/playable side number when available."""
    side = str(side).upper()
    out = dict(s)
    if side == "OVER":
        line = s.get("playable_over_best_point") if s.get("playable_over_best_point") is not None else s.get("live_total")
        price = s.get("playable_over_best_price") if s.get("playable_over_best_price") is not None else s.get("over_price")
        book = s.get("playable_over_best_book") or s.get("book")
        edge = round(s["projection"]["projected_total"] - safe_float(line), 1)
    else:
        line = s.get("playable_under_best_point") if s.get("playable_under_best_point") is not None else s.get("live_total")
        price = s.get("playable_under_best_price") if s.get("playable_under_best_price") is not None else s.get("under_price")
        book = s.get("playable_under_best_book") or s.get("book")
        edge = round(safe_float(line) - s["projection"]["projected_total"], 1)
    out["live_total"] = safe_float(line)
    out["side_line"] = safe_float(line)
    out["side_price"] = price
    out["side_book"] = book
    out["side_edge"] = edge
    return out

def over_live_signal_score(info, sg, s):
    """OVER engine: pace, possessions, FTs/fouls, extra possessions, paint/transition, and real scoring support."""
    proj = s["projection"]
    pace = proj["pace"]
    eff = proj["eff"]
    minutes = safe_float(info.get("minutes_elapsed"), 0)
    move = safe_float(s.get("move_from_open"), 0)
    velocity = safe_float(s.get("velocity"), 0)
    short_velocity = safe_float(s.get("short_velocity"), 0)

    score = 0
    reasons = []

    if pace.get("pace_vs_default", 0) >= 4:
        score += 18; reasons.append("pace above baseline")
    elif pace.get("pace_vs_default", 0) >= 1.5:
        score += 9; reasons.append("pace slightly above baseline")
    if pace.get("possessions_left", 0) >= 34:
        score += 12; reasons.append("large possessions remaining")
    if proj.get("expected_remaining_ppp", 0) >= 1.04:
        score += 12; reasons.append("remaining PPP support")
    if eff.get("ftr", 0) >= 0.30:
        score += 14; reasons.append("free-throw rate support")
    if eff.get("fouls", 0) >= 18:
        score += 10; reasons.append("foul pressure")
    if eff.get("off_reb", 0) >= 10:
        score += 10; reasons.append("extra possessions from OREB")
    if eff.get("fast_break", 0) >= 12 or eff.get("points_in_paint", 0) >= 34:
        score += 8; reasons.append("paint/transition scoring")
    if move <= -3:
        score += round(abs(move) * OPENING_TOTAL_REFERENCE_WEIGHT * 4, 1); reasons.append("small opening-reference discount")
    if short_velocity >= 2 or velocity >= 3:
        score += 5; reasons.append("market starting to reprice up")

    # Penalize fake over signals: all shooting, no FTs/OREB/paint.
    if eff.get("three_pct", 0) >= 0.43 and eff.get("three_rate", 0) >= 0.36 and eff.get("ftr", 0) < 0.24 and eff.get("off_reb", 0) < 8:
        score -= 14; reasons.append("hot 3PT without structural scoring support")
    if eff.get("turnovers", 0) >= 18:
        score -= 8; reasons.append("turnovers suppress over quality")
    if minutes < MIN_TOTAL_MINUTES_ELAPSED:
        score -= 18; reasons.append("sample too early")

    real_support = (
        pace.get("pace_vs_default", 0) >= 3
        or eff.get("ftr", 0) >= 0.30
        or eff.get("fouls", 0) >= 18
        or eff.get("off_reb", 0) >= 10
        or eff.get("points_in_paint", 0) >= 34
    )
    return {"score": round(clamp(score, -30, 70)), "reasons": reasons[:5], "real_support": real_support}

def under_live_signal_score(info, sg, s):
    """UNDER engine: dead possessions, poor shot quality, low FTs/fouls, turnover pressure, no OREB, and inflated live number."""
    proj = s["projection"]
    pace = proj["pace"]
    eff = proj["eff"]
    minutes = safe_float(info.get("minutes_elapsed"), 0)
    move = safe_float(s.get("move_from_open"), 0)
    velocity = safe_float(s.get("velocity"), 0)
    short_velocity = safe_float(s.get("short_velocity"), 0)

    score = 0
    reasons = []
    suppression_signals = 0

    if pace.get("pace_vs_default", 0) <= -4:
        score += 18; suppression_signals += 1; reasons.append("pace below baseline")
    elif pace.get("pace_vs_default", 0) <= -1.5:
        score += 8; reasons.append("pace slightly below baseline")
    if proj.get("expected_remaining_ppp", 1.02) <= 0.98 and minutes >= MIN_UNDER_LIVE_SAMPLE_MINUTES:
        score += 12; suppression_signals += 1; reasons.append("remaining PPP suppressed")
    if eff.get("turnovers", 0) >= 16:
        score += 14; suppression_signals += 1; reasons.append("turnovers creating dead trips")
    if eff.get("efg", 1) <= 0.45 and eff.get("ftr", 0) < 0.25 and minutes >= MIN_UNDER_LIVE_SAMPLE_MINUTES:
        score += 16; suppression_signals += 1; reasons.append("poor eFG with low FT rate")
    if eff.get("ftr", 0) < 0.22 and eff.get("fouls", 0) < 16:
        score += 10; suppression_signals += 1; reasons.append("low FT/foul environment")
    if eff.get("off_reb", 0) <= 6 and minutes >= MIN_UNDER_LIVE_SAMPLE_MINUTES:
        score += 7; reasons.append("limited second-chance points")
    if move >= 4:
        score += round(move * OPENING_TOTAL_REFERENCE_WEIGHT * 4, 1); reasons.append("small opening-reference inflation")
    if velocity >= 4 and short_velocity >= 1:
        score += 8; reasons.append("live total spike to fade")

    # Penalize fragile unders.
    if eff.get("ftr", 0) >= 0.32 or eff.get("fouls", 0) >= 20:
        score -= 15; reasons.append("FT/foul pressure threatens under")
    if eff.get("off_reb", 0) >= 11:
        score -= 9; reasons.append("OREB extends possessions")
    if pace.get("pace_vs_default", 0) >= 3:
        score -= 12; reasons.append("pace too high for under")
    if minutes < MIN_UNDER_LIVE_SAMPLE_MINUTES:
        score -= 12; reasons.append("under sample too early")

    return {"score": round(clamp(score, -30, 70)), "reasons": reasons[:5], "suppression_signals": suppression_signals}

def total_side_scenario(side, s, signal):
    side = str(side).upper()
    if side == "OVER":
        if safe_float(s.get("move_from_open"), 0) <= -4:
            return "OVER_DISCOUNT_BUY"
        if s["projection"]["pace"].get("pace_vs_default", 0) >= 4:
            return "OVER_PACE_CONTINUATION"
        if s["projection"]["eff"].get("ftr", 0) >= 0.30 or s["projection"]["eff"].get("fouls", 0) >= 18:
            return "OVER_FT_FOUL_PRESSURE"
        return "OVER_LIVE_VALUE"
    if safe_float(s.get("move_from_open"), 0) >= 4 or safe_float(s.get("velocity"), 0) >= 4:
        return "UNDER_INFLATED_SPIKE_FADE"
    if s["projection"]["pace"].get("pace_vs_default", 0) <= -4:
        return "UNDER_PACE_SUPPRESSION"
    if s["projection"]["eff"].get("turnovers", 0) >= 16:
        return "UNDER_DEAD_POSSESSIONS"
    return "UNDER_LIVE_VALUE"

def build_total_side_opportunity(info, sg, markets, side, base_scores=None):
    side = str(side).upper()
    s = base_scores or total_scores(info, sg, markets)
    if not s:
        return None
    s = total_engine_market_context(side, s)

    edge = s["side_edge"]
    price = s["side_price"]
    book = s["side_book"]
    live_line = s["side_line"]

    if side == "OVER":
        signal = over_live_signal_score(info, sg, s)
        confidence = round(clamp(42 + signal["score"] * 0.65 + edge * 3.6 - s["risk_over"] * 0.18))
        value = round(clamp(42 + signal["score"] * 0.62 + edge * 3.8 - s["risk_over"] * 0.25))
        risk = round(clamp(s["risk_over"]))
        min_edge, min_conf, min_value, max_risk = MIN_OVER_EDGE_POINTS, MIN_OVER_CONFIDENCE, MIN_OVER_VALUE_SCORE, MAX_OVER_RISK_SCORE
    else:
        signal = under_live_signal_score(info, sg, s)
        confidence = round(clamp(43 + signal["score"] * 0.70 + edge * 3.5 - s["risk_under"] * 0.20))
        value = round(clamp(42 + signal["score"] * 0.66 + edge * 3.6 - s["risk_under"] * 0.28))
        risk = round(clamp(s["risk_under"]))
        min_edge, min_conf, min_value, max_risk = MIN_UNDER_EDGE_POINTS, MIN_UNDER_CONFIDENCE, MIN_UNDER_VALUE_SCORE, MAX_UNDER_RISK_SCORE

    # Predictor/discrepancy must see the side-specific BetMGM line.
    predictor = market_misprice_score_for_total(info, sg, s, side) if ENABLE_MARKET_PREDICTOR_ENGINE else {
        "market_misprice_score": 50,
        "predicted_line_move": 0,
        "future_state": {},
    }
    market_discrepancy = market_discrepancy_for_total(s, side) if ENABLE_MARKET_DISCREPANCY_ENGINE else {"status": "DISABLED", "score": 0}

    confidence = round(clamp(confidence + max(0, predictor.get("market_misprice_score", 50) - 65) * 0.18))
    value = round(clamp(value + max(0, predictor.get("market_misprice_score", 50) - 65) * 0.15))
    confidence = round(clamp(confidence + safe_float(market_discrepancy.get("score"), 0) * 0.14))
    value = round(clamp(value + safe_float(market_discrepancy.get("score"), 0) * 0.13))
    if market_discrepancy.get("status") == "AGAINST_CONSENSUS":
        risk = round(clamp(risk + 10))

    scenario = total_side_scenario(side, s, signal)
    action = "WATCH"
    block_reason = ""

    if safe_float(info.get("minutes_elapsed"), 0) < MIN_TOTAL_MINUTES_ELAPSED:
        block_reason = f"NO BET: total sample too early before {MIN_TOTAL_MINUTES_ELAPSED} minutes elapsed"
    elif abs(edge) > MAX_TOTAL_PAID_EDGE_POINTS:
        block_reason = f"LOG ONLY: total edge {edge} exceeds paid sanity cap {MAX_TOTAL_PAID_EDGE_POINTS}"
    elif side == "UNDER" and s["projection"]["quarter_profile"] == "Q1_EARLY_SAMPLE" and safe_float(info.get("minutes_elapsed"), 0) < MIN_Q1_UNDER_MINUTES_ELAPSED:
        block_reason = f"NO BET: Q1 UNDER too early before {MIN_Q1_UNDER_MINUTES_ELAPSED} minutes elapsed"
    elif side == "UNDER" and UNDER_REQUIRE_TWO_SUPPRESSION_SIGNALS and signal.get("suppression_signals", 0) < 2:
        block_reason = f"NO BET: UNDER needs at least 2 suppression signals, found {signal.get('suppression_signals', 0)}"
    elif side == "OVER" and OVER_REQUIRE_REAL_SCORING_SUPPORT and not signal.get("real_support", False):
        block_reason = "NO BET: OVER lacks real pace/FT/OREB/paint support"
    elif s["projection"]["pace"]["possessions_left"] < MIN_TOTAL_POSSESSIONS_LEFT:
        block_reason = "possessions left too low for total entry"
    elif ENABLE_MARKET_PREDICTOR_ENGINE and not WIDE_NET_LEARNING_MODE and predictor.get("market_misprice_score", 0) < MIN_MARKET_MISPRICE_SCORE:
        block_reason = f"predictor miss: market misprice {predictor.get('market_misprice_score')} below {MIN_MARKET_MISPRICE_SCORE}"
    elif ENABLE_MARKET_PREDICTOR_ENGINE and not WIDE_NET_LEARNING_MODE and predictor.get("future_state", {}).get("future_state_score", 0) < MIN_FUTURE_STATE_SCORE:
        block_reason = f"future-state miss: {predictor.get('future_state', {}).get('future_state_score')} below {MIN_FUTURE_STATE_SCORE}"
    elif abs(edge) >= BIG_EDGE_CONSENSUS_REQUIRED and market_discrepancy.get("status") in {"AGAINST_CONSENSUS", "MARKET_ALIGNED", "NO_MARKET"} and confidence < 82:
        block_reason = f"big model edge without market confirmation: {market_discrepancy.get('status')}"
    elif not price_ok(price, MAX_TOTAL_PRICE):
        elite_price_ok = price_ok(price, ELITE_TOTAL_MAX_PRICE)
        elite_score_ok = confidence >= ELITE_TOTAL_MIN_CONFIDENCE and market_discrepancy.get("status") in ELITE_TOTAL_ALLOWED_MARKET_STATES
        if not (elite_price_ok and elite_score_ok):
            block_reason = f"total price too expensive for BetMGM discipline: {price}"
    elif edge >= min_edge and confidence >= min_conf and value >= min_value and risk <= max_risk:
        action = "STRIKE"
    elif wide_net_strike_ok(edge, confidence, value, risk, predictor, scenario):
        action = "STRIKE"
    else:
        block_reason = f"{side} gate miss: edge {edge}, conf {confidence}, value {value}, risk {risk}, signal {signal.get('score')}"

    return finalize_opportunity(info, sg, {
        "market_type": "TOTAL", "side": side, "team_side": "",
        "line": live_line, "price": price, "book": book,
        "edge": edge, "projected_total": s["projection"]["projected_total"],
        "confidence": confidence, "value_score": value, "risk_score": risk,
        "action": action, "block_reason": block_reason,
        "scenario": scenario, "quarter_profile": s["projection"]["quarter_profile"],
        "scores": {**s, "minutes_elapsed": info.get("minutes_elapsed"), "total_engine": side, "engine_signal_score": signal.get("score"), "engine_reasons": "; ".join(signal.get("reasons", []))},
        "predictor": predictor,
        "market_misprice_score": predictor.get("market_misprice_score"),
        "predicted_line_move": predictor.get("predicted_line_move"),
        "future_state_score": predictor.get("future_state", {}).get("future_state_score"),
        "market_discrepancy": market_discrepancy,
        "market_discrepancy_status": market_discrepancy.get("status"),
        "market_discrepancy_score": market_discrepancy.get("score"),
    })

def choose_best_total_opportunity(over_opp, under_opp):
    """Pick one total side per game/check. OVER and UNDER remain separate engines, hard lock prevents both texts."""
    candidates = [o for o in [over_opp, under_opp] if o]
    strikes = [o for o in candidates if o.get("action") == "STRIKE"]
    pool = strikes or candidates
    if not pool:
        return None
    def rank(o):
        market_bonus = 6 if o.get("market_discrepancy_status") in {"OFF_MARKET_EDGE", "STRONG_OFF_MARKET_EDGE"} else 0
        side_bonus = 2 if o.get("side") == "OVER" else 0  # slight under caution in WNBA without paid lineup data
        return safe_float(o.get("confidence")) + safe_float(o.get("value_score")) * 0.45 - safe_float(o.get("risk_score")) * 0.28 + safe_float(o.get("market_misprice_score")) * 0.12 + market_bonus + side_bonus
    return sorted(pool, key=rank, reverse=True)[0]

def build_total_opportunity(info, sg, markets):
    """Compatibility wrapper: build separate OVER/UNDER engines, then choose one total side."""
    s = total_scores(info, sg, markets)
    if not s:
        return None
    over_opp = build_total_side_opportunity(info, sg, markets, "OVER", base_scores=s)
    under_opp = build_total_side_opportunity(info, sg, markets, "UNDER", base_scores=s)
    return choose_best_total_opportunity(over_opp, under_opp)


# =============================================================================
# Favorite buyback professional model
# =============================================================================
def pregame_favorite_side(sg, markets, info):
    anchor = sg.get("pregame_anchor", {}) or {}
    if anchor.get("favorite_side") in {"home", "away"}:
        return anchor.get("favorite_side")
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

def live_moneyline_consensus(markets, side):
    offers = markets.get("h2h", {}).get(side, []) or []
    if not offers:
        return {"status": "NO_MARKET", "score": 0, "advantage_points": 0, "reason": "missing moneyline market"}
    chosen = choose_moneyline_for_side(markets, side) or {}
    book_price = safe_int(chosen.get("price"), None)
    probs = []
    for o in offers:
        if o.get("book") in MARKET_REFERENCE_BOOKS and o.get("price") is not None:
            prob = american_to_prob(o.get("price"))
            if prob is not None:
                probs.append(prob)
    if not probs or book_price is None:
        return {"status": "NO_MARKET", "score": 0, "advantage_points": 0, "reason": "missing moneyline consensus"}
    market_prob = sum(probs) / len(probs)
    book_prob = american_to_prob(book_price)
    advantage = round((market_prob - book_prob) * 100, 2)
    score = 15 if len(probs) >= MARKET_CONSENSUS_MIN_BOOKS else 0
    if advantage >= 3.0:
        score += 35
    elif advantage >= 1.5:
        score += 22
    elif advantage >= 0.5:
        score += 10
    elif advantage <= -1.0:
        score -= 18
    status = "STRONG_OFF_MARKET_EDGE" if advantage >= 3.0 else "OFF_MARKET_EDGE" if advantage >= 1.5 else "AGAINST_CONSENSUS" if advantage <= -1.0 else "MARKET_ALIGNED"
    return {
        "status": status, "score": round(clamp(score, -30, 70)),
        "advantage_points": advantage, "books": len(probs),
        "book_vs_market": round(book_prob * 100 - market_prob * 100, 2),
        "reason": f"ML implied edge {advantage}% vs consensus for playable {book_price}",
    }

def favorite_dominance_index(info, fav_side):
    """
    Measures whether the favorite is still controlling the game underneath the score.
    This is intentionally not restrictive; it adds/subtracts confidence so we can learn.
    """
    dog_side = opponent_side(fav_side)
    fav = team_box(info, fav_side)
    dog = team_box(info, dog_side)

    paint_gap = safe_int(fav.get("points_in_paint")) - safe_int(dog.get("points_in_paint"))
    reb_gap = safe_int(fav.get("rebounds")) - safe_int(dog.get("rebounds"))
    oreb_gap = safe_int(fav.get("off_reb")) - safe_int(dog.get("off_reb"))
    tov_gap = safe_int(dog.get("turnovers")) - safe_int(fav.get("turnovers"))
    fta_gap = safe_int(fav.get("fta")) - safe_int(dog.get("fta"))
    efg_gap = safe_float(fav.get("efg")) - safe_float(dog.get("efg"))

    score = 50
    notes = []
    if paint_gap >= 8:
        score += 12; notes.append(f"paint +{paint_gap}")
    elif paint_gap <= -8:
        score -= 10; notes.append(f"paint {paint_gap}")
    if reb_gap >= 6:
        score += 10; notes.append(f"reb +{reb_gap}")
    elif reb_gap <= -8:
        score -= 10; notes.append(f"reb {reb_gap}")
    if oreb_gap >= 3:
        score += 6; notes.append(f"OREB +{oreb_gap}")
    if tov_gap >= 3:
        score += 9; notes.append("favorite turnover edge")
    elif tov_gap <= -4:
        score -= 10; notes.append("favorite turnover problem")
    if fta_gap >= 5:
        score += 8; notes.append(f"FTA +{fta_gap}")
    elif fta_gap <= -6:
        score -= 8; notes.append(f"FTA {fta_gap}")
    if efg_gap >= 0.08:
        score += 8; notes.append("favorite eFG edge")
    elif efg_gap <= -0.10:
        score -= 8; notes.append("favorite cold shooting")

    return {
        "dominance_score": round(clamp(score)),
        "paint_gap": paint_gap,
        "rebound_gap": reb_gap,
        "oreb_gap": oreb_gap,
        "turnover_edge": tov_gap,
        "fta_gap": fta_gap,
        "efg_gap": round(efg_gap, 3),
        "notes": notes[:5],
    }


def favorite_run_regression_score(info, fav_side, sg):
    """
    Scores whether an underdog run against the favorite is likely noisy/regressible.
    High = buyback-friendly. Low = underdog control looks real.
    """
    dog_side = opponent_side(fav_side)
    run = scoring_run_info(sg, info)
    fav = team_box(info, fav_side)
    dog = team_box(info, dog_side)

    score = 50
    notes = []
    run_against_fav = run.get("leader") == dog_side and safe_int(run.get("margin")) >= STRONG_RUN_MARGIN
    if run_against_fav:
        score += 8
        notes.append(f"dog run {run.get('margin')} pts")

    dog_three_gap = safe_int(dog.get("tpm")) - safe_int(fav.get("tpm"))
    dog_paint_gap = safe_int(dog.get("points_in_paint")) - safe_int(fav.get("points_in_paint"))
    dog_fta_gap = safe_int(dog.get("fta")) - safe_int(fav.get("fta"))
    dog_reb_gap = safe_int(dog.get("rebounds")) - safe_int(fav.get("rebounds"))
    fav_tov_gap = safe_int(fav.get("turnovers")) - safe_int(dog.get("turnovers"))

    # Noisy run: underdog threes without paint/FT/rebound control.
    if dog_three_gap >= 3 and dog_paint_gap < 8 and dog_fta_gap < 6:
        score += 20; notes.append("dog 3PT spike looks noisy")
    if dog_paint_gap >= 10:
        score -= 16; notes.append("dog paint control")
    if dog_fta_gap >= 7:
        score -= 12; notes.append("dog FT control")
    if dog_reb_gap >= 8:
        score -= 10; notes.append("dog rebounding control")
    if fav_tov_gap >= 5:
        score -= 12; notes.append("favorite turnovers fueling run")
    elif fav_tov_gap <= -2:
        score += 8; notes.append("favorite not giving it away")

    profile = "RUN_REGRESSION_BUYBACK" if score >= 62 else "RUN_STRUCTURAL_CAUTION" if score <= 42 else "RUN_MIXED_LEARN"
    return {"run_regression_score": round(clamp(score)), "profile": profile, "run_against_favorite": run_against_fav, "run": run, "notes": notes[:5]}


def favorite_market_overreaction_score(info, fav_side, sg, live_line=None, live_ml=None):
    anchor = sg.get("pregame_anchor", {}) or {}
    opening_spread = safe_float((anchor.get("spreads", {}) or {}).get(fav_side), None)
    if opening_spread is None:
        opening_spread = safe_float((sg.get("opening_spreads", {}) or {}).get(fav_side), None)

    fav_margin = side_score(info, fav_side) - side_score(info, opponent_side(fav_side))
    score = 45
    spread_swing = None
    notes = []

    if opening_spread is not None and live_line is not None:
        spread_swing = round(safe_float(live_line) - opening_spread, 1)
        if spread_swing >= FAVORITE_MARKET_OVERREACTION_MIN:
            score += min(25, spread_swing * 3.0)
            notes.append(f"spread swing +{spread_swing} from anchor")
        elif spread_swing >= 2:
            score += 8
            notes.append(f"small spread discount +{spread_swing}")

    if fav_margin <= -FAVORITE_EARLY_DOWN_MIN_MARGIN:
        score += min(16, abs(fav_margin) * 1.0)
        notes.append(f"favorite down {abs(fav_margin)}")
    if fav_margin <= -FAVORITE_DOWN_BUYBACK_MAX_MARGIN:
        score -= 12
        notes.append("favorite deficit getting large")

    if live_ml is not None:
        p = safe_int(live_ml)
        if -160 <= p <= 125:
            score += 10; notes.append("ML in playable buyback zone")
        elif -190 <= p < -160:
            score += 3; notes.append("ML slightly above core range")

    return {"market_overreaction_score": round(clamp(score)), "spread_swing": spread_swing, "favorite_margin": fav_margin, "notes": notes[:5]}


def favorite_in_game_context(info, fav_side, sg):
    dog_side = opponent_side(fav_side)
    fav_box = team_box(info, fav_side)
    dog_box = team_box(info, dog_side)
    run = scoring_run_info(sg, info)
    run_against_fav = run.get("leader") == dog_side and run.get("margin", 0) >= STRONG_RUN_MARGIN
    star = team_context_for_side(info, fav_side).get("star", {})
    diff = abs(safe_int(info.get("home_score")) - safe_int(info.get("away_score")))
    q = safe_int(info.get("period", 0))
    min_left = safe_float(info.get("minutes_remaining"), 0)
    fav_players = player_context_for_side(info, fav_side)

    dominance = favorite_dominance_index(info, fav_side)
    regression = favorite_run_regression_score(info, fav_side, sg)

    risk_notes = []
    support_notes = []
    risk = 18
    support = 44

    support += max(-10, min(14, (dominance["dominance_score"] - 50) * 0.45))
    support += max(-8, min(12, (regression["run_regression_score"] - 50) * 0.35))
    support_notes.extend(dominance.get("notes", [])[:3])
    support_notes.extend(regression.get("notes", [])[:2])

    if run_against_fav:
        # Do not over-penalize runs; basketball runs create the opportunity.
        risk += 5
        risk_notes.append(f"opponent run {run.get('margin')}-pt swing")

    fav_tov_gap = safe_int(fav_box.get("turnovers")) - safe_int(dog_box.get("turnovers"))
    if fav_tov_gap >= 5:
        risk += 10
        risk_notes.append(f"favorite turnover gap +{fav_tov_gap}")
    elif fav_tov_gap <= -2:
        support += 7
        support_notes.append("favorite protecting ball")

    fav_foul_gap = safe_int(fav_box.get("fouls")) - safe_int(dog_box.get("fouls"))
    if fav_foul_gap >= 5:
        risk += 8
        risk_notes.append(f"favorite foul trouble gap +{fav_foul_gap}")

    if star.get("star_status") in {"out", "limited", "questionable"}:
        risk += STAR_OUT_RISK_BUMP if star.get("star_status") == "out" else STAR_LIMITED_RISK_BUMP
        risk_notes.append(f"star status {star.get('star_status')}")

    if fav_players.get("foul_trouble"):
        risk += 8
        risk_notes.append("player foul trouble: " + ", ".join(fav_players.get("foul_trouble")[:2]))
    if fav_players.get("turnover_warnings"):
        risk += 5
        risk_notes.append("player TO warning: " + ", ".join(fav_players.get("turnover_warnings")[:2]))

    if q >= 4 and diff >= STARTER_SIT_BLOWOUT_MARGIN and min_left <= STARTER_SIT_MINUTES_LEFT:
        risk += 16
        risk_notes.append("starter/rotation sit risk from blowout")

    return {
        "support_score": round(clamp(support)),
        "risk_score": round(clamp(risk)),
        "run_against_favorite": run_against_fav,
        "run": run,
        "risk_notes": risk_notes[:4],
        "support_notes": support_notes[:5],
        "star_status": star.get("star_status"),
        "player_context": fav_players,
        "dominance": dominance,
        "run_regression": regression,
    }


def prob_to_american(prob):
    """Convert win probability 0-1 to American odds. Used only for internal fair ML display."""
    try:
        p = max(0.01, min(0.99, float(prob)))
        if p >= 0.5:
            return int(round(-100 * p / (1 - p)))
        return int(round(100 * (1 - p) / p))
    except Exception:
        return None

def expected_live_favorite_line(info, fav_side, sg, live_spread=None, live_ml=None):
    """
    V2.8 expected-live-line engine.
    For the pregame favorite, estimate what the live full-game spread and ML should be now
    based on anchor spread, current margin, time remaining, dominance, and run regression.
    Positive spread_edge means the current BetMGM spread is better than our fair line.
    Positive ml_edge_pct means BetMGM's implied probability is cheaper than our fair ML.
    """
    if not ENABLE_EXPECTED_LIVE_LINE_ENGINE or fav_side not in {"home", "away"}:
        return {"enabled": False}

    anchor = sg.get("pregame_anchor", {}) or {}
    opening_spread = safe_float((anchor.get("spreads", {}) or {}).get(fav_side), None)
    if opening_spread is None:
        opening_spread = safe_float((sg.get("opening_spreads", {}) or {}).get(fav_side), None)
    if opening_spread is None:
        return {"enabled": False, "reason": "missing favorite anchor spread"}

    pregame_expected_margin = max(0.0, -opening_spread)
    fav_margin_now = side_score(info, fav_side) - side_score(info, opponent_side(fav_side))
    minutes_remaining = safe_float(info.get("minutes_remaining"), 0)
    remaining_factor = max(0.0, min(1.0, minutes_remaining / REGULATION_MINUTES))

    dominance = favorite_dominance_index(info, fav_side)
    regression = favorite_run_regression_score(info, fav_side, sg)
    ppi = possession_pressure_index(info, side=fav_side)

    dominance_adj = (safe_float(dominance.get("dominance_score"), 50) - 50) / 8.0
    regression_adj = (safe_float(regression.get("run_regression_score"), 50) - 50) / 10.0
    pressure_adj = (safe_float(ppi, 50) - 50) / 25.0

    # Current margin matters more as the game gets late. Pregame strength matters more early.
    expected_final_margin = fav_margin_now + (pregame_expected_margin * remaining_factor) + dominance_adj + regression_adj + pressure_adj
    expected_live_spread = round(-expected_final_margin, 1)

    actual_spread = safe_float(live_spread, None)
    spread_edge = None
    if actual_spread is not None:
        # Higher number is better for the favorite bettor. Example: fair -3, BetMGM +2 => +5 edge.
        spread_edge = round(actual_spread - expected_live_spread, 1)

    # Convert expected final margin into internal win probability. WNBA 1 possession swings are noisy,
    # so keep slope gentle.
    fair_win_prob = 1.0 / (1.0 + math.exp(-expected_final_margin / 7.5))
    expected_ml_price = prob_to_american(fair_win_prob)

    ml_edge_pct = None
    if live_ml is not None:
        book_prob = american_to_prob(live_ml)
        if book_prob is not None:
            ml_edge_pct = round((fair_win_prob - book_prob) * 100, 2)

    if spread_edge is not None and spread_edge >= EXPECTED_LINE_STRONG_EDGE:
        profile = "EXPECTED_LINE_STRONG_BUYBACK"
    elif spread_edge is not None and spread_edge >= EXPECTED_LINE_EDGE_BONUS_THRESHOLD:
        profile = "EXPECTED_LINE_BUYBACK"
    elif ml_edge_pct is not None and ml_edge_pct >= EXPECTED_ML_STRONG_EDGE:
        profile = "EXPECTED_ML_STRONG_BUYBACK"
    elif ml_edge_pct is not None and ml_edge_pct >= EXPECTED_ML_EDGE_BONUS_THRESHOLD:
        profile = "EXPECTED_ML_BUYBACK"
    else:
        profile = "EXPECTED_LINE_MONITOR"

    return {
        "enabled": True,
        "profile": profile,
        "opening_spread": opening_spread,
        "pregame_expected_margin": round(pregame_expected_margin, 1),
        "favorite_margin_now": fav_margin_now,
        "expected_final_margin": round(expected_final_margin, 1),
        "expected_live_spread": expected_live_spread,
        "actual_live_spread": actual_spread,
        "expected_spread_edge": spread_edge,
        "fair_win_prob": round(fair_win_prob * 100, 1),
        "expected_ml_price": expected_ml_price,
        "actual_ml_price": live_ml,
        "expected_ml_edge_pct": ml_edge_pct,
        "dominance_score": dominance.get("dominance_score"),
        "run_regression_score": regression.get("run_regression_score"),
        "ppi": ppi,
        "notes": (dominance.get("notes") or [])[:2] + (regression.get("notes") or [])[:2],
    }

def favorite_moneyline_buyback_scores(info, sg, markets):
    fav = pregame_favorite_side(sg, markets, info)
    if not fav:
        return None
    ml = choose_moneyline_for_side(markets, fav)
    if not ml or ml.get("price") is None:
        return None
    price = safe_int(ml.get("price"))
    if price < FAVORITE_ML_MIN_PRICE or price > FAVORITE_ML_MAX_PRICE:
        return None

    ctx = favorite_in_game_context(info, fav, sg)
    side_ctx = team_context_for_side(info, fav)
    strength_edge = safe_float(side_ctx.get("strength_edge"), 0)
    md = live_moneyline_consensus(markets, fav) if ENABLE_MARKET_DISCREPANCY_ENGINE else {"status": "DISABLED", "score": 0}
    implied = american_to_prob(price) or 0.5
    overreaction = favorite_market_overreaction_score(info, fav, sg, live_line=None, live_ml=price)
    expected_line = expected_live_favorite_line(info, fav, sg, live_spread=None, live_ml=price)

    expected_ml_bonus = 0.0
    if expected_line.get("enabled") and expected_line.get("expected_ml_edge_pct") is not None:
        edge_pct = safe_float(expected_line.get("expected_ml_edge_pct"), 0)
        if edge_pct >= EXPECTED_ML_STRONG_EDGE:
            expected_ml_bonus = 14
        elif edge_pct >= EXPECTED_ML_EDGE_BONUS_THRESHOLD:
            expected_ml_bonus = 8
        elif edge_pct <= -4:
            expected_ml_bonus = -10

    confidence = 42 + strength_edge * 1.55 + ctx["support_score"] * 0.34 + overreaction["market_overreaction_score"] * 0.16 + safe_float(md.get("score"), 0) * 0.18 + expected_ml_bonus * 0.80 - ctx["risk_score"] * 0.18
    value = 40 + (1.0 - implied) * 24 + strength_edge * 1.1 + safe_float(md.get("score"), 0) * 0.22 + ctx["support_score"] * 0.20 + overreaction["market_overreaction_score"] * 0.18 + expected_ml_bonus - ctx["risk_score"] * 0.16
    risk = ctx["risk_score"]
    if expected_ml_bonus < 0:
        risk += 6

    block_reason = ""
    action = "WATCH"
    if strength_edge < -2:
        block_reason = f"NO BET: favorite no longer rates better after context edge {strength_edge}"
    elif ctx.get("star_status") == "out":
        block_reason = "NO BET: favorite star marked out"
    elif ctx.get("risk_score", 0) >= 72:
        block_reason = "NO BET: favorite live risk too high: " + "; ".join(ctx.get("risk_notes") or [])
    elif md.get("status") == "AGAINST_CONSENSUS" and confidence < 82:
        block_reason = f"moneyline against market consensus: {md.get('reason')}"
    elif confidence >= FAVORITE_ML_MIN_CONFIDENCE and value >= FAVORITE_ML_MIN_VALUE and risk <= FAVORITE_ML_MAX_RISK:
        action = "STRIKE"
    elif FAVORITE_MARKET_SOFT_STRIKE and confidence >= FAVORITE_SOFT_MIN_CONFIDENCE and value >= FAVORITE_SOFT_MIN_VALUE and risk <= FAVORITE_SOFT_MAX_RISK and (ctx.get("run_against_favorite") or overreaction.get("market_overreaction_score", 0) >= 55 or ctx.get("dominance", {}).get("dominance_score", 0) >= FAVORITE_DOMINANCE_BONUS_THRESHOLD):
        action = "STRIKE"
        block_reason = ""
    else:
        block_reason = f"gate miss: conf {round(confidence)}, value {round(value)}, risk {risk}"

    return finalize_opportunity(info, sg, {
        "market_type": "MONEYLINE",
        "side": team_side_name(info, fav),
        "team_side": fav,
        "line": price,
        "price": price,
        "book": ml.get("book"),
        "edge": round((1.0 - implied) * 10, 1),
        "projected_total": projected_total(info, sg).get("projected_total"),
        "confidence": round(clamp(confidence)),
        "value_score": round(clamp(value)),
        "risk_score": round(clamp(risk)),
        "action": action,
        "block_reason": block_reason,
        "scenario": "FAVORITE_ML_BUYBACK_PLAYABLE_RANGE",
        "quarter_profile": quarter_profile(info),
        "scores": {"favorite_side": fav, "strength_edge": strength_edge, "favorite_context": ctx, "moneyline_price": price, "market_overreaction": overreaction, "expected_line": expected_line},
        "predictor": {},
        "market_misprice_score": round(clamp(42 + strength_edge * 1.7 + safe_float(md.get("score"), 0) + (overreaction.get("market_overreaction_score", 45) - 45) * 0.55 + (ctx.get("dominance", {}).get("dominance_score", 50) - 50) * 0.30 + max(-8, min(12, safe_float(expected_line.get("expected_ml_edge_pct"), 0) * 1.2)))),
        "predicted_spread_contract": "",
        "future_state_score": possession_pressure_index(info),
        "market_discrepancy": md,
        "market_discrepancy_status": md.get("status"),
        "market_discrepancy_score": md.get("score"),
        "profile_rule": "MONITOR",
    }, favorite_side=fav)

def favorite_spread_drop_scores(info, sg, markets):
    fav = pregame_favorite_side(sg, markets, info)
    if not fav:
        return None
    anchor = sg.get("pregame_anchor", {}) or {}
    opening = safe_float((anchor.get("spreads", {}) or {}).get(fav), None)
    if opening is None:
        opening = safe_float((sg.get("opening_spreads", {}) or {}).get(fav), None)
    if opening is None or opening > PREGAME_FAVORITE_MIN_SPREAD:
        return None
    spread = choose_spread_for_side(markets, fav)
    if not spread:
        return None
    live_spread = safe_float(spread.get("point"), None)
    if live_spread is None or live_spread < FAVORITE_LIVE_SPREAD_MIN or live_spread > FAVORITE_LIVE_SPREAD_MAX:
        return None
    swing = round(live_spread - opening, 1)
    if swing < FAVORITE_SPREAD_DROP_MIN_SWING:
        return None

    ctx = favorite_in_game_context(info, fav, sg)
    side_ctx = team_context_for_side(info, fav)
    strength_edge = safe_float(side_ctx.get("strength_edge"), 0)
    md = market_discrepancy_for_spread(spread) if ENABLE_MARKET_DISCREPANCY_ENGINE else {"status": "DISABLED", "score": 0}
    poss_value = possession_value_score(info, live_spread, projected_total(info, sg).get("pace", {}))
    overreaction = favorite_market_overreaction_score(info, fav, sg, live_line=live_spread, live_ml=None)
    expected_line = expected_live_favorite_line(info, fav, sg, live_spread=live_spread, live_ml=None)

    expected_spread_bonus = 0.0
    if expected_line.get("enabled") and expected_line.get("expected_spread_edge") is not None:
        exp_edge = safe_float(expected_line.get("expected_spread_edge"), 0)
        if exp_edge >= EXPECTED_LINE_STRONG_EDGE:
            expected_spread_bonus = 14
        elif exp_edge >= EXPECTED_LINE_EDGE_BONUS_THRESHOLD:
            expected_spread_bonus = 8
        elif exp_edge <= -2:
            expected_spread_bonus = -8

    confidence = 42 + strength_edge * 1.35 + min(max(swing, 0), 12) * 2.1 + poss_value * 0.14 + ctx["support_score"] * 0.18 + overreaction["market_overreaction_score"] * 0.16 + safe_float(md.get("score"), 0) * 0.14 + expected_spread_bonus * 0.75 - ctx["risk_score"] * 0.18
    value = 40 + min(max(swing, 0), 12) * 2.4 + poss_value * 0.17 + ctx["support_score"] * 0.14 + overreaction["market_overreaction_score"] * 0.18 + safe_float(md.get("score"), 0) * 0.18 + expected_spread_bonus - ctx["risk_score"] * 0.16
    risk = ctx["risk_score"]
    if expected_spread_bonus < 0:
        risk += 5

    block_reason = ""
    action = "WATCH"
    if strength_edge < -2:
        block_reason = f"NO BET: favorite no longer rates better after context edge {strength_edge}"
    elif ctx.get("star_status") == "out":
        block_reason = "NO BET: favorite star marked out"
    elif ctx.get("risk_score", 0) >= 72:
        block_reason = "NO BET: favorite spread risk too high: " + "; ".join(ctx.get("risk_notes") or [])
    elif md.get("status") == "AGAINST_CONSENSUS" and confidence < 82:
        block_reason = f"spread against market consensus: {md.get('reason')}"
    elif confidence >= FAVORITE_SPREAD_DROP_MIN_CONFIDENCE and value >= FAVORITE_SPREAD_DROP_MIN_VALUE and risk <= FAVORITE_SPREAD_DROP_MAX_RISK:
        action = "STRIKE"
    elif FAVORITE_MARKET_SOFT_STRIKE and confidence >= FAVORITE_SOFT_MIN_CONFIDENCE and value >= FAVORITE_SOFT_MIN_VALUE and risk <= FAVORITE_SOFT_MAX_RISK and (swing >= FAVORITE_SPREAD_DROP_MIN_SWING or ctx.get("run_against_favorite") or ctx.get("dominance", {}).get("dominance_score", 0) >= FAVORITE_DOMINANCE_BONUS_THRESHOLD):
        action = "STRIKE"
        block_reason = ""
    else:
        block_reason = f"gate miss: conf {round(confidence)}, value {round(value)}, risk {risk}"

    return finalize_opportunity(info, sg, {
        "market_type": "FAVORITE_SPREAD_DROP",
        "side": team_side_name(info, fav),
        "team_side": fav,
        "line": live_spread,
        "price": spread.get("price"),
        "book": spread.get("book"),
        "edge": round(swing, 1),
        "projected_total": projected_total(info, sg).get("projected_total"),
        "confidence": round(clamp(confidence)),
        "value_score": round(clamp(value)),
        "risk_score": round(clamp(risk)),
        "action": action,
        "block_reason": block_reason,
        "scenario": "PREGAME_FAVORITE_SPREAD_DROP_BUYBACK",
        "quarter_profile": quarter_profile(info),
        "scores": {"favorite_side": fav, "opening_spread": opening, "live_spread": live_spread, "spread_swing": swing, "favorite_context": ctx, "possession_value_score": poss_value, "strength_edge": strength_edge, "market_overreaction": overreaction, "expected_line": expected_line},
        "predictor": {},
        "market_misprice_score": round(clamp(42 + swing * 2.2 + safe_float(md.get("score"), 0) + (overreaction.get("market_overreaction_score", 45) - 45) * 0.45 + (ctx.get("dominance", {}).get("dominance_score", 50) - 50) * 0.25 + max(-8, min(12, safe_float(expected_line.get("expected_spread_edge"), 0) * 2.0)))),
        "predicted_spread_contract": round(max(0, swing / 2), 2),
        "future_state_score": possession_pressure_index(info),
        "market_discrepancy": md,
        "market_discrepancy_status": md.get("status"),
        "market_discrepancy_score": md.get("score"),
        "profile_rule": "MONITOR",
    }, favorite_side=fav)

# =============================================================================
# Decision, SMS, logging
# =============================================================================

def smart_unit_size_for_opp(opp, tier, base_units):
    """V3.0 price-aware staking. ML risk is capped because -150 is not the same as -110."""
    units = safe_float(base_units, UNIT_B)
    if not ENABLE_SMART_ML_STAKING or not opp:
        return units
    if opp.get("market_type") == "MONEYLINE":
        price = safe_int(opp.get("price"), -110)
        if price < ML_EXPENSIVE_CUTOFF:
            units *= 0.50
        elif price < -120:
            units *= 0.70
        elif price > 100:
            units *= 0.85
        units = max(ML_UNIT_MIN, min(ML_UNIT_MAX, units))
    return round(units, 2)

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

    if opp.get("market_type") == "TOTAL" and (sanity == "HARD_SANITY_CHECK" or abs(edge) > MAX_TOTAL_PAID_EDGE_POINTS):
        tier, units = "SMALL_LEAN", UNIT_SMALL
    elif score >= 64 and confidence >= 76 and value >= 72 and risk <= 48 and sanity == "NORMAL_EDGE":
        tier, units = "A_PLUS", UNIT_A_PLUS
    elif score >= 52 and confidence >= 66 and value >= 62 and risk <= 62 and sanity != "HARD_SANITY_CHECK":
        tier, units = "B_STRIKE", UNIT_B
    else:
        tier, units = "SMALL_LEAN", UNIT_SMALL

    units = smart_unit_size_for_opp(opp, tier, units)
    opp["alert_tier"] = tier
    opp["unit_size"] = units
    opp["sanity_tag"] = sanity
    opp["learning_score"] = round(score, 1)

    # Learning can remain wide, but paid alerts should be controlled.
    paid_alert = tier in {"A_PLUS", "B_STRIKE"}
    if opp.get("market_type") == "TOTAL" and (sanity == "HARD_SANITY_CHECK" or abs(edge) > MAX_TOTAL_PAID_EDGE_POINTS):
        paid_alert = False
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


def near_miss_quality_score(opp):
    if not opp:
        return 0.0
    return max(
        safe_float(opp.get("learning_score"), 0),
        safe_float(opp.get("confidence"), 0) * 0.35 +
        safe_float(opp.get("value_score"), 0) * 0.25 +
        safe_float(opp.get("market_misprice_score"), 0) * 0.20 +
        safe_float(opp.get("market_discrepancy_score"), 0) * 0.20 -
        safe_float(opp.get("risk_score"), 0) * 0.10,
    )

def previous_total_alerts(sg):
    return [a for a in sg.get("alerts", []) if a.get("market_type") == "TOTAL"]

def is_true_total_reversal(sg, opp):
    if not ALLOW_TRUE_REVERSAL or not opp or opp.get("market_type") != "TOTAL":
        return False
    prev_totals = previous_total_alerts(sg)
    if not prev_totals:
        return False
    prev = prev_totals[-1]
    if str(prev.get("side", "")).upper() == str(opp.get("side", "")).upper():
        return False
    previous_line = safe_float(prev.get("line"), None)
    current_line = safe_float(opp.get("line"), None)
    line_move = abs(current_line - previous_line) if previous_line is not None and current_line is not None else 0.0
    return (
        safe_float(opp.get("confidence"), 0) >= TRUE_REVERSAL_MIN_CONFIDENCE
        and safe_float(opp.get("edge"), 0) >= TRUE_REVERSAL_MIN_EDGE
        and safe_float(opp.get("market_discrepancy_score"), 0) >= TRUE_REVERSAL_MIN_MARKET_SCORE
        and line_move >= TRUE_REVERSAL_MIN_LINE_MOVE
    )

def opportunity_key(opp):
    if not opp:
        return ""
    if opp["market_type"] == "TOTAL":
        return f"TOTAL:{opp['side']}"
    if opp["market_type"] == "MONEYLINE":
        return f"MONEYLINE:{opp.get('team_side')}"
    if opp["market_type"] == "FAVORITE_SPREAD_DROP":
        return f"FAVORITE_SPREAD_DROP:{opp.get('team_side')}"
    return f"SPREAD:{opp.get('team_side')}"

def already_alerted(sg, opp):
    key = opportunity_key(opp)
    now_ts = time.time()

    # Professional position lock: never fire both OVER and UNDER in the same game.
    # Only allow an opposite total if the reversal is extreme and market-confirmed.
    if opp and opp.get("market_type") == "TOTAL" and TOTAL_POSITION_LOCK_MODE == "same_game":
        for a in sg.get("alerts", []):
            if a.get("market_type") != "TOTAL":
                continue
            prev_side = str(a.get("side", "")).upper()
            new_side = str(opp.get("side", "")).upper()
            if prev_side and new_side and prev_side != new_side:
                if is_true_total_reversal(sg, opp):
                    continue
                return True, f"TOTAL POSITION LOCK: existing {prev_side} alert blocks opposite {new_side}"

    for a in sg.get("alerts", []):
        if a.get("key") == key:
            age = now_ts - safe_float(a.get("ts"), 0)
            if ONE_STRIKE_PER_GAME_MARKET:
                return True, "one STRIKE already sent for this game/market"
            if age < ALERT_COOLDOWN_SECONDS:
                return True, "cooldown active"
    return False, ""


def expected_close_for_opp(opp):
    """Predict the likely next/closing line for learning comparison."""
    if not ENABLE_EXPECTED_CLOSE_TRACKING or not opp:
        return {}
    market = opp.get("market_type")
    line = safe_float(opp.get("line"), None)
    if line is None:
        return {}
    if market == "TOTAL":
        move = safe_float(opp.get("predicted_line_move"), 0)
        side = str(opp.get("side", "")).upper()
        expected = line + move if side == "OVER" else line - move
        edge = (expected - line) if side == "OVER" else (line - expected)
        return {"expected_close_line": round(expected, 2), "expected_close_edge": round(edge, 2), "expected_close_note": "model predicted total repricing"}
    if market == "FAVORITE_SPREAD_DROP":
        contract = safe_float(opp.get("predicted_spread_contract"), 0)
        expected = line - contract
        return {"expected_close_line": round(expected, 2), "expected_close_edge": round(line - expected, 2), "expected_close_note": "model predicted favorite spread contraction"}
    if market == "MONEYLINE":
        scores = opp.get("scores") or {}
        exp = scores.get("expected_line") or {}
        if exp.get("expected_ml_price") is not None:
            return {"expected_close_line": exp.get("expected_ml_price"), "expected_close_edge": exp.get("expected_ml_edge_pct"), "expected_close_note": "model fair ML vs BetMGM"}
    return {}

def alert_timing_quality(info, sg, opp):
    """Classify whether the alert appears early, fair, or chasing after the move."""
    if not opp:
        return {"alert_timing_quality": "UNKNOWN", "alert_timing_note": "no opportunity"}
    market = opp.get("market_type")
    if market == "TOTAL":
        hist = sg.get("line_history", []) or []
        recent = hist[-10:]
        if not recent:
            return {"alert_timing_quality": "NO_HISTORY", "alert_timing_note": "no recent line history"}
        points = [safe_float(h.get("total"), None) for h in recent if h.get("total") is not None]
        points = [x for x in points if x is not None]
        if not points:
            return {"alert_timing_quality": "NO_HISTORY", "alert_timing_note": "no recent total points"}
        line = safe_float(opp.get("line"), 0)
        if opp.get("side") == "OVER":
            if line <= min(points) + 0.5:
                q = "BEST_OR_EARLY"
            elif line >= max(points) - 0.5:
                q = "CHASE_RISK"
            else:
                q = "FAIR_TIMING"
        else:
            if line >= max(points) - 0.5:
                q = "BEST_OR_EARLY"
            elif line <= min(points) + 0.5:
                q = "CHASE_RISK"
            else:
                q = "FAIR_TIMING"
        return {"alert_timing_quality": q, "alert_timing_note": f"recent total range {min(points)}-{max(points)}"}
    scores = opp.get("scores") or {}
    overreaction = scores.get("market_overreaction") or {}
    swing = overreaction.get("spread_swing") or scores.get("spread_swing")
    if swing is not None and safe_float(swing) >= FAVORITE_MARKET_OVERREACTION_MIN:
        return {"alert_timing_quality": "DISCOUNT_WINDOW", "alert_timing_note": f"favorite discount swing {swing}"}
    return {"alert_timing_quality": "FAIR_TIMING", "alert_timing_note": "no obvious chase signal"}

def game_exposure_units(sg):
    return round(sum(safe_float(a.get("unit_size"), 0) for a in sg.get("alerts", [])), 2)

def daily_exposure_units(market_type=None):
    rows = [r for r in read_csv_rows(STRIKE_HISTORY_FILE) if r.get("date") == today()]
    if market_type:
        rows = [r for r in rows if r.get("market_type") == market_type]
    return round(sum(safe_float(r.get("unit_size"), 0) for r in rows), 2)

def exposure_cap_check(sg, opp):
    if not ENABLE_EXPOSURE_CAPS or not opp:
        return True, "exposure ok"
    units = safe_float(opp.get("unit_size"), UNIT_B)
    market = opp.get("market_type")
    if game_exposure_units(sg) + units > MAX_GAME_EXPOSURE_UNITS:
        return False, f"EXPOSURE CAP: game exposure {game_exposure_units(sg)}u + {units}u exceeds {MAX_GAME_EXPOSURE_UNITS}u"
    if daily_exposure_units() + units > MAX_DAILY_EXPOSURE_UNITS:
        return False, f"EXPOSURE CAP: daily exposure {daily_exposure_units()}u + {units}u exceeds {MAX_DAILY_EXPOSURE_UNITS}u"
    if daily_exposure_units(market) + units > MAX_MARKET_EXPOSURE_UNITS:
        return False, f"EXPOSURE CAP: {market} exposure {daily_exposure_units(market)}u + {units}u exceeds {MAX_MARKET_EXPOSURE_UNITS}u"
    if market == "MONEYLINE" and daily_exposure_units("MONEYLINE") + units > MAX_ML_EXPOSURE_UNITS:
        return False, f"EXPOSURE CAP: ML exposure {daily_exposure_units('MONEYLINE')}u + {units}u exceeds {MAX_ML_EXPOSURE_UNITS}u"
    return True, "exposure ok"

def recheck_betmgm_line_before_sms(info, opp):
    """Final BetMGM/current-market validation immediately before SMS."""
    if not ENABLE_BETMGM_RECHECK_BEFORE_SMS or not opp:
        return True, "recheck disabled/ok", opp
    latest_odds = get_odds()
    latest_markets = find_markets(latest_odds, info.get("home"), info.get("away"))
    if not latest_markets or latest_markets.get("books_seen", 0) <= 0:
        return False, "RECHECK BLOCK: no live market returned before SMS", opp
    row = {"market_type": opp.get("market_type"), "side": opp.get("side"), "team_side": opp.get("team_side"), "line": opp.get("line")}
    current_line, current_price, book = find_current_line_for_strike(latest_markets, row)
    if current_line is None:
        return False, "RECHECK BLOCK: BetMGM/current line no longer available", opp
    if book and USER_PLAYABLE_BOOKS and book not in USER_PLAYABLE_BOOKS:
        return False, f"RECHECK BLOCK: playable book changed to {book}", opp
    market = opp.get("market_type")
    if market == "TOTAL":
        delta = abs(safe_float(current_line) - safe_float(opp.get("line")))
        if delta > RECHECK_MAX_TOTAL_LINE_MOVE:
            return False, f"RECHECK BLOCK: total moved {delta} pts before SMS ({opp.get('line')} -> {current_line})", opp
    elif market == "FAVORITE_SPREAD_DROP":
        delta = abs(safe_float(current_line) - safe_float(opp.get("line")))
        if delta > RECHECK_MAX_SPREAD_LINE_MOVE:
            return False, f"RECHECK BLOCK: spread moved {delta} pts before SMS ({opp.get('line')} -> {current_line})", opp
    elif market == "MONEYLINE":
        old_prob = american_to_prob(opp.get("price"))
        new_prob = american_to_prob(current_line)
        if old_prob is not None and new_prob is not None:
            delta = abs(new_prob - old_prob) * 100
            if delta > RECHECK_MAX_ML_IMPLIED_MOVE_PCT:
                return False, f"RECHECK BLOCK: ML implied probability moved {round(delta,2)}% before SMS", opp
    opp["line"] = current_line if current_line is not None else opp.get("line")
    opp["price"] = current_price if current_price is not None else opp.get("price")
    opp["book"] = book or opp.get("book")
    opp["recheck_status"] = "PASSED"
    return True, "recheck passed", opp


def is_user_playable_book(book):
    return (book or "").lower() in USER_PLAYABLE_BOOKS

def paid_book_check(opp):
    if not REQUIRE_PLAYABLE_BOOK_FOR_PAID_ALERT or not opp:
        return True, "book ok"
    if is_user_playable_book(opp.get("book")):
        return True, "book ok"
    return False, f"BOOK BLOCK: paid alerts must be from playable book(s) {USER_PLAYABLE_BOOKS}; got {opp.get('book')}"

def correlated_market_conflict(existing_opps, opp):
    """Avoid double exposure in highly correlated same-game markets unless the second alert is elite."""
    if not ENABLE_CORRELATED_MARKET_EXPOSURE_CONTROL or not opp or not existing_opps:
        return False, "no correlated conflict"
    market = opp.get("market_type")
    for existing in existing_opps:
        em = existing.get("market_type")
        favorite_combo = market in {"MONEYLINE", "FAVORITE_SPREAD_DROP", "SPREAD"} and em in {"MONEYLINE", "FAVORITE_SPREAD_DROP", "SPREAD"}
        total_favorite_combo = (market == "TOTAL" and em in {"MONEYLINE", "FAVORITE_SPREAD_DROP", "SPREAD"}) or (em == "TOTAL" and market in {"MONEYLINE", "FAVORITE_SPREAD_DROP", "SPREAD"})
        if not (favorite_combo or total_favorite_combo):
            continue
        strong_enough = safe_float(opp.get("learning_score"), 0) >= CORRELATED_SECOND_ALERT_MIN_SCORE
        if CORRELATED_SECOND_ALERT_REQUIRE_A_PLUS and opp.get("alert_tier") != "A_PLUS":
            strong_enough = False
        if not strong_enough:
            return True, f"CORRELATED EXPOSURE BLOCK: {em} already selected; {market} needs stronger score/A+"
    return False, "no correlated conflict"

def warn_missing_team_ratings(info):
    if not ENABLE_MISSING_TEAM_WARNINGS:
        return
    known = {normalize_team(k) for k in TEAM_RATINGS.keys()}
    for side in ["away", "home"]:
        team = info.get(side)
        if not team or normalize_team(team) in known:
            continue
        # Avoid repeating the same warning all day.
        rows = [r for r in read_csv_rows(MISSING_TEAM_WARN_FILE) if r.get("date") == today() and normalize_team(r.get("team")) == normalize_team(team)]
        if rows:
            continue
        append_csv(MISSING_TEAM_WARN_FILE, {
            "date": today(), "time": now_local().isoformat(), "team": team,
            "message": "Team missing from WNBA_TEAM_RATINGS; using neutral 75 defaults",
        }, ["date", "time", "team", "message"])
        print(f"TEAM RATING WARNING | {team} missing from ratings; neutral defaults used")

def post_alert_key(row):
    return "|".join([str(row.get("event_id")), str(row.get("time")), str(row.get("market_type")), str(row.get("side")), str(row.get("line"))])

def existing_post_alert_keys():
    return {post_alert_key(r) for r in read_csv_rows(POST_ALERT_MOVE_FILE)}

def calculate_post_alert_move(row, current_line, current_price):
    market = row.get("market_type")
    if current_line in (None, ""):
        return "", "NO_LINE", "line unavailable"
    if market == "TOTAL":
        side = str(row.get("side", "")).upper()
        entry = safe_float(row.get("line"))
        current = safe_float(current_line)
        move = round(current - entry, 2) if side == "OVER" else round(entry - current, 2)
        quality = "FAVORABLE" if move >= POST_ALERT_MOVE_TOLERANCE_TOTAL else "AGAINST" if move <= -POST_ALERT_MOVE_TOLERANCE_TOTAL else "FLAT"
        return move, quality, f"5-min total move from {entry} to {current}"
    if market in {"FAVORITE_SPREAD_DROP", "SPREAD"}:
        entry = safe_float(row.get("line"))
        current = safe_float(current_line)
        move = round(entry - current, 2)  # +4.5 to +3.5 is favorable +1.0
        quality = "FAVORABLE" if move >= POST_ALERT_MOVE_TOLERANCE_SPREAD else "AGAINST" if move <= -POST_ALERT_MOVE_TOLERANCE_SPREAD else "FLAT"
        return move, quality, f"5-min spread move from {entry} to {current}"
    if market == "MONEYLINE":
        entry_prob = american_to_prob(row.get("price"))
        current_prob = american_to_prob(current_price if current_price not in (None, "") else current_line)
        if entry_prob is None or current_prob is None:
            return "", "NO_PRICE", "moneyline probability unavailable"
        # Favorable for a favorite ML when market probability increases after alert.
        move = round((current_prob - entry_prob) * 100, 2)
        quality = "FAVORABLE" if move >= POST_ALERT_MOVE_TOLERANCE_ML_PCT else "AGAINST" if move <= -POST_ALERT_MOVE_TOLERANCE_ML_PCT else "FLAT"
        return move, quality, f"5-min ML implied move {round(entry_prob*100,2)}% to {round(current_prob*100,2)}%"
    return "", "UNKNOWN", "unsupported market"

def update_post_alert_movement(label, info, markets):
    """After POST_ALERT_MOVE_CHECK_MINUTES, record whether BetMGM/market moved in our favor."""
    strikes = [r for r in read_csv_rows(STRIKE_HISTORY_FILE) if r.get("date") == today() and str(r.get("event_id")) == str(info.get("event_id"))]
    if not strikes:
        return
    done = existing_post_alert_keys()
    now_dt = now_local()
    for r in strikes:
        key = post_alert_key(r)
        if key in done:
            continue
        try:
            alert_dt = datetime.fromisoformat(r.get("time"))
        except Exception:
            continue
        age_min = (now_dt - alert_dt).total_seconds() / 60.0
        if age_min < POST_ALERT_MOVE_CHECK_MINUTES:
            continue
        current_line, current_price, book = find_current_line_for_strike(markets, r)
        move, quality, note = calculate_post_alert_move(r, current_line, current_price)
        append_csv(POST_ALERT_MOVE_FILE, {
            "date": today(), "time": now_local().isoformat(), "event_id": info.get("event_id"), "game": label,
            "alert_time": r.get("time"), "age_minutes": round(age_min, 1), "market_type": r.get("market_type"),
            "side": r.get("side"), "team_side": r.get("team_side"), "entry_line": r.get("line"),
            "entry_price": r.get("price"), "current_line": current_line, "current_price": current_price,
            "book": book, "post_alert_move": move, "post_alert_quality": quality, "note": note,
            "quarter_profile": r.get("quarter_profile"), "scenario": r.get("scenario"),
        }, ["date","time","event_id","game","alert_time","age_minutes","market_type","side","team_side","entry_line","entry_price","current_line","current_price","book","post_alert_move","post_alert_quality","note","quarter_profile","scenario"])

def approve_opportunity(sg, opp):
    if not opp or opp.get("action") != "STRIKE":
        return False, opp.get("block_reason", "not STRIKE") if opp else "no opportunity"

    # Absolute paid-alert blocks. These protect units even if confidence/value scores get inflated.
    if opp.get("market_type") == "TOTAL":
        if opp.get("sanity_tag") == "HARD_SANITY_CHECK":
            return False, f"log-only: hard sanity edge {opp.get('edge')} pts"
        if abs(safe_float(opp.get("edge"), 0)) > MAX_TOTAL_PAID_EDGE_POINTS:
            return False, f"log-only: total edge {opp.get('edge')} exceeds paid cap {MAX_TOTAL_PAID_EDGE_POINTS}"
        if str(opp.get("side", "")).upper() == "UNDER" and opp.get("quarter_profile") == "Q1_EARLY_SAMPLE":
            minutes_elapsed = safe_float((opp.get("scores") or {}).get("projection", {}).get("minutes_elapsed"), 0)
            # Fallback: not all projection dicts carry minutes_elapsed.
            if minutes_elapsed <= 0:
                minutes_elapsed = safe_float((opp.get("scores") or {}).get("minutes_elapsed"), 0)
            if minutes_elapsed < MIN_Q1_UNDER_MINUTES_ELAPSED:
                return False, f"log-only: Q1 UNDER too early before {MIN_Q1_UNDER_MINUTES_ELAPSED} minutes elapsed"

    if not opp.get("paid_alert", True):
        return False, f"log-only learning play: tier {opp.get('alert_tier')} | profile {opp.get('profile_rule', 'MONITOR')} | market {opp.get('market_discrepancy_status', 'N/A')}"
    book_ok, book_reason = paid_book_check(opp)
    if not book_ok:
        return False, book_reason
    blocked, reason = already_alerted(sg, opp)
    if blocked:
        return False, reason
    exposure_ok, exposure_reason = exposure_cap_check(sg, opp)
    if not exposure_ok:
        return False, exposure_reason
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
    scores = opp.get("scores", {}) or {}
    lines = []
    market_type = opp.get("market_type")

    if market_type == "TOTAL":
        proj = scores.get("projection", {}) or {}
        pace = proj.get("pace", {}) or {}
        eff = proj.get("eff", {}) or {}
        lines.append(f"Projected {opp.get('projected_total')} vs live {opp.get('line')} = {opp.get('edge')} pt edge")
        lines.append(f"Pace {pace.get('projected_game_possessions')} poss | left {pace.get('possessions_left')} | team PPP {proj.get('ppp')} | live wt {proj.get('live_weight')}")
        lines.append(f"Profile {opp.get('scenario')} | open move {scores.get('move_from_open')} | velocity {scores.get('velocity')} | short {scores.get('short_velocity')}")
        lines.append(f"Predictor: misprice {opp.get('market_misprice_score')} | future {opp.get('future_state_score')} | next move {opp.get('predicted_line_move')}")
        md = opp.get("market_discrepancy") or {}
        if md:
            lines.append(f"Market deficiency: {md.get('status')} | adv {md.get('advantage_points')} | books {md.get('books')} | stale {md.get('stale_line')}")
        lines.append(f"eFG {eff.get('efg')} | FTr {eff.get('ftr')} | TO {eff.get('turnovers')} | OREB {eff.get('off_reb')} | Fouls {eff.get('fouls')}")
        return lines[:5]

    if market_type == "FAVORITE_SPREAD_DROP":
        ctx = scores.get("favorite_context", {}) or {}
        run = ctx.get("run", {}) or {}
        exp = scores.get("expected_line", {}) or {}
        overreaction = scores.get("market_overreaction", {}) or {}
        lines.append(f"Pregame favorite {scores.get('opening_spread')} now live {opp.get('line')} | swing {scores.get('spread_swing')}")
        lines.append(f"Favorite context: support {ctx.get('support_score')} | risk {ctx.get('risk_score')} | notes {', '.join((ctx.get('risk_notes') or ctx.get('support_notes') or ['clean'])[:2])}")
        lines.append(f"Dominance {ctx.get('dominance', {}).get('dominance_score')} | Run regression {ctx.get('run_regression', {}).get('run_regression_score')} | Overreaction {overreaction.get('market_overreaction_score')}")
        if exp.get("enabled"):
            lines.append(f"Expected line: fair {exp.get('expected_live_spread')} vs live {exp.get('actual_live_spread')} | edge {exp.get('expected_spread_edge')}")
        lines.append(f"Strength edge {scores.get('strength_edge')} | market {opp.get('market_discrepancy_status')} | score {opp.get('market_discrepancy_score')}")
        lines.append(f"Recent run: home {run.get('home_run')}, away {run.get('away_run')} over {run.get('window_minutes')} min")
        return lines[:5]

    if market_type == "MONEYLINE":
        ctx = scores.get("favorite_context", {}) or {}
        run = ctx.get("run", {}) or {}
        exp = scores.get("expected_line", {}) or {}
        overreaction = scores.get("market_overreaction", {}) or {}
        lines.append(f"Favorite ML playable range {FAVORITE_ML_MIN_PRICE} to +{FAVORITE_ML_MAX_PRICE}; current {opp.get('price')}")
        lines.append(f"Favorite context: support {ctx.get('support_score')} | risk {ctx.get('risk_score')} | notes {', '.join((ctx.get('risk_notes') or ctx.get('support_notes') or ['clean'])[:2])}")
        lines.append(f"Dominance {ctx.get('dominance', {}).get('dominance_score')} | Run regression {ctx.get('run_regression', {}).get('run_regression_score')} | Overreaction {overreaction.get('market_overreaction_score')}")
        if exp.get("enabled"):
            lines.append(f"Expected ML: fair {exp.get('expected_ml_price')} | edge {exp.get('expected_ml_edge_pct')}%")
        lines.append(f"Strength edge {scores.get('strength_edge')} | market {opp.get('market_discrepancy_status')} | score {opp.get('market_discrepancy_score')}")
        lines.append(f"Recent run: home {run.get('home_run')}, away {run.get('away_run')} over {run.get('window_minutes')} min")
        return lines[:5]

    # Defensive fallback so a future/experimental market never crashes the SMS formatter.
    lines.append(f"Market {market_type}: confidence {opp.get('confidence')} | value {opp.get('value_score')} | risk {opp.get('risk_score')}")
    lines.append(f"Scenario {opp.get('scenario')} | side {opp.get('side')} | line {opp.get('line')} | price {opp.get('price')}")
    return lines[:5]

def format_sms(label, info, opp):
    price = opp.get("price")
    price_text = price if price is not None else "N/A"
    title = "🚨 SHIFT WNBA STRIKE — BET NOW"
    if opp["market_type"] == "TOTAL":
        play = f"{opp['side']} {opp['line']} ({price_text})"
        market = "TOTAL"
    elif opp["market_type"] == "MONEYLINE":
        play = f"{opp['side']} ML ({price_text})"
        market = "FAVORITE MONEYLINE BUYBACK"
    elif opp["market_type"] == "FAVORITE_SPREAD_DROP":
        play = f"{opp['side']} {opp['line']} ({price_text})"
        market = "PREGAME FAVORITE SPREAD DROP"
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
        "Mode: SAME-GAME TEST — hard total lock active" if opp.get("market_type") == "TOTAL" else "Mode: SAME-GAME TEST",
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
    elif opp["market_type"] == "MONEYLINE":
        lines.append(f"Target: favorite ML buyback | Live ML: {opp.get('price')}")
    elif opp["market_type"] == "FAVORITE_SPREAD_DROP":
        lines.append(f"Target: pregame favorite discount | Live spread: {opp['line']}")
    else:
        lines.append(f"Target: favorite around +{FAVORITE_BUYBACK_TARGET} | Live: +{opp['line']}")
    if SHOW_LIVE_CONTEXT_IN_ALERTS:
        fav_side = opp.get("team_side") if opp.get("market_type") in {"MONEYLINE", "SPREAD", "FAVORITE_SPREAD_DROP"} else None
        lines.append("")
        lines.append("Live Context:")
        for ctx_line in live_context_lines(info, favorite_side=fav_side, ctx=opp.get("live_context"))[:3]:
            lines.append(f"• {ctx_line}")
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
    "alert_tier","unit_size","sanity_tag","learning_score","profile_rule","paid_alert","market_discrepancy_status","market_discrepancy_score","market_advantage_points",
    "favorite_alert_margin","favorite_final_margin","favorite_retook_control","cover_margin","dominance_score","run_regression_score","market_overreaction_score",
    "expected_live_spread","actual_live_spread","expected_spread_edge","expected_ml_price","expected_ml_edge_pct",
    "expected_close_line","expected_close_edge","expected_close_note","alert_timing_quality","alert_timing_note","recheck_status",
    "closing_line","closing_price","clv","expected_close_delta","final_score","final_total","result","units"
]

def log_strike(info, label, opp):
    scores = opp.get("scores") or {}
    fav_ctx = scores.get("favorite_context") or {}
    dominance = fav_ctx.get("dominance") or {}
    regression = fav_ctx.get("run_regression") or {}
    overreaction = scores.get("market_overreaction") or {}
    expected_line = scores.get("expected_line") or {}
    expected_close = expected_close_for_opp(opp)
    timing = {"alert_timing_quality": opp.get("alert_timing_quality"), "alert_timing_note": opp.get("alert_timing_note")}
    fav_side = opp.get("team_side")
    fav_alert_margin = ""
    if fav_side in {"home", "away"}:
        fav_alert_margin = side_score(info, fav_side) - side_score(info, opponent_side(fav_side))
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
        "predicted_market_move": opp.get("predicted_line_move") if opp.get("market_type") == "TOTAL" else opp.get("predicted_spread_contract", ""),
        "alert_tier": opp.get("alert_tier"), "unit_size": opp.get("unit_size"),
        "sanity_tag": opp.get("sanity_tag"), "learning_score": opp.get("learning_score"),
        "profile_rule": opp.get("profile_rule"),
        "paid_alert": opp.get("paid_alert"),
        "market_discrepancy_status": opp.get("market_discrepancy_status"),
        "market_discrepancy_score": opp.get("market_discrepancy_score"),
        "market_advantage_points": (opp.get("market_discrepancy") or {}).get("advantage_points"),
        "favorite_alert_margin": fav_alert_margin,
        "favorite_final_margin": "",
        "favorite_retook_control": "",
        "cover_margin": "",
        "dominance_score": dominance.get("dominance_score"),
        "run_regression_score": regression.get("run_regression_score"),
        "market_overreaction_score": overreaction.get("market_overreaction_score"),
        "expected_live_spread": expected_line.get("expected_live_spread"),
        "actual_live_spread": expected_line.get("actual_live_spread"),
        "expected_spread_edge": expected_line.get("expected_spread_edge"),
        "expected_ml_price": expected_line.get("expected_ml_price"),
        "expected_ml_edge_pct": expected_line.get("expected_ml_edge_pct"),
        "expected_close_line": expected_close.get("expected_close_line"),
        "expected_close_edge": expected_close.get("expected_close_edge"),
        "expected_close_note": expected_close.get("expected_close_note"),
        "alert_timing_quality": timing.get("alert_timing_quality"),
        "alert_timing_note": timing.get("alert_timing_note"),
        "recheck_status": opp.get("recheck_status", "NOT_RUN"),
        "score": f"{info['away_score']}-{info['home_score']}",
        "period": info.get("period"), "clock": info.get("clock"),
        "closing_line": "", "closing_price": "", "clv": "", "expected_close_delta": "",
        "final_score": "", "final_total": "", "result": "", "units": "",
    }, STRIKE_FIELDS)
    post_tracking_event("wnba_strike", {
        "date": today(), "time": now_local().isoformat(), "event_id": info.get("event_id"), "game": label,
        "market_type": opp.get("market_type"), "side": opp.get("side"), "team_side": opp.get("team_side"),
        "line": opp.get("line"), "price": opp.get("price"), "book": opp.get("book"),
        "scenario": opp.get("scenario"), "quarter_profile": opp.get("quarter_profile"),
        "confidence": opp.get("confidence"), "value_score": opp.get("value_score"), "risk_score": opp.get("risk_score"),
        "alert_tier": opp.get("alert_tier"), "unit_size": opp.get("unit_size"), "edge": opp.get("edge"),
    })

def log_near_miss(info, label, opp, reason):
    if not opp:
        return
    quality = near_miss_quality_score(opp)
    reason_text = str(reason or opp.get("block_reason") or "")
    if quality < MIN_NEAR_MISS_LOG_SCORE and not (LOG_BLOCKED_POSITION_LOCKS and "POSITION LOCK" in reason_text.upper()):
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
        "predicted_market_move": opp.get("predicted_line_move") if opp.get("market_type") == "TOTAL" else opp.get("predicted_spread_contract", ""),
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
    elif market == "MONEYLINE":
        base = "Moneyline result graded by final winner."
        if row.get("favorite_retook_control"):
            base += f" Favorite retook/held control: {row.get('favorite_retook_control')}."
    else:
        base = "Spread result graded by cover margin."
        if row.get("cover_margin") not in (None, ""):
            base += f" Cover margin {row.get('cover_margin')}."

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
        play = f"{side} {line}" if market == "TOTAL" else f"{side} ML" if market == "MONEYLINE" else f"{side} {line}"
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
    if market_type in {"SPREAD", "FAVORITE_SPREAD_DROP"} and team_side:
        offer = choose_spread_for_side(markets, team_side)
        if offer:
            return offer.get("point"), offer.get("price"), offer.get("book")
    if market_type == "MONEYLINE" and team_side:
        offer = choose_moneyline_for_side(markets, team_side)
        if offer:
            return offer.get("price"), offer.get("price"), offer.get("book")
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

    if market_type in {"SPREAD", "FAVORITE_SPREAD_DROP"}:
        # If we got +4.5 and close is +3.5, we beat the line by +1.0.
        return round(entry - current, 2)

    if market_type == "MONEYLINE":
        entry_prob = american_to_prob(entry)
        current_prob = american_to_prob(current)
        if entry_prob is None or current_prob is None:
            return ""
        # If we took -120 and it moved to -160, implied probability rose and CLV is positive.
        return round((current_prob - entry_prob) * 100, 2)

    return ""


def decision_row_time(row):
    return row.get("timestamp") or row.get("time") or ""

def decision_outcome_bucket_for_pass(row, result, hypothetical):
    """Separate a useful missed winner from a good pass/avoided loss."""
    action = row.get("action")
    category = row.get("pass_reason_category") or pass_reason_category(row.get("reject_reason"), row.get("decision_type"))
    clv = safe_float(row.get("clv"), 0) if row.get("clv") not in (None, "") else 0
    if action in {"BET_NOW", "TEST_UNIT"}:
        return "ACCEPTED_BET_GRADED"
    if result == "WIN":
        if category in {"PRICE_PASS", "DATA_QUALITY_PASS", "EXPOSURE_PASS"}:
            return f"PASSED_WIN_ACCEPTABLE_{category}"
        if clv >= GOOD_CLV_THRESHOLD:
            return "TRUE_MISSED_EDGE_GOOD_CLV"
        return f"PASSED_WIN_REVIEW_{category}"
    if result == "LOSS":
        return f"GOOD_PASS_AVOIDED_LOSS_{category}"
    return f"PASSED_PUSH_NEUTRAL_{category}"

def calculate_decision_outcome_units(action, result, price, unit_size, row=None):
    """Return actual and hypothetical units for accepted and passed decisions."""
    row = row or {}
    stake = safe_float(unit_size, UNIT_B)
    if stake <= 0:
        stake = UNIT_B
    hypothetical = result_units(result, price, stake)
    if action in {"BET_NOW", "TEST_UNIT"}:
        actual = hypothetical
        missed = 0.0
    else:
        actual = 0.0
        missed = hypothetical
    bucket = decision_outcome_bucket_for_pass({**row, "action": action}, result, hypothetical)
    return round(actual, 2), round(hypothetical, 2), round(actual - hypothetical, 2), round(missed, 2), bucket

def update_decision_market_tracking(label, info, markets):
    """Track CLV and 5-minute market movement for every logged decision, not only SMS alerts.

    Google Sheets webhooks append records, so this also emits a wnba_decision_market_update
    event whenever a decision row receives CLV or post-5m movement fields.
    """
    if not WNBA_ENABLE_DECISION_LOG:
        return
    rows = read_csv_rows(WNBA_DECISION_LOG_FILE)
    if not rows:
        return
    changed = False
    now_dt = now_local()
    for r in rows:
        if r.get("date") != today() or str(r.get("event_id")) != str(info.get("event_id")):
            continue
        if r.get("result") in {"WIN", "LOSS", "PUSH"}:
            continue
        current_line, current_price, book = find_current_line_for_strike(markets, r)
        clv = calculate_clv(r, current_line)
        row_changed = False
        if clv != "":
            r["closing_line"] = current_line
            r["closing_price"] = current_price
            r["clv"] = clv
            row_changed = True
        # 5-minute move for all decisions, not just BET_NOW.
        if r.get("post_5m_move") in (None, ""):
            try:
                decision_dt = datetime.fromisoformat(decision_row_time(r))
                age_min = (now_dt - decision_dt).total_seconds() / 60.0
            except Exception:
                age_min = 0
            if age_min >= POST_ALERT_MOVE_CHECK_MINUTES:
                move, quality, note = calculate_post_alert_move(r, current_line, current_price)
                if move != "":
                    r["post_5m_line"] = current_line
                    r["post_5m_move"] = move
                    # Reuse alert_timing fields rather than adding another massive set of columns.
                    if not r.get("alert_timing_quality"):
                        r["alert_timing_quality"] = quality
                    if not r.get("alert_timing_note"):
                        r["alert_timing_note"] = note
                    row_changed = True
        if row_changed:
            changed = True
            payload = {k: r.get(k, "") for k in wnba_decision_log_fieldnames()}
            payload["market_tracking_updated_at"] = now_local().isoformat()
            post_tracking_event("wnba_decision_market_update", payload)
    if changed:
        write_csv_rows(WNBA_DECISION_LOG_FILE, wnba_decision_log_fieldnames(), rows)

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
    grade_completed_wnba_decision_log(event_id, label, final_score)
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

        favorite_final_margin = ""
        cover_margin = ""
        favorite_retook_control = ""

        if market_type == "TOTAL":
            if side == "OVER":
                result = "WIN" if final_total > line else "LOSS" if final_total < line else "PUSH"
            elif side == "UNDER":
                result = "WIN" if final_total < line else "LOSS" if final_total > line else "PUSH"
        elif market_type in {"SPREAD", "FAVORITE_SPREAD_DROP"}:
            margin_for_side = home_margin if team_side == "home" else -home_margin
            favorite_final_margin = margin_for_side
            cover_margin = round(margin_for_side + line, 2)
            favorite_retook_control = "YES" if margin_for_side > 0 else "NO"
            result = "WIN" if cover_margin > 0 else "LOSS" if cover_margin < 0 else "PUSH"
        elif market_type == "MONEYLINE":
            if team_side == "home":
                favorite_final_margin = home_margin
                favorite_retook_control = "YES" if home_margin > 0 else "NO"
                result = "WIN" if home_margin > 0 else "LOSS"
            elif team_side == "away":
                favorite_final_margin = -home_margin
                favorite_retook_control = "YES" if home_margin < 0 else "NO"
                result = "WIN" if home_margin < 0 else "LOSS"

        closing_line, closing_price, clv = latest_clv_for_strike(r)
        out = dict(r)
        out["closing_line"] = closing_line
        out["closing_price"] = closing_price
        out["clv"] = clv
        if out.get("expected_close_line") not in (None, "") and closing_line not in (None, ""):
            try:
                out["expected_close_delta"] = round(safe_float(closing_line) - safe_float(out.get("expected_close_line")), 2)
            except Exception:
                out["expected_close_delta"] = ""
        out["final_score"] = final_score
        out["final_total"] = final_total
        out["favorite_final_margin"] = favorite_final_margin
        out["favorite_retook_control"] = favorite_retook_control
        out["cover_margin"] = cover_margin
        out["result"] = result
        out["units"] = result_units(result, price, r.get("unit_size", 1.0))
        out["graded_at"] = now_local().isoformat()
        append_csv(GRADED_RESULTS_FILE, out, list(out.keys()))
        new_graded.append(out)
        print(f"GRADED | {label} | {market_type} {side} {line} | {result} | CLV {clv} | Final {final_score}")
        post_tracking_event("wnba_result", out)

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

def clv_summary_by_market(date_text):
    rows = [r for r in read_csv_rows(CLV_HISTORY_FILE) if r.get("date") == date_text and r.get("clv") not in (None, "")]
    buckets = {}
    for r in rows:
        mk = r.get("market_type") or "UNKNOWN"
        buckets.setdefault(mk, []).append(safe_float(r.get("clv"), 0))
    lines = []
    for mk, vals in sorted(buckets.items()):
        if not vals:
            continue
        pos = sum(1 for v in vals if v >= GOOD_CLV_THRESHOLD)
        avgv = round(sum(vals) / len(vals), 2)
        unit = "implied%" if mk == "MONEYLINE" else "pts"
        lines.append(f"{mk} CLV: avg {avgv}{unit} | +CLV {pos}/{len(vals)}")
    return lines


def market_bucket_key(row):
    mk = row.get("market_type") or "UNKNOWN"
    if mk == "TOTAL":
        return f"TOTAL_{str(row.get('side','')).upper() or 'UNKNOWN'}"
    return mk

def market_split_summary_lines(date_text):
    rows = [r for r in read_csv_rows(GRADED_RESULTS_FILE) if r.get("date") == date_text]
    buckets = {}
    for r in rows:
        key = market_bucket_key(r)
        rec = buckets.setdefault(key, {"rows": []})
        rec["rows"].append(r)
    lines = []
    preferred = ["TOTAL_OVER", "TOTAL_UNDER", "MONEYLINE", "FAVORITE_SPREAD_DROP", "SPREAD"]
    for key in preferred + sorted(k for k in buckets.keys() if k not in preferred):
        if key not in buckets:
            continue
        sm = summarize_rows(buckets[key]["rows"])
        clvs = [safe_float(r.get("clv"), None) for r in buckets[key]["rows"] if r.get("clv") not in (None, "")]
        clvs = [c for c in clvs if c is not None]
        avg_c = round(sum(clvs) / len(clvs), 2) if clvs else 0.0
        lines.append(f"{key}: {sm['wins']}-{sm['losses']}-{sm['pushes']} | {sm['units']}u | ROI {sm['roi']}% | CLV {avg_c}")
    return lines

def favorite_learning_lines(date_text):
    rows = [r for r in read_csv_rows(GRADED_RESULTS_FILE) if r.get("date") == date_text and r.get("market_type") in {"MONEYLINE", "FAVORITE_SPREAD_DROP", "SPREAD"}]
    if not rows:
        return []
    retook = sum(1 for r in rows if str(r.get("favorite_retook_control", "")).upper() == "YES")
    dom = [safe_float(r.get("dominance_score"), None) for r in rows if r.get("dominance_score") not in (None, "")]
    dom = [d for d in dom if d is not None]
    reg = [safe_float(r.get("run_regression_score"), None) for r in rows if r.get("run_regression_score") not in (None, "")]
    reg = [d for d in reg if d is not None]
    exp = [safe_float(r.get("expected_spread_edge"), None) for r in rows if r.get("expected_spread_edge") not in (None, "")]
    exp = [e for e in exp if e is not None]
    lines = [f"Favorite control: retook/held lead {retook}/{len(rows)}"]
    if dom:
        lines.append(f"Favorite dominance avg: {round(sum(dom)/len(dom),1)}")
    if reg:
        lines.append(f"Run regression avg: {round(sum(reg)/len(reg),1)}")
    if exp:
        lines.append(f"Expected spread edge avg: {round(sum(exp)/len(exp),1)} pts")
    return lines


def quarter_market_learning_lines(date_text):
    rows = [r for r in read_csv_rows(GRADED_RESULTS_FILE) if r.get("date") == date_text]
    buckets = {}
    for r in rows:
        key = f"{market_bucket_key(r)}|{r.get('quarter_profile') or 'UNKNOWN'}"
        buckets.setdefault(key, []).append(r)
    lines = []
    for key, vals in sorted(buckets.items()):
        if len(vals) < 1:
            continue
        sm = summarize_rows(vals)
        clvs = [safe_float(r.get("clv"), None) for r in vals if r.get("clv") not in (None, "")]
        clvs = [c for c in clvs if c is not None]
        avg_c = round(sum(clvs) / len(clvs), 2) if clvs else 0.0
        action = "TRUST" if sm["units"] > 0 and avg_c >= 0 else "TIGHTEN" if sm["units"] < 0 and avg_c < 0 else "MONITOR"
        lines.append(f"{key}: {sm['wins']}-{sm['losses']}-{sm['pushes']} | {sm['units']}u | CLV {avg_c} | {action}")
    return lines

def execution_quality_lines(date_text):
    rows = [r for r in read_csv_rows(GRADED_RESULTS_FILE) if r.get("date") == date_text]
    move_rows = [r for r in read_csv_rows(POST_ALERT_MOVE_FILE) if r.get("date") == date_text]
    if not rows and not move_rows:
        return []
    timing = {}
    for r in rows:
        q = r.get("alert_timing_quality") or "UNKNOWN"
        timing[q] = timing.get(q, 0) + 1
    deltas = [safe_float(r.get("expected_close_delta"), None) for r in rows if r.get("expected_close_delta") not in (None, "")]
    deltas = [d for d in deltas if d is not None]
    out = []
    if timing:
        out.append("Timing: " + " | ".join(f"{k} {v}" for k, v in sorted(timing.items())))
    if move_rows:
        fav = sum(1 for r in move_rows if r.get("post_alert_quality") == "FAVORABLE")
        flat = sum(1 for r in move_rows if r.get("post_alert_quality") == "FLAT")
        against = sum(1 for r in move_rows if r.get("post_alert_quality") == "AGAINST")
        out.append(f"5-min market move: FAVORABLE {fav} | FLAT {flat} | AGAINST {against}")
    if deltas:
        out.append(f"Expected close delta avg: {round(sum(deltas)/len(deltas),2)}")
    return out[:4]

def format_daily_report(summary):
    season = summary.get("season_summary", {}) or {}
    lines = [
        f"📊 SHIFT WNBA DAILY SUMMARY — {summary['date']}",
        "",
        f"Today: {summary['wins']}-{summary['losses']}-{summary['pushes']} | {summary['units']}u",
        f"Risked: {summary.get('risked', 0)}u | ROI: {summary.get('roi', 0)}%",
        f"Alerts: {summary['strikes']} STRIKE | Near-misses: {summary['near_misses']}",
        f"CLV: avg {summary['avg_clv']} | +CLV {summary['positive_clv_count']}/{summary['clv_snapshots']}",
        *clv_summary_by_market(summary["date"])[:4],
        "",
        "Market Split:",
        *market_split_summary_lines(summary["date"])[:6],
        "",
        "Favorite Learning:",
        *favorite_learning_lines(summary["date"])[:4],
        "",
        "Quarter / Market Learning:",
        *quarter_market_learning_lines(summary["date"])[:6],
        "",
        "Execution Quality:",
        *execution_quality_lines(summary["date"])[:3],
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
    ]
    lines.extend(wnba_decision_report_lines(summary.get('date')))
    lines.append("")
    lines.extend(wnba_passed_play_learning_lines(summary.get('date')))
    lines.append("")
    lines.extend(wnba_feature_learning_lines(summary.get('date')))
    lines.extend([
        "",
        "Rule: trust +units/+CLV profiles, tighten -units/-CLV profiles, keep SMALL_LEAN log-only."
    ])
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
            for path in [STRIKE_HISTORY_FILE, GRADED_RESULTS_FILE, CLV_HISTORY_FILE, NEAR_MISS_FILE, DAILY_SUMMARY_FILE, PROFILE_SUMMARY_FILE, MARKET_DISCREPANCY_FILE, PROFILE_RULES_FILE, BANKROLL_TRACKER_FILE, POST_ALERT_MOVE_FILE, MISSING_TEAM_WARN_FILE, WNBA_DECISION_LOG_FILE, WNBA_FEATURE_LEARNING_FILE, WNBA_ADAPTIVE_CONFIG_FILE]:
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

def choose_best_opportunity(*opps):
    candidates = [o for o in opps if o]
    strikes = [o for o in candidates if o.get("action") == "STRIKE"]
    if strikes:
        def rank(o):
            spread_bonus = 7 if o.get("market_type") in {"SPREAD", "FAVORITE_SPREAD_DROP"} and ("PLUS_4_5" in o.get("scenario", "") or "SPREAD_DROP" in o.get("scenario", "")) else 0
            ml_bonus = 5 if o.get("market_type") == "MONEYLINE" else 0
            clv_bonus = 4 if o.get("book") in USER_PLAYABLE_BOOKS else 0
            paid_bonus = 6 if o.get("paid_alert") else -20
            return o.get("confidence", 0) + o.get("value_score", 0) * 0.45 - o.get("risk_score", 0) * 0.22 + spread_bonus + ml_bonus + clv_bonus + paid_bonus
        return sorted(strikes, key=rank, reverse=True)[0]
    return None

def select_approved_opportunities(sg, opportunities):
    candidates = [o for o in opportunities if o and o.get("action") == "STRIKE"]
    if not candidates:
        return []
    def rank(o):
        market_bonus = 13 if o.get("market_type") in {"MONEYLINE", "FAVORITE_SPREAD_DROP"} else 5 if o.get("market_type") == "SPREAD" else 0
        clv_bonus = 4 if o.get("book") in USER_PLAYABLE_BOOKS else 0
        paid_bonus = 8 if o.get("paid_alert") else -25
        aplus_bonus = 8 if o.get("alert_tier") == "A_PLUS" else 0
        return safe_float(o.get("confidence")) + safe_float(o.get("value_score")) * 0.45 - safe_float(o.get("risk_score")) * 0.25 + market_bonus + clv_bonus + paid_bonus + aplus_bonus
    ordered = sorted(candidates, key=rank, reverse=True)
    approved = []
    used_markets = set()
    favorite_market_sent = False
    for opp in ordered:
        if len(approved) >= max(1, MAX_ALERTS_PER_GAME_CHECK if ENABLE_MULTI_MARKET_ALERTS else 1):
            break
        if len(approved) >= 1 and REQUIRE_A_PLUS_FOR_SECOND_ALERT and opp.get("alert_tier") != "A_PLUS":
            continue
        if opp.get("market_type") in used_markets:
            continue

        # V2.8 conflict control: do not send both favorite ML and favorite spread in the
        # same check unless explicitly allowed. The higher-ranked one becomes the live alert;
        # the other still goes to near-miss/learning logs.
        is_favorite_market = opp.get("market_type") in {"MONEYLINE", "FAVORITE_SPREAD_DROP", "SPREAD"}
        if ENABLE_FAVORITE_MARKET_CONFLICT_CONTROL and is_favorite_market and favorite_market_sent and not ALLOW_ALIGNED_FAVORITE_ML_AND_SPREAD:
            opp["approval_block_reason"] = "FAVORITE MARKET CONFLICT: higher-ranked favorite ML/spread alert already selected"
            continue

        conflict, conflict_reason = correlated_market_conflict(approved, opp)
        if conflict:
            opp["approval_block_reason"] = conflict_reason
            continue

        ok, reason = approve_opportunity(sg, opp)
        if ok:
            approved.append(opp)
            used_markets.add(opp.get("market_type"))
            if is_favorite_market:
                favorite_market_sent = True
        else:
            opp["approval_block_reason"] = reason
    return approved

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

        warn_missing_team_ratings(info)
        markets = find_markets(odds, info["home"], info["away"])
        update_line_state(sg, info, markets)
        recent_game_snapshots(sg, info)
        update_clv_snapshots(label, info, markets)
        update_post_alert_movement(label, info, markets)
        update_decision_market_tracking(label, info, markets)

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
        base_total_scores = total_scores(info, sg, markets)
        total_over_opp = build_total_side_opportunity(info, sg, markets, "OVER", base_scores=base_total_scores) if base_total_scores else None
        total_under_opp = build_total_side_opportunity(info, sg, markets, "UNDER", base_scores=base_total_scores) if base_total_scores else None
        total_opp = choose_best_total_opportunity(total_over_opp, total_under_opp)
        fav_ml_opp = favorite_moneyline_buyback_scores(info, sg, markets) if ENABLE_FAVORITE_MONEYLINE_BUYBACK else None
        fav_spread_drop_opp = favorite_spread_drop_scores(info, sg, markets) if ENABLE_FAVORITE_SPREAD_DROP else None
        # Keep OVER and UNDER as separate loggable engines, but only allow one TOTAL into the paid-alert selector.
        opportunities = [total_opp, fav_ml_opp, fav_spread_drop_opp]
        total_learning_candidates = [o for o in [total_over_opp, total_under_opp] if o and o is not total_opp]
        approved_opps = select_approved_opportunities(sg, opportunities)

        for opp in opportunities:
            if not opp:
                continue
            if opp not in approved_opps:
                reason = opp.get("approval_block_reason") or opp.get("block_reason")
                log_near_miss(info, label, opp, reason)
                log_wnba_decision(sg, info, label, opp, action=wnba_decision_action_from_opp(opp, approved=False, reason=reason), decision_type="EVALUATED_REJECTED", reject_reason=reason)
        for opp in total_learning_candidates:
            reason = f"opposite total engine log-only; selected side was {total_opp.get('side') if total_opp else 'NONE'}"
            log_near_miss(info, label, opp, reason)
            log_wnba_decision(sg, info, label, opp, action="RESEARCH_ONLY", decision_type="OPPOSITE_TOTAL_ENGINE", reject_reason=reason)

        for best in approved_opps:
            timing = alert_timing_quality(info, sg, best)
            best["alert_timing_quality"] = timing.get("alert_timing_quality")
            best["alert_timing_note"] = timing.get("alert_timing_note")
            recheck_ok, recheck_reason, best = recheck_betmgm_line_before_sms(info, best)
            if not recheck_ok:
                best["approval_block_reason"] = recheck_reason
                log_near_miss(info, label, best, recheck_reason)
                log_wnba_decision(sg, info, label, best, action="NO_BET", decision_type="RECHECK_BLOCK", reject_reason=recheck_reason)
                print(f"BET NOW BLOCKED | {label} | {recheck_reason}")
                continue
            sms = format_sms(label, info, best)
            send_text(sms)
            log_wnba_decision(sg, info, label, best, action=wnba_decision_action_from_opp(best, approved=True), decision_type="APPROVED_SMS", reject_reason="")
            log_strike(info, label, best)
            log_market_discrepancy(info, label, best)
            mark_alert_sent(sg, best)
            save_state(st)

    maybe_send_daily_report(st)
    save_state(st)
    return FAST_POLL_SECONDS if active_found else ACTIVE_POLL_SECONDS if needs_odds else SLOW_POLL_SECONDS

def main():
    print(f"BOOT: {APP_BUILD_LABEL}")
    print(f"DATE: {today()} | TZ: America/Phoenix")
    print(f"Playable books: {USER_PLAYABLE_BOOKS}")
    print("Strategy: WNBA BetMGM Pro V3.4 — stable decision/opportunity IDs, Sheets upsert hints, accepted + passed-play outcome grading, feature learning, and adaptive profile config.")
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
