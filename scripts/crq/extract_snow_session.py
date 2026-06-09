#!/usr/bin/env python3
"""
extract_snow_session.py — Extract ServiceNow session cookie via Chrome.

Two modes:
  Refresh mode (default): headless Chrome using an already-SSO'd chrome_profile.
    Used by: sarthi-snow-auth MCP (refresh_session tool), cron jobs.
    Requires: existing chrome_profile with valid Walmart PingFed session.

  First-time / bootstrap mode (--interactive): headed Chrome, visible window.
    Used by: scripts/first-time-auth.sh (run ONCE per machine, never again).
    User manually completes Walmart AD SSO in the browser window.
    Saves the chrome_profile so future headless refreshes work automatically.

Usage:
    python3 extract_snow_session.py [--profile-dir PATH] [--interactive]

Output:
    ~/.wibey/snow-session.json  — { "cookie_header": "...", "extracted_at": "...", ... }
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import TimeoutException, WebDriverException
except ImportError:
    print("❌ selenium not installed.")
    print("   Run: pip install selenium --index-url https://repository.cache.walmart.com/repository/pypi-proxy/simple/")
    sys.exit(1)

SERVICENOW_URL = "https://walmartglobal.service-now.com/wm_sp"
SESSION_FILE = Path.home() / ".wibey" / "snow-session.json"
DEFAULT_PROFILE_DIR = Path(__file__).parent / "chrome_profile"

# Cookie names ServiceNow uses for session auth
SESSION_COOKIE_NAMES = [
    "glide_user_session",
    "glide_session_store",
    "JSESSIONID",
    "BIGipServerpool_walmartglobal",
]


def find_chrome_profile():
    """Find an existing Chrome profile with a ServiceNow session."""
    candidates = [
        Path(__file__).parent / "chrome_profile",
        Path.home() / ".wibey" / "crq" / "chrome_profile",
        Path.home() / ".wibey" / "servicenow-ad-automation" / "chrome_profile",
    ]
    for p in candidates:
        if p.exists() and any(p.iterdir()):
            print(f"  ✅ Found Chrome profile: {p}")
            return str(p)
    return None


def extract_session(profile_dir: str = None, interactive: bool = False, timeout: int = 120) -> dict:
    """
    Launch Chrome, navigate to ServiceNow, extract session cookies.

    interactive=False (default): headless mode — profile must already have SSO session.
    interactive=True: headed mode — browser window opens, user completes SSO manually.
    """
    options = Options()

    if not interactive:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        print("  🤖 Mode: headless refresh")
    else:
        # Headed mode — user will see and interact with the browser
        options.add_argument("--window-size=1200,900")
        options.add_argument("--start-maximized")
        print("  🖥️  Mode: interactive first-time login")
        print("  👆 A Chrome window will open. Log in to ServiceNow with your Walmart credentials.")
        print("  ⏳ Waiting up to 2 minutes for you to complete SSO...")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")

    if profile_dir:
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir}")
        print(f"  📂 Chrome profile: {profile_dir}")
    else:
        print("  ⚠️  No profile dir specified — session won't be saved for future refreshes")

    driver = None
    try:
        print("  🌐 Launching Chrome...")
        driver = webdriver.Chrome(options=options)

        print(f"  🌐 Navigating to: {SERVICENOW_URL}")
        driver.get(SERVICENOW_URL)

        wait = WebDriverWait(driver, timeout)
        try:
            wait.until(lambda d: "service-now.com" in d.current_url and "login" not in d.current_url.lower())
            print(f"  ✅ ServiceNow loaded: {driver.current_url[:80]}")
        except TimeoutException:
            url = driver.current_url
            print(f"  ❌ Timed out waiting for ServiceNow — still at: {url}")
            if interactive:
                print("     Did you complete the SSO login in the browser window?")
            else:
                print("     Chrome profile may have an expired session.")
                print("     Fix: run first-time-auth.sh to re-establish the session.")
            sys.exit(1)

        # Wait for cookies to be fully set
        time.sleep(3)

        all_cookies = driver.get_cookies()
        print(f"  📦 Found {len(all_cookies)} cookies total")

        session_cookies = {}
        for cookie in all_cookies:
            if any(name.lower() in cookie["name"].lower() for name in SESSION_COOKIE_NAMES):
                session_cookies[cookie["name"]] = cookie["value"]
                print(f"    ✅ {cookie['name']} = {cookie['value'][:20]}...")

        if not session_cookies:
            print("  ⚠️  No known session cookies — using all cookies as fallback")
            cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in all_cookies)
            cookies_dict = {c["name"]: c["value"] for c in all_cookies}
        else:
            cookie_header = "; ".join(f"{k}={v}" for k, v in session_cookies.items())
            cookies_dict = session_cookies

        result = {
            "cookie_header": cookie_header,
            "cookies": cookies_dict,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "servicenow_url": SERVICENOW_URL,
            "profile_used": profile_dir or "none",
        }
        return result

    except WebDriverException as e:
        if "user data directory is already in use" in str(e):
            print("  ❌ Chrome profile is locked — close Google Chrome and retry.")
        elif "cannot find chrome binary" in str(e).lower():
            print("  ❌ Google Chrome not found.")
            print("     Install Google Chrome from: https://www.google.com/chrome/")
        else:
            print(f"  ❌ Chrome error: {e}")
        sys.exit(1)
    finally:
        if driver:
            driver.quit()
            print("  🔒 Browser closed")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Extract ServiceNow session cookie via Chrome",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Normal headless refresh (called by sarthi-snow-auth MCP):
  python3 extract_snow_session.py

  # First-time interactive login (run once to bootstrap):
  python3 extract_snow_session.py --interactive

  # Use a specific Chrome profile directory:
  python3 extract_snow_session.py --profile-dir ~/.wibey/crq/chrome_profile
        """
    )
    parser.add_argument("--profile-dir", help="Chrome profile directory (default: auto-detect from script dir)")
    parser.add_argument("--interactive", action="store_true",
                        help="Open headed Chrome for first-time SSO login (run once per machine)")
    args = parser.parse_args()

    print("=" * 60)
    print("🍪 ServiceNow Session Extractor")
    print("=" * 60)

    # Determine profile dir
    if args.profile_dir:
        profile_dir = args.profile_dir
    elif args.interactive:
        # First-time: always use the canonical sarthi profile location
        profile_dir = str(DEFAULT_PROFILE_DIR)
        print(f"  📂 Will create/use profile at: {profile_dir}")
    else:
        profile_dir = find_chrome_profile()
        if not profile_dir:
            print("  ❌ No existing Chrome profile found.")
            print("     This is a first-time setup. Run with --interactive:")
            print("     python3 extract_snow_session.py --interactive")
            sys.exit(1)

    session = extract_session(profile_dir=profile_dir, interactive=args.interactive)

    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SESSION_FILE, "w") as f:
        json.dump(session, f, indent=2)

    print(f"\n✅ Session saved: {SESSION_FILE}")
    print(f"   Cookies: {list(session['cookies'].keys())}")
    print(f"   Extracted at: {session['extracted_at']}")
    if args.interactive:
        print("\n🎉 First-time setup complete!")
        print("   Future refreshes will run headlessly (no browser window needed).")


if __name__ == "__main__":
    main()
