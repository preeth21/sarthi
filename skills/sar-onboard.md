---
name: sar-onboard
description: Interactive onboarding for new teams. Captures system details (Airflow, BQ, Trino, GCS, GitHub, Kafka endpoints), writes ~/.wibey/sarthi/config.yaml, seeds the knowledge base, scaffolds missing MCP servers, and registers the GitHub listener cron. Run once per team or re-run to update config.
tools: Bash, Read, Write, Edit
---

# sárthí Onboarding

You are running the **sárthí onboard** flow. Guide the user through a friendly, conversational intake to capture their team's system details. At the end, write the config file and set up the listener.

## What to ask (one message, all at once)

Ask all questions in a single message:

```
Welcome to sárthí onboarding! I'll set up everything in about 5 minutes.

Please answer these questions in one reply:

1. **Team name** (e.g. "INTL COIM", "SmartComms", "ET360")
2. **Airflow URL** (e.g. https://your-airflow.example.com)
3. **BigQuery project** (e.g. wmt-intl-cons-mc-mx-prod)  — leave blank if not used
4. **Trino/Dengy host** (e.g. presto-datadiscovery.walmart.com:8443) — leave blank if not used
5. **GCS bucket(s)** for Hudi/data (comma-separated, e.g. gs://bucket1, gs://bucket2) — leave blank if not used
6. **GitHub org** on gecgithub01.walmart.com (e.g. WITDnA)
7. **GitHub repo** to use as chat channel (e.g. sarthi)
8. **GitHub issue number** for the chat channel (e.g. 6)
9. **Do you have existing MCP servers?** (yes/no — if no, I'll scaffold one for you)
```

## After receiving answers

### Step 1 — Write config.yaml

Write to `~/.wibey/sarthi/config.yaml`:

```yaml
team: <team_name>

airflow:
  url: <airflow_url>
  # Auth: set AIRFLOW_USERNAME and AIRFLOW_PASSWORD env vars, or run sar-setup for SSO

bigquery:
  project: <bq_project>
  max_bytes_billed: 1073741824  # 1GB cost cap

trino:
  host: <trino_host>
  # Auth: run sarthi-trino --set-password once

gcs:
  buckets:
    - <bucket_1>
    - <bucket_2>

github:
  org: <github_org>
  repo: <github_repo>
  issue: <issue_number>
  hostname: gecgithub01.walmart.com

monitoring:
  poll_interval_s: 60
  session_idle_timeout_s: 120
  session_poll_interval_s: 10
```

### Step 2 — Check for MCP servers

Run:
```bash
ls ~/sarthi/mcp/
```

If the user said they don't have MCP servers, or if the `mcp/` directory is missing key servers, scaffold a minimal one:

```bash
mkdir -p ~/sarthi/mcp/sarthi-custom
```

Create `~/sarthi/mcp/sarthi-custom/server.py` with:

```python
#!/usr/bin/env python3
"""
sarthi-custom MCP server — auto-scaffolded by sar-onboard.
Add your tools here following the pattern in sarthi-airflow-read/server.py.
"""
import sys, json, os

TOOLS = [
    {
        "name": "custom_health_check",
        "description": "Check the health of <team_name> systems",
        "inputSchema": {"type": "object", "properties": {"detail": {"type": "string"}}, "required": []}
    }
]

def handle_tool_call(name, args):
    if name == "custom_health_check":
        return {"ok": True, "status": "Scaffold tool — replace with real implementation"}
    return {"error": f"Unknown tool: {name}"}

# MCP stdio loop
for line in sys.stdin:
    try:
        msg = json.loads(line.strip())
        method = msg.get("method", "")
        mid = msg.get("id")
        if method == "initialize":
            resp = {"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"sarthi-custom","version":"1.0.0"}}}
        elif method == "tools/list":
            resp = {"jsonrpc":"2.0","id":mid,"result":{"tools":TOOLS}}
        elif method == "tools/call":
            p = msg.get("params",{})
            result = handle_tool_call(p.get("name",""), p.get("arguments",{}))
            resp = {"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":json.dumps(result)}]}}
        else:
            resp = {"jsonrpc":"2.0","id":mid,"result":{}}
        print(json.dumps(resp), flush=True)
    except Exception as e:
        print(json.dumps({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":str(e)}}), flush=True)
```

Tell the user: "I've scaffolded `~/sarthi/mcp/sarthi-custom/server.py`. Open it and replace `custom_health_check` with tools specific to your team. See `~/sarthi/mcp/sarthi-airflow-read/server.py` as a reference."

### Step 3 — Register launchd listener

Check if the plist already exists:
```bash
ls ~/Library/LaunchAgents/com.sarthi.github-listener.plist 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

If MISSING, create it:
```bash
cat > ~/Library/LaunchAgents/com.sarthi.github-listener.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.sarthi.github-listener</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string><string>-c</string>
        <string>/Users/akiran/.dengy/venv/bin/python3 /Users/akiran/sarthi/agents/sarthi/github_listener.py >> /tmp/sarthi-github-listener.log 2>&1</string>
    </array>
    <key>StartInterval</key><integer>60</integer>
    <key>RunAtLoad</key><false/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>/Users/akiran/.dengy/venv/bin:/Users/akiran/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key><string>/Users/akiran</string>
    </dict>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.sarthi.github-listener.plist
```

### Step 4 — Start caffeinate

```bash
pgrep -x caffeinate || caffeinate -i &
```

### Step 5 — Summary

Print a clean summary:

```
✅ sárthí onboarding complete!

Team:     <team_name>
Airflow:  <airflow_url>
Channel:  gecgithub01.walmart.com/<github_org>/<github_repo>/issues/<issue_number>
Listener: com.sarthi.github-listener (every 60s)
Config:   ~/.wibey/sarthi/config.yaml

Next steps:
1. Open gecgithub01.walmart.com/<github_org>/<github_repo>/issues/<issue_number>
2. Comment anything to start a live sárthí session
3. sárthí will reply within 60 seconds

Monitoring log: tail -f /tmp/sarthi-github-listener.log
```

## Important rules

- NEVER hardcode credentials. Tell the user to set env vars or use `sar-setup` for auth.
- If any field is left blank, omit that section from config.yaml (don't write empty strings).
- If GitHub issue number is not provided, default to `1` and tell the user to update it.
- After writing config, always verify it parsed correctly: `python3 -c "import yaml; yaml.safe_load(open('~/.wibey/sarthi/config.yaml').read()); print('OK')"` (expand ~ first).
