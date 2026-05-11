from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv
import json
import os
import time


# ----------------------------
# Load config and credentials
# ----------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.local.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_PATH)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

PROFILE_DIR = config["profile_dir"]
URL = config["url"]
SCRAPER_PATH = config["scraper_path"]

ROULETTE_USER = os.getenv("ROULETTE_USER")
ROULETTE_PASS = os.getenv("ROULETTE_PASS")


# ----------------------------
# Selectors
# ----------------------------

GAME_FRAME_URL_PART = "webiframe.launcher"
GAME_FRAME_GAME_PART = "/game/"

STATS_BUTTON_SELECTOR = 'button[data-qa="button-statistics"]'
LAST_500_SELECTOR = 'button.tabs-bar-item:has-text("Last 500")'
STATS_ITEM_SELECTOR = 'div[class^="stats-item-"], div[class*=" stats-item-"]'


# ----------------------------
# Helpers
# ----------------------------

def debug_frames(page):
    print("Main page:", page.url)
    print("Frames found:", len(page.frames))

    for i, frame in enumerate(page.frames):
        try:
            print(f"\nFRAME {i}")
            print("url:", frame.url)
            print("title:", frame.title())
            body = frame.locator("body").inner_text(timeout=3000)
            print(body[:750])
        except Exception as e:
            print("Could not read frame:", e)


def login_if_needed(page):
    """
    Attempts login only if the outer Bovada page appears logged out.
    You may need to adjust the username/password selectors after inspecting the login modal.
    """

    login_button = page.locator('text=LOGIN')

    if login_button.count() == 0:
        print("Login button not visible. Assuming already logged in.")
        return

    if not ROULETTE_USER or not ROULETTE_PASS:
        print("Login required, but ROULETTE_USER / ROULETTE_PASS are missing from .env.")
        print("Please log in manually in the opened browser.")
        page.wait_for_timeout(30000)
        return

    print("Login appears required. Attempting login...")

    login_button.first.click(timeout=30000)
    page.wait_for_timeout(3000)

    # These may need adjustment depending on Bovada's login form.
    username_input = page.locator(
        'input[name="username"], input[name="email"], input[type="email"], input[type="text"]'
    ).first

    password_input = page.locator(
        'input[name="password"], input[type="password"]'
    ).first

    username_input.wait_for(state="visible", timeout=30000)
    username_input.fill(ROULETTE_USER)

    password_input.wait_for(state="visible", timeout=30000)
    password_input.fill(ROULETTE_PASS)

    # Optional remember-me checkbox.
    try:
        remember = page.locator('input[type="checkbox"]')
        if remember.count() > 0:
            remember.first.check(timeout=3000)
            print("Checked remember-me checkbox.")
    except Exception:
        print("No remember-me checkbox checked.")

    submit_button = page.locator(
        'button:has-text("Log In"), button:has-text("Login"), button[type="submit"]'
    ).first

    submit_button.click(timeout=30000)

    print("Login submitted. Waiting for page/session to settle...")
    page.wait_for_timeout(15000)


def find_game_frame(page, timeout_seconds=60):
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        for frame in page.frames:
            if GAME_FRAME_URL_PART in frame.url and GAME_FRAME_GAME_PART in frame.url:
                return frame

        page.wait_for_timeout(1000)

    raise Exception("Could not find the live roulette game iframe.")


def open_last_500(game_frame):
    print("Clicking Statistics...")

    stats_button = game_frame.locator(STATS_BUTTON_SELECTOR)
    stats_button.wait_for(state="visible", timeout=30000)
    stats_button.click()

    print("Clicking Last 500...")

    try:
        last_500 = game_frame.locator(LAST_500_SELECTOR)
        last_500.wait_for(state="visible", timeout=30000)
        last_500.click()
    except PlaywrightTimeoutError:
        print("Specific Last 500 selector failed. Trying broad text selector...")
        game_frame.locator('button:has-text("Last 500")').click(timeout=30000)

    print("Waiting for stats items...")

    game_frame.wait_for_selector(STATS_ITEM_SELECTOR, timeout=30000)

    game_frame.evaluate("""
        window.scrollBy(0, 1);
        window.dispatchEvent(new Event('resize'));
        document.body.click();
    """)

    item_count = game_frame.locator(STATS_ITEM_SELECTOR).count()
    print(f"Stats item count found: {item_count}")

    if item_count < 450:
        print("Warning: expected close to 500 stats items, but fewer were found.")


def inject_scraper(game_frame):
    print("Injecting scraper...")

    with open(SCRAPER_PATH, "r", encoding="utf-8") as f:
        scraper_js = f.read()

    game_frame.evaluate(scraper_js)

    print("Scraper started.")


# ----------------------------
# Main
# ----------------------------

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=False,
        viewport={"width": 1400, "height": 900}
    )

    page = context.pages[0] if context.pages else context.new_page()

    print("Loading Bovada page...")
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)

    page.wait_for_timeout(5000)

    login_if_needed(page)

    print("Waiting for live game shell...")
    page.wait_for_timeout(15000)

    debug_frames(page)

    game_frame = find_game_frame(page)
    print("Using game frame:", game_frame.url)

    open_last_500(game_frame)
    inject_scraper(game_frame)

    print("Running. Press CTRL+C to stop.")

    while True:
        time.sleep(10)