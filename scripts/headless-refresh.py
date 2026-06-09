#!/usr/bin/env python3
"""
sArthI — Headless Airflow session refresh. Completes in ~15s.

Key insight: navigate to Houston OAuth start URL directly.
Google auto-authenticates with saved cookies → Houston issues fresh JWT.
No user interaction needed.

Paths owned by sArthI (~/.wibey/sarthi/), not prod-monitor.
"""

import sys, os, time, json
from urllib.parse import urlparse
sys.stdout.reconfigure(line_buffering=True)

SESSION_FILE     = os.path.expanduser("~/.wibey/sarthi/session.json")
COOKIES_FILE     = os.path.expanduser("~/.wibey/sarthi/cookies.txt")
CONFIG_FILE      = os.path.expanduser("~/.wibey/sarthi/config.yaml")
DEV_CONFIG_FILE  = os.path.expanduser("~/.wibey/sarthi/dev-config.yaml")

def houston_oauth_url(deployment_url):
    """Derive Houston OAuth start URL from a deployment URL's hostname cluster."""
    host = urlparse(deployment_url).netloc  # e.g. deployments.astro-prod3.us-central1.us.walmart.net
    # Replace 'deployments.' prefix with 'houston.'
    houston_host = host.replace("deployments.", "houston.", 1)
    return f"https://{houston_host}/v1/oauth/start?provider=google"

def main():
    if not os.path.exists(SESSION_FILE):
        print("❌ No session.json. Run: python3 ~/sarthi/scripts/setup-session.py", file=sys.stderr)
        sys.exit(1)

    try:
        from playwright.sync_api import sync_playwright
        import yaml
    except ImportError as e:
        print(f"❌ Missing dependency: {e}", file=sys.stderr)
        sys.exit(1)

    cfg          = yaml.safe_load(open(CONFIG_FILE))
    environments = cfg.get("environments", [])
    # Skip disabled environments and those with invalid/TODO URLs
    deployment_urls = [
        e["url"] for e in environments
        if not e.get("disabled")
        and e.get("url", "").startswith("https://")
    ]

    # Include dev environments if dev-config.yaml exists
    if os.path.exists(DEV_CONFIG_FILE):
        try:
            dev_cfg  = yaml.safe_load(open(DEV_CONFIG_FILE))
            dev_envs = dev_cfg.get("dev_environments", [])
            dev_urls = [e["url"] for e in dev_envs]
            # Only add dev URLs that aren't already covered by prod clusters
            new_dev_urls = [u for u in dev_urls if u not in deployment_urls]
            if new_dev_urls:
                print(f"   ℹ️  Including {len(new_dev_urls)} new dev cluster URL(s) from dev-config.yaml")
            deployment_urls = deployment_urls + new_dev_urls
        except Exception as e:
            print(f"⚠️  Could not read dev-config.yaml: {e} (skipping dev environments)")

    # Deduplicate OAuth endpoints by cluster (multiple envs may share a cluster)
    oauth_urls = list(dict.fromkeys(houston_oauth_url(u) for u in deployment_urls))

    print("🔄 Headless session refresh starting...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(storage_state=SESSION_FILE)
        page    = ctx.new_page()

        # Step 1: Authenticate to each unique cluster via Houston OAuth
        for oauth_url in oauth_urls:
            print(f"   → OAuth: {oauth_url}")
            try:
                page.goto(oauth_url, wait_until="networkidle", timeout=30000)
            except Exception as e:
                print(f"⚠️  OAuth nav warning: {e}", file=sys.stderr)

            cookies = ctx.cookies()
            jwt = next((c for c in cookies if "astronomer" in c["name"].lower() and "auth" in c["name"].lower()), None)
            if not jwt:
                print(f"❌ JWT not obtained for {oauth_url}. Google SSO may have expired.", file=sys.stderr)
                print("   Run: python3 ~/sarthi/scripts/setup-session.py to re-authenticate.", file=sys.stderr)
                browser.close()
                sys.exit(1)
            print(f"   ✅ JWT obtained: {jwt['name']}")

        # Step 2: Touch each deployment URL (gets session cookie for API calls)
        for dep_url in deployment_urls:
            print(f"   → Deployment: {dep_url}")
            try:
                page.goto(dep_url, wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                print(f"⚠️  Dep nav warning: {e}", file=sys.stderr)
            print(f"   ✓ {page.url[:80]}")

        # Save session + cookies
        ctx.storage_state(path=SESSION_FILE)

        cookies = ctx.cookies()
        lines = ["# Netscape HTTP Cookie File"]
        for c in cookies:
            domain = c.get("domain", "")
            flag   = "TRUE" if domain.startswith(".") else "FALSE"
            expiry = int(c.get("expires", 0)) if c.get("expires", -1) > 0 else 0
            lines.append(f"{domain}\t{flag}\t{c['path']}\t{'TRUE' if c.get('secure') else 'FALSE'}\t{expiry}\t{c['name']}\t{c['value']}")
        open(COOKIES_FILE, "w").write("\n".join(lines) + "\n")

        browser.close()

    print(f"✅ Refreshed — {len(cookies)} cookies saved.")

if __name__ == "__main__":
    main()
