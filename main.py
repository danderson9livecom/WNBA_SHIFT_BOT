
import os
import time
import json
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

# =========================
# WNBA SHIFT V3.1
# MARKET INEFFICIENCY BOT
# COST-OPTIMIZED VERSION
# =========================
#
# Main goal:
# Find live market inefficiencies between -140 and +100.
#
# Cost-saving changes from V3:
# 1. Does NOT pull ESPN summary every loop unless the game/line changed.
# 2. Uses per-game sleep timing instead of treating every game the same.
# 3. Skips heavy model work when market and score are unchanged.
# 4. Stops monitoring obvious dead/blowout games.
# 5. Uses alert cooldowns to avoid repeated reprocessing/spam.
# 6. Pulls full markets in one odds call, but avoids summary/model calls unless needed.
#
# Expected API/runtime reduction:
# Usually 50-70% fewer heavy summary/model cycles.

TZ = ZoneInfo("America/Phoenix")
STATE_FILE = "wnba_shift_state_v31_cost_optimized.json"

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
ALERT_TO_NUMBER = os.getenv("ALERT_TO_NUMBER", "")

SPORT_KEY = "basketball_wnba"

# Global sleep bounds
SLOW_POLL_SECONDS = int(os.getenv("SLOW_POLL_SECONDS", "300"))
PREGAME_POLL_SECONDS = int(os.getenv("PREGAME_POLL_SECONDS", "180"))
ACTIVE_POLL_SECONDS = int(os.getenv("ACTIVE_POLL_SECONDS", "60"))
FAST_POLL_SECONDS = int(os.getenv("FAST_POLL_SECONDS", "20"))
LATE_FAST_POLL_SECONDS = int(os.getenv("LATE_FAST_POLL_SECONDS", "15"))

PREGAME_WINDOW_MINUTES = int(os.getenv("PREGAME_WINDOW_MINUTES", "75"))

# Playable price range
MIN_PRICE = int(os.getenv("MIN_PRICE", "-140"))
MAX_PRICE = int(os.getenv("MAX_PRICE", "100"))

# Data validation
MIN_ELAPSED_SECONDS = int(os.getenv("MIN_ELAPSED_SECONDS", "480"))
MIN_VALID_FGA = int(os.getenv("MIN_VALID_FGA", "32"))
MIN_VALID_POSSESSIONS = float(os.getenv("MIN_VALID_POSSESSIONS", "18"))
MAX_VALID_PPP = float(os.getenv("MAX_VALID_PPP", "1.75"))

# Market trigger thresholds
SPREAD_MARKET_MOVE_TRIGGER = float(os.getenv("SPREAD_MARKET_MOVE_TRIGGER", "6.0"))
TOTAL_MARKET_MOVE_TRIGGER = float(os.getenv("TOTAL_MARKET_MOVE_TRIGGER", "7.0"))
MIN_SPREAD_EDGE = float(os.getenv("MIN_SPREAD_EDGE", "4.0"))
MIN_TOTAL_EDGE = float(os.getenv("MIN_TOTAL_EDGE", "5.5"))
MIN_MISPRICING_SCORE = int(os.getenv("MIN_MISPRICING_SCORE", "70"))

# Skip/reprocess thresholds
MIN_SCORE_CHANGE_TO_REMODEL = int(os.getenv("MIN_SCORE_CHANGE_TO_REMODEL", "2"))
MIN_TOTAL_CHANGE_TO_REMODEL = float(os.getenv("MIN_TOTAL_CHANGE_TO_REMODEL", "1.5"))
MIN_SPREAD_CHANGE_TO_REMODEL = float(os.getenv("MIN_SPREAD_CHANGE_TO_REMODEL", "1.0"))
MIN_ML_CHANGE_TO_REMODEL = int(os.getenv("MIN_ML_CHANGE_TO_REMODEL", "20"))

# No-bet filters
MAX_SPREAD_PLAY = float(os.getenv("MAX_SPREAD_PLAY", "14.5"))
MIN_POSSESSIONS_REMAINING = float(os.getenv("MIN_POSSESSIONS_REMAINING", "8"))

# Dead-game filters
DEAD_GAME_Q4_LEAD = int(os.getenv("DEAD_GAME_Q4_LEAD", "22"))
DEAD_GAME_Q4_SECONDS = int(os.getenv("DEAD_GAME_Q4_SECONDS", "240"))

# Cooldowns
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))

ENABLE_TOTAL_ALERTS = os.getenv("ENABLE_TOTAL_ALERTS", "true").lower() == "true"
ENABLE_SPREAD_ALERTS = os.getenv("ENABLE_SPREAD_ALERTS", "true").lower() == "true"
ENABLE_MONEYLINE_ALERTS = os.getenv("ENABLE_MONEYLINE_ALERTS", "true").lower() == "true"

TEAM_ALIASES = {
    "las vegas aces": "aces",
    "phoenix mercury": "mercury",
    "new york liberty": "liberty",
    "connecticut sun": "sun",
    "seattle storm": "storm",
    "minnesota lynx": "lynx",
    "chicago sky": "sky",
    "washington mystics": "mystics",
    "atlanta dream": "dream",
    "indiana fever": "fever",
    "dallas wings": "wings",
    "los angeles sparks": "sparks",
    "golden state valkyries": "valkyries",
}


# =========================
# BASIC HELPERS
# =========================

def now_local():
    return datetime.now(TZ)


def today():
    return now_local().strftime("%Y-%m-%d")


def espn_date():
    return now_local().strftime("%Y%m%d")


def now_ts():
    return int(time.time())


def safe_float(x, default=None):
    try:
        if x is None:
            return default
        if isinstance(x, str):
            x = x.replace("%", "").replace(",", "").strip()
            if x in ["", "--", "None"]:
                return default
        return float(x)
    except Exception:
        return default


def safe_int(x, default=0):
    v = safe_float(x, None)
    return int(v) if v is not None else default


def clamp(x, low=0, high=100):
    return max(low, min(high, x))


def clean_team(name):
    if not name:
        return ""
    n = str(name).lower().replace(".", "").replace("-", " ").strip()
    return TEAM_ALIASES.get(n, n)


def parse_made_att(value):
    if value is None:
        return 0, 0
    s = str(value).strip()
    if "-" in s:
        made, att = s.split("-", 1)
        return safe_int(made), safe_int(att)
    return 0, 0


def parse_clock_to_seconds(clock):
    if not clock:
        return 0
    s = str(clock)
    if ":" in s:
        mins, secs = s.split(":", 1)
        return safe_int(mins) * 60 + safe_int(secs)
    return safe_int(s)


