from flask import Flask, request, jsonify, render_template, redirect, session
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from pathlib import Path
from datetime import datetime, timezone
import requests
import ipaddress
import pandas as pd
import json
import os

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Chicago")
except Exception:
    TZ = None

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
STATS_CSV = DATA_DIR / "strategy_statistics_output.csv"
STATS_ALL_CSV = DATA_DIR / "strategy_statistics_output_all.csv"
ROULETTE_JSON = DATA_DIR / "roulette_data.json"
ROULETTE_ALL_JSON = DATA_DIR / "roulette_data_all.json"
CONFIG_PATH = ROOT_DIR / "config" / "config.local.json"
ENV_PATH = ROOT_DIR / ".env"

load_dotenv(ENV_PATH, override=True)

server_name = os.environ.get("SERVER_NAME", "unknown")

config = {}
if CONFIG_PATH.exists():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)

WHEEL_ID = config.get("wheel_id", os.getenv("SERVER_NAME", "unknown-wheel"))
GLOBAL_INGEST_ENABLED = bool(config.get("global_ingest_enabled", False))
GLOBAL_INGEST_URL = config.get("global_ingest_url")

print(f"Starting server: {server_name}")
app = Flask(
    __name__,
    template_folder=os.path.join(ROOT_DIR, "templates")
)
# Set a secret key for sessions (set via env var in production)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-me-in-prod")
CORS(app)

# Trust proxy headers for real client IP when behind nginx/Cloudflare
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# --- Blacklist/attempts state ---
BLACKLIST_PATH = BASE_DIR / "blacklist.json"
_state = {"blacklist": {}, "attempts": {}}

def _load_state():
    global _state
    if BLACKLIST_PATH.exists():
        try:
            with BLACKLIST_PATH.open("r", encoding="utf-8") as f:
                _state = json.load(f)
            _state.setdefault("blacklist", {})
            _state.setdefault("attempts", {})
        except Exception:
            _state = {"blacklist": {}, "attempts": {}}
    else:
        _state = {"blacklist": {}, "attempts": {}}

def _save_state():
    try:
        with BLACKLIST_PATH.open("w", encoding="utf-8") as f:
            json.dump(_state, f, indent=2)
    except Exception as e:
        app.logger.exception("Failed to save blacklist state: %s", e)

_load_state()

# --- Config ---
MAX_TRIES = 3
REDIRECT_URL = "https://www.google.com/search?q=colostomy+bags"
DEV_IGNORE_PRIVATE_IPS = False  # don't blacklist loopback/private in dev

# --- IP helpers ---
def sync_to_global_collector(rolls):
    if not GLOBAL_INGEST_ENABLED or not GLOBAL_INGEST_URL:
        return

    try:
        payload = {
            "wheel_id": WHEEL_ID,
            "rolls": rolls
        }

        response = requests.post(
            GLOBAL_INGEST_URL,
            json=payload,
            timeout=5
        )

        if response.status_code >= 400:
            print(f"[GLOBAL SYNC] Failed: {response.status_code} {response.text}")
        else:
            print(f"[GLOBAL SYNC] OK: {response.text}")

    except Exception as e:
        print(f"[GLOBAL SYNC] Error: {e}")

def _first_public_from_xff(header_value: str):
    if not header_value:
        return None
    parts = [p.strip() for p in header_value.split(",") if p.strip()]
    for p in parts:
        try:
            addr = ipaddress.ip_address(p)
            if not (addr.is_private or addr.is_loopback):
                return p
        except Exception:
            continue
    return None

def get_client_ip():
    # Prefer CDN/proxy real-ip headers
    for header in ("CF-Connecting-IP", "X-Real-IP"):
        v = request.headers.get(header)
        if v:
            try:
                addr = ipaddress.ip_address(v)
                if not (DEV_IGNORE_PRIVATE_IPS and (addr.is_private or addr.is_loopback)):
                    return v
            except Exception:
                pass
    # Next: first public in XFF
    xff = request.headers.get("X-Forwarded-For", "")
    cand = _first_public_from_xff(xff)
    if cand:
        return cand
    # Fallback: remote_addr
    ip = request.remote_addr or request.environ.get("REMOTE_ADDR") or "unknown"
    try:
        addr = ipaddress.ip_address(ip)
        if DEV_IGNORE_PRIVATE_IPS and (addr.is_private or addr.is_loopback):
            return ip
    except Exception:
        pass
    return ip

