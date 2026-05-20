from flask import Flask, request, jsonify, render_template, redirect, session
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import threading
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

DATA_LOCK = threading.Lock()
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
GLOBAL_DB_PATH = ROOT_DIR / "global" / "global_rolls.sqlite"

load_dotenv(ENV_PATH, override=True)

server_name = os.environ.get("SERVER_NAME", "unknown")

REMOTE_SERVERS = {
    "classic": {
        "host": "BP-Classic",
        "cred": r"C:\Roll\certs\classic-rouletteadmin.xml",
        "collector": False,
    },
    "eu": {
        "host": "BP-Euro0",
        "cred": r"C:\Roll\certs\eu-rouletteadmin.xml",
        "collector": True,
    },
    "flash": {
        "host": "BP-EuroFlash",
        "cred": r"C:\Roll\certs\flash-rouletteadmin.xml",
        "collector": False,
    },
}

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

import subprocess

def get_remote_status(server):
    ps = f"""
    $Cred = Import-Clixml "{server['cred']}";
    Invoke-Command -ComputerName {server['host']} `
      -Credential $Cred `
      -Authentication Negotiate `
      -ScriptBlock {{
        powershell.exe -ExecutionPolicy Bypass -File "C:\\Roll\\scripts\\rollctl.ps1" -Action status
      }}
    """

    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=30
    )

    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }

# --- Utility JSON helpers ---
def json_read(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def json_write(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def global_db_rows(query, params=()):
    import sqlite3

    if not GLOBAL_DB_PATH.exists():
        return []

    conn = sqlite3.connect(GLOBAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(query, params)
    rows = [dict(row) for row in cur.fetchall()]

    conn.close()
    return rows

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
    return render_template("index.html",server_name=server_name)

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

@app.route("/data", methods=["POST", "OPTIONS"])
def receive_data():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    with DATA_LOCK:
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

            return jsonify({"status": "success", "message": "Data processed."})

        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/global-summary")
def global_summary():
    rows = global_db_rows("""
        SELECT
            wheel_id,
            COUNT(*) AS total_rolls,
            MIN(seq) AS min_seq,
            MAX(seq) AS max_seq,
            MAX(created_at_utc) AS last_write_utc
        FROM wheel_rolls
        GROUP BY wheel_id
        ORDER BY wheel_id
    """)

    return jsonify(rows)


@app.route("/global-latest")
def global_latest():
    rows = global_db_rows("""
        SELECT
            wr.wheel_id,
            wr.seq,
            wr.number,
            wr.color,
            wr.created_at_utc
        FROM wheel_rolls wr
        INNER JOIN (
            SELECT wheel_id, MAX(seq) AS max_seq
            FROM wheel_rolls
            GROUP BY wheel_id
        ) latest
            ON wr.wheel_id = latest.wheel_id
           AND wr.seq = latest.max_seq
        ORDER BY wr.wheel_id
    """)

    return jsonify(rows)

@app.route("/admin/server-status")
def admin_server_status():
    results = {}

    for name, server in REMOTE_SERVERS.items():
        results[name] = get_remote_status(server)
        results[name]["collector_expected"] = server["collector"]

    return jsonify(results)

@app.route("/admin/servers")
def admin_servers():
    return render_template("server_admin.html")

@app.route("/global-monitor")
def global_monitor():

    rows = global_db_rows("""
        WITH ordered AS (
            SELECT
                wheel_id,
                seq,
                created_at_utc,
                LAG(created_at_utc) OVER (
                    PARTITION BY wheel_id
                    ORDER BY seq
                ) AS prev_created
            FROM wheel_rolls
        ),
        timing AS (
            SELECT
                wheel_id,
                ROUND(AVG(
                    (julianday(created_at_utc) - julianday(prev_created)) * 86400.0
                ), 2) AS avg_gap_seconds,
                ROUND(MAX(
                    (julianday(created_at_utc) - julianday(prev_created)) * 86400.0
                ), 2) AS max_gap_seconds
            FROM ordered
            WHERE prev_created IS NOT NULL
            GROUP BY wheel_id
        ),
        latest AS (
            SELECT
                wheel_id,
                COUNT(*) AS total_rolls,
                MAX(seq) AS latest_seq,
                MAX(created_at_utc) AS last_write_utc
            FROM wheel_rolls
            GROUP BY wheel_id
        )
        SELECT
            latest.wheel_id,
            latest.total_rolls,
            latest.latest_seq,
            latest.last_write_utc,
            timing.avg_gap_seconds,
            timing.max_gap_seconds
        FROM latest
        LEFT JOIN timing
            ON latest.wheel_id = timing.wheel_id
        ORDER BY latest.wheel_id
    """)

    now = datetime.now(timezone.utc)
    results = []

    for row in rows:
        status = "OK"
        stale_minutes = None
        stale_seconds = None

        avg_gap_seconds = row.get("avg_gap_seconds") or 60

        warning_seconds = max(avg_gap_seconds * 3, 120)
        stale_threshold_seconds = max(avg_gap_seconds * 5, 180)
        down_threshold_seconds = max(avg_gap_seconds * 10, 600)

        try:
            last_write = datetime.fromisoformat(row["last_write_utc"])
            stale_seconds = round((now - last_write).total_seconds(), 2)
            stale_minutes = round(stale_seconds / 60.0, 2)

            if stale_seconds >= down_threshold_seconds:
                status = "DOWN"
            elif stale_seconds >= stale_threshold_seconds:
                status = "STALE"
            elif stale_seconds >= warning_seconds:
                status = "WARNING"

        except Exception:
            status = "UNKNOWN"

        results.append({
            "wheel_id": row["wheel_id"],
            "status": status,
            "stale_seconds": stale_seconds,
            "stale_minutes": stale_minutes,
            "avg_gap_seconds": row.get("avg_gap_seconds"),
            "max_gap_seconds": row.get("max_gap_seconds"),
            "warning_seconds": round(warning_seconds, 2),
            "stale_threshold_seconds": round(stale_threshold_seconds, 2),
            "down_threshold_seconds": round(down_threshold_seconds, 2),
            "latest_seq": row["latest_seq"],
            "total_rolls": row["total_rolls"],
            "last_write_utc": row["last_write_utc"]
        })

    return jsonify(results)

@app.route("/global-roll-timing")
def global_roll_timing():

    rows = global_db_rows("""

        WITH ordered AS (
            SELECT
                wheel_id,
                seq,
                created_at_utc,
                LAG(created_at_utc) OVER (
                    PARTITION BY wheel_id
                    ORDER BY seq
                ) AS prev_created
            FROM wheel_rolls
        )

        SELECT
            wheel_id,
            ROUND(AVG(
                (
                    julianday(created_at_utc) -
                    julianday(prev_created)
                ) * 86400.0
            ), 2) AS avg_gap_seconds,

            ROUND(MAX(
                (
                    julianday(created_at_utc) -
                    julianday(prev_created)
                ) * 86400.0
            ), 2) AS max_gap_seconds

        FROM ordered
        WHERE prev_created IS NOT NULL
        GROUP BY wheel_id
        ORDER BY wheel_id

    """)

    return jsonify(rows)

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