def price_ok(price):
    price = safe_int(price, None)
    if price is None:
        return False
    return MIN_PRICE <= price <= MAX_PRICE


def line_changed(prev, current, threshold):
    if prev is None or current is None:
        return True
    try:
        return abs(float(current) - float(prev)) >= threshold
    except Exception:
        return True


def ml_changed(prev, current, threshold):
    if prev is None or current is None:
        return True
    try:
        return abs(int(current) - int(prev)) >= threshold
    except Exception:
        return True


# =========================
# TEXT / HEALTH
# =========================

def send_text(msg):
    print("\n" + msg + "\n")

    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, ALERT_TO_NUMBER]):
        print("TEXT NOT SENT: Missing Twilio variables.")
        return

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(body=msg, from_=TWILIO_FROM_NUMBER, to=ALERT_TO_NUMBER)
        print("TEXT SENT SUCCESSFULLY")
    except Exception as e:
        print("TEXT ERROR:", repr(e))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"WNBA SHIFT V3.1 COST-OPTIMIZED MARKET INEFFICIENCY BOT RUNNING"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health server running on port {port}")
    server.serve_forever()


# =========================
# STATE
# =========================

def default_game_state():
    return {
        "opening_total": None,
        "opening_home_spread": None,
        "opening_away_spread": None,
        "opening_home_ml": None,
        "opening_away_ml": None,

        "last_total": None,
        "last_home_spread": None,
        "last_away_spread": None,
        "last_home_ml": None,
        "last_away_ml": None,
        "last_score_sum": None,
        "last_home_score": None,
        "last_away_score": None,

        "last_heavy_check_ts": 0,
        "last_light_check_ts": 0,
        "next_allowed_check_ts": 0,

        "line_snapshots": [],
        "alerts": [],
        "alert_times": {},

        "started_text_sent": False,
        "final_logged": False,
        "dead_game": False,
    }


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"date": today(), "games": {}}

    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    except Exception:
        return {"date": today(), "games": {}}

    if state.get("date") != today():
        return {"date": today(), "games": {}}

    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# =========================
# API CALLS
# =========================

def get_schedule():
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
    params = {"dates": espn_date()}

    try:
        data = requests.get(url, params=params, timeout=15).json()
        return data.get("events", [])
    except Exception as e:
        print("SCHEDULE ERROR:", repr(e))
        return []


def get_summary(event_id):
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"
    params = {"event": event_id}

    try:
        return requests.get(url, params=params, timeout=15).json()
    except Exception as e:
        print("SUMMARY ERROR:", event_id, repr(e))
        return {}


def get_odds():
    if not ODDS_API_KEY:
        print("ODDS API KEY MISSING")
        return []

    url = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "totals,spreads,h2h",
        "oddsFormat": "american",
    }

    try:
        r = requests.get(url, params=params, timeout=15)

        if r.status_code != 200:
            print("ODDS API ERROR:", r.status_code, r.text)
            return []

        data = r.json()
        print(f"ODDS EVENTS RETURNED: {len(data)}")
        return data

    except Exception as e:
        print("ODDS ERROR:", repr(e))
        return []


# =========================
# SCHEDULE / ODDS PARSING
# =========================

def parse_start_time(event):
    raw = event.get("date")
    if not raw:
        return None

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(TZ)
    except Exception:
        return None


def should_fetch_summary(start_time):
    if not start_time:
        return True

    minutes_until = (start_time - now_local()).total_seconds() / 60
    return minutes_until <= PREGAME_WINDOW_MINUTES


def parse_event_basic(event):
    comp = event.get("competitions", [{}])[0]
    competitors = comp.get("competitors", [])

    home = {}
    away = {}

    for c in competitors:
        if c.get("homeAway") == "home":
            home = c
        elif c.get("homeAway") == "away":
            away = c

    status = event.get("status", {}).get("type", {})

    return {
        "event_id": str(event.get("id")),
        "home": home.get("team", {}).get("displayName", "Home"),
        "away": away.get("team", {}).get("displayName", "Away"),
        "home_score": safe_int(home.get("score")),
        "away_score": safe_int(away.get("score")),
        "state": status.get("state", "pre"),
        "start_time": parse_start_time(event),
    }


def find_odds(odds_events, home, away):
    ch = clean_team(home)
    ca = clean_team(away)

    for ev in odds_events:
        oh = clean_team(ev.get("home_team"))
        oa = clean_team(ev.get("away_team"))

        if not ((oh == ch and oa == ca) or (oh == ca and oa == ch)):
            continue

        result = {
            "matched": True,
            "total": None,
            "over_price": None,
            "under_price": None,
            "home_spread": None,
            "away_spread": None,
            "home_spread_price": None,
            "away_spread_price": None,
            "home_ml_price": None,
            "away_ml_price": None,
            "book_count": len(ev.get("bookmakers", [])),
        }

        for book in ev.get("bookmakers", []):
            for market in book.get("markets", []):
                key = market.get("key")

                if key == "totals":
                    for out in market.get("outcomes", []):
                        if out.get("name") == "Over":
                            result["total"] = out.get("point")
                            result["over_price"] = out.get("price")
                        elif out.get("name") == "Under":
                            result["total"] = out.get("point")
                            result["under_price"] = out.get("price")

                elif key == "spreads":
                    for out in market.get("outcomes", []):
                        name = clean_team(out.get("name"))

                        if name == ch:
                            result["home_spread"] = out.get("point")
                            result["home_spread_price"] = out.get("price")

                        if name == ca:
                            result["away_spread"] = out.get("point")
                            result["away_spread_price"] = out.get("price")

                elif key == "h2h":
                    for out in market.get("outcomes", []):
                        name = clean_team(out.get("name"))

                        if name == ch:
                            result["home_ml_price"] = out.get("price")

                        if name == ca:
                            result["away_ml_price"] = out.get("price")

        return result

    print(f"NO ODDS MATCH FOR: {away} at {home}")
    return {"matched": False, "book_count": 0}


# =========================
# BOX SCORE / ADVANCED DATA
# =========================

def map_stat_key(name):
    k = name.lower().replace(" ", "_").replace("-", "_")

    mapping = {
        "field_goals": "fg",
        "fg": "fg",
        "three_point_field_goals": "3pt",
        "3pt": "3pt",
        "free_throws": "ft",
        "ft": "ft",
        "offensive_rebounds": "orb",
        "oreb": "orb",
        "defensive_rebounds": "drb",
        "dreb": "drb",
        "rebounds": "reb",
        "total_rebounds": "reb",
        "assists": "ast",
        "steals": "stl",
        "blocks": "blk",
        "turnovers": "tov",
        "fouls": "fouls",
        "personal_fouls": "fouls",
        "fast_break_points": "fast_break",
        "points_in_paint": "paint",
    }

    return mapping.get(k, k)


