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

TZ = ZoneInfo("America/Phoenix")
STATE_FILE = "wnba_shift_state.json"

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
ALERT_TO_NUMBER = os.getenv("ALERT_TO_NUMBER", "")

SPORT_KEY = "basketball_wnba"

SLOW_POLL_SECONDS = int(os.getenv("SLOW_POLL_SECONDS", "300"))
ACTIVE_POLL_SECONDS = int(os.getenv("ACTIVE_POLL_SECONDS", "60"))
FAST_POLL_SECONDS = int(os.getenv("FAST_POLL_SECONDS", "30"))

PREGAME_WINDOW_MINUTES = int(os.getenv("PREGAME_WINDOW_MINUTES", "45"))
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "80"))

TOTAL_EDGE_TRIGGER = float(os.getenv("TOTAL_EDGE_TRIGGER", "8.0"))
SPREAD_EDGE_TRIGGER = float(os.getenv("SPREAD_EDGE_TRIGGER", "5.5"))
MIN_LIVE_SPREAD_VALUE = float(os.getenv("MIN_LIVE_SPREAD_VALUE", "4.5"))

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
    "portland fire": "fire",
    "toronto tempo": "tempo",
}


def now_local():
    return datetime.now(TZ)


def today():
    return now_local().strftime("%Y-%m-%d")


def espn_date():
    return now_local().strftime("%Y%m%d")


def safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        if isinstance(x, str):
            x = x.replace("%", "").replace(",", "").strip()
            if x in ["", "--"]:
                return default
        return float(x)
    except Exception:
        return default


def safe_int(x, default=0):
    try:
        return int(float(str(x).replace("%", "").replace(",", "").strip()))
    except Exception:
        return default


def clamp(x, low=0, high=100):
    return max(low, min(high, x))


def avg(nums):
    clean = [safe_float(x, None) for x in nums if x is not None]
    clean = [x for x in clean if x is not None]
    return round(sum(clean) / len(clean), 2) if clean else 0


def clean_team(name):
    if not name:
        return ""
    n = str(name).lower().replace(".", "").replace("-", " ").strip()
    return TEAM_ALIASES.get(n, n)


