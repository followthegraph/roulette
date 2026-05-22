import subprocess
import threading
import requests
import ipaddress
import pandas as pd
import json
import math
import os
from flask import Flask, request, jsonify, render_template, redirect, session, url_for
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from pathlib import Path
from datetime import datetime, timezone
from functools import wraps

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
URGENCY_SNAPSHOT_JSON = DATA_DIR / "urgency_snapshot.json"

load_dotenv(ENV_PATH, override=True)

server_name = os.environ.get("SERVER_NAME", "unknown")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("admin_auth") != ADMIN_PASSWORD:
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

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
        "local": True,
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
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=86400,
)
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

def get_remote_status(server):
    if server.get("local"):
        ps = r'powershell.exe -ExecutionPolicy Bypass -File "C:\Roll\scripts\rollctl.ps1" -Action json_status'
        cmd = ["powershell.exe", "-NoProfile", "-Command", ps]
    else:
        ps = f"""
        $Cred = Import-Clixml "{server['cred']}";
        Invoke-Command -ComputerName {server['host']} `
          -Credential $Cred `
          -Authentication Negotiate `
          -ScriptBlock {{
            powershell.exe -ExecutionPolicy Bypass -File "C:\\Roll\\scripts\\rollctl.ps1" -Action json_status
          }}
        """
        cmd = ["powershell.exe", "-NoProfile", "-Command", ps]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30
    )

    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }

def run_remote_action(server, action):
    if server.get("local"):
        ps = f'powershell.exe -ExecutionPolicy Bypass -File "C:\\Roll\\scripts\\rollctl.ps1" -Action {action}'
    else:
        ps = f"""
        $Cred = Import-Clixml "{server['cred']}";
        Invoke-Command -ComputerName {server['host']} `
          -Credential $Cred `
          -Authentication Negotiate `
          -ScriptBlock {{
            param($Action)
            powershell.exe -ExecutionPolicy Bypass -File "C:\\Roll\\scripts\\rollctl.ps1" -Action $Action
          }} -ArgumentList "{action}"
        """

    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=60
    )

    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }

def get_strategy_numbers(strategy):
    strategy = str(strategy or "").lstrip("'").strip()

    bets = {
        "Odds": list(range(1, 37, 2)),
        "Even": list(range(2, 37, 2)),
        "Red": [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36],
        "Black": [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35],
        "1 to 18": list(range(1, 19)),
        "19 to 36": list(range(19, 37)),

        "First Line": [1, 2, 3, 4, 5, 6],
        "Second Line": [7, 8, 9, 10, 11, 12],
        "Third Line": [13, 14, 15, 16, 17, 18],
        "Fourth Line": [19, 20, 21, 22, 23, 24],
        "Fifth Line": [25, 26, 27, 28, 29, 30],
        "Sixth Line": [31, 32, 33, 34, 35, 36],

        "1st & 2nd & 12": list(range(1, 25)),
        "1st & 3rd & 12": list(range(1, 13)) + list(range(25, 37)),
        "2nd & 3rd & 12": list(range(13, 37)),

        "Top & Middle Row": list(range(3, 37, 3)) + list(range(2, 36, 3)),
        "Top & Bottom Row": list(range(3, 37, 3)) + list(range(1, 35, 3)),
        "Middle & Bottom Row": list(range(2, 36, 3)) + list(range(1, 35, 3)),
        "Zero": [0, 3, 12, 15, 26, 32, 35],
        "Tiers": [5, 8, 10, 11, 13, 16, 23, 24, 27, 30, 33, 36],
        "Orphelins": [1, 6, 9, 14, 17, 20, 31, 34],
        "Voisins Du Zero": [0, 2, 3, 4, 7, 12, 15, 18, 19, 21, 22, 25, 26, 28, 29, 32, 35],

        "Top Row": list(range(3, 37, 3)),
        "Middle Row": list(range(2, 36, 3)),
        "Bottom Row": list(range(1, 35, 3)),

        "1st & 12": list(range(1, 13)),
        "2nd & 12": list(range(13, 25)),
        "3rd & 12": list(range(25, 37)),

        "First Street": [1, 2, 3],
        "Second Street": [4, 5, 6],
        "Third Street": [7, 8, 9],
        "Fourth Street": [10, 11, 12],
        "Fifth Street": [13, 14, 15],
        "Sixth Street": [16, 17, 18],
        "Seventh Street": [19, 20, 21],
        "Eighth Street": [22, 23, 24],
        "Ninth Street": [25, 26, 27],
        "Tenth Street": [28, 29, 30],
        "Eleventh Street": [31, 32, 33],
        "Twelfth Street": [34, 35, 36],

        "Crossfire, 1st & top": sorted(set(list(range(1, 13)) + list(range(3, 37, 3)))),
        "Crossfire, 1st & middle": sorted(set(list(range(1, 13)) + list(range(2, 36, 3)))),
        "Crossfire, 1st & bottom": sorted(set(list(range(1, 13)) + list(range(1, 35, 3)))),
        "Crossfire, 2nd & top": sorted(set(list(range(13, 25)) + list(range(3, 37, 3)))),
        "Crossfire, 2nd & middle": sorted(set(list(range(13, 25)) + list(range(2, 36, 3)))),
        "Crossfire, 2nd & bottom": sorted(set(list(range(13, 25)) + list(range(1, 35, 3)))),
        "Crossfire, 3rd & top": sorted(set(list(range(25, 37)) + list(range(3, 37, 3)))),
        "Crossfire, 3rd & middle": sorted(set(list(range(25, 37)) + list(range(2, 36, 3)))),
        "Crossfire, 3rd & bottom": sorted(set(list(range(25, 37)) + list(range(1, 35, 3)))),

        "Adj Street, 1st & 2nd": [1, 2, 3, 4, 5, 6],
        "Adj Street, 2nd & 3rd": [4, 5, 6, 7, 8, 9],
        "Adj Street, 3rd & 4th": [7, 8, 9, 10, 11, 12],
        "Adj Street, 4th & 5th": [10, 11, 12, 13, 14, 15],
        "Adj Street, 5th & 6th": [13, 14, 15, 16, 17, 18],
        "Adj Street, 6th & 7th": [16, 17, 18, 19, 20, 21],
        "Adj Street, 7th & 8th": [19, 20, 21, 22, 23, 24],
        "Adj Street, 8th & 9th": [22, 23, 24, 25, 26, 27],
        "Adj Street, 9th & 10th": [25, 26, 27, 28, 29, 30],
        "Adj Street, 10th & 11th": [28, 29, 30, 31, 32, 33],
        "Adj Street, 11th & 12th": [31, 32, 33, 34, 35, 36],
    }

    # Strip parenthetical street labels.
    if "(" in strategy:
        strategy = strategy.split("(")[0].strip()

    return bets.get(strategy)