def normalize_team_stats(raw):
    fgm = safe_int(raw.get("fgm"))
    fga = safe_int(raw.get("fga"))
    tpm = safe_int(raw.get("3pm"))
    tpa = safe_int(raw.get("3pa"))
    ftm = safe_int(raw.get("ftm"))
    fta = safe_int(raw.get("fta"))

    orb = safe_int(raw.get("orb"))
    drb = safe_int(raw.get("drb"))
    reb = safe_int(raw.get("reb"))
    ast = safe_int(raw.get("ast"))
    stl = safe_int(raw.get("stl"))
    blk = safe_int(raw.get("blk"))
    tov = safe_int(raw.get("tov"))
    fouls = safe_int(raw.get("fouls"))
    fast_break = safe_int(raw.get("fast_break"))
    paint = safe_int(raw.get("paint"))

    efg = ((fgm + 0.5 * tpm) / fga * 100) if fga else 0
    fg_pct = (fgm / fga * 100) if fga else 0
    three_pct = (tpm / tpa * 100) if tpa else 0
    ft_rate = (fta / fga * 100) if fga else 0

    return {
        "fgm": fgm,
        "fga": fga,
        "3pm": tpm,
        "3pa": tpa,
        "ftm": ftm,
        "fta": fta,
        "orb": orb,
        "drb": drb,
        "reb": reb,
        "ast": ast,
        "stl": stl,
        "blk": blk,
        "tov": tov,
        "fouls": fouls,
        "fast_break": fast_break,
        "paint": paint,
        "fg_pct": round(fg_pct, 1),
        "three_pct": round(three_pct, 1),
        "efg": round(efg, 1),
        "ft_rate": round(ft_rate, 1),
    }


def team_stats_from_summary(summary):
    result = {"home": normalize_team_stats({}), "away": normalize_team_stats({})}
    box = summary.get("boxscore", {})

    for t in box.get("teams", []):
        side = t.get("homeAway")

        if side not in ["home", "away"]:
            continue

        raw = {}

        for s in t.get("statistics", []):
            name = s.get("name") or s.get("label") or ""
            value = s.get("displayValue", s.get("value"))
            key = map_stat_key(name)

            if key == "fg":
                raw["fgm"], raw["fga"] = parse_made_att(value)
            elif key == "3pt":
                raw["3pm"], raw["3pa"] = parse_made_att(value)
            elif key == "ft":
                raw["ftm"], raw["fta"] = parse_made_att(value)
            elif key in ["orb", "drb", "reb", "ast", "stl", "blk", "tov", "fouls", "fast_break", "paint"]:
                raw[key] = safe_int(value)

        result[side] = normalize_team_stats(raw)

    return result


def player_stats_from_summary(summary):
    players = {"home": [], "away": []}
    box = summary.get("boxscore", {})

    for team in box.get("players", []):
        side = team.get("homeAway")

        if side not in ["home", "away"]:
            continue

        for group in team.get("statistics", []):
            labels = [x.lower() for x in group.get("labels", [])]

            for athlete in group.get("athletes", []):
                person = athlete.get("athlete", {})
                values = athlete.get("stats", [])

                row = {"name": person.get("displayName", "Unknown")}

                for i, label in enumerate(labels):
                    if i < len(values):
                        row[label] = values[i]

                players[side].append(row)

    return players


def player_impact(players):
    impact = {
        "foul_trouble": [],
        "hot": [],
        "cold_high_usage": [],
        "turnover_pressure": [],
    }

    for p in players:
        name = p.get("name", "Unknown")
        pts = safe_float(p.get("pts"), 0)
        fga = safe_float(p.get("fga"), 0)
        fgm = safe_float(p.get("fgm"), None)
        fouls = safe_float(p.get("pf", p.get("fouls", 0)), 0)
        turnovers = safe_float(p.get("to", p.get("turnovers", 0)), 0)
        mins_raw = p.get("min", p.get("minutes", "0"))

        if isinstance(mins_raw, str) and ":" in mins_raw:
            minutes = safe_float(mins_raw.split(":")[0], 0)
        else:
            minutes = safe_float(mins_raw, 0)

        if fouls >= 4:
            impact["foul_trouble"].append(f"{name}: {int(fouls)} fouls")
        elif fouls >= 3 and minutes <= 24:
            impact["foul_trouble"].append(f"{name}: {int(fouls)} early fouls")

        if fga >= 8 and fgm is not None:
            fg_pct = fgm / fga if fga else 0

            if fg_pct <= 0.30:
                impact["cold_high_usage"].append(f"{name}: {int(fgm)}/{int(fga)} shooting")

            if fg_pct >= 0.65 and pts >= 12:
                impact["hot"].append(f"{name}: {int(fgm)}/{int(fga)} shooting")

        if turnovers >= 4:
            impact["turnover_pressure"].append(f"{name}: {int(turnovers)} turnovers")

    for k in impact:
        impact[k] = impact[k][:3]

    return impact


def game_clock_context(summary):
    comp = summary.get("header", {}).get("competitions", [{}])[0]
    status = comp.get("status", {})

    period = safe_int(status.get("period", 0))
    clock = status.get("displayClock", "")

    clock_seconds = parse_clock_to_seconds(clock)

    if period <= 0:
        elapsed = 0
    else:
        elapsed = max(0, (period - 1) * 600 + (600 - clock_seconds))

    total_seconds = 2400
    remaining = max(0, total_seconds - elapsed)

    return {
        "period": period,
        "clock": clock,
        "elapsed": elapsed,
        "remaining": remaining,
        "game_fraction": elapsed / total_seconds if total_seconds else 0,
    }


def estimate_possessions(home_stats, away_stats):
    def poss(s):
        return s["fga"] + 0.44 * s["fta"] - s["orb"] + s["tov"]

    return max(0, (poss(home_stats) + poss(away_stats)) / 2)