def parse_made_att(value):
    if value is None:
        return 0, 0
    s = str(value)
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
        body = b"WNBA SHIFT BOT RUNNING"
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
    state = status.get("state", "pre")
    detail = status.get("detail", "")

    return {
        "event_id": str(event.get("id")),
        "home": home.get("team", {}).get("displayName", "Home"),
        "away": away.get("team", {}).get("displayName", "Away"),
        "home_score": safe_int(home.get("score")),
        "away_score": safe_int(away.get("score")),
        "state": state,
        "detail": detail,
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
            "total": None,
            "over_price": None,
            "under_price": None,
            "home_spread": None,
            "away_spread": None,
            "home_spread_price": None,
            "away_spread_price": None,
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

                if key == "spreads":
                    for out in market.get("outcomes", []):
                        name = clean_team(out.get("name"))

                        if name == ch:
                            result["home_spread"] = out.get("point")
                            result["home_spread_price"] = out.get("price")

                        if name == ca:
                            result["away_spread"] = out.get("point")
                            result["away_spread_price"] = out.get("price")

        return result

    print(f"NO ODDS MATCH FOR: {away} at {home}")
    return {}


def normalize_team_stats(raw):
    fgm = safe_int(raw.get("fgm"))
    fga = safe_int(raw.get("fga"))
    tpm = safe_int(raw.get("3pm"))
    tpa = safe_int(raw.get("3pa"))
    ftm = safe_int(raw.get("ftm"))
    fta = safe_int(raw.get("fta"))

    def find_value(keys):
        for k, v in raw.items():
            low = k.lower()
            if any(x in low for x in keys):
                return safe_float(v)
        return 0

    orb = find_value(["offensive_rebounds", "offensive rebounds", "oreb"])
    drb = find_value(["defensive_rebounds", "defensive rebounds", "dreb"])
    reb = find_value(["total_rebounds", "total rebounds", "rebounds"])
    ast = find_value(["assists"])
    stl = find_value(["steals"])
    blk = find_value(["blocks"])
    tov = find_value(["turnovers"])
    fouls = find_value(["fouls", "personal"])
    fast_break = find_value(["fast_break", "fast break"])
    paint = find_value(["points_in_paint", "paint"])

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
    teams = box.get("teams", [])

    for t in teams:
        side = t.get("homeAway")
        if side not in ["home", "away"]:
            continue

        raw = {}

        for s in t.get("statistics", []):
            name = s.get("name") or s.get("label") or ""
            key = name.lower().replace(" ", "_")
            value = s.get("displayValue", s.get("value"))
            raw[key] = value

            if "field_goals" in key or key == "fg":
                made, att = parse_made_att(value)
                raw["fgm"] = made
                raw["fga"] = att

            if "three_point" in key or key == "3pt":
                made, att = parse_made_att(value)
                raw["3pm"] = made
                raw["3pa"] = att

            if "free_throws" in key or key == "ft":
                made, att = parse_made_att(value)
                raw["ftm"] = made
                raw["fta"] = att

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
        "abnormal": [],
        "usage_pressure": 0,
    }

    for p in players:
        name = p.get("name", "Unknown")
        pts = safe_float(p.get("pts"))
        fga = safe_float(p.get("fga"))
        fouls = safe_float(p.get("pf", p.get("fouls", 0)))
        turnovers = safe_float(p.get("to", p.get("turnovers", 0)))
        mins_raw = p.get("min", p.get("minutes", "0"))

        if isinstance(mins_raw, str) and ":" in mins_raw:
            minutes = safe_float(mins_raw.split(":")[0])
        else:
            minutes = safe_float(mins_raw)

        if fouls >= 4:
            impact["foul_trouble"].append(f"{name}: {int(fouls)} fouls")
        elif fouls >= 3 and minutes <= 24:
            impact["foul_trouble"].append(f"{name}: {int(fouls)} early fouls")

        if minutes > 0:
            pts_per_36 = pts / minutes * 36
            fga_per_36 = fga / minutes * 36

            if pts_per_36 >= 35 and minutes >= 8:
                impact["abnormal"].append(f"{name}: hot scoring pace {round(pts_per_36, 1)} pts/36")

            if fga_per_36 >= 24 and minutes >= 8:
                impact["usage_pressure"] += 10

            if turnovers >= 4:
                impact["abnormal"].append(f"{name}: {int(turnovers)} turnovers")

    impact["usage_pressure"] = clamp(impact["usage_pressure"])
    impact["foul_trouble"] = impact["foul_trouble"][:4]
    impact["abnormal"] = impact["abnormal"][:4]

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
    game_fraction = elapsed / total_seconds if total_seconds else 0

    return {
        "period": period,
        "clock": clock,
        "elapsed": elapsed,
        "remaining": remaining,
        "game_fraction": game_fraction,
    }


def estimate_possessions(home_stats, away_stats):
    def poss(s):
        return s["fga"] + 0.44 * s["fta"] - s["orb"] + s["tov"]

    home_poss = poss(home_stats)
    away_poss = poss(away_stats)

    return max(1, (home_poss + away_poss) / 2)