# --- Utility JSON helpers ---
def json_read(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def json_write(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_global_rolls_for_stats(wheel_id, window="500"):
    params = [wheel_id]
    limit_clause = ""

    if str(window).lower() != "all":
        try:
            limit = max(1, int(window))
        except Exception:
            limit = 500

        limit_clause = "LIMIT ?"
        params.append(limit)

    rows = global_db_rows(f"""
        SELECT number, color, seq, created_at_utc
        FROM wheel_rolls
        WHERE wheel_id = ?
        ORDER BY seq DESC
        {limit_clause}
    """, tuple(params))

    # strategy generator expects newest-first, same as roulette_data.json
    return [
        {
            "number": int(r["number"]),
            "color": r.get("color", ""),
            "seq": r.get("seq"),
            "created_at_utc": r.get("created_at_utc"),
        }
        for r in rows
    ]

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

@app.after_request
def add_security_headers(resp):
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp

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

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None

    if request.method == "POST":
        password = request.form.get("password", "")

        if password == ADMIN_PASSWORD:
            session.permanent = True
            session["admin_auth"] = ADMIN_PASSWORD
            return redirect("/ops/control-center")
        else:
            error = "Invalid password"

    return f"""
    <html>
    <head>
        <title>Roulette Admin Login</title>
        <style>
            body {{
                font-family: Arial;
                background: #111827;
                color: white;
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
                margin: 0;
            }}

            .card {{
                background: #1f2937;
                padding: 32px;
                border-radius: 16px;
                width: 320px;
                box-shadow: 0 10px 40px rgba(0,0,0,.4);
            }}

            input {{
                width: 100%;
                padding: 12px;
                margin-top: 12px;
                border-radius: 10px;
                border: 1px solid #374151;
                background: #111827;
                color: white;
            }}

            button {{
                width: 100%;
                padding: 12px;
                margin-top: 16px;
                border: 0;
                border-radius: 10px;
                background: #2563eb;
                color: white;
                font-weight: bold;
                cursor: pointer;
            }}

            .error {{
                color: #f87171;
                margin-top: 10px;
            }}
        </style>
    </head>

    <body>
        <div class="card">
            <h2>Roulette Admin</h2>

            <form method="POST">
                <input
                    type="password"
                    name="password"
                    placeholder="Password"
                    autofocus
                />

                <button type="submit">
                    Login
                </button>
            </form>

            {f'<div class="error">{error}</div>' if error else ''}
        </div>
    </body>
    </html>
    """

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_auth", None)
    return redirect("/admin/login")


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

@app.route("/stats-window.json")
def stats_window():
    import tempfile
    from strategy_stats_generator import generate_strategy_stats

    wheel_id = request.args.get("wheel_id") or WHEEL_ID
    window = request.args.get("window", "500")

    rolls = get_global_rolls_for_stats(wheel_id, window)

    if not rolls:
        return jsonify([])

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8"
    ) as jf:
        json.dump(rolls, jf)
        temp_json_path = jf.name

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".csv",
        delete=False,
        encoding="utf-8"
    ) as cf:
        temp_csv_path = cf.name

    try:
        generate_strategy_stats(temp_json_path, temp_csv_path)

        df = pd.read_csv(temp_csv_path).fillna("")
        records = df.to_dict(orient="records")

        for r in records:
            r["Stats Window"] = window
            r["Wheel ID"] = wheel_id
            r["Stats Source"] = "global_rolls.sqlite"

        return jsonify(records)

    finally:
        try:
            os.remove(temp_json_path)
        except Exception:
            pass

        try:
            os.remove(temp_csv_path)
        except Exception:
            pass

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
# @admin_required
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
# @admin_required
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