def live_advanced(summary, basic):
    teams = team_stats_from_summary(summary)
    players = player_stats_from_summary(summary)
    clock = game_clock_context(summary)

    h = teams["home"]
    a = teams["away"]

    poss = estimate_possessions(h, a)
    game_fraction = max(clock["game_fraction"], 0.01)

    projected_possessions = clamp(poss / game_fraction if poss > 0 else 0, 60, 95)

    total_points = basic["home_score"] + basic["away_score"]
    current_margin_home = basic["home_score"] - basic["away_score"]

    live_ppp = total_points / poss if poss else 0

    seconds_remaining = clock["remaining"]
    possessions_remaining = max(0, (seconds_remaining / 2400) * projected_possessions)

    return {
        "clock": clock,
        "home_stats": h,
        "away_stats": a,
        "home_player": player_impact(players["home"]),
        "away_player": player_impact(players["away"]),
        "possessions": round(poss, 1),
        "projected_possessions": round(projected_possessions, 1),
        "possessions_remaining": round(possessions_remaining, 1),
        "live_ppp": round(live_ppp, 3),
        "home_ppp": round(basic["home_score"] / poss, 3) if poss else 0,
        "away_ppp": round(basic["away_score"] / poss, 3) if poss else 0,
        "projected_total_simple": round(total_points / game_fraction, 1) if game_fraction else 0,
        "current_margin_home": current_margin_home,
        "combined_efg": round((h["efg"] + a["efg"]) / 2, 1),
        "combined_3p": round((h["three_pct"] + a["three_pct"]) / 2, 1),
        "combined_ft_rate": round((h["ft_rate"] + a["ft_rate"]) / 2, 1),
        "combined_tov": h["tov"] + a["tov"],
        "combined_orb": h["orb"] + a["orb"],
        "combined_reb": h["reb"] + a["reb"],
        "combined_fast_break": h["fast_break"] + a["fast_break"],
        "combined_fouls": h["fouls"] + a["fouls"],
    }


# =========================
# COST OPTIMIZATION
# =========================

def update_openers_if_pregame(game_state, odds_data, state_type):
    if state_type == "in":
        return

    if game_state["opening_total"] is None and odds_data.get("total") is not None:
        game_state["opening_total"] = odds_data.get("total")

    if game_state["opening_home_spread"] is None and odds_data.get("home_spread") is not None:
        game_state["opening_home_spread"] = odds_data.get("home_spread")

    if game_state["opening_away_spread"] is None and odds_data.get("away_spread") is not None:
        game_state["opening_away_spread"] = odds_data.get("away_spread")

    if game_state["opening_home_ml"] is None and odds_data.get("home_ml_price") is not None:
        game_state["opening_home_ml"] = odds_data.get("home_ml_price")

    if game_state["opening_away_ml"] is None and odds_data.get("away_ml_price") is not None:
        game_state["opening_away_ml"] = odds_data.get("away_ml_price")


def meaningful_change(game_state, basic, odds_data):
    score_sum = basic["home_score"] + basic["away_score"]

    if game_state.get("last_score_sum") is None:
        return True, "first_live_check"

    if abs(score_sum - game_state.get("last_score_sum", 0)) >= MIN_SCORE_CHANGE_TO_REMODEL:
        return True, "score_changed"

    if line_changed(game_state.get("last_total"), odds_data.get("total"), MIN_TOTAL_CHANGE_TO_REMODEL):
        return True, "total_changed"

    if line_changed(game_state.get("last_home_spread"), odds_data.get("home_spread"), MIN_SPREAD_CHANGE_TO_REMODEL):
        return True, "spread_changed"

    if ml_changed(game_state.get("last_home_ml"), odds_data.get("home_ml_price"), MIN_ML_CHANGE_TO_REMODEL):
        return True, "moneyline_changed"

    return False, "unchanged"


def update_last_market_state(game_state, basic, odds_data):
    game_state["last_total"] = odds_data.get("total")
    game_state["last_home_spread"] = odds_data.get("home_spread")
    game_state["last_away_spread"] = odds_data.get("away_spread")
    game_state["last_home_ml"] = odds_data.get("home_ml_price")
    game_state["last_away_ml"] = odds_data.get("away_ml_price")
    game_state["last_score_sum"] = basic["home_score"] + basic["away_score"]
    game_state["last_home_score"] = basic["home_score"]
    game_state["last_away_score"] = basic["away_score"]


def record_snapshot(game_state, basic, odds_data, clock=None):
    snapshot = {
        "time": now_local().isoformat(),
        "period": clock.get("period") if clock else None,
        "clock": clock.get("clock") if clock else None,
        "total": odds_data.get("total"),
        "home_spread": odds_data.get("home_spread"),
        "away_spread": odds_data.get("away_spread"),
        "home_ml": odds_data.get("home_ml_price"),
        "away_ml": odds_data.get("away_ml_price"),
        "score": f"{basic['away_score']}-{basic['home_score']}",
    }

    game_state["line_snapshots"].append(snapshot)
    game_state["line_snapshots"] = game_state["line_snapshots"][-20:]


def game_interval_seconds(basic, game_state, near_strike=False):
    if game_state.get("dead_game"):
        return SLOW_POLL_SECONDS

    start_time = basic.get("start_time")
    state_type = basic.get("state")

    if state_type != "in":
        if not start_time:
            return SLOW_POLL_SECONDS

        minutes_until = (start_time - now_local()).total_seconds() / 60

        if minutes_until > PREGAME_WINDOW_MINUTES:
            return SLOW_POLL_SECONDS

        return PREGAME_POLL_SECONDS

    if near_strike:
        return FAST_POLL_SECONDS

    return ACTIVE_POLL_SECONDS


def should_skip_game_this_loop(game_state):
    return now_ts() < game_state.get("next_allowed_check_ts", 0)


def set_next_check(game_state, basic, near_strike=False):
    interval = game_interval_seconds(basic, game_state, near_strike)
    game_state["next_allowed_check_ts"] = now_ts() + interval
    return interval


def alert_allowed(game_state, alert_key):
    last = game_state.get("alert_times", {}).get(alert_key)
    if last is None:
        return True
    return now_ts() - int(last) >= ALERT_COOLDOWN_SECONDS


def mark_alert_sent(game_state, alert_key):
    if "alert_times" not in game_state:
        game_state["alert_times"] = {}
    game_state["alert_times"][alert_key] = now_ts()
    if alert_key not in game_state["alerts"]:
        game_state["alerts"].append(alert_key)


# =========================
# VALIDATION / FILTERS
# =========================

def validate_live_data(odds_data, adv):
    reasons = []

    if not odds_data.get("matched"):
        reasons.append("odds_not_matched")

    if odds_data.get("book_count", 0) <= 0:
        reasons.append("no_bookmakers")

    if adv["clock"]["elapsed"] < MIN_ELAPSED_SECONDS:
        reasons.append("too_early")

    h = adv["home_stats"]
    a = adv["away_stats"]

    combined_fga = h["fga"] + a["fga"]

    if combined_fga < MIN_VALID_FGA:
        reasons.append(f"bad_or_missing_fga:{combined_fga}")

    if adv["possessions"] < MIN_VALID_POSSESSIONS:
        reasons.append(f"bad_possessions:{adv['possessions']}")

    if adv["live_ppp"] <= 0 or adv["live_ppp"] > MAX_VALID_PPP:
        reasons.append(f"impossible_ppp:{adv['live_ppp']}")

    if adv["combined_efg"] == 0:
        reasons.append("zero_efg")

    return {
        "valid": len(reasons) == 0,
        "reasons": reasons,
    }


