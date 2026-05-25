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
# WNBA SHIFT V3.2
# PROFESSIONAL RECOMMENDATION BOT
# =========================
#
# Goal:
# Send fewer, better alerts.
#
# Alert types:
# 1. START alert when game goes live
# 2. WATCHLIST alert when a game is close to a recommendation
# 3. STRIKE alert when the bot has a playable recommendation
#
# This version is less restrictive than V3.1 but not spammy.
# It only sends the best recommendation per check.

TZ = ZoneInfo("America/Phoenix")
STATE_FILE = "wnba_shift_state_v32_professional.json"

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
ALERT_TO_NUMBER = os.getenv("ALERT_TO_NUMBER", "")

SPORT_KEY = "basketball_wnba"

SLOW_POLL_SECONDS = int(os.getenv("SLOW_POLL_SECONDS", "300"))
PREGAME_POLL_SECONDS = int(os.getenv("PREGAME_POLL_SECONDS", "180"))
ACTIVE_POLL_SECONDS = int(os.getenv("ACTIVE_POLL_SECONDS", "60"))
FAST_POLL_SECONDS = int(os.getenv("FAST_POLL_SECONDS", "25"))

PREGAME_WINDOW_MINUTES = int(os.getenv("PREGAME_WINDOW_MINUTES", "75"))

MIN_PRICE = int(os.getenv("MIN_PRICE", "-140"))
MAX_PRICE = int(os.getenv("MAX_PRICE", "100"))

# Less restrictive than old version
MIN_ELAPSED_SECONDS = int(os.getenv("MIN_ELAPSED_SECONDS", "240"))
MIN_VALID_FGA = int(os.getenv("MIN_VALID_FGA", "20"))
MIN_VALID_POSSESSIONS = float(os.getenv("MIN_VALID_POSSESSIONS", "10"))
MAX_VALID_PPP = float(os.getenv("MAX_VALID_PPP", "1.85"))

MIN_TOTAL_EDGE = float(os.getenv("MIN_TOTAL_EDGE", "3.5"))
MIN_SPREAD_EDGE = float(os.getenv("MIN_SPREAD_EDGE", "3.0"))

WATCHLIST_SCORE = int(os.getenv("WATCHLIST_SCORE", "50"))
STRIKE_SCORE = int(os.getenv("STRIKE_SCORE", "58"))

MAX_ALERTS_PER_GAME = int(os.getenv("MAX_ALERTS_PER_GAME", "3"))
WATCHLIST_COOLDOWN_SECONDS = int(os.getenv("WATCHLIST_COOLDOWN_SECONDS", "900"))
STRIKE_COOLDOWN_SECONDS = int(os.getenv("STRIKE_COOLDOWN_SECONDS", "600"))

MIN_SCORE_CHANGE_TO_REMODEL = int(os.getenv("MIN_SCORE_CHANGE_TO_REMODEL", "2"))
MIN_TOTAL_CHANGE_TO_REMODEL = float(os.getenv("MIN_TOTAL_CHANGE_TO_REMODEL", "1.0"))
MIN_SPREAD_CHANGE_TO_REMODEL = float(os.getenv("MIN_SPREAD_CHANGE_TO_REMODEL", "1.0"))
MIN_ML_CHANGE_TO_REMODEL = int(os.getenv("MIN_ML_CHANGE_TO_REMODEL", "20"))

MIN_POSSESSIONS_REMAINING = float(os.getenv("MIN_POSSESSIONS_REMAINING", "6"))
MAX_SPREAD_PLAY = float(os.getenv("MAX_SPREAD_PLAY", "14.5"))

DEAD_GAME_Q4_LEAD = int(os.getenv("DEAD_GAME_Q4_LEAD", "22"))
DEAD_GAME_Q4_SECONDS = int(os.getenv("DEAD_GAME_Q4_SECONDS", "240"))

ENABLE_START_ALERTS = os.getenv("ENABLE_START_ALERTS", "true").lower() == "true"
ENABLE_WATCHLIST_ALERTS = os.getenv("ENABLE_WATCHLIST_ALERTS", "true").lower() == "true"
ENABLE_STRIKE_ALERTS = os.getenv("ENABLE_STRIKE_ALERTS", "true").lower() == "true"

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
    return price is not None and MIN_PRICE <= price <= MAX_PRICE


def send_text(msg):
    print("\n" + msg + "\n")

    missing = []
    if not TWILIO_ACCOUNT_SID:
        missing.append("TWILIO_ACCOUNT_SID")
    if not TWILIO_AUTH_TOKEN:
        missing.append("TWILIO_AUTH_TOKEN")
    if not TWILIO_FROM_NUMBER:
        missing.append("TWILIO_FROM_NUMBER")
    if not ALERT_TO_NUMBER:
        missing.append("ALERT_TO_NUMBER")

    if missing:
        print("TEXT NOT SENT. Missing:", ", ".join(missing))
        return False

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=msg,
            from_=TWILIO_FROM_NUMBER,
            to=ALERT_TO_NUMBER,
        )
        print("TEXT SENT SUCCESSFULLY")
        return True
    except Exception as e:
        print("TEXT ERROR:", repr(e))
        return False


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"WNBA SHIFT V3.2 PROFESSIONAL BOT RUNNING"
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

        "started_text_sent": False,
        "final_logged": False,
        "dead_game": False,

        "next_allowed_check_ts": 0,
        "last_watchlist_ts": 0,
        "last_strike_ts": 0,

        "alerts_sent": [],
        "line_snapshots": [],
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

        if fouls >= 4:
            impact["foul_trouble"].append(f"{name}: {int(fouls)} fouls")

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

    total_points = basic["home_score"] + basic["away_score"]
    current_margin_home = basic["home_score"] - basic["away_score"]

    live_ppp = total_points / poss if poss else 0
    projected_possessions = clamp(poss / game_fraction if poss > 0 else 0, 60, 95)
    possessions_remaining = max(0, (clock["remaining"] / 2400) * projected_possessions)

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

    if abs(safe_float(odds_data.get("total"), 0) - safe_float(game_state.get("last_total"), 0)) >= MIN_TOTAL_CHANGE_TO_REMODEL:
        return True, "total_changed"

    if abs(safe_float(odds_data.get("home_spread"), 0) - safe_float(game_state.get("last_home_spread"), 0)) >= MIN_SPREAD_CHANGE_TO_REMODEL:
        return True, "spread_changed"

    if abs(safe_int(odds_data.get("home_ml_price"), 0) - safe_int(game_state.get("last_home_ml"), 0)) >= MIN_ML_CHANGE_TO_REMODEL:
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


def validate_live_data(odds_data, adv):
    reasons = []

    if not odds_data.get("matched"):
        reasons.append("odds_not_matched")

    if odds_data.get("book_count", 0) <= 0:
        reasons.append("no_bookmakers")

    if adv["clock"]["elapsed"] < MIN_ELAPSED_SECONDS:
        reasons.append("early_but_monitoring")

    h = adv["home_stats"]
    a = adv["away_stats"]

    combined_fga = h["fga"] + a["fga"]

    if combined_fga < MIN_VALID_FGA:
        reasons.append(f"low_fga:{combined_fga}")

    if adv["possessions"] < MIN_VALID_POSSESSIONS:
        reasons.append(f"low_possessions:{adv['possessions']}")

    if adv["live_ppp"] <= 0 or adv["live_ppp"] > MAX_VALID_PPP:
        reasons.append(f"bad_ppp:{adv['live_ppp']}")

    hard_invalid = [
        r for r in reasons
        if not r.startswith("early_but_monitoring")
    ]

    return {
        "valid": len(hard_invalid) == 0,
        "reasons": reasons,
    }


