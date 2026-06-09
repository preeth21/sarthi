#!/usr/bin/env python3
"""
patch-slack-api.py — Patch the slack-api Wibey skill to use curl instead of Node.js fetch.

Why: Node.js TLS stack rejects Walmart's enterprise Slack TLS cert.
     curl uses the macOS system TLS keychain which trusts it correctly.
     The slack-api skill SKILL.md says it uses curl, but api.js v1.0.x uses fetch
     for the initial call and only falls back to curl on invalid_auth.
     This patch makes curl the primary transport.

Usage:
  python3 ~/sarthi/scripts/patch-slack-api.py

Idempotent — safe to run multiple times and after skill updates.
Run after every: wibey --skill-install slack-api
"""

import sys
import re
from pathlib import Path

HOME = Path.home()


def find_api_js() -> Path | None:
    for root in [HOME / ".wibey", HOME / ".claude"]:
        for match in root.rglob("slack-api/scripts/api.js"):
            return match
    return None


# Try multiple patterns in order — handles different versions of the skill
FETCH_PATTERNS = [
    # v1.0.x exact pattern
    re.compile(
        r"const resp = await fetch\(`\$\{SLACK_API\}/\$\{method\}\?\$\{qp\}`.*?const data = await resp\.json\(\);",
        re.DOTALL,
    ),
    # More generic: any await fetch to SLACK_API followed by resp.json()
    re.compile(
        r"const resp = await fetch\(`\$\{SLACK_API\}.*?const data = await resp\.json\(\);",
        re.DOTALL,
    ),
    # Even more generic: any fetch block with resp.json
    re.compile(
        r"const resp = await fetch\(.*?SLACK_API.*?\).*?const data = await resp\.json\(\);",
        re.DOTALL,
    ),
]
FETCH_PATTERN = None  # resolved at runtime

CURL_REPLACEMENT = """// Use curl instead of Node fetch — Node.js TLS stack rejects Walmart's enterprise cert
  // curl uses the system TLS stack which works correctly on Walmart network
  // Patched by ~/sarthi/scripts/patch-slack-api.py — re-run after skill updates
  const curlResult = spawnSync('curl', [
    '-sk', '--max-time', '30', '-X', 'POST',
    '-H', `Cookie: ${session.cookieString}`,
    '-H', 'Content-Type: application/x-www-form-urlencoded',
    '-H', `Origin: https://app.slack.com`,
    '-H', `User-Agent: ${BASE_HEADERS['User-Agent']}`,
    '--data-raw', body.toString(),
    `${SLACK_API}/${method}?${qp}`,
  ], { encoding: 'utf8', maxBuffer: 10 * 1024 * 1024 });

  if (curlResult.error) throw curlResult.error;
  if (!curlResult.stdout) throw new Error(`curl returned empty response for ${method}`);

  const data = JSON.parse(curlResult.stdout);"""

PATCH_MARKER = "// Patched by ~/sarthi/scripts/patch-slack-api.py"


def main():
    api_js = find_api_js()
    if not api_js:
        print("❌ slack-api skill not found — run /skill-installer slack-api first")
        return 1

    print(f"Found: {api_js}")
    content = api_js.read_text()

    if PATCH_MARKER in content:
        print("✅ Already patched — no changes needed")
        return 0

    # Try each pattern in order
    active_pattern = None
    for p in FETCH_PATTERNS:
        if p.search(content):
            active_pattern = p
            break

    if not active_pattern:
        print("⚠️  fetch pattern not found in api.js — skill may have been updated to a new version")
        print("   Check api.js manually: find the 'await fetch(SLACK_API' block and replace with curl")
        print("   Then add the comment: // Patched by ~/sarthi/scripts/patch-slack-api.py")
        return 1

    patched = active_pattern.sub(CURL_REPLACEMENT, content, count=1)

    if patched == content:
        print("⚠️  Pattern found but substitution produced no change — check api.js manually")
        return 1

    # Backup original
    backup = api_js.with_suffix(".js.orig")
    if not backup.exists():
        backup.write_text(content)
        print(f"Backup: {backup}")

    api_js.write_text(patched)
    print(f"✅ Patched: {api_js}")
    print("   Node.js fetch → curl (system TLS, works with Walmart enterprise cert)")

    # Quick verify
    import subprocess
    r = subprocess.run(["node", str(api_js), "auth.test"],
                       capture_output=True, text=True, timeout=30,
                       cwd=str(api_js.parent.parent))
    if r.returncode == 0 and '"ok": true' in r.stdout or '"ok":true' in r.stdout:
        import json
        d = json.loads(r.stdout)
        print(f"✅ Verified: authenticated as {d.get('user', '?')} on {d.get('team', '?')}")
    else:
        print(f"⚠️  auth.test after patch: {r.stdout[:200] or r.stderr[:200]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