def live_advanced(summary, basic):
    teams = team_stats_from_summary(summary)
    players = player_stats_from_summary(summary)
    clock = game_clock_context(summary)

    home_stats = teams["home"]
    away_stats = teams["away"]

    poss = estimate_possessions(home_stats, away_stats)
    game_fraction = max(clock["game_fraction"], 0.01)

    projected_possessions = poss / game_fraction
    projected_possessions = clamp(projected_possessions, 60, 95)

    total_points = basic["home_score"] + basic["away_score"]
    current_margin_home = basic["home_score"] - basic["away_score"]

    live_ppp = total_points / poss if poss else 0
    projected_total_simple = total_points / game_fraction if game_fraction > 0 else 0

    home_ppp = basic["home_score"] / poss if poss else 0
    away_ppp = basic["away_score"] / poss if poss else 0

    combined_efg = avg([home_stats["efg"], away_stats["efg"]])
    combined_3p = avg([home_stats["three_pct"], away_stats["three_pct"]])
    combined_ft_rate = avg([home_stats["ft_rate"], away_stats["ft_rate"]])
    combined_tov = home_stats["tov"] + away_stats["tov"]
    combined_orb = home_stats["orb"] + away_stats["orb"]
    combined_fast_break = home_stats["fast_break"] + away_stats["fast_break"]
    combined_fouls = home_stats["fouls"] + away_stats["fouls"]

    return {
        "clock": clock,
        "home_stats": home_stats,
        "away_stats": away_stats,
        "home_player": player_impact(players["home"]),
        "away_player": player_impact(players["away"]),
        "possessions": round(poss, 1),
        "projected_possessions": round(projected_possessions, 1),
        "live_ppp": round(live_ppp, 3),
        "home_ppp": round(home_ppp, 3),
        "away_ppp": round(away_ppp, 3),
        "projected_total_simple": round(projected_total_simple, 1),
        "current_margin_home": current_margin_home,
        "combined_efg": combined_efg,
        "combined_3p": combined_3p,
        "combined_ft_rate": combined_ft_rate,
        "combined_tov": combined_tov,
        "combined_orb": combined_orb,
        "combined_fast_break": combined_fast_break,
        "combined_fouls": combined_fouls,
    }


def market_over_pressure(opening, live):
    if opening is None or live is None:
        return 0

    drop = opening - live

    if drop >= 12:
        return 100
    if drop >= 10:
        return 92
    if drop >= 8:
        return 84
    if drop >= 6:
        return 72
    if drop >= 4:
        return 58
    if drop >= 2:
        return 42

    return 15


def market_under_pressure(opening, live):
    if opening is None or live is None:
        return 0

    rise = live - opening

    if rise >= 12:
        return 100
    if rise >= 10:
        return 92
    if rise >= 8:
        return 84
    if rise >= 6:
        return 72
    if rise >= 4:
        return 58
    if rise >= 2:
        return 42

    return 15


def pace_score(adv):
    proj = adv["projected_possessions"]

    if proj >= 86:
        return 95
    if proj >= 83:
        return 85
    if proj >= 80:
        return 72
    if proj >= 77:
        return 55
    if proj >= 74:
        return 38

    return 20


def slow_down_score(adv):
    proj = adv["projected_possessions"]

    if proj <= 70:
        return 95
    if proj <= 73:
        return 82
    if proj <= 76:
        return 68
    if proj <= 78:
        return 52

    return 25


def shooting_over_score(adv):
    score = 0

    if adv["combined_efg"] < 42:
        score += 35
    elif adv["combined_efg"] < 46:
        score += 22
    elif adv["combined_efg"] < 50:
        score += 10

    if adv["combined_3p"] < 25:
        score += 22
    elif adv["combined_3p"] < 30:
        score += 12

    if adv["combined_ft_rate"] >= 30:
        score += 20
    elif adv["combined_ft_rate"] >= 24:
        score += 12

    if adv["combined_orb"] >= 14:
        score += 15
    elif adv["combined_orb"] >= 10:
        score += 9

    if adv["combined_fast_break"] >= 18:
        score += 12
    elif adv["combined_fast_break"] >= 12:
        score += 7

    return clamp(score)


def shooting_under_score(adv):
    score = 0

    if adv["combined_efg"] >= 58:
        score += 35
    elif adv["combined_efg"] >= 54:
        score += 24
    elif adv["combined_efg"] >= 51:
        score += 12

    if adv["combined_3p"] >= 48:
        score += 25
    elif adv["combined_3p"] >= 42:
        score += 16
    elif adv["combined_3p"] >= 38:
        score += 8

    if adv["combined_tov"] >= 20:
        score += 15

    return clamp(score)


def foul_total_score(adv):
    score = 0

    if adv["combined_fouls"] >= 32:
        score += 35
    elif adv["combined_fouls"] >= 26:
        score += 24
    elif adv["combined_fouls"] >= 20:
        score += 12

    if adv["combined_ft_rate"] >= 32:
        score += 30
    elif adv["combined_ft_rate"] >= 25:
        score += 18

    return clamp(score)


def project_total(opening, live, adv):
    if opening is None:
        return None

    simple = adv["projected_total_simple"]
    pace_adj = (adv["projected_possessions"] - 78) * 1.15

    efficiency_adj = 0

    if adv["combined_efg"] < 43:
        efficiency_adj += 6
    elif adv["combined_efg"] > 57:
        efficiency_adj -= 6

    if adv["combined_3p"] < 27:
        efficiency_adj += 4
    elif adv["combined_3p"] > 45:
        efficiency_adj -= 4

    foul_adj = 0

    if adv["combined_ft_rate"] >= 28:
        foul_adj += 4

    if adv["combined_fouls"] >= 28:
        foul_adj += 3

    turnover_adj = 0

    if adv["combined_tov"] >= 20:
        turnover_adj -= 4
    elif adv["combined_tov"] <= 10:
        turnover_adj += 2

    rebound_adj = 3 if adv["combined_orb"] >= 12 else 0
    transition_adj = 3 if adv["combined_fast_break"] >= 16 else 0

    model_component = opening + pace_adj + efficiency_adj + foul_adj + turnover_adj + rebound_adj + transition_adj

    if simple > 0:
        projected = (opening * 0.45) + (simple * 0.35) + (model_component * 0.20)
    else:
        projected = model_component

    return round(projected, 1)


def total_scores(opening, live, adv, projected_total):
    if opening is None or live is None or projected_total is None:
        return 0, 0, None

    edge = round(projected_total - live, 1)

    over_score = round(
        market_over_pressure(opening, live) * 0.22
        + pace_score(adv) * 0.20
        + shooting_over_score(adv) * 0.20
        + foul_total_score(adv) * 0.16
        + min(adv["combined_orb"] * 3, 50) * 0.10
        + min(adv["combined_fast_break"] * 2.5, 50) * 0.07
        + max(0, 30 - adv["combined_tov"]) * 0.05
    )

    under_score = round(
        market_under_pressure(opening, live) * 0.25
        + slow_down_score(adv) * 0.22
        + shooting_under_score(adv) * 0.20
        + min(adv["combined_tov"] * 3, 60) * 0.13
        + max(0, 25 - adv["combined_ft_rate"]) * 0.10
        + max(0, 14 - adv["combined_orb"]) * 0.10
    )

    if edge >= TOTAL_EDGE_TRIGGER:
        over_score += 8

    if edge <= -TOTAL_EDGE_TRIGGER:
        under_score += 8

    return clamp(over_score), clamp(under_score), edge


def spread_market_edge(opening_home_spread, live_home_spread):
    if opening_home_spread is None or live_home_spread is None:
        return 0
    return abs(live_home_spread - opening_home_spread)


def project_home_margin(opening_home_spread, live_home_spread, adv):
    current_margin = adv["current_margin_home"]
    remaining_frac = adv["clock"]["remaining"] / 2400 if adv["clock"]["remaining"] else 0

    h = adv["home_stats"]
    a = adv["away_stats"]

    home_eff_edge = (adv["home_ppp"] - adv["away_ppp"]) * 18
    efg_edge = (h["efg"] - a["efg"]) * 0.18
    reb_edge = (h["orb"] - a["orb"]) * 0.25
    tov_edge = (a["tov"] - h["tov"]) * 0.35
    foul_edge = (a["fouls"] - h["fouls"]) * 0.20
    transition_edge = (h["fast_break"] - a["fast_break"]) * 0.18

    live_component = current_margin + (
        home_eff_edge
        + efg_edge
        + reb_edge
        + tov_edge
        + foul_edge
        + transition_edge
    ) * remaining_frac

    if opening_home_spread is not None:
        market_component = -opening_home_spread
        projected = live_component * 0.55 + market_component * 0.45
    else:
        projected = live_component

    return round(projected, 1)