def project_total(opening_total, live_total, adv):
    if opening_total is None or live_total is None:
        return None

    simple = adv["projected_total_simple"]
    pace_component = opening_total + ((adv["projected_possessions"] - 78) * 1.0)
    foul_component = 3 if adv["combined_ft_rate"] >= 28 or adv["combined_fouls"] >= 28 else 0
    turnover_component = -3 if adv["combined_tov"] >= 20 else 0

    projected = (
        (opening_total * 0.42)
        + (simple * 0.38)
        + ((pace_component + foul_component + turnover_component) * 0.20)
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

    total_move = abs(live_total - opening_total) if live_total is not None and opening_total is not None else 0
    spread_move = abs(live_home_spread - opening_home_spread) if live_home_spread is not None and opening_home_spread is not None else 0

    if total_move >= 5:
        scenarios.append("large_total_market_move")

    if spread_move >= 4:
        scenarios.append("large_spread_market_move")

    if adv["combined_efg"] <= 44 and adv["projected_possessions"] >= 74:
        scenarios.append("cold_shooting_playable_pace")

    if adv["combined_3p"] <= 28 and (h["3pa"] + a["3pa"]) >= 14:
        scenarios.append("three_point_cold_variance")

    if adv["combined_efg"] >= 57 or adv["combined_3p"] >= 44:
        scenarios.append("hot_shooting_regression_risk")

    if adv["combined_ft_rate"] >= 28 or adv["combined_fouls"] >= 28:
        scenarios.append("foul_free_throw_environment")

    if adv["combined_tov"] >= 20:
        scenarios.append("turnover_drag")

    if adv["projected_possessions"] <= 70:
        scenarios.append("true_slow_pace")

    if adv["possessions_remaining"] <= 10:
        scenarios.append("low_possessions_remaining")

    if adv["home_player"]["foul_trouble"] or adv["away_player"]["foul_trouble"]:
        scenarios.append("foul_trouble")

    if adv["home_player"]["cold_high_usage"] or adv["away_player"]["cold_high_usage"]:
        scenarios.append("high_usage_cold_shooting")

    if adv["home_player"]["hot"] or adv["away_player"]["hot"]:
        scenarios.append("hot_player_variance")

    return scenarios


def market_score(edge, market_move, scenarios, play_type):
    score = 0

    score += min(abs(edge) * 9, 42)
    score += min(market_move * 3, 22)

    positive = {
        "large_total_market_move": 7,
        "large_spread_market_move": 7,
        "cold_shooting_playable_pace": 9,
        "three_point_cold_variance": 7,
        "foul_free_throw_environment": 7,
        "high_usage_cold_shooting": 5,
        "hot_shooting_regression_risk": 8,
    }

    negative = {
        "true_slow_pace": -8,
        "turnover_drag": -5,
        "low_possessions_remaining": -10,
        "foul_trouble": -3,
    }

    for s in scenarios:
        score += positive.get(s, 0)
        score += negative.get(s, 0)

    if play_type == "over":
        if "true_slow_pace" in scenarios:
            score -= 8
        if "foul_free_throw_environment" in scenarios:
            score += 5

    if play_type == "under":
        if "foul_free_throw_environment" in scenarios:
            score -= 8
        if "hot_shooting_regression_risk" in scenarios:
            score += 5

    return clamp(round(score))


def no_bet_filter(candidate, adv):
    reasons = []

    if not price_ok(candidate["price"]):
        reasons.append(f"price_outside_range:{candidate['price']}")

    if adv["possessions_remaining"] < MIN_POSSESSIONS_REMAINING:
        reasons.append(f"too_few_possessions_left:{adv['possessions_remaining']}")

    if candidate["market"] == "spread":
        if candidate["line"] is None:
            reasons.append("missing_spread")
        elif abs(float(candidate["line"])) > MAX_SPREAD_PLAY:
            reasons.append(f"spread_too_large:{candidate['line']}")

    if candidate["market"] == "total":
        if candidate["line"] is None:
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


def scenario_text(scenarios):
    pretty = {
        "large_total_market_move": "Large live total move",
        "large_spread_market_move": "Large live spread move",
        "cold_shooting_playable_pace": "Cold shooting but pace is still playable",
        "three_point_cold_variance": "Poor 3PT shooting may regress",
        "hot_shooting_regression_risk": "Hot shooting may cool off",
        "foul_free_throw_environment": "Foul and free throw environment",
        "turnover_drag": "Turnovers are dragging scoring",
        "true_slow_pace": "True slow pace",
        "low_possessions_remaining": "Limited possessions left",
        "foul_trouble": "Key foul trouble",
        "high_usage_cold_shooting": "High-usage players shooting cold",
        "hot_player_variance": "Hot player variance",
    }

    if not scenarios:
        return "• No major scenario detected"

    return "\n".join([f"• {pretty.get(s, s)}" for s in scenarios[:7]])


def driver_text(adv):
    drivers = [
        f"Pace projection: {adv['projected_possessions']} possessions",
        f"Possessions remaining: {adv['possessions_remaining']}",
        f"Live PPP: {adv['live_ppp']}",
        f"Combined eFG: {adv['combined_efg']}%",
        f"3PT%: {adv['combined_3p']}%",
        f"FT rate: {adv['combined_ft_rate']}%",
        f"Turnovers: {adv['combined_tov']}",
        f"Fouls: {adv['combined_fouls']}",
        f"Off rebounds: {adv['combined_orb']}",
        f"Fast-break points: {adv['combined_fast_break']}",
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

    return "\n".join([f"• {d}" for d in drivers[:12]])


def recommendation_reason(candidate, scenarios):
    if candidate["play_type"] == "over":
        if "cold_shooting_playable_pace" in scenarios:
            return "The market may have pushed the total too low because of cold shooting, but pace still supports scoring."
        if "foul_free_throw_environment" in scenarios:
            return "The foul and free throw environment supports late scoring."
        return "Projected total is meaningfully above the live number."

    if candidate["play_type"] == "under":
        if "hot_shooting_regression_risk" in scenarios:
            return "The market may have pushed the total too high because of hot shooting variance."
        if "true_slow_pace" in scenarios:
            return "The live total looks high compared to actual possession pace."
        return "Projected total is meaningfully below the live number."

    if candidate["play_type"] in ["home_spread", "away_spread"]:
        return "The spread appears to have moved farther than the actual game damage supports."

    if candidate["play_type"] in ["home_ml", "away_ml"]:
        return "Moneyline price appears playable compared with projected margin, but this is higher risk than spread."

    return "Market price may be inefficient compared with live game conditions."


def build_candidates(basic, odds_data, adv, projections, scenarios):
    candidates = []

    live_total = odds_data.get("total")
    live_home_spread = odds_data.get("home_spread")
    live_away_spread = odds_data.get("away_spread")

    opening_total = projections["opening_total"]
    opening_home_spread = projections["opening_home_spread"]

    projected_total = projections["projected_total"]
    projected_home_margin = projections["projected_home_margin"]

    total_edge = None
    if projected_total is not None and live_total is not None:
        total_edge = round(projected_total - live_total, 1)

    home_edge = None
    away_edge = None
    if projected_home_margin is not None and live_home_spread is not None:
        market_home_margin = -live_home_spread
        home_edge = round(projected_home_margin - market_home_margin, 1)
        away_edge = round(-home_edge, 1)

    total_move = abs(live_total - opening_total) if live_total is not None and opening_total is not None else 0
    spread_move = abs(live_home_spread - opening_home_spread) if live_home_spread is not None and opening_home_spread is not None else 0

    if total_edge is not None and total_edge >= MIN_TOTAL_EDGE:
        candidates.append({
            "play_type": "over",
            "market": "total",
            "play": f"Over {live_total}",
            "line": live_total,
            "price": odds_data.get("over_price"),
            "edge": total_edge,
            "market_move": total_move,
            "score": market_score(total_edge, total_move, scenarios, "over"),
        })

    if total_edge is not None and total_edge <= -MIN_TOTAL_EDGE:
        candidates.append({
            "play_type": "under",
            "market": "total",
            "play": f"Under {live_total}",
            "line": live_total,
            "price": odds_data.get("under_price"),
            "edge": total_edge,
            "market_move": total_move,
            "score": market_score(total_edge, total_move, scenarios, "under"),
        })

    if home_edge is not None and home_edge >= MIN_SPREAD_EDGE:
        candidates.append({
            "play_type": "home_spread",
            "market": "spread",
            "play": f"{basic['home']} {live_home_spread:+}",
            "line": live_home_spread,
            "price": odds_data.get("home_spread_price"),
            "edge": home_edge,
            "market_move": spread_move,
            "score": market_score(home_edge, spread_move, scenarios, "spread"),
        })

    if away_edge is not None and away_edge >= MIN_SPREAD_EDGE:
        candidates.append({
            "play_type": "away_spread",
            "market": "spread",
            "play": f"{basic['away']} {live_away_spread:+}",
            "line": live_away_spread,
            "price": odds_data.get("away_spread_price"),
            "edge": away_edge,
            "market_move": spread_move,
            "score": market_score(away_edge, spread_move, scenarios, "spread"),
        })

    if home_edge is not None and home_edge >= MIN_SPREAD_EDGE + 1:
        candidates.append({
            "play_type": "home_ml",
            "market": "moneyline",
            "play": f"{basic['home']} Moneyline",
            "line": None,
            "price": odds_data.get("home_ml_price"),
            "edge": home_edge,
            "market_move": spread_move,
            "score": market_score(home_edge, spread_move, scenarios, "moneyline"),
        })

    if away_edge is not None and away_edge >= MIN_SPREAD_EDGE + 1:
        candidates.append({
            "play_type": "away_ml",
            "market": "moneyline",
            "play": f"{basic['away']} Moneyline",
            "line": None,
            "price": odds_data.get("away_ml_price"),
            "edge": away_edge,
            "market_move": spread_move,
            "score": market_score(away_edge, spread_move, scenarios, "moneyline"),
        })

    playable = []

    for c in candidates:
        nb = no_bet_filter(c, adv)
        c["no_bet_reasons"] = nb["reasons"]
        c["playable"] = nb["ok"]
        if nb["ok"]:
            playable.append(c)

    playable.sort(key=lambda x: x["score"], reverse=True)
    candidates.sort(key=lambda x: x["score"], reverse=True)

    return playable, candidates


def can_send_watchlist(game_state):
    if not ENABLE_WATCHLIST_ALERTS:
        return False

    if len(game_state.get("alerts_sent", [])) >= MAX_ALERTS_PER_GAME:
        return False

    return now_ts() - int(game_state.get("last_watchlist_ts", 0)) >= WATCHLIST_COOLDOWN_SECONDS


def can_send_strike(game_state, alert_key):
    if not ENABLE_STRIKE_ALERTS:
        return False

    if len(game_state.get("alerts_sent", [])) >= MAX_ALERTS_PER_GAME:
        return False

    if alert_key in game_state.get("alerts_sent", []):
        return False

    return now_ts() - int(game_state.get("last_strike_ts", 0)) >= STRIKE_COOLDOWN_SECONDS


def mark_alert(game_state, alert_key, alert_type):
    if alert_key not in game_state["alerts_sent"]:
        game_state["alerts_sent"].append(alert_key)

    if alert_type == "watchlist":
        game_state["last_watchlist_ts"] = now_ts()

    if alert_type == "strike":
        game_state["last_strike_ts"] = now_ts()


def send_watchlist(game_state, label, basic, adv, best, projections, scenarios):
    clock = adv["clock"]

    msg = (
        f"WNBA SHIFT WATCHLIST\n\n"
        f"{label}\n\n"
        f"Close to a recommendation, but not a full strike yet.\n\n"
        f"Best Lean:\n"
        f"{best['play']}\n\n"
        f"Price: {best['price']}\n"
        f"Score: {best['score']}/100\n"
        f"Edge: {best['edge']}\n\n"
        f"Score/Clock:\n"
        f"{basic['away_score']}-{basic['home_score']} | Q{clock['period']} {clock['clock']}\n\n"
        f"Market:\n"
        f"Live Total: {projections['live_total']}\n"
        f"Projected Total: {projections['projected_total']}\n"
        f"Live Home Spread: {projections['live_home_spread']}\n"
        f"Projected Home Margin: {projections['projected_home_margin']}\n\n"
        f"Why it is close:\n"
        f"{recommendation_reason(best, scenarios)}\n\n"
        f"Scenarios:\n"
        f"{scenario_text(scenarios)}\n\n"
        f"Action:\n"
        f"Monitor only. Full strike sends at {STRIKE_SCORE}+."
    )

    send_text(msg)
    mark_alert(game_state, "WATCHLIST", "watchlist")


def send_strike(game_state, label, basic, adv, best, projections, scenarios):
    clock = adv["clock"]
    alert_key = f"STRIKE_{best['play_type']}"

    msg = (
        f"WNBA MARKET INEFFICIENCY STRIKE\n\n"
        f"{label}\n\n"
        f"Recommended Play:\n"
        f"{best['play']}\n\n"
        f"Price: {best['price']}\n"
        f"Score: {best['score']}/100\n"
        f"Edge: {best['edge']}\n\n"
        f"Score/Clock:\n"
        f"{basic['away_score']}-{basic['home_score']} | Q{clock['period']} {clock['clock']}\n\n"
        f"Opening Market:\n"
        f"Total: {projections['opening_total']}\n"
        f"Home Spread: {projections['opening_home_spread']}\n"
        f"Home ML: {projections['opening_home_ml']}\n\n"
        f"Live Market:\n"
        f"Total: {projections['live_total']}\n"
        f"Home Spread: {projections['live_home_spread']}\n"
        f"Home ML: {projections['home_ml_price']}\n\n"
        f"Model Reality Check:\n"
        f"Projected Total: {projections['projected_total']}\n"
        f"Projected Home Margin: {projections['projected_home_margin']}\n\n"
        f"Why:\n"
        f"{recommendation_reason(best, scenarios)}\n\n"
        f"Scenarios:\n"
        f"{scenario_text(scenarios)}\n\n"
        f"Drivers:\n"
        f"{driver_text(adv)}\n\n"
        f"Action:\n"
        f"Playable only from {MIN_PRICE} to {MAX_PRICE}. Do not chase if the price or number moves away."
    )

    send_text(msg)
    mark_alert(game_state, alert_key, "strike")


def is_dead_game(basic, adv):
    clock = adv["clock"]
    margin = abs(basic["home_score"] - basic["away_score"])

    return clock["period"] >= 4 and clock["remaining"] <= DEAD_GAME_Q4_SECONDS and margin >= DEAD_GAME_Q4_LEAD


def game_interval_seconds(basic, game_state, near=False):
    if game_state.get("dead_game"):
        return SLOW_POLL_SECONDS

    state_type = basic.get("state")
    start_time = basic.get("start_time")

    if state_type != "in":
        if not start_time:
            return SLOW_POLL_SECONDS

        minutes_until = (start_time - now_local()).total_seconds() / 60

        if minutes_until > PREGAME_WINDOW_MINUTES:
            return SLOW_POLL_SECONDS

        return PREGAME_POLL_SECONDS

    if near:
        return FAST_POLL_SECONDS

    return ACTIVE_POLL_SECONDS


def should_skip_game_this_loop(game_state):
    return now_ts() < game_state.get("next_allowed_check_ts", 0)


def set_next_check(game_state, basic, near=False):
    interval = game_interval_seconds(basic, game_state, near)
    game_state["next_allowed_check_ts"] = now_ts() + interval
    return interval


def main():
    threading.Thread(target=start_health_server, daemon=True).start()

    print("WNBA SHIFT V3.2 PROFESSIONAL BOT STARTING")
    print(f"Price range: {MIN_PRICE} to {MAX_PRICE}")
    print(f"Watchlist score: {WATCHLIST_SCORE}")
    print(f"Strike score: {STRIKE_SCORE}")

    state = load_state()

    while True:
        next_loop_sleep = SLOW_POLL_SECONDS

        try:
            games = get_schedule()
            odds = get_odds()

            print(f"\n--- WNBA SHIFT V3.2 CHECK {now_local().strftime('%I:%M:%S %p')} ---")

            for event in games:
                basic = parse_event_basic(event)
                event_id = basic["event_id"]
                start_time = basic["start_time"]
                label = f"{basic['away']} at {basic['home']}"
                start_label = start_time.strftime("%I:%M %p AZ") if start_time else "Unknown"

                if event_id not in state["games"]:
                    state["games"][event_id] = default_game_state()

                game_state = state["games"][event_id]

                if should_skip_game_this_loop(game_state):
                    remaining = game_state["next_allowed_check_ts"] - now_ts()
                    print(f"SKIP | {label} | Next check in {remaining}s")
                    next_loop_sleep = min(next_loop_sleep, max(10, remaining))
                    continue

                if game_state.get("dead_game"):
                    print(f"DEAD GAME SKIP | {label}")
                    interval = set_next_check(game_state, basic)
                    next_loop_sleep = min(next_loop_sleep, interval)
                    continue

                if start_time and not should_fetch_summary(start_time):
                    print(f"DORMANT | {label} | Start {start_label}")
                    interval = set_next_check(game_state, basic)
                    next_loop_sleep = min(next_loop_sleep, interval)
                    continue

                odds_data = find_odds(odds, basic["home"], basic["away"])
                state_type = basic["state"]

                update_openers_if_pregame(game_state, odds_data, state_type)

                opening_total = game_state["opening_total"]
                opening_home_spread = game_state["opening_home_spread"]
                opening_home_ml = game_state["opening_home_ml"]

                if state_type == "post":
                    if not game_state["final_logged"]:
                        print(f"FINAL | {label} | Score {basic['away_score']}-{basic['home_score']}")
                        game_state["final_logged"] = True
                    interval = set_next_check(game_state, basic)
                    next_loop_sleep = min(next_loop_sleep, interval)
                    save_state(state)
                    continue

                if state_type != "in":
                    print(
                        f"PREGAME | {label} | Start {start_label} | "
                        f"OpenTotal {opening_total} | OpenHomeSpread {opening_home_spread}"
                    )
                    record_snapshot(game_state, basic, odds_data)
                    update_last_market_state(game_state, basic, odds_data)
                    interval = set_next_check(game_state, basic)
                    next_loop_sleep = min(next_loop_sleep, interval)
                    save_state(state)
                    continue

                if ENABLE_START_ALERTS and not game_state["started_text_sent"]:
                    send_text(
                        f"WNBA SHIFT V3.2 STARTED\n\n"
                        f"{label}\n"
                        f"Start: {start_label}\n\n"
                        f"Bot is live. It will send WATCHLIST first, then STRIKE only if recommendation strength improves."
                    )
                    game_state["started_text_sent"] = True

                changed, change_reason = meaningful_change(game_state, basic, odds_data)

                if not changed:
                    print(
                        f"LIGHT SKIP | {label} | No meaningful change | "
                        f"Score {basic['away_score']}-{basic['home_score']} | "
                        f"Total {odds_data.get('total')} | HomeSpread {odds_data.get('home_spread')}"
                    )
                    record_snapshot(game_state, basic, odds_data)
                    interval = set_next_check(game_state, basic)
                    next_loop_sleep = min(next_loop_sleep, interval)
                    save_state(state)
                    continue

                print(f"HEAVY CHECK | {label} | Reason: {change_reason}")

                summary = get_summary(event_id)
                adv = live_advanced(summary, basic)
                clock = adv["clock"]

                record_snapshot(game_state, basic, odds_data, clock)
                update_last_market_state(game_state, basic, odds_data)

                if is_dead_game(basic, adv):
                    game_state["dead_game"] = True
                    print(f"DEAD GAME MARKED | {label}")
                    interval = set_next_check(game_state, basic)
                    next_loop_sleep = min(next_loop_sleep, interval)
                    save_state(state)
                    continue

                validation = validate_live_data(odds_data, adv)

                if not validation["valid"]:
                    print(
                        f"DATA INVALID | {label} | "
                        f"Reasons: {', '.join(validation['reasons'])} | "
                        f"Q{clock['period']} {clock['clock']} | "
                        f"Score {basic['away_score']}-{basic['home_score']}"
                    )
                    interval = set_next_check(game_state, basic)
                    next_loop_sleep = min(next_loop_sleep, interval)
                    save_state(state)
                    continue

                live_total = odds_data.get("total")
                live_home_spread = odds_data.get("home_spread")

                projected_total = project_total(opening_total, live_total, adv)
                projected_home_margin = project_home_margin(opening_home_spread, adv)

                scenarios = classify_scenarios(
                    opening_total,
                    live_total,
                    opening_home_spread,
                    live_home_spread,
                    adv,
                )

                projections = {
                    "opening_total": opening_total,
                    "opening_home_spread": opening_home_spread,
                    "opening_home_ml": opening_home_ml,
                    "live_total": live_total,
                    "live_home_spread": live_home_spread,
                    "home_ml_price": odds_data.get("home_ml_price"),
                    "projected_total": projected_total,
                    "projected_home_margin": projected_home_margin,
                }

                playable, all_candidates = build_candidates(
                    basic,
                    odds_data,
                    adv,
                    projections,
                    scenarios,
                )

                best = playable[0] if playable else None
                best_any = all_candidates[0] if all_candidates else None

                best_score = best["score"] if best else 0
                near = best_score >= WATCHLIST_SCORE

                print(
                    f"ACTIVE | {label} | Q{clock['period']} {clock['clock']} | "
                    f"Score {basic['away_score']}-{basic['home_score']} | "
                    f"OpenTotal {opening_total} LiveTotal {live_total} ProjTotal {projected_total} | "
                    f"OpenHomeSpread {opening_home_spread} LiveHomeSpread {live_home_spread} "
                    f"ProjHomeMargin {projected_home_margin} | "
                    f"BestPlayable {best['play'] if best else 'None'} "
                    f"Score {best_score} | "
                    f"Scenarios {scenarios}"
                )

                if best and best["score"] >= STRIKE_SCORE:
                    alert_key = f"STRIKE_{best['play_type']}"
                    if can_send_strike(game_state, alert_key):
                        send_strike(game_state, label, basic, adv, best, projections, scenarios)

                elif best and best["score"] >= WATCHLIST_SCORE:
                    if can_send_watchlist(game_state):
                        send_watchlist(game_state, label, basic, adv, best, projections, scenarios)

                elif best_any:
                    print(
                        f"NO ALERT | {label} | Best candidate {best_any['play']} "
                        f"Score {best_any['score']} | Playable {best_any['playable']} | "
                        f"Reasons {best_any.get('no_bet_reasons', [])}"
                    )
                else:
                    print(f"NO EDGE | {label}")

                interval = set_next_check(game_state, basic, near=near)
                next_loop_sleep = min(next_loop_sleep, interval)
                save_state(state)

        except Exception as e:
            print("MAIN LOOP ERROR:", repr(e))

        next_loop_sleep = max(10, min(next_loop_sleep, SLOW_POLL_SECONDS))
        print(f"Sleeping {next_loop_sleep} seconds...\n")
        time.sleep(next_loop_sleep)


if __name__ == "__main__":
    main()