ALLOWED_SERVER_ACTIONS = {
    "start_app", "stop_app", "restart_app",
    "start_tunnel", "stop_tunnel", "restart_tunnel",
    "start_persistence", "restart_persistence",
    "start_collector", "restart_collector",
    "restart_all_clean",
    "update",
    "update_and_restart",
    "json_status",
}

@app.route("/admin/server-action/<server_name>/<action>", methods=["POST"])
@admin_required
def admin_server_action(server_name, action):
    if server_name not in REMOTE_SERVERS:
        return jsonify({"ok": False, "error": "Unknown server"}), 404

    if action not in ALLOWED_SERVER_ACTIONS:
        return jsonify({"ok": False, "error": "Action not allowed"}), 400

    server = REMOTE_SERVERS[server_name]

    try:
        result = run_remote_action(server, action)
        return jsonify({
            "ok": result["ok"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/admin/server-status")
@admin_required
def admin_server_status():
    results = {}

    for name, server in REMOTE_SERVERS.items():
        results[name] = get_remote_status(server)
        results[name]["collector_expected"] = server["collector"]

    return jsonify(results)

@app.route("/ops/control-center")
@admin_required
def admin_servers():
    return render_template("server_admin.html")

@app.route("/global-monitor")
# @admin_required
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

@app.route("/strategy-profile")
# @admin_required
def strategy_profile():
    import statistics
    import math

    wheel_id = request.args.get("wheel_id") or WHEEL_ID
    strategy = request.args.get("strategy", "").lstrip("'").strip()
    window = request.args.get("window", "500")

    numbers = get_strategy_numbers(strategy)

    if not numbers:
        return jsonify({
            "ok": False,
            "error": "Unknown strategy",
            "strategy": strategy
        }), 404

    limit_clause = ""
    params = [wheel_id]

    if window != "all":
        try:
            limit = max(1, int(window))
            limit_clause = "LIMIT ?"
            params.append(limit)
        except Exception:
            limit = 500
            limit_clause = "LIMIT ?"
            params.append(limit)

    rows = global_db_rows(f"""
        SELECT number, seq, created_at_utc
        FROM wheel_rolls
        WHERE wheel_id = ?
        ORDER BY seq DESC
        {limit_clause}
    """, tuple(params))

    rolls = list(reversed(rows))  # oldest -> newest

    hit_indices = [
        idx for idx, row in enumerate(rolls)
        if int(row["number"]) in numbers
    ]

    delays = [
        hit_indices[i] - hit_indices[i - 1]
        for i in range(1, len(hit_indices))
    ]

    latest_index = len(rolls) - 1
    last_hit_index = hit_indices[-1] if hit_indices else None
    current_delay = latest_index - last_hit_index if last_hit_index is not None else None

    def percentile(values, p):
        if not values:
            return None
        values = sorted(values)
        k = (len(values) - 1) * (p / 100)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return values[int(k)]
        return values[f] * (c - k) + values[c] * (k - f)

    def current_percentile(values, current):
        if not values or current is None:
            return None
        below_or_equal = sum(1 for v in values if v <= current)
        return round((below_or_equal / len(values)) * 100, 2)

    profile = {
        "ok": True,
        "wheel_id": wheel_id,
        "strategy": strategy,
        "window": window,
        "covered_numbers": numbers,
        "roll_count": len(rolls),
        "hit_count": len(hit_indices),
        "current_delay": current_delay,
        "avg_delay": round(statistics.mean(delays), 2) if delays else None,
        "median_delay": round(statistics.median(delays), 2) if delays else None,
        "stddev_delay": round(statistics.stdev(delays), 2) if len(delays) > 1 else None,
        "min_delay": min(delays) if delays else None,
        "max_delay": max(delays) if delays else None,
        "p90_delay": round(percentile(delays, 90), 2) if delays else None,
        "p95_delay": round(percentile(delays, 95), 2) if delays else None,
        "p99_delay": round(percentile(delays, 99), 2) if delays else None,
        "current_percentile": current_percentile(delays, current_delay),
        "recent_delays": delays[-10:],
        "delays": delays,
    }

    return jsonify(profile)

@app.route("/backtest-entry.json")
def backtest_entry():
    wheel_id = request.args.get("wheel_id") or WHEEL_ID
    strategy = request.args.get("strategy", "").lstrip("'").strip()
    window = request.args.get("window", "500")

    success_rolls = int(request.args.get("success_rolls", 5))
    min_entries = int(request.args.get("min_entries", 8))
    max_wait_limit = request.args.get("max_wait_limit", "")

    try:
        max_wait_limit = int(max_wait_limit) if max_wait_limit != "" else None
    except Exception:
        max_wait_limit = None

    numbers = get_strategy_numbers(strategy)

    if not numbers:
        return jsonify({
            "ok": False,
            "error": "Unknown strategy",
            "strategy": strategy
        }), 404

    rows = get_global_rolls_for_stats(wheel_id, window)

    rolls = list(reversed(rows))
    nums = [int(r["number"]) for r in rolls]

    hit_indices = [
        i for i, n in enumerate(nums)
        if n in numbers
    ]

    delays = [
        hit_indices[i] - hit_indices[i - 1]
        for i in range(1, len(hit_indices))
    ]

    def percentile(values, p):
        if not values:
            return None

        values = sorted(values)
        k = (len(values) - 1) * (p / 100)
        f = int(k)
        c = min(f + 1, len(values) - 1)

        if f == c:
            return values[f]

        return values[f] * (c - k) + values[c] * (k - f)

    def simulate_threshold(label, threshold):
        if threshold is None:
            return None

        waits = []

        for delay in delays:
            if delay >= threshold:
                waits.append(delay - threshold)

        if not waits:
            return {
                "label": label,
                "threshold": math.ceil(threshold),
                "entries": 0,
                "avg_wait": None,
                "max_wait": None,
                "success_rolls": success_rolls,
                "success_rate": None,
                "hit_within_1": None,
                "hit_within_3": None,
                "hit_within_5": None,
                "hit_within_10": None,
                "recommendation_score": 0,
            }

        def hit_within(n):
            return round(
                sum(1 for w in waits if w <= n) / len(waits) * 100,
                2
            )

        success_rate = hit_within(success_rolls)
        avg_wait = round(sum(waits) / len(waits), 2)
        max_wait = max(waits)

        entry_count_score = min(25, (len(waits) / max(min_entries, 1)) * 25)
        success_score = (success_rate / 100) * 45
        max_wait_score = 20 if max_wait_limit is None else max(0, 20 - max(0, max_wait - max_wait_limit) * 4)
        efficiency_score = max(0, 10 - avg_wait)

        recommendation_score = round(
            min(100, entry_count_score + success_score + max_wait_score + efficiency_score)
        )

        return {
            "label": label,
            "threshold": math.ceil(threshold),
            "entries": len(waits),
            "avg_wait": avg_wait,
            "max_wait": math.ceil(max_wait),
            "success_rolls": success_rolls,
            "success_rate": success_rate,
            "hit_within_1": hit_within(1),
            "hit_within_3": hit_within(3),
            "hit_within_5": hit_within(5),
            "hit_within_10": hit_within(10),
            "recommendation_score": recommendation_score,
        }

    tests = {
        "P90": simulate_threshold("P90", percentile(delays, 90)),
        "P95": simulate_threshold("P95", percentile(delays, 95)),
        "P97": simulate_threshold("P97", percentile(delays, 97)),
        "P99": simulate_threshold("P99", percentile(delays, 99)),
    }

    def recommendation_payload(best, reason_prefix=""):
        if not best:
            return None

        prefix = f"{reason_prefix} " if reason_prefix else ""

        return {
            "label": best["label"],
            "threshold": math.ceil(best["threshold"]),
            "entries": best["entries"],
            "success_rolls": success_rolls,
            "success_rate": best["success_rate"],
            "avg_wait": best["avg_wait"],
            "max_wait": math.ceil(best["max_wait"]),
            "recommendation_score": best["recommendation_score"],
            "recommended_bankroll_depth": math.ceil(best["max_wait"]),
            "reason": (
                f"{prefix}{best['label']} is recommended because it had "
                f"{best['entries']} historical entries, "
                f"{best['success_rate']}% hit within {success_rolls} rolls, "
                f"an average wait of {best['avg_wait']} rolls, "
                f"and a worst wait of {best['max_wait']} rolls."
            )
        }


    all_valid = [
        t for t in tests.values()
        if t and t["entries"] > 0 and t["success_rate"] is not None
    ]

    strict_eligible = [
        t for t in all_valid
        if t["entries"] >= min_entries
        and (max_wait_limit is None or t["max_wait"] <= max_wait_limit)
    ]

    best_available_pool = [
        t for t in all_valid
        if t["entries"] >= max(3, min_entries // 2)
    ]

    def rank_key(t):
        return (
            t["recommendation_score"],
            t["success_rate"],
            -t["avg_wait"],
            t["entries"],
        )

    strict_best = sorted(strict_eligible, key=rank_key, reverse=True)[0] if strict_eligible else None
    best_available = sorted(best_available_pool, key=rank_key, reverse=True)[0] if best_available_pool else None

    strict_recommended_entry = recommendation_payload(strict_best)

    if strict_recommended_entry is None:
        strict_recommended_entry = {
            "label": None,
            "threshold": None,
            "reason": (
                f"No entry met the strict requirements of "
                f"{min_entries} historical entries"
                + (
                    f" and max wait <= {max_wait_limit}."
                    if max_wait_limit is not None else "."
                )
            )
        }

    best_available_entry = recommendation_payload(
        best_available,
        "Best available:"
    )

    if best_available_entry is None:
        best_available_entry = {
            "label": None,
            "threshold": None,
            "reason": "No historical entry point had enough examples to evaluate."
        }

    recommended_entry = (
        strict_recommended_entry
        if strict_recommended_entry.get("label")
        else best_available_entry
    )

    return jsonify({
        "ok": True,
        "wheel_id": wheel_id,
        "strategy": strategy,
        "window": window,
        "roll_count": len(nums),
        "hit_count": len(hit_indices),
        "delay_count": len(delays),
        "covered_numbers": numbers,
        "settings": {
            "success_rolls": success_rolls,
            "min_entries": min_entries,
            "max_wait_limit": max_wait_limit,
        },
        "entry_tests": tests,
        "recommended_entry": recommended_entry,
        "strict_recommended_entry": strict_recommended_entry,
        "best_available_entry": best_available_entry,
    })

@app.route("/global-roll-timing")
# @admin_required
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

@app.route("/urgency-snapshot", methods=["GET", "POST"])
def urgency_snapshot():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}

        snapshot = {
            "wheel_id": WHEEL_ID,
            "server_name": server_name,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "summary": payload.get("summary", {}),
            "top": payload.get("top", []),
        }

        json_write(URGENCY_SNAPSHOT_JSON, snapshot)
        return jsonify({"ok": True, "snapshot": snapshot})

    if not URGENCY_SNAPSHOT_JSON.exists():
        return jsonify({
            "wheel_id": WHEEL_ID,
            "server_name": server_name,
            "updated_at_utc": None,
            "summary": {"critical": 0, "imminent": 0, "watch": 0},
            "top": [],
        })

    return jsonify(json_read(URGENCY_SNAPSHOT_JSON))

@app.route("/global-urgency-snapshots")
def global_urgency_snapshots():
    hosts = {
        "eu-wheel": "https://eu.getdatbp.com",
        "flash-wheel": "https://flash.getdatbp.com",
        "classic-wheel": "https://classic.getdatbp.com",
    }

    results = {}

    for wheel_id, base_url in hosts.items():
        try:
            r = requests.get(f"{base_url}/urgency-snapshot", timeout=4)
            results[wheel_id] = r.json()
        except Exception as e:
            results[wheel_id] = {
                "wheel_id": wheel_id,
                "error": str(e),
                "summary": {"critical": 0, "imminent": 0, "watch": 0},
                "top": [],
            }

    return jsonify(results)

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "100"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    _load_state()
    app.run(host=host, port=port, debug=debug, threaded=True)