def spread_scores(opening_home_spread, live_home_spread, adv, projected_home_margin):
    if live_home_spread is None or projected_home_margin is None:
        return 0, 0, None, None

    market_implied_home_margin = -live_home_spread
    home_edge = round(projected_home_margin - market_implied_home_margin, 1)
    away_edge = round(-home_edge, 1)

    market_swing = spread_market_edge(opening_home_spread, live_home_spread)

    h = adv["home_stats"]
    a = adv["away_stats"]

    home_recovery = 0
    away_recovery = 0

    if h["three_pct"] < 28 and h["efg"] < 46:
        home_recovery += 20

    if a["three_pct"] < 28 and a["efg"] < 46:
        away_recovery += 20

    if h["orb"] > a["orb"]:
        home_recovery += 10

    if a["orb"] > h["orb"]:
        away_recovery += 10

    if h["tov"] < a["tov"]:
        home_recovery += 10

    if a["tov"] < h["tov"]:
        away_recovery += 10

    if adv["home_player"]["foul_trouble"]:
        away_recovery += 15

    if adv["away_player"]["foul_trouble"]:
        home_recovery += 15

    home_score = round(
        min(abs(home_edge) * 9, 55)
        + min(market_swing * 4, 24)
        + home_recovery * 0.35
        + pace_score(adv) * 0.08
    )

    away_score = round(
        min(abs(away_edge) * 9, 55)
        + min(market_swing * 4, 24)
        + away_recovery * 0.35
        + pace_score(adv) * 0.08
    )

    return clamp(home_score), clamp(away_score), home_edge, away_edge


def price_ok(price):
    if price is None:
        return True

    try:
        return -130 <= int(price) <= 115
    except Exception:
        return True


def format_drivers(adv):
    drivers = [
        f"Pace projection: {adv['projected_possessions']} possessions",
        f"Live PPP: {adv['live_ppp']}",
        f"Combined eFG: {adv['combined_efg']}%",
        f"3PT%: {adv['combined_3p']}%",
        f"FT rate: {adv['combined_ft_rate']}%",
        f"Turnovers: {adv['combined_tov']}",
        f"Off rebounds: {adv['combined_orb']}",
        f"Fast-break pts: {adv['combined_fast_break']}",
        f"Fouls: {adv['combined_fouls']}",
    ]

    foul_flags = adv["home_player"]["foul_trouble"] + adv["away_player"]["foul_trouble"]
    abnormal = adv["home_player"]["abnormal"] + adv["away_player"]["abnormal"]

    if foul_flags:
        drivers.append("Foul trouble: " + "; ".join(foul_flags[:3]))

    if abnormal:
        drivers.append("Abnormal player game: " + "; ".join(abnormal[:3]))

    return "\n".join([f"• {d}" for d in drivers[:12]])


def determine_next_sleep(any_live, any_near_strike):
    if any_near_strike:
        return FAST_POLL_SECONDS

    if any_live:
        return ACTIVE_POLL_SECONDS

    return SLOW_POLL_SECONDS


