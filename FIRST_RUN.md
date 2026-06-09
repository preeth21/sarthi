# sArthI — First Run Guide

This document describes exactly what happens when you install and start sArthI for the first time.
Every step maps 1:1 to a deterministic shell script — nothing is interpreted by AI.

---

## Installation (run in terminal, not inside Wibey)

```bash
bash <(curl -fsSL \
  -H "Authorization: token $(gh auth token --hostname gecgithub01.walmart.com)" \
  https://gecgithub01.walmart.com/raw/WITDnA/sarthi/main/install.sh)
```

> **If gh is not installed yet**, clone manually first:
> ```bash
> git clone https://gecgithub01.walmart.com/WITDnA/sarthi.git ~/sarthi
> bash ~/sarthi/install.sh
> ```

---

## What install.sh does automatically (no input needed)

| Step | What | Time |
|------|------|------|
| Check macOS, network, git, python3 | Prerequisite checks | <5s |
| Check/install bun | via Walmart Artifactory npm | <30s |
| Check/install Wibey CLI | clone wibey-cli + setup-local | ~2 min |
| Clone/pull WITDnA/sarthi → ~/sarthi | git clone | <30s |
| Run setup.sh | See below | ~3 min |

---

## What setup.sh does automatically (no input needed)

| Step | What |
|------|------|
| Install Python deps | `selenium`, `playwright`, `pyyaml`, `requests`, `pycryptodome` via Walmart Nexus |
| Install Playwright Chromium browser | headless browser for Airflow auth |
| Check Google Chrome | required for ServiceNow auth (install manually if missing) |
| Create `~/.wibey/` directories | commands/, skills/, agents/, knowledge/, crq/ |
| Symlink skills/commands/agents | ~/sarthi/ → ~/.wibey/ |
| Inject 11 MCP servers | into ~/.wibey/mcp.json |
| Install kubectl + sledge | from Walmart Artifactory |
| Check all dependencies | shows ✅/⚠️ per item |
| **Run first-time-auth.sh** | 6 browser-based auth sessions (see below) |

---

## First-time authentication (6 steps, ~10 minutes)

Handled by `scripts/first-time-auth.sh`. This runs automatically at the end of setup.
Each step opens a browser window — you log in once, then it's automatic forever.

| Step | Service | How | Interactive? | Used by |
|------|---------|-----|-------------|---------|
| 1 | GEC GitHub | `gh auth login --hostname gecgithub01.walmart.com --web` | Terminal prompts, browser opens | sarthi-git MCP, sar-pr |
| 2 | GCP / BigQuery | `gcloud auth application-default login` | Browser opens → Walmart Google SSO | sarthi-bq, sarthi-gcp MCPs |
| 3 | Airflow / Houston | `python3 ~/sarthi/scripts/setup-session.py` (Playwright Chromium, headed) | Browser opens → Walmart Google SSO → closes automatically | sarthi-airflow-* MCPs |
| 4 | ServiceNow | `python3 ~/sarthi/scripts/crq/extract_snow_session.py --interactive` (Selenium + Chrome, headed) | Chrome window opens → Walmart AD/PingFed SSO → closes automatically | sarthi-snow MCP |
| 5 | Microsoft 365 | `bun ~/.wibey/skills/msgraph/scripts/auth.ts login` (Playwright, headed) | Browser opens → Walmart Microsoft SSO + MFA → closes automatically | sarthi-msgraph MCP |
| 6 | Slack | `node ~/.wibey/skills/slack-api/scripts/reauth.js` (Playwright, headed) | Browser opens → Walmart Enterprise Slack SSO → closes automatically | sarthi-slack MCP |

**After first-time auth, all future refreshes are automatic (headless, no browser):**
- Airflow: `headless-refresh.py` runs on cron / triggered by sarthi-airflow-auth MCP
- ServiceNow: `extract_snow_session.py` (headless) runs via sarthi-snow-auth MCP
- Microsoft 365: token auto-refreshes silently
- Slack: session lasts ~2 weeks, re-run `node scripts/reauth.js` when expired

---

## After installation completes

1. **Restart Wibey** — close terminal and reopen, then run `wibey`
2. **Run health check** inside Wibey: `/sar-setup`
3. **Start using sArthI**: `/sarthi`

---

## Re-running auth (when sessions expire)

```bash
# Re-run all auth (safe, skips already-valid sessions):
bash ~/sarthi/scripts/first-time-auth.sh

# Force re-run all (even if sessions are valid):
bash ~/sarthi/scripts/first-time-auth.sh --force

# Individual refreshes (for specific services):
python3 ~/sarthi/scripts/headless-refresh.py          # Airflow (headless)
python3 ~/.wibey/crq/extract_snow_session.py           # ServiceNow (headless)
# For msgraph/Slack: inside Wibey use /msgraph login or re-run reauth.js
```

---

## What NOT to do

- ❌ Do NOT ask Wibey/sArthI to "authenticate" or "open a browser" for you
- ❌ Do NOT run auth scripts inside a Wibey session — run them in terminal
- ❌ Do NOT edit `~/.wibey/mcp.json` manually — use `setup.sh` to regenerate
- ❌ Do NOT commit `session.json`, `snow-session.json`, `chrome_profile/` — they contain credentials

---

## Auth script → browser tool mapping (definitive)

| Script | Browser tool | First-time mode | Refresh mode |
|--------|-------------|-----------------|-------------|
| `scripts/setup-session.py` | Playwright Chromium | `--` (always headed) | n/a (use headless-refresh.py) |
| `scripts/headless-refresh.py` | Playwright Chromium | n/a | headless, no window |
| `scripts/crq/extract_snow_session.py` | Selenium + Google Chrome | `--interactive` flag | headless (default) |
| `~/.wibey/skills/msgraph/scripts/auth.ts` | Playwright Chromium | `login` subcommand | auto token refresh |
| `~/.wibey/skills/slack-api/scripts/reauth.js` | Playwright Chromium | always headed | re-run when expired |
