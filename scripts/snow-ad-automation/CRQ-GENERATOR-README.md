# /crq-generator — End-to-End CRQ Workflow

Generate, preview, and submit ServiceNow Change Requests from GitHub PR URLs.  
One command: `/crq-generator <pr-url>` → Draft CRQ in ServiceNow, HTML preview, dashboard entry.

---

## Quick Start (Existing User)

```bash
/crq-generator https://gecgithub01.walmart.com/WITDnA/intldl-gcp-crew/pull/385
```

---

## First-Time Setup (New Users)

Run the setup script once. It is interactive and idempotent (safe to re-run).

```bash
bash ~/.wibey/servicenow-ad-automation/crq-setup.sh
```

The script handles:
1. Python dependencies (`selenium`, `requests`)
2. GitHub PAT — prompts you to create one and saves it to your shell profile
3. ServiceNow SSO — opens Chrome, you complete MFA once, session saved to `~/.wibey/snow-session.json`
4. End-to-end verification (reads a known CRQ to confirm everything works)
5. Optional cron session refresh

### Manual Setup (if you prefer step-by-step)

#### 1. Python Dependencies
```bash
pip install selenium requests -q
python3 -c "import selenium, requests; print('OK')"
```

#### 2. GitHub PAT
1. Go to: `https://gecgithub01.walmart.com/settings/tokens`
2. Generate new token → **Classic** → Scopes: `repo`, `read:org`
3. Add to shell profile:
```bash
echo 'export GECGITHUB_PAT=<your-token>' >> ~/.zshrc && source ~/.zshrc
```
4. Verify: `GITHUB_TOKEN=$GECGITHUB_PAT gh repo view WITDnA/intldl-gcp-crew --json name`

#### 3. ServiceNow SSO (one-time)
```bash
python3 ~/.wibey/servicenow-ad-automation/extract_snow_session.py
# Chrome opens → complete SSO/MFA → session saved
```

**If Chrome shows "user data directory is already in use":**
```bash
rm -f ~/.wibey/servicenow-ad-automation/chrome_profile/Singleton*
python3 ~/.wibey/servicenow-ad-automation/extract_snow_session.py
```

#### 4. Verify
```bash
python3 ~/.wibey/servicenow-ad-automation/snow_client.py get CHG3978198
# Expected: ✅ Found: CHG3978198 — MX ET360 | ...
```

---

## Workflow Overview

```
/crq-generator <pr-url>
        │
        ▼
1. Preflight: check ServiceNow session alive
   └─ stale? → run extract_snow_session.py → retry
        │
        ▼
2. Fetch PR details via GitHub API
   └─ parse: Jira ticket, DAG IDs, changed files, GEO
        │
        ▼
3. Build CRQ text (.txt) using:
   ├─ functional-CHG3978198-INTL-ET360.json  → team/group/app fields
   └─ quality-CHG3943471-structure.json      → section structure/format
        │
        ▼
4. Submit to ServiceNow as DRAFT (state=-5)
   └─ never submitted for approval from CLI
        │
        ▼
5. Generate HTML preview
        │
        ▼
6. Open: HTML preview + ServiceNow CRQ URL in browser
        │
        ▼
7. Update crq-index.json → appears in dashboard.html CRQ tab
```

---

## Output Files

| File | Description |
|------|-------------|
| `~/.wibey/knowledge/crqs/<slug>.txt` | CRQ text (source of truth for API payload) |
| `~/.wibey/knowledge/crqs/<slug>-preview.html` | Styled HTML preview |
| `~/.wibey/knowledge/crq-index.json` | Index of all generated CRQs (feeds dashboard) |

---

## Dashboard Integration

CRQs appear automatically in the **CRQ tab** of your Wibey dashboard after running `/crq-generator`.

To refresh the dashboard:
```bash
python3 ~/.wibey/prod-monitor/generate_dashboard.py && open ~/.wibey/prod-monitor/dashboard.html
```

Dashboard columns: CHG # (clickable → ServiceNow), Summary, Status, Repo, Date, Jira, DAGs.

---

## Session Management

ServiceNow cookies expire in ~1 hour.

**Manual refresh:**
```bash
python3 ~/.wibey/servicenow-ad-automation/extract_snow_session.py
```

**Automatic refresh via cron (every 45 min):**
```bash
crontab -e
# Add:
*/45 * * * * python3 ~/.wibey/servicenow-ad-automation/extract_snow_session.py >> ~/.wibey/snow-session-refresh.log 2>&1
```
The cron setup option is also offered at the end of `crq-setup.sh`.

---

## Reference Files

| File | Role | Description |
|------|------|-------------|
| `~/.wibey/knowledge/crq-references/functional-CHG3978198-INTL-ET360.json` | **FUNCTIONAL** | INTL-ET360 team fields — copy verbatim into every payload |
| `~/.wibey/knowledge/crq-references/quality-CHG3943471-structure.json` | **QUALITY (structure only)** | Section format from score-90 CRQ — different team, never copy field values |

> ⚠️ These two references serve different roles. The quality ref is a DIFFERENT team.
> Agent instructions in `crq-generator.md` enforce this separation explicitly.

---

## Script Reference

| Script | Purpose |
|--------|---------|
| `crq-setup.sh` | First-time setup (interactive) |
| `extract_snow_session.py` | Extract ServiceNow SSO session to `~/.wibey/snow-session.json` |
| `snow_client.py get <CHG#>` | Fetch existing CRQ fields |
| `snow_client.py create <file.txt>` | Create CRQ draft from txt file |
| `snow_client.py create <file.txt> --dry-run` | Preview payload without POSTing |
| `snow_client.py discover [<CHG#>]` | Dump all ServiceNow field names from a CRQ |

---

## ServiceNow Fields — What's Auto-Derived

Do **not** set these manually — ServiceNow derives them automatically:

| Field | Derived from |
|-------|-------------|
| `risk` | ML model (based on description + history) |
| `impact` | ServiceNow defaults |
| `u_vp_approval` | `assignment_group` (INTL-ET360 → auto-resolves approvers) |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `401 Unauthorized` | Session expired. Run `extract_snow_session.py` |
| `Chrome: user data directory in use` | `rm -f chrome_profile/Singleton*` then retry |
| `GECGITHUB_PAT not set` | Run `crq-setup.sh` or add to shell profile manually |
| `gh: command not found` | Workflow uses GitHub API directly — `gh` CLI not required |
| CRQ not appearing in dashboard | Run `generate_dashboard.py` to regenerate dashboard |
| `requests not installed` | `pip install selenium requests` |