def no_bet_filter(market_type, line, price, adv, odds_data):
    reasons = []

    if not price_ok(price):
        reasons.append(f"price_outside_range:{price}")

    if adv["possessions_remaining"] < MIN_POSSESSIONS_REMAINING:
        reasons.append(f"too_few_possessions_left:{adv['possessions_remaining']}")

    if market_type == "spread":
        if line is None:
            reasons.append("missing_spread")
        elif abs(float(line)) > MAX_SPREAD_PLAY:
            reasons.append(f"spread_too_large:{line}")

    if market_type == "total" and odds_data.get("total") is None:
        reasons.append("missing_total")

    if adv["clock"]["period"] >= 4 and adv["clock"]["remaining"] <= 150:
        close_game = abs(adv["current_margin_home"]) <= 8
        foul_environment = adv["combined_fouls"] >= 26 or adv["combined_ft_rate"] >= 25

        if not close_game and not foul_environment:
            reasons.append("late_game_no_foul_edge")

    return {
        "ok": len(reasons) == 0,
        "reasons": reasons,
    }


def is_dead_game(basic, adv):
    clock = adv["clock"]
    margin = abs(basic["home_score"] - basic["away_score"])

    if clock["period"] >= 4 and clock["remaining"] <= DEAD_GAME_Q4_SECONDS and margin >= DEAD_GAME_Q4_LEAD:
        return True

    return False


# =========================
# MODEL / SCENARIOS
# =========================

def project_total(opening_total, live_total, adv):
    if opening_total is None or live_total is None:
        return None

    simple = adv["projected_total_simple"]
    pace_component = opening_total + ((adv["projected_possessions"] - 78) * 1.0)
    foul_component = 3 if adv["combined_ft_rate"] >= 28 or adv["combined_fouls"] >= 28 else 0
    tov_component = -3 if adv["combined_tov"] >= 20 else 0

    projected = (
        (opening_total * 0.45)
        + (simple * 0.35)
        + ((pace_component + foul_component + tov_component) * 0.20)
    )

    return round(projected, 1)


def project_home_margin(opening_home_spread, adv):
    if opening_home_spread is None:
        return None

    current_margin = adv["current_margin_home"]
    remaining_frac = adv["clock"]["remaining"] / 2400 if adv["clock"]["remaining"] else 0

    h = adv["home_stats"]
    a = adv["away_stats"]

    pregame_margin = -opening_home_spread

    live_damage = (
        ((adv["home_ppp"] - adv["away_ppp"]) * 10)
        + ((h["efg"] - a["efg"]) * 0.08)
        + ((h["orb"] - a["orb"]) * 0.12)
        + ((a["tov"] - h["tov"]) * 0.20)
        + ((a["fouls"] - h["fouls"]) * 0.10)
    ) * remaining_frac

    projected = (current_margin + live_damage) * 0.60 + pregame_margin * 0.40

    return round(projected, 1)


def classify_scenarios(opening_total, live_total, opening_home_spread, live_home_spread, adv):
    scenarios = []

    h = adv["home_stats"]
    a = adv["away_stats"]

    market_spread_move = abs(live_home_spread - opening_home_spread) if live_home_spread is not None and opening_home_spread is not None else 0
    market_total_move = abs(live_total - opening_total) if live_total is not None and opening_total is not None else 0

    if market_spread_move >= SPREAD_MARKET_MOVE_TRIGGER:
        scenarios.append("large_spread_market_move")

    if market_total_move >= TOTAL_MARKET_MOVE_TRIGGER:
        scenarios.append("large_total_market_move")

    if adv["combined_efg"] <= 43 and adv["projected_possessions"] >= 74:
        scenarios.append("cold_shooting_with_playable_pace")

    if adv["combined_3p"] <= 27 and (h["3pa"] + a["3pa"]) >= 16:
        scenarios.append("three_point_cold_variance")

    if adv["combined_efg"] >= 57 or adv["combined_3p"] >= 44:
        scenarios.append("hot_shooting_possible_regression")

    if adv["combined_tov"] >= 20:
        scenarios.append("turnover_drag")

    if adv["combined_ft_rate"] >= 28 or adv["combined_fouls"] >= 28:
        scenarios.append("foul_free_throw_environment")

    if adv["projected_possessions"] <= 70:
        scenarios.append("true_slow_pace")

    if adv["possessions_remaining"] <= 12:
        scenarios.append("low_possessions_remaining")

    if adv["home_player"]["foul_trouble"] or adv["away_player"]["foul_trouble"]:
        scenarios.append("star_or_rotation_foul_trouble")

    if adv["home_player"]["cold_high_usage"] or adv["away_player"]["cold_high_usage"]:
        scenarios.append("high_usage_cold_shooting")

    if adv["home_player"]["hot"] or adv["away_player"]["hot"]:
        scenarios.append("hot_player_variance")

    return scenarios


def market_inefficiency_score(edge, market_move, scenarios):
    score = 0

    score += min(abs(edge) * 8, 40)
    score += min(market_move * 3, 25)

    positive_scenarios = {
        "cold_shooting_with_playable_pace": 10,
        "three_point_cold_variance": 8,
        "large_spread_market_move": 8,
        "large_total_market_move": 8,
        "foul_free_throw_environment": 6,
        "high_usage_cold_shooting": 6,
        "hot_shooting_possible_regression": 8,
    }

    negative_scenarios = {
        "true_slow_pace": -8,
        "turnover_drag": -6,
        "low_possessions_remaining": -12,
        "star_or_rotation_foul_trouble": -5,
    }

    for s in scenarios:
        score += positive_scenarios.get(s, 0)
        score += negative_scenarios.get(s, 0)

    return clamp(round(score))