def is_blacklisted(ip):
    return ip in _state.get("blacklist", {})

def record_failed_attempt(ip):
    attempts = _state.setdefault("attempts", {})
    rec = attempts.setdefault(ip, {"tries": 0, "last": None})
    rec["tries"] = rec.get("tries", 0) + 1
    rec["last"] = int(datetime.now(timezone.utc).timestamp())
    if rec["tries"] >= MAX_TRIES:
        _state.setdefault("blacklist", {})[ip] = {"added": int(datetime.now(timezone.utc).timestamp())}
        attempts.pop(ip, None)
    _save_state()
    return rec["tries"]

def clear_attempts(ip):
    attempts = _state.setdefault("attempts", {})
    if ip in attempts:
        attempts.pop(ip)
        _save_state()

# --- Utility JSON helpers ---
def json_read(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def json_write(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# --- Routes ---
@app.route("/")
def index():
    ip = get_client_ip()
    if is_blacklisted(ip):
        return redirect(REDIRECT_URL, code=302)
    # If not authenticated, serve LOCKED page (no sensitive content)
    if not session.get("authed"):
        return render_template("locked.html")
    # Authenticated: serve the real page
    return render_template("index.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/check-password", methods=["POST"])
def check_password():
    ip = get_client_ip()
    if is_blacklisted(ip):
        return jsonify({"ok": False, "blockedRedirect": REDIRECT_URL}), 200

    payload = request.get_json(silent=True) or {}
    provided = (payload.get("password") or "").strip()

    # Compute today's password (America/Chicago if available)
    try:
        now = datetime.now(TZ) if TZ else datetime.now()
        day = now.day
        expected = f"GetDatBP{day + 10}"
    except Exception:
        expected = "GetDatBP"

    if provided == expected:
        session["authed"] = True
        clear_attempts(ip)
        return jsonify({"ok": True}), 200

    tries = record_failed_attempt(ip)
    attempts_left = max(0, MAX_TRIES - tries)
    if is_blacklisted(ip):
        return jsonify({"ok": False, "blockedRedirect": REDIRECT_URL}), 200
    return jsonify({"ok": False, "message": "Wrong password", "attemptsLeft": attempts_left}), 200

# --- Your existing data routes (kept) ---
@app.route("/stats.json")
def stats():
    if not STATS_CSV.exists():
        return jsonify([])

    df = pd.read_csv(STATS_CSV)
    df = df.fillna("")
    return jsonify(df.to_dict(orient="records"))


@app.route("/roulette_data.json")
def get_roulette_data():
    if not ROULETTE_JSON.exists():
        return jsonify([])

    data = json_read(ROULETTE_JSON)
    return jsonify(data)


@app.route("/stats_all.json")
def stats_all():
    if not ROULETTE_ALL_JSON.exists():
        return jsonify([])

    from strategy_stats_generator import generate_strategy_stats
    generate_strategy_stats(
        str(ROULETTE_ALL_JSON),
        str(STATS_ALL_CSV),
    )

    if not STATS_ALL_CSV.exists():
        return jsonify([])

    df = pd.read_csv(STATS_ALL_CSV).fillna("")
    return jsonify(df.to_dict(orient="records"))

@app.route("/data", methods=["POST"])
def receive_data():
    try:
        new_data = request.json["data"]

        json_write(ROULETTE_JSON, new_data)

        try:
            existing = json_read(ROULETTE_ALL_JSON)
        except FileNotFoundError:
            existing = new_data.copy()
            json_write(ROULETTE_ALL_JSON, existing)

        newest_roll = new_data[0] if new_data else None

        if newest_roll and (not existing or newest_roll != existing[0]):
            updated = [newest_roll] + existing
            json_write(ROULETTE_ALL_JSON, updated)

        from strategy_stats_generator import generate_strategy_stats
        generate_strategy_stats(
            str(ROULETTE_JSON),
            str(STATS_CSV),
        )

        sync_to_global_collector(new_data)

        return jsonify({"status": "success", "message": "New roll added to ALL file."})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "server": os.environ.get("SERVER_NAME", "unknown"),
        "time": datetime.now(timezone.utc).isoformat()
    })

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "100"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    _load_state()
    app.run(host=host, port=port, debug=debug, threaded=True)
