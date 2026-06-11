# sárthí — Work from Phone

> **WFO** · Work from Office — Millennial  
> **WFH** · Work from Home — Gen Z  
> **WFP** · Work from Phone — **Gen Alpha** ✦

sárthí is a **Work from Phone enablement framework** that exposes your team's operational capability as agentic workflows — triggered from a GitHub comment on your phone, resolved autonomously on your Mac.

Any team. Any stack. Up and running in under 10 minutes.

---

## How it works — 5 steps

### 1 · Onboard your system
Run `sarthi onboard`. A guided intake captures your team name, Airflow URL, BigQuery project, Trino endpoint, GCS paths, and GitHub org — then writes `config.yaml` and seeds your knowledge base automatically.

**No MCP server?** sárthí scaffolds a local `stdio` MCP server for your stack in under 10 minutes.

```bash
sarthi onboard
```

### 2 · Monitoring starts automatically
`install.sh` registers a **launchd background agent** that polls your GitHub input channel every 60 seconds — even when your screen is locked (via `caffeinate`). Health summaries, SLA tracking, and DAG run reports are generated on schedule.

### 3 · Patterns detected, issues solved autonomously
sárthí learns what "normal" looks like. Recurring failures (stuck tasks, sensor timeouts, OOM pods) are cleared automatically using a growing pattern library. Novel patterns are escalated to the team with full diagnostic context.

### 4 · Chat-native notifications
sárthí pushes updates through a **GitHub issue thread** — the chat window your team already uses. Comment from your phone to ask a question or trigger an action. Every interaction is audited.

### 5 · Your team operates from a phone
No laptop. No VPN. No dashboard. Check health, trigger runs, read logs, clear failures, and review incidents — all from a GitHub comment on any device.

---

## Quick start

```bash
# 1. Clone and install
git clone https://gecgithub01.walmart.com/WITDnA/sarthi.git ~/sarthi
bash ~/sarthi/install.sh

# 2. Onboard your team (guided, ~5 min)
sarthi onboard
```

See [FIRST_RUN.md](./FIRST_RUN.md) for the full step-by-step guide including auth setup.

---

## Background listener & cron schedule

`install.sh` automatically adds a **launchd plist** (`com.sarthi.github-listener`) that runs every 60 seconds:

```xml
<key>StartInterval</key>
<integer>60</integer>
<key>ProgramArguments</key>
<array>
  <string>/bin/sh</string>
  <string>-c</string>
  <string>python3 ~/sarthi/agents/sarthi/github_listener.py >> /tmp/sarthi-listener.log 2>&1</string>
</array>
```

To keep the listener firing even when your screen is locked, run:

```bash
caffeinate -i &
```

**Session lifecycle:**
- New comment on your GitHub issue → session loop launches within 60s
- Session polls every 10s while active
- Session closes automatically after 2 min of idle
- Cron resumes 1-min polling after session ends

To manually start/stop:
```bash
# Start
launchctl load ~/Library/LaunchAgents/com.sarthi.github-listener.plist

# Stop
launchctl unload ~/Library/LaunchAgents/com.sarthi.github-listener.plist
```

---

## What sárthí can do

| Category | Capability |
|----------|-----------|
| **Operational checks** | DAG health, pipeline status across all environments |
| **Health analysis** | SLA tracking, failure patterns, running/failed summary |
| **Pattern recognition** | Recurring failure detection, autonomous resolution |
| **Automated resolution** | Clear tasks, trigger runs, restart services (confirm-gated) |
| **Manual review** | Task logs, Spark driver logs, GCS file inspection |
| **Simulation** | Trigger test DAGs, validate pipeline config in dev |
| **Analysis & exploration** | BQ queries, Hudi/Trino row counts, table schemas |
| **Knowledge base** | Runbooks, architecture questions, MCP server map |

---

## MCP servers (7 · ~45 tools)

All servers run **locally** on your Mac via `stdio`. No cloud API keys. No Anthropic API required.

| Server | Purpose |
|--------|---------|
| `sarthi-airflow-read` | DAG runs, task status, logs, topology |
| `sarthi-airflow-ops` | Clear tasks, trigger runs, set states |
| `sarthi-airflow-auth` | Refresh Airflow session tokens |
| `sarthi-gcp` | GCS browser, Hudi metadata, Dataproc logs |
| `sarthi-bq` | BigQuery queries, schema, table search |
| `sarthi-trino` | Hudi/Hive table queries via Dengy |
| `sarthi-git` | Source code, PRs, commits — and the chat channel |

**Building your own MCP server?** Run `sarthi onboard` and choose "scaffold new MCP server" — sárthí generates a working `stdio` server template for your stack in under 10 minutes.

---

## Repository structure

```
sarthi/
├── install.sh              ← one-liner installer (sets up launchd, caffeinate, MCP servers)
├── setup.sh                ← full setup (deps, symlinks, MCP injection, auth)
├── FIRST_RUN.md            ← step-by-step installation guide
├── index.html              ← project landing page (Work from Phone)
├── sarthi-demo.mov         ← product demo video
├── mcp/                    ← 7+ sarthi MCP servers (stdio, local)
├── skills/                 ← sar-* skills (onboard, monitor, investigate, resolve…)
├── agents/sarthi/          ← github_listener.py + github_session_loop.py
├── commands/               ← Wibey custom commands
└── knowledge/              ← team config, environments, resolution patterns
```

---

## Input channel

sárthí uses a **GitHub issue** as the persistent chat window. The default is `WITDnA/sarthi#6`.

To configure your own:
```yaml
# ~/.wibey/sarthi/config.yaml
github:
  org: YourOrg
  repo: your-repo
  issue: 1
  hostname: gecgithub01.walmart.com
```

---

## Team

Built by [WITDnA](https://gecgithub01.walmart.com/WITDnA) · Walmart International Data & Analytics

---

*WFP — Work from Phone. Your stack, in your pocket.*
