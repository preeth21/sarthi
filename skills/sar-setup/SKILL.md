---
name: "sar-setup"
key: "sar-setup"
description: "sArthI's first-time and re-run installer. Validates all runtime dependencies (Python, Node/Bun, gh CLI, gcloud), installs missing Wibey skills (bigquery-explorer, msgraph), checks auth tokens (GEC GitHub, msgraph, mcp-jira, ServiceNow), and reports what's working vs. what needs attention."
allowed-tools: [Read, Bash, Skill]
metadata:
  author: "akiran"
  version: "2.0.0"
  part-of: "sarthi"
  status: "active"
---

# sar-setup — Wibey-Layer Setup & Health Validator

## Purpose
Run once after first install, or any time sArthI reports missing dependencies.
Covers Wibey-layer dependencies that `setup.sh` cannot install (skills, auth flows).
`setup.sh` handles shell-layer: symlinks, MCP injection, Python packages.

## When to invoke
- First-time setup after cloning `~/sarthi/` and running `setup.sh`
- When `sar-monitor` or `sar-investigate` report missing skills/auth
- After a Wibey update that may have reset skills

## Execution Steps

### Step 1 — Check CLI prerequisites

Use `Bash` to verify:
```bash
python3 --version 2>&1
node --version 2>/dev/null || echo "missing"
bun --version 2>/dev/null || bun_path="$HOME/.local/bin/bun" && "$bun_path" --version 2>/dev/null || echo "missing"
gh --version 2>&1 | head -1
gcloud --version 2>&1 | head -1
```

Record each as ✅ / ⚠️ / ❌.

### Step 2 — Install bigquery-explorer skill (if missing)

Check:
```bash
test -d ~/.wibey/skills/bigquery-explorer && echo "INSTALLED" || echo "MISSING"
```

If MISSING → invoke skill installer:
```
Skill("skill-installer", "bigquery-explorer")
```

If INSTALLED, check SDK:
```bash
test -d ~/.local/lib/bigquery-explorer/node_modules/@google-cloud/bigquery && echo "SDK_OK" || echo "SDK_MISSING"
```

If SDK_MISSING → install it:
```bash
bash ~/.wibey/skills/bigquery-explorer/scripts/install-bigquery.sh
```

Report: ✅ bigquery-explorer ready / ⚠️ skill-installer ran (restart Wibey to activate) / ❌ install failed.

### Step 3 — Install msgraph skill (if missing)

Check:
```bash
test -d ~/.wibey/skills/msgraph && echo "INSTALLED" || echo "MISSING"
```

If MISSING → invoke skill installer:
```
Skill("skill-installer", "msgraph")
```

If INSTALLED, check auth status via auth.ts (tokens stored in macOS Keychain):
```bash
AUTH_STATUS=$(NODE_PATH="$HOME/.local/lib/node_modules" bun "$HOME/.wibey/skills/msgraph/scripts/auth.ts" status 2>/dev/null)
AUTHED=$(echo "$AUTH_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('authenticated',False)).lower())" 2>/dev/null)

if [ "$AUTHED" = "true" ]; then
    USER=$(echo "$AUTH_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('user',{}).get('email',''))" 2>/dev/null)
    echo "✅ msgraph authenticated as $USER"
else
    echo "NO_TOKEN"
fi
```

If NO_TOKEN → instruct: `Run in Wibey: /msgraph login`

Report: ✅ msgraph ready (authenticated) / ⚠️ installed, needs auth → /msgraph login / ❌ install failed.

### Step 4 — Check ServiceNow session

```bash
test -f ~/.wibey/snow-session.json && echo "EXISTS" || echo "MISSING"
```

If EXISTS, check age:
```bash
python3 -c "
import json, datetime
d = json.load(open('$HOME/.wibey/snow-session.json'))
t = d.get('extracted_at','')
if t:
    age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(t)).total_seconds()/3600
    print(f'{age:.1f}h old')
else:
    print('unknown age')
" 2>/dev/null || echo "parse_failed"
```