def main():
    threading.Thread(target=start_health_server, daemon=True).start()

    state = load_state()

    while True:
        any_live = False
        any_near_strike = False

        try:
            games = get_schedule()
            odds = get_odds()

            print(f"\n--- WNBA SHIFT CHECK {now_local().strftime('%I:%M:%S %p')} ---")

            for event in games:
                basic = parse_event_basic(event)
                event_id = basic["event_id"]
                start_time = basic["start_time"]
                label = f"{basic['away']} at {basic['home']}"
                start_label = start_time.strftime("%I:%M %p AZ") if start_time else "Unknown"

                if event_id not in state["games"]:
                    state["games"][event_id] = {
                        "opening_total": None,
                        "opening_home_spread": None,
                        "alerts": [],
                        "started_text_sent": False,
                        "final_logged": False,
                    }

                game_state = state["games"][event_id]

                if start_time and not should_fetch_summary(start_time):
                    print(f"DORMANT | {label} | Start {start_label} | Too early")
                    continue

                summary = get_summary(event_id)

                odds_data = find_odds(odds, basic["home"], basic["away"])

                live_total = odds_data.get("total")
                live_home_spread = odds_data.get("home_spread")
                live_away_spread = odds_data.get("away_spread")
                over_price = odds_data.get("over_price")
                under_price = odds_data.get("under_price")
                home_spread_price = odds_data.get("home_spread_price")
                away_spread_price = odds_data.get("away_spread_price")

                if game_state["opening_total"] is None and live_total is not None:
                    game_state["opening_total"] = live_total

                if game_state["opening_home_spread"] is None and live_home_spread is not None:
                    game_state["opening_home_spread"] = live_home_spread

                opening_total = game_state["opening_total"]
                opening_home_spread = game_state["opening_home_spread"]

                state_type = basic["state"]
                mode = "ACTIVE" if state_type == "in" else "FINAL" if state_type == "post" else "DORMANT"

                if state_type == "in":
                    any_live = True

                    if not game_state["started_text_sent"]:
                        send_text(
                            f"WNBA SHIFT STARTED\n\n"
                            f"{label}\n"
                            f"Start: {start_label}\n\n"
                            f"Bot is now active for this game."
                        )
                        game_state["started_text_sent"] = True

                if state_type == "post":
                    if not game_state["final_logged"]:
                        print(f"FINAL | {label} | Score {basic['away_score']}-{basic['home_score']}")
                        game_state["final_logged"] = True

                    save_state(state)
                    continue

                if state_type != "in":
                    print(f"{mode} | {label} | Start {start_label}")
                    save_state(state)
                    continue

                adv = live_advanced(summary, basic)

                projected_total = project_total(opening_total, live_total, adv)
                over_score, under_score, total_edge = total_scores(opening_total, live_total, adv, projected_total)

                projected_home_margin = project_home_margin(opening_home_spread, live_home_spread, adv)

                home_spread_score, away_spread_score, home_edge, away_edge = spread_scores(
                    opening_home_spread,
                    live_home_spread,
                    adv,
                    projected_home_margin,
                )

                if total_edge is not None and abs(total_edge) >= TOTAL_EDGE_TRIGGER - 2:
                    any_near_strike = True

                if home_edge is not None and abs(home_edge) >= SPREAD_EDGE_TRIGGER - 1:
                    any_near_strike = True

                clock = adv["clock"]

                print(
                    f"{mode} | {label} | Q{clock['period']} {clock['clock']} | "
                    f"Score {basic['away_score']}-{basic['home_score']} | "
                    f"OpenTotal {opening_total} LiveTotal {live_total} ProjTotal {projected_total} TotalEdge {total_edge} | "
                    f"OpenHomeSpread {opening_home_spread} LiveHomeSpread {live_home_spread} "
                    f"ProjHomeMargin {projected_home_margin} HomeEdge {home_edge} | "
                    f"Poss {adv['possessions']} ProjPoss {adv['projected_possessions']} PPP {adv['live_ppp']} | "
                    f"eFG {adv['combined_efg']} 3P {adv['combined_3p']} FT rate {adv['combined_ft_rate']} | "
                    f"TOV {adv['combined_tov']} ORB {adv['combined_orb']} FB {adv['combined_fast_break']} Fouls {adv['combined_fouls']} | "
                    f"OVER {over_score}% UNDER {under_score}% "
                    f"HOME_SPREAD {home_spread_score}% AWAY_SPREAD {away_spread_score}%"
                )

                alerts = game_state["alerts"]
                drivers = format_drivers(adv)

                if (
                    over_score >= MIN_CONFIDENCE
                    and total_edge is not None
                    and total_edge >= TOTAL_EDGE_TRIGGER
                    and live_total is not None
                    and price_ok(over_price)
                    and "OVER" not in alerts
                ):
                    msg = (
                        f"WNBA SHIFT STRIKE\n\n"
                        f"{label}\n\n"
                        f"PLAY: Over {live_total}\n"
                        f"Odds: {over_price}\n"
                        f"Confidence: {over_score}%\n\n"
                        f"Opening Total: {opening_total}\n"
                        f"Live Total: {live_total}\n"
                        f"SHIFT Projected Total: {projected_total}\n"
                        f"Edge: +{total_edge}\n\n"
                        f"Score: {basic['away_score']}-{basic['home_score']}\n"
                        f"Clock: Q{clock['period']} {clock['clock']}\n\n"
                        f"Drivers:\n{drivers}"
                    )
                    send_text(msg)
                    alerts.append("OVER")

                if (
                    under_score >= MIN_CONFIDENCE
                    and total_edge is not None
                    and total_edge <= -TOTAL_EDGE_TRIGGER
                    and live_total is not None
                    and price_ok(under_price)
                    and "UNDER" not in alerts
                ):
                    msg = (
                        f"WNBA SHIFT STRIKE\n\n"
                        f"{label}\n\n"
                        f"PLAY: Under {live_total}\n"
                        f"Odds: {under_price}\n"
                        f"Confidence: {under_score}%\n\n"
                        f"Opening Total: {opening_total}\n"
                        f"Live Total: {live_total}\n"
                        f"SHIFT Projected Total: {projected_total}\n"
                        f"Edge: {total_edge}\n\n"
                        f"Score: {basic['away_score']}-{basic['home_score']}\n"
                        f"Clock: Q{clock['period']} {clock['clock']}\n\n"
                        f"Drivers:\n{drivers}"
                    )
                    send_text(msg)
                    alerts.append("UNDER")

                home_spread_value_ok = live_home_spread is not None and live_home_spread >= MIN_LIVE_SPREAD_VALUE
                away_spread_value_ok = live_away_spread is not None and live_away_spread >= MIN_LIVE_SPREAD_VALUE

                if (
                    home_spread_score >= MIN_CONFIDENCE
                    and home_edge is not None
                    and home_edge >= SPREAD_EDGE_TRIGGER
                    and home_spread_value_ok
                    and price_ok(home_spread_price)
                    and "HOME_SPREAD" not in alerts
                ):
                    msg = (
                        f"WNBA SPREAD FLIP STRIKE\n\n"
                        f"{label}\n\n"
                        f"PLAY: {basic['home']} {live_home_spread}\n"
                        f"Odds: {home_spread_price}\n"
                        f"Confidence: {home_spread_score}%\n\n"
                        f"Opening Home Spread: {opening_home_spread}\n"
                        f"Live Home Spread: {live_home_spread}\n"
                        f"Projected Home Margin: {projected_home_margin}\n"
                        f"Edge: +{home_edge}\n\n"
                        f"Score: {basic['away_score']}-{basic['home_score']}\n"
                        f"Clock: Q{clock['period']} {clock['clock']}\n\n"
                        f"Drivers:\n{drivers}"
                    )
                    send_text(msg)
                    alerts.append("HOME_SPREAD")

                if (
                    away_spread_score >= MIN_CONFIDENCE
                    and away_edge is not None
                    and away_edge >= SPREAD_EDGE_TRIGGER
                    and away_spread_value_ok
                    and price_ok(away_spread_price)
                    and "AWAY_SPREAD" not in alerts
                ):
                    msg = (
                        f"WNBA SPREAD FLIP STRIKE\n\n"
                        f"{label}\n\n"
                        f"PLAY: {basic['away']} {live_away_spread}\n"
                        f"Odds: {away_spread_price}\n"
                        f"Confidence: {away_spread_score}%\n\n"
                        f"Opening Away Spread: {None if opening_home_spread is None else -opening_home_spread}\n"
                        f"Live Away Spread: {live_away_spread}\n"
                        f"Projected Away Margin: {-projected_home_margin if projected_home_margin is not None else None}\n"
                        f"Edge: +{away_edge}\n\n"
                        f"Score: {basic['away_score']}-{basic['home_score']}\n"
                        f"Clock: Q{clock['period']} {clock['clock']}\n\n"
                        f"Drivers:\n{drivers}"
                    )
                    send_text(msg)
                    alerts.append("AWAY_SPREAD")

                save_state(state)

        except Exception as e:
            print("ERROR:", repr(e))

        sleep_seconds = determine_next_sleep(any_live, any_near_strike)
        print(f"Sleeping {sleep_seconds} seconds...\n")
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
