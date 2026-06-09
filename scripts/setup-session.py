#!/usr/bin/env python3
"""
setup-session.py — First-time Airflow/Houston session bootstrap via headed Playwright.

Run ONCE per machine to establish a Google SSO session for Airflow (AFaaS / Astronomer).
After this runs successfully, headless-refresh.py handles all future refreshes automatically.

What it does:
  1. Opens a visible browser window (Playwright Chromium, headed)
  2. Navigates to the Houston OAuth URL for your first configured environment
  3. User completes Walmart Google SSO (may involve MFA)
  4. Saves the authenticated session to ~/.wibey/sarthi/session.json
  5. All future airflow auth runs headlessly — no browser needed

Usage:
    python3 ~/sarthi/scripts/setup-session.py [--config PATH]

Called by:
    scripts/first-time-auth.sh  (step 3 of 6 in the auth wizard)
"""

import sys
import os
import json
import time
from pathlib import Path
from urllib.parse import urlparse

SESSION_FILE = Path.home() / ".wibey" / "sarthi" / "session.json"
CONFIG_FILE = os.environ.get(
    "AIRFLOW_MCP_CONFIG",
    str(Path.home() / ".wibey" / "sarthi" / "config.yaml")
)
TIMEOUT_MS = 180_000  # 3 minutes for manual SSO


def houston_oauth_url(deployment_url: str) -> str:
    """Derive Houston OAuth start URL from a deployment URL."""
    host = urlparse(deployment_url).netloc
    houston_host = host.replace("deployments.", "houston.", 1)
    return f"https://{houston_host}/v1/oauth/start?provider=google"


def load_config() -> list:
    """Load environments from config.yaml. Returns list of deployment URLs."""
    try:
        import yaml
    except ImportError:
        print("❌ pyyaml not installed.")
        print("   Run: pip install pyyaml --index-url https://repository.cache.walmart.com/repository/pypi-proxy/simple/")
        sys.exit(1)

    cfg_path = Path(CONFIG_FILE)
    if not cfg_path.exists():
        print(f"❌ Config not found: {cfg_path}")
        print("   Create ~/.wibey/sarthi/config.yaml with your AFaaS environment URLs.")
        sys.exit(1)

    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    environments = cfg.get("environments", [])
    urls = [
        e["url"] for e in environments
        if not e.get("disabled") and e.get("url", "").startswith("https://")
    ]
    if not urls:
        print(f"❌ No enabled environments found in {cfg_path}")
        sys.exit(1)
    return urls


def main():
    import argparse
    parser = argparse.ArgumentParser(description="First-time Airflow session bootstrap (headed browser)")
    parser.add_argument("--config", help=f"Path to config.yaml (default: {CONFIG_FILE})")
    args = parser.parse_args()
    if args.config:
        global CONFIG_FILE
        CONFIG_FILE = args.config

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright not installed.")
        print("   Run: pip install playwright --index-url https://repository.cache.walmart.com/repository/pypi-proxy/simple/")
        print("        python3 -m playwright install chromium")
        sys.exit(1)

    print("=" * 60)
    print("✈️  Airflow Session Bootstrap (First-Time Setup)")
    print("=" * 60)

    deployment_urls = load_config()
    print(f"  Found {len(deployment_urls)} environment(s) in config")

    # Use the first env for initial SSO — headless-refresh.py will cover all of them later
    first_url = deployment_urls[0]
    oauth_url = houston_oauth_url(first_url)

    print(f"\n  🌐 Opening browser for Google SSO...")
    print(f"  📍 OAuth URL: {oauth_url}")
    print(f"\n  👆 A browser window will open.")
    print(f"     Log in with your Walmart Google account (@walmart.com).")
    print(f"     The window will close automatically when login succeeds.")
    print(f"  ⏳ Waiting up to 3 minutes...\n")

    session_dir = SESSION_FILE.parent
    session_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Headed — user must complete SSO
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            page.goto(oauth_url, wait_until="networkidle", timeout=TIMEOUT_MS)
        except Exception as e:
            print(f"  ⚠️  Navigation warning (may be OK): {e}")

        # Poll until we see an astronomer auth cookie (SSO complete)
        deadline = time.time() + (TIMEOUT_MS / 1000)
        jwt_found = False
        while time.time() < deadline:
            cookies = ctx.cookies()
            jwt = next(
                (c for c in cookies if "astronomer" in c["name"].lower() and "auth" in c["name"].lower()),
                None
            )
            if jwt:
                print(f"  ✅ SSO complete — JWT obtained: {jwt['name']}")
                jwt_found = True
                break
            time.sleep(2)

        if not jwt_found:
            print("  ❌ Timed out waiting for Google SSO.")
            print("     Did you complete the login in the browser window?")
            browser.close()
            sys.exit(1)

        # Touch all deployment URLs to get full session cookies
        for dep_url in deployment_urls:
            try:
                page.goto(dep_url, wait_until="domcontentloaded", timeout=30_000)
                print(f"  ✓ Touched: {dep_url[:80]}")
            except Exception as e:
                print(f"  ⚠️  {dep_url[:60]}: {e}")

        # Save session
        ctx.storage_state(path=str(SESSION_FILE))
        all_cookies = ctx.cookies()
        browser.close()

    print(f"\n✅ Session saved: {SESSION_FILE}")
    print(f"   Cookies: {len(all_cookies)}")
    print(f"\n🎉 Airflow first-time setup complete!")
    print(f"   Future refreshes run headlessly via headless-refresh.py — no browser needed.")


if __name__ == "__main__":
    main()