- < 8h → ✅ session fresh
- >= 8h → ⚠️ session may be expired — sarthi-snow-auth will auto-refresh on next use
- MISSING → ❌ Run once: `python3 ~/sarthi/scripts/crq/extract_snow_session.py` (opens browser for Walmart AD SSO)

**Do NOT run extract_snow_session.py automatically** — it opens a browser and blocks.

### Step 5 — Check mcp-jira plugin

```bash
wibey plugin list 2>/dev/null | grep -i jira || echo "NOT_FOUND"
```

If NOT_FOUND → ⚠️ Enable at: https://wibey.walmart.com → Plugins → Jira

### Step 6 — Check GEC GitHub token

```bash
git ls-remote https://gecgithub01.walmart.com/ HEAD 2>&1 | head -1 || echo "AUTH_FAILED"
```

- Returns a SHA → ✅ GEC GitHub auth working
- AUTH_FAILED or timeout → ⚠️ Configure PAT: `gh auth login --hostname gecgithub01.walmart.com`

### Step 7 — Check gcloud ADC

```bash
gcloud auth list 2>/dev/null | grep -E "ACTIVE|\\*" | head -3
```

- Active account present → ✅ gcloud ADC configured
- Empty → ⚠️ Run: `gcloud auth application-default login`

### Step 8 — Check sarthi MCP servers in .mcp.json

> **Note**: Wibey loads `~/.wibey/.mcp.json` (hidden file) at startup — NOT `mcp.json`.
> `setup.sh` writes to both. Check the hidden file:

```bash
python3 -c "
import json, os
hidden = os.path.expanduser('~/.wibey/.mcp.json')
visible = os.path.expanduser('~/.wibey/mcp.json')
for label, path in [('.mcp.json (loaded by Wibey)', hidden), ('mcp.json (source of truth)', visible)]:
    try:
        cfg = json.load(open(path))
        servers = cfg.get('mcpServers', {})
        required = ['sarthi-airflow-read','sarthi-airflow-auth','sarthi-airflow-ops','sarthi-snow','sarthi-snow-auth','sarthi-gcp','sarthi-msgraph','sarthi-bq']
        missing = [s for s in required if s not in servers]
        status = '✅' if not missing else f'❌ MISSING: {missing}'
        print(f'{status}  {label} ({len(servers)} servers)')
    except FileNotFoundError:
        print(f'❌ NOT FOUND: {path}')
" 2>/dev/null
```

If any are MISSING in `.mcp.json` → instruct: `Run: bash ~/sarthi/setup.sh` (syncs both files).

### Step 9 — Report

Print a summary:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  sArthI Setup — 2026-06-01
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLI Tools
  ✅ Python 3.11.9
  ✅ Bun 1.1.x
  ✅ gh CLI
  ✅ gcloud (achallaravi.kiran@walmart.com)

Wibey Skills
  ✅ bigquery-explorer (SDK installed)
  ✅ msgraph (authenticated)

Auth
  ✅ ServiceNow session (2.1h old)
  ✅ GEC GitHub token
  ⚠️  mcp-jira: enable at wibey.walmart.com → Plugins

MCP Servers (8/8 registered)
  ✅ sarthi-airflow-read / auth / ops
  ✅ sarthi-snow / snow-auth
  ✅ sarthi-gcp
  ✅ sarthi-msgraph
  ✅ sarthi-bq

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  sArthI is ready. Any ⚠️ items above are non-blocking.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Notes

- This skill covers Wibey-layer setup only. For shell-layer (symlinks, Python packages, MCP injection): run `bash ~/sarthi/setup.sh` first.
- Steps are idempotent — safe to re-run anytime.
- Snow session refresh after first setup is handled automatically by `sarthi-snow-auth` MCP when a tool returns `session_expired`.
- bigquery-explorer auth (OAuth2 browser flow) is handled by the skill itself on first BQ query — not bootstrapped here.
- **MCP config split**: Wibey loads `~/.wibey/.mcp.json` (hidden), not `mcp.json`. `setup.sh` writes to both. If you add new servers manually to `mcp.json`, also add them to `.mcp.json` or re-run `setup.sh`.