def scenario_label(scenarios, play_type):
    if play_type in ["spread", "moneyline"]:
        if "cold_shooting_with_playable_pace" in scenarios or "three_point_cold_variance" in scenarios:
            return "Market may be overreacting to cold shooting"

        if "hot_shooting_possible_regression" in scenarios:
            return "Market may be overreacting to opponent hot shooting"

        if "large_spread_market_move" in scenarios:
            return "Large spread move may be bigger than actual game damage"

    if play_type == "over":
        if "cold_shooting_with_playable_pace" in scenarios:
            return "Live total may be too low because of poor shooting variance"

        if "foul_free_throw_environment" in scenarios:
            return "Foul and free throw environment supports scoring"

    if play_type == "under":
        if "hot_shooting_possible_regression" in scenarios:
            return "Live total may be too high because of hot shooting"

        if "true_slow_pace" in scenarios:
            return "Live total may be too high for the possession pace"

    return "Market move may be larger than basketball reality"


# =========================
# ALERT FORMATTING
# =========================

def format_drivers(adv):
    drivers = [
        f"Pace projection: {adv['projected_possessions']} possessions",
        f"Possessions remaining: {adv['possessions_remaining']}",
        f"Live PPP: {adv['live_ppp']}",
        f"Combined eFG: {adv['combined_efg']}%",
        f"3PT%: {adv['combined_3p']}%",
        f"FT rate: {adv['combined_ft_rate']}%",
        f"Turnovers: {adv['combined_tov']}",
        f"Off rebounds: {adv['combined_orb']}",
        f"Total rebounds: {adv['combined_reb']}",
        f"Fast-break pts: {adv['combined_fast_break']}",
        f"Fouls: {adv['combined_fouls']}",
    ]

    foul_flags = adv["home_player"]["foul_trouble"] + adv["away_player"]["foul_trouble"]
    cold_flags = adv["home_player"]["cold_high_usage"] + adv["away_player"]["cold_high_usage"]
    hot_flags = adv["home_player"]["hot"] + adv["away_player"]["hot"]

    if foul_flags:
        drivers.append("Foul trouble: " + "; ".join(foul_flags[:3]))

    if cold_flags:
        drivers.append("Cold high-usage: " + "; ".join(cold_flags[:3]))

    if hot_flags:
        drivers.append("Hot player: " + "; ".join(hot_flags[:3]))

    return "\n".join([f"• {d}" for d in drivers[:14]])


def format_scenarios(scenarios):
    if not scenarios:
        return "• No major scenario detected"

    pretty = {
        "large_spread_market_move": "Large spread market move",
        "large_total_market_move": "Large total market move",
        "cold_shooting_with_playable_pace": "Cold shooting with playable pace",
        "three_point_cold_variance": "Three-point cold variance",
        "hot_shooting_possible_regression": "Hot shooting possible regression",
        "turnover_drag": "Turnover drag",
        "foul_free_throw_environment": "Foul/free throw environment",
        "true_slow_pace": "True slow pace",
        "low_possessions_remaining": "Low possessions remaining",
        "star_or_rotation_foul_trouble": "Star/rotation foul trouble",
        "high_usage_cold_shooting": "High-usage cold shooting",
        "hot_player_variance": "Hot player variance",
    }

    return "\n".join([f"• {pretty.get(s, s)}" for s in scenarios[:8]])


def send_market_alert(
    game_state,
    alert_key,
    label,
    basic,
    adv,
    play,
    price,
    score,
    edge,
    market_move,
    play_type,
    risk_note,
    opening_total,
    opening_home_spread,
    opening_home_ml,
    live_total,
    live_home_spread,
    home_ml_price,
    projected_total,
    projected_home_margin,
    scenarios,
):
    if not alert_allowed(game_state, alert_key):
        print(f"ALERT COOLDOWN ACTIVE | {label} | {alert_key}")
        return

    scenario = scenario_label(scenarios, play_type)
    scenario_text = format_scenarios(scenarios)
    drivers = format_drivers(adv)
    clock = adv["clock"]

    msg = (
        f"WNBA MARKET INEFFICIENCY STRIKE\n\n"
        f"{label}\n\n"
        f"Recommended Play:\n"
        f"{play}\n\n"
        f"Price: {price}\n"
        f"Market Inefficiency Score: {score}/100\n\n"
        f"Scenario:\n"
        f"{scenario}\n\n"
        f"Opening Market:\n"
        f"Total: {opening_total}\n"
        f"Home Spread: {opening_home_spread}\n"
        f"Home ML: {opening_home_ml}\n\n"
        f"Live Market:\n"
        f"Total: {live_total}\n"
        f"Home Spread: {live_home_spread}\n"
        f"Home ML: {home_ml_price}\n\n"
        f"Market Move:\n"
        f"{market_move}\n\n"
        f"Model Reality Check:\n"
        f"Projected Total: {projected_total}\n"
        f"Projected Home Margin: {projected_home_margin}\n"
        f"Edge: {edge}\n\n"
        f"Score/Clock:\n"
        f"{basic['away_score']}-{basic['home_score']} | Q{clock['period']} {clock['clock']}\n\n"
        f"Detected Scenarios:\n{scenario_text}\n\n"
        f"Live Drivers:\n{drivers}\n\n"
        f"Risk:\n"
        f"{risk_note}\n\n"
        f"Action:\n"
        f"Playable only from {MIN_PRICE} to {MAX_PRICE}. Do not chase if the number moves away."
    )

    send_text(msg)
    mark_alert_sent(game_state, alert_key)


# =========================
# MAIN LOOP
# =========================

def main():
    threading.Thread(target=start_health_server, daemon=True).start()
    state = load_state()

    while True:
        next_loop_sleep = SLOW_POLL_SECONDS

        try:
            games = get_schedule()
            odds = get_odds()

            print(f"\n--- WNBA SHIFT V3.1 COST CHECK {now_local().strftime('%I:%M:%S %p')} ---")

            for event in games:
                basic = parse_event_basic(event)
                event_id = basic["event_id"]
                start_time = basic["start_time"]
                label = f"{basic['away']} at {basic['home']}"
                start_label = start_time.strftime("%I:%M %p AZ") if start_time else "Unknown"

                if event_id not in state["games"]:
                    state["games"][event_id] = default_game_state()

                game_state = state["games"][event_id]

                # Per-game throttle. This is one of the biggest cost savers.
                if should_skip_game_this_loop(game_state):
                    remaining = game_state["next_allowed_check_ts"] - now_ts()
                    print(f"SKIP | {label} | Next check in {remaining}s")
                    next_loop_sleep = min(next_loop_sleep, max(10, remaining))
                    continue

                if game_state.get("dead_game"):
                    print(f"DEAD GAME SKIP | {label}")
                    set_next_check(game_state, basic, near_strike=False)
                    continue

                if start_time and not should_fetch_summary(start_time):
                    print(f"DORMANT | {label} | Start {start_label} | Too early")
                    set_next_check(game_state, basic, near_strike=False)
                    continue

                odds_data = find_odds(odds, basic["home"], basic["away"])
                state_type = basic["state"]
                mode = "ACTIVE" if state_type == "in" else "FINAL" if state_type == "post" else "DORMANT"

                update_openers_if_pregame(game_state, odds_data, state_type)

                live_total = odds_data.get("total")
                live_home_spread = odds_data.get("home_spread")
                live_away_spread = odds_data.get("away_spread")
                over_price = odds_data.get("over_price")
                under_price = odds_data.get("under_price")
                home_spread_price = odds_data.get("home_spread_price")
                away_spread_price = odds_data.get("away_spread_price")
                home_ml_price = odds_data.get("home_ml_price")
                away_ml_price = odds_data.get("away_ml_price")

                opening_total = game_state["opening_total"]
                opening_home_spread = game_state["opening_home_spread"]
                opening_away_spread = game_state["opening_away_spread"]
                opening_home_ml = game_state["opening_home_ml"]
                opening_away_ml = game_state["opening_away_ml"]

                if state_type == "post":
                    if not game_state["final_logged"]:
                        print(f"FINAL | {label} | Score {basic['away_score']}-{basic['home_score']}")
                        game_state["final_logged"] = True

                    set_next_check(game_state, basic, near_strike=False)
                    save_state(state)
                    continue

                if state_type != "in":
                    print(
                        f"{mode} | {label} | Start {start_label} | "
                        f"OpenTotal {opening_total} | OpenHomeSpread {opening_home_spread} | OpenHomeML {opening_home_ml}"
                    )
                    record_snapshot(game_state, basic, odds_data)
                    update_last_market_state(game_state, basic, odds_data)
                    interval = set_next_check(game_state, basic, near_strike=False)
                    next_loop_sleep = min(next_loop_sleep, interval)
                    save_state(state)
                    continue

                if not game_state["started_text_sent"]:
                    send_text(
                        f"WNBA SHIFT V3.1 STARTED\n\n"
                        f"{label}\n"
                        f"Start: {start_label}\n\n"
                        f"Cost-optimized market inefficiency bot is now active."
                    )
                    game_state["started_text_sent"] = True

                changed, change_reason = meaningful_change(game_state, basic, odds_data)

                if not changed:
                    print(
                        f"LIGHT SKIP | {label} | No meaningful score/line change | "
                        f"Score {basic['away_score']}-{basic['home_score']} | "
                        f"Total {live_total} | HomeSpread {live_home_spread} | HomeML {home_ml_price}"
                    )
                    record_snapshot(game_state, basic, odds_data)
                    interval = set_next_check(game_state, basic, near_strike=False)
                    next_loop_sleep = min(next_loop_sleep, interval)
                    save_state(state)
                    continue

                print(f"HEAVY CHECK | {label} | Reason: {change_reason}")

                # Heavy ESPN summary call only happens here.
                summary = get_summary(event_id)
                adv = live_advanced(summary, basic)
                validation = validate_live_data(odds_data, adv)
                clock = adv["clock"]

                record_snapshot(game_state, basic, odds_data, clock=clock)
                update_last_market_state(game_state, basic, odds_data)
                game_state["last_heavy_check_ts"] = now_ts()

                if is_dead_game(basic, adv):
                    game_state["dead_game"] = True
                    print(
                        f"DEAD GAME MARKED | {label} | "
                        f"Q{clock['period']} {clock['clock']} | "
                        f"Score {basic['away_score']}-{basic['home_score']}"
                    )
                    set_next_check(game_state, basic, near_strike=False)
                    save_state(state)
                    continue

                if not validation["valid"]:
                    print(
                        f"DATA INVALID — NO ALERT | {label} | "
                        f"Q{clock['period']} {clock['clock']} | "
                        f"Score {basic['away_score']}-{basic['home_score']} | "
                        f"Reasons: {', '.join(validation['reasons'])} | "
                        f"FGA {adv['home_stats']['fga'] + adv['away_stats']['fga']} | "
                        f"Poss {adv['possessions']} | PPP {adv['live_ppp']} | eFG {adv['combined_efg']}"
                    )
                    interval = set_next_check(game_state, basic, near_strike=False)
                    next_loop_sleep = min(next_loop_sleep, interval)
                    save_state(state)
                    continue

                projected_total = project_total(opening_total, live_total, adv)
                projected_home_margin = project_home_margin(opening_home_spread, adv)

                scenarios = classify_scenarios(
                    opening_total,
                    live_total,
                    opening_home_spread,
                    live_home_spread,
                    adv,
                )

                total_edge = round(projected_total - live_total, 1) if projected_total is not None and live_total is not None else None

                home_edge = None
                away_edge = None

                if projected_home_margin is not None and live_home_spread is not None:
                    market_implied_home_margin = -live_home_spread
                    home_edge = round(projected_home_margin - market_implied_home_margin, 1)
                    away_edge = round(-home_edge, 1)

                spread_market_move = abs(live_home_spread - opening_home_spread) if live_home_spread is not None and opening_home_spread is not None else 0
                total_market_move = abs(live_total - opening_total) if live_total is not None and opening_total is not None else 0

                over_score = market_inefficiency_score(total_edge, total_market_move, scenarios) if total_edge is not None and total_edge >= MIN_TOTAL_EDGE else 0
                under_score = market_inefficiency_score(total_edge, total_market_move, scenarios) if total_edge is not None and total_edge <= -MIN_TOTAL_EDGE else 0

                home_spread_score = market_inefficiency_score(home_edge, spread_market_move, scenarios) if home_edge is not None and home_edge >= MIN_SPREAD_EDGE else 0
                away_spread_score = market_inefficiency_score(away_edge, spread_market_move, scenarios) if away_edge is not None and away_edge >= MIN_SPREAD_EDGE else 0

                home_ml_score = 0
                away_ml_score = 0

                if home_edge is not None and home_edge >= MIN_SPREAD_EDGE + 1 and price_ok(home_ml_price):
                    home_ml_score = market_inefficiency_score(home_edge, spread_market_move, scenarios)

                if away_edge is not None and away_edge >= MIN_SPREAD_EDGE + 1 and price_ok(away_ml_price):
                    away_ml_score = market_inefficiency_score(away_edge, spread_market_move, scenarios)

                max_score = max(
                    over_score,
                    under_score,
                    home_spread_score,
                    away_spread_score,
                    home_ml_score,
                    away_ml_score,
                )

                near_strike = max_score >= MIN_MISPRICING_SCORE - 8

                print(
                    f"{mode} | {label} | Q{clock['period']} {clock['clock']} | "
                    f"Score {basic['away_score']}-{basic['home_score']} | "
                    f"OpenTotal {opening_total} LiveTotal {live_total} ProjTotal {projected_total} "
                    f"TotalEdge {total_edge} TotalMove {total_market_move} | "
                    f"OpenHomeSpread {opening_home_spread} LiveHomeSpread {live_home_spread} "
                    f"ProjHomeMargin {projected_home_margin} HomeEdge {home_edge} AwayEdge {away_edge} "
                    f"SpreadMove {spread_market_move} | "
                    f"PossRemain {adv['possessions_remaining']} PPP {adv['live_ppp']} "
                    f"eFG {adv['combined_efg']} 3P {adv['combined_3p']} "
                    f"TOV {adv['combined_tov']} Fouls {adv['combined_fouls']} | "
                    f"Scores O:{over_score} U:{under_score} HS:{home_spread_score} "
                    f"AS:{away_spread_score} HML:{home_ml_score} AML:{away_ml_score}"
                )

                # ALERTS

                if ENABLE_TOTAL_ALERTS and over_score >= MIN_MISPRICING_SCORE:
                    nb = no_bet_filter("total", live_total, over_price, adv, odds_data)
                    if nb["ok"]:
                        send_market_alert(
                            game_state,
                            "OVER",
                            label,
                            basic,
                            adv,
                            f"Over {live_total}",
                            over_price,
                            over_score,
                            f"+{total_edge}",
                            f"Total moved {total_market_move} points from open",
                            "over",
                            "If pace drops further, turnovers spike, or shooting remains poor, edge can disappear.",
                            opening_total,
                            opening_home_spread,
                            opening_home_ml,
                            live_total,
                            live_home_spread,
                            home_ml_price,
                            projected_total,
                            projected_home_margin,
                            scenarios,
                        )

                if ENABLE_TOTAL_ALERTS and under_score >= MIN_MISPRICING_SCORE:
                    nb = no_bet_filter("total", live_total, under_price, adv, odds_data)
                    if nb["ok"]:
                        send_market_alert(
                            game_state,
                            "UNDER",
                            label,
                            basic,
                            adv,
                            f"Under {live_total}",
                            under_price,
                            under_score,
                            total_edge,
                            f"Total moved {total_market_move} points from open",
                            "under",
                            "If fouls increase or the game becomes close late, foul scoring can hurt the under.",
                            opening_total,
                            opening_home_spread,
                            opening_home_ml,
                            live_total,
                            live_home_spread,
                            home_ml_price,
                            projected_total,
                            projected_home_margin,
                            scenarios,
                        )

                if ENABLE_SPREAD_ALERTS and home_spread_score >= MIN_MISPRICING_SCORE:
                    nb = no_bet_filter("spread", live_home_spread, home_spread_price, adv, odds_data)
                    if nb["ok"] and live_home_spread is not None and live_home_spread > 0:
                        send_market_alert(
                            game_state,
                            "HOME_SPREAD",
                            label,
                            basic,
                            adv,
                            f"{basic['home']} +{abs(live_home_spread)}",
                            home_spread_price,
                            home_spread_score,
                            f"+{home_edge}",
                            f"Home spread moved {spread_market_move} points from open",
                            "spread",
                            "If the deficit is structural, not variance, the spread edge is weaker.",
                            opening_total,
                            opening_home_spread,
                            opening_home_ml,
                            live_total,
                            live_home_spread,
                            home_ml_price,
                            projected_total,
                            projected_home_margin,
                            scenarios,
                        )

                if ENABLE_SPREAD_ALERTS and away_spread_score >= MIN_MISPRICING_SCORE:
                    nb = no_bet_filter("spread", live_away_spread, away_spread_price, adv, odds_data)
                    if nb["ok"] and live_away_spread is not None and live_away_spread > 0:
                        send_market_alert(
                            game_state,
                            "AWAY_SPREAD",
                            label,
                            basic,
                            adv,
                            f"{basic['away']} +{abs(live_away_spread)}",
                            away_spread_price,
                            away_spread_score,
                            f"+{away_edge}",
                            f"Home spread moved {spread_market_move} points from open",
                            "spread",
                            "If the deficit is structural, not variance, the spread edge is weaker.",
                            opening_total,
                            opening_home_spread,
                            opening_home_ml,
                            live_total,
                            live_home_spread,
                            home_ml_price,
                            projected_total,
                            projected_home_margin,
                            scenarios,
                        )

                if ENABLE_MONEYLINE_ALERTS and home_ml_score >= MIN_MISPRICING_SCORE:
                    nb = no_bet_filter("moneyline", None, home_ml_price, adv, odds_data)
                    if nb["ok"]:
                        send_market_alert(
                            game_state,
                            "HOME_ML",
                            label,
                            basic,
                            adv,
                            f"{basic['home']} Moneyline",
                            home_ml_price,
                            home_ml_score,
                            f"Projected home margin edge +{home_edge}",
                            f"Home ML shifted from {opening_home_ml} to {home_ml_price}",
                            "moneyline",
                            "Moneyline is higher risk than spread; only play if the live number remains inside target range.",
                            opening_total,
                            opening_home_spread,
                            opening_home_ml,
                            live_total,
                            live_home_spread,
                            home_ml_price,
                            projected_total,
                            projected_home_margin,
                            scenarios,
                        )

                if ENABLE_MONEYLINE_ALERTS and away_ml_score >= MIN_MISPRICING_SCORE:
                    nb = no_bet_filter("moneyline", None, away_ml_price, adv, odds_data)
                    if nb["ok"]:
                        send_market_alert(
                            game_state,
                            "AWAY_ML",
                            label,
                            basic,
                            adv,
                            f"{basic['away']} Moneyline",
                            away_ml_price,
                            away_ml_score,
                            f"Projected away margin edge +{away_edge}",
                            f"Away ML shifted from {opening_away_ml} to {away_ml_price}",
                            "moneyline",
                            "Moneyline is higher risk than spread; only play if the live number remains inside target range.",
                            opening_total,
                            opening_home_spread,
                            opening_home_ml,
                            live_total,
                            live_home_spread,
                            home_ml_price,
                            projected_total,
                            projected_home_margin,
                            scenarios,
                        )

                interval = set_next_check(game_state, basic, near_strike=near_strike)
                next_loop_sleep = min(next_loop_sleep, interval)
                save_state(state)

        except Exception as e:
            print("ERROR:", repr(e))

        next_loop_sleep = max(10, min(next_loop_sleep, SLOW_POLL_SECONDS))
        print(f"Sleeping {next_loop_sleep} seconds...\n")
        time.sleep(next_loop_sleep)


if __name__ == "__main__":
    main()
