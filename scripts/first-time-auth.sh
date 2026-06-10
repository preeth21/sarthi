#!/usr/bin/env bash
# ============================================================
# sArthI First-Time Authentication Setup
# scripts/first-time-auth.sh
#
# Run ONCE after installing sArthI (called by setup.sh automatically).
# Sets up all 6 authentication sessions needed for sArthI to function.
# Safe to re-run: skips steps that already have valid sessions.
#
# After this completes, all auth refreshes happen automatically:
#   - Airflow:      headless-refresh.py (headless, no browser)
#   - ServiceNow:   extract_snow_session.py (headless, no browser)
#   - Msgraph:      token auto-refreshes in background
#   - Slack:        session lasts ~2 weeks, reauth.js when expired
#   - gh/gcloud:    long-lived tokens, rarely need refresh
#
# What is interactive vs automatic:
#   Interactive (browser opens, YOU must log in):
#     [1] gh CLI           — one-time, runs in terminal
#     [2] gcloud ADC       — browser window, Walmart Google SSO
#     [3] Airflow          — browser window, Walmart Google SSO
#     [4] ServiceNow       — browser window, Walmart AD/PingFed SSO
#     [5] Microsoft 365    — browser window, Walmart Microsoft SSO + MFA
#     [6] Slack            — browser window, Walmart Enterprise Slack SSO
#
# Usage:
#   bash ~/sarthi/scripts/first-time-auth.sh
#   bash ~/sarthi/scripts/first-time-auth.sh --force   # re-run all even if already authed
# ============================================================

set -uo pipefail

SARTHI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WIBEY_DIR="$HOME/.wibey"
AUTH_COMPLETE="$WIBEY_DIR/sarthi/.auth-complete"
FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; RESET='\033[0m'
ok()    { echo -e "${GREEN}  ✅ $1${RESET}"; }
warn()  { echo -e "${YELLOW}  ⚠️  $1${RESET}"; }
err()   { echo -e "${RED}  ❌ $1${RESET}"; }
info()  { echo -e "${BLUE}  ℹ️  $1${RESET}"; }
hdr()   { echo -e "\n${CYAN}━━━ $1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; }
step()  { echo -e "\n${CYAN}[$1/6]${RESET} ${2}"; }
pause() { echo -e "${YELLOW}  Press ENTER when done (or Ctrl+C to skip and continue later)...${RESET}"; read -r || true; }

AUTH_RESULTS=()

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  sArthI — First-Time Authentication (6 steps)"
echo "  Run once. Future sessions are automatic."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Each step opens a browser window for Walmart SSO."
echo "  Complete the login, then the script continues."
echo "  You CANNOT skip auth — sArthI requires all 6."
echo ""

# ── AUTH 1 — GEC GitHub ──────────────────────────────────────
step 1 "GEC GitHub (gh CLI)"
echo "  Tool: gh CLI (terminal-based, no browser)"
echo "  Used by: sar-pr, sarthi-git MCP (read repos, create PRs)"

GH_OK=false
if command -v gh &>/dev/null && gh auth status --hostname gecgithub01.walmart.com &>/dev/null 2>&1; then
    GH_USER=$(gh api user --hostname gecgithub01.walmart.com --jq .login 2>/dev/null || echo "unknown")
    ok "Already authenticated as: $GH_USER"
    GH_OK=true
elif $FORCE || ! command -v gh &>/dev/null || ! gh auth status --hostname gecgithub01.walmart.com &>/dev/null 2>&1; then
    info "Running: gh auth login --hostname gecgithub01.walmart.com --web"
    echo "  → Your browser will open. Log in with your Walmart credentials."
    if gh auth login --hostname gecgithub01.walmart.com --web 2>&1; then
        ok "GitHub auth complete"
        GH_OK=true
    else
        warn "GitHub auth failed or skipped — sar-pr and sarthi-git MCP will not work"
    fi
fi
$GH_OK && AUTH_RESULTS+=("gh:ok") || AUTH_RESULTS+=("gh:failed")

# ── AUTH 2 — GCP / BigQuery ──────────────────────────────────
step 2 "GCP / BigQuery (gcloud ADC)"
echo "  Tool: gcloud CLI (browser window — Walmart Google SSO)"
echo "  Used by: sarthi-bq MCP, sarthi-gcp MCP (query BigQuery, GCS, Dataproc)"

GCP_OK=false
if command -v gcloud &>/dev/null; then
    if gcloud auth application-default print-access-token &>/dev/null 2>&1; then
        ok "GCP ADC already authenticated"
        GCP_OK=true
    else
        info "Running: gcloud auth application-default login"
        echo "  → Browser window opens. Log in with your @walmart.com Google account."
        if gcloud auth application-default login 2>&1; then
            ok "GCP auth complete"
            GCP_OK=true
        else
            warn "GCP auth failed — sarthi-bq and sarthi-gcp MCPs will not work"
        fi
    fi
else
    warn "gcloud not installed — sarthi-bq and sarthi-gcp MCPs will not work"
    info "Install gcloud SDK from Walmart's internal documentation or ask your team"
fi
$GCP_OK && AUTH_RESULTS+=("gcp:ok") || AUTH_RESULTS+=("gcp:failed")

# ── AUTH 3 — Airflow / Houston ────────────────────────────────
step 3 "Airflow (Houston Google SSO)"
echo "  Tool: Playwright Chromium (browser window — Walmart Google SSO)"
echo "  Used by: sarthi-airflow-read, sarthi-airflow-ops, sarthi-airflow-auth MCPs"

AIRFLOW_OK=false
AIRFLOW_SESSION="$WIBEY_DIR/sarthi/session.json"

if [[ -f "$AIRFLOW_SESSION" ]] && ! $FORCE; then
    # Verify it's not just an empty/legacy file
    SESSION_ORIGINS=$(python3 -c "import json; d=json.load(open('$AIRFLOW_SESSION')); print(len(d.get('origins',[])))" 2>/dev/null || echo "0")
    if [[ "$SESSION_ORIGINS" -gt 0 ]]; then
        ok "Airflow session already exists ($SESSION_ORIGINS origin(s) saved)"
        AIRFLOW_OK=true
    fi
fi

if ! $AIRFLOW_OK; then
    info "Running: python3 $SARTHI_ROOT/scripts/setup-session.py"
    echo "  → Browser window opens. Log in with your @walmart.com Google account."
    echo "  → The window closes automatically after successful login."
    if AIRFLOW_MCP_CONFIG="$WIBEY_DIR/sarthi/config.yaml" python3 "$SARTHI_ROOT/scripts/setup-session.py" 2>&1; then
        ok "Airflow session established"
        AIRFLOW_OK=true
    else
        warn "Airflow auth failed — sarthi-airflow-* MCPs will not work"
        info "Retry: python3 ~/sarthi/scripts/setup-session.py"
    fi
fi
$AIRFLOW_OK && AUTH_RESULTS+=("airflow:ok") || AUTH_RESULTS+=("airflow:failed")

# ── AUTH 4 — ServiceNow ───────────────────────────────────────
step 4 "ServiceNow (Walmart PingFed SSO)"
echo "  Tool: Selenium + Chrome (browser window — Walmart AD/PingFed SSO)"
echo "  Used by: sarthi-snow MCP (get CRQs, incidents, RITM approvals)"

SNOW_OK=false
SNOW_SESSION="$WIBEY_DIR/snow-session.json"
SNOW_PROFILE="$SARTHI_ROOT/scripts/crq/chrome_profile"

if [[ -f "$SNOW_SESSION" ]] && [[ -d "$SNOW_PROFILE" ]] && ! $FORCE; then
    SNOW_AGE=$(python3 -c "
import json, datetime, sys
try:
    d = json.load(open('$SNOW_SESSION'))
    t = d.get('extracted_at','')
    if t:
        age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(t)).total_seconds() / 3600
        print(f'{age:.1f}')
    else:
        print('999')
except: print('999')
" 2>/dev/null || echo "999")
    if python3 -c "exit(0 if float('$SNOW_AGE') < 7 else 1)" 2>/dev/null; then
        ok "ServiceNow session exists (${SNOW_AGE}h old, valid)"
        SNOW_OK=true
    else
        info "ServiceNow session exists but is ${SNOW_AGE}h old — refreshing"
    fi
fi

if ! $SNOW_OK; then
    info "Running: python3 $SARTHI_ROOT/scripts/crq/extract_snow_session.py --interactive"
    echo "  → Chrome window opens. Log in with your Walmart username + password."
    echo "  → If prompted, complete MFA or AD authentication."
    echo "  → The window closes automatically after successful login."
    if python3 "$SARTHI_ROOT/scripts/crq/extract_snow_session.py" --interactive \
        --profile-dir "$SNOW_PROFILE" 2>&1; then
        ok "ServiceNow session established"
        SNOW_OK=true
    else
        warn "ServiceNow auth failed — sarthi-snow MCP will not work"
        info "Retry: python3 ~/sarthi/scripts/crq/extract_snow_session.py --interactive"
    fi
fi
$SNOW_OK && AUTH_RESULTS+=("snow:ok") || AUTH_RESULTS+=("snow:failed")

# ── AUTH 5 — Microsoft 365 ────────────────────────────────────
step 5 "Microsoft 365 / Outlook / Teams"
echo "  Tool: Playwright + bun (browser window — Walmart Microsoft SSO + MFA)"
echo "  Used by: sarthi-msgraph MCP (read email, Teams messages, create drafts)"

MSGRAPH_OK=false
BUN_BIN=$(command -v bun 2>/dev/null || echo "$HOME/.local/bin/bun")
MSGRAPH_AUTH="$WIBEY_DIR/skills/msgraph/scripts/auth.ts"

if [[ ! -f "$MSGRAPH_AUTH" ]]; then
    warn "msgraph skill not installed — skipping"
    info "Install first: open Wibey and run /skill-installer msgraph"
    AUTH_RESULTS+=("msgraph:skipped")
elif [[ ! -x "$BUN_BIN" ]] && [[ ! -f "$BUN_BIN" ]]; then
    warn "bun not found — cannot run msgraph auth"
    AUTH_RESULTS+=("msgraph:skipped")
else
    AUTHED=$(NODE_PATH="$HOME/.local/lib/node_modules" "$BUN_BIN" "$MSGRAPH_AUTH" status 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('authenticated',False)).lower())" 2>/dev/null || echo "false")

    if [[ "$AUTHED" == "true" ]] && ! $FORCE; then
        MSUSER=$(NODE_PATH="$HOME/.local/lib/node_modules" "$BUN_BIN" "$MSGRAPH_AUTH" status 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('user',{}).get('email',''))" 2>/dev/null || echo "")
        ok "Microsoft 365 already authenticated${MSUSER:+ as $MSUSER}"
        MSGRAPH_OK=true
    else
        # Ensure playwright is installed for msgraph
        if ! NODE_PATH="$HOME/.local/lib/node_modules" "$BUN_BIN" -e "require('playwright')" &>/dev/null 2>&1; then
            info "Installing Playwright for msgraph..."
            bash "$WIBEY_DIR/skills/msgraph/scripts/install-playwright.sh" 2>/dev/null || true
        fi
        info "Running: bun $MSGRAPH_AUTH login"
        echo "  → Browser window opens. Log in with your Walmart Microsoft account."
        echo "  → Complete any MFA prompts. Window closes automatically."
        if NODE_PATH="$HOME/.local/lib/node_modules" "$BUN_BIN" "$MSGRAPH_AUTH" login 2>&1; then
            ok "Microsoft 365 auth complete"
            MSGRAPH_OK=true
        else
            warn "Microsoft 365 auth failed — sarthi-msgraph MCP will not work"
            info "Retry inside Wibey: /msgraph login"
        fi
    fi
fi
if $MSGRAPH_OK; then
    AUTH_RESULTS+=("msgraph:ok")
elif [[ ! " ${AUTH_RESULTS[*]} " =~ " msgraph:skipped " ]]; then
    AUTH_RESULTS+=("msgraph:failed")
fi

# ── AUTH 6 — Slack ────────────────────────────────────────────
step 6 "Walmart Enterprise Slack"
echo "  Tool: Node.js + Playwright (browser window — Walmart Enterprise Slack SSO)"
echo "  Used by: sarthi-slack MCP (read channels, post messages)"

SLACK_OK=false
SLACK_REAUTH="$WIBEY_DIR/skills/slack-api/scripts/reauth.js"
SLACK_COOKIES="$WIBEY_DIR/slack-api-cookies.json"

if [[ ! -f "$SLACK_REAUTH" ]]; then
    warn "slack-api skill not installed — skipping"
    info "Install first: open Wibey and run /skill-installer slack-api"
    AUTH_RESULTS+=("slack:skipped")
else
    # Check cookie age (valid ~2 weeks)
    COOKIE_AGE=999
    if [[ -f "$SLACK_COOKIES" ]]; then
        COOKIE_AGE=$(python3 -c "
import os, datetime
mtime = os.path.getmtime('$SLACK_COOKIES')
age = (datetime.datetime.now().timestamp() - mtime) / 3600
print(f'{age:.1f}')
" 2>/dev/null || echo "999")
    fi

    if python3 -c "exit(0 if float('$COOKIE_AGE') < 336 else 1)" 2>/dev/null && ! $FORCE; then  # 336h = 2 weeks
        ok "Slack session exists (${COOKIE_AGE}h old, valid)"
        SLACK_OK=true
    else
        info "Running: node $SLACK_REAUTH"
        echo "  → Browser window opens. Log in with your Walmart Slack account."
        echo "  → Window closes automatically when login succeeds."
        if node "$SLACK_REAUTH" 2>&1; then
            ok "Slack auth complete"
            SLACK_OK=true
        else
            warn "Slack auth failed — sarthi-slack MCP will not work"
            info "Retry: cd ~/.wibey/skills/slack-api && node scripts/reauth.js"
        fi
    fi
fi
if $SLACK_OK; then
    AUTH_RESULTS+=("slack:ok")
elif [[ ! " ${AUTH_RESULTS[*]} " =~ " slack:skipped " ]]; then
    AUTH_RESULTS+=("slack:failed")
fi

# ── SUMMARY ────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Auth Setup Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

FAILED=0
for r in "${AUTH_RESULTS[@]}"; do
    SERVICE="${r%%:*}"
    STATUS="${r##*:}"
    case "$STATUS" in
        ok)      echo -e "  ${GREEN}✅ $SERVICE${RESET}" ;;
        skipped) echo -e "  ${YELLOW}⏭️  $SERVICE (skipped — install skill first)${RESET}" ;;
        failed)  echo -e "  ${RED}❌ $SERVICE (failed — re-run or fix manually)${RESET}"; FAILED=$((FAILED+1)) ;;
    esac
done

echo ""

if [[ $FAILED -eq 0 ]]; then
    # Write sentinel — all auths successful
    mkdir -p "$(dirname "$AUTH_COMPLETE")"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) all:ok ${AUTH_RESULTS[*]}" > "$AUTH_COMPLETE"
    echo -e "${GREEN}  ✅ All auth complete! Sentinel written: $AUTH_COMPLETE${RESET}"
    echo ""
    echo "  Next step: restart Wibey (close + reopen)"
    echo "  Then try: /sar-setup   (runs health check)"
else
    echo -e "${YELLOW}  ⚠️  $FAILED auth(s) failed. Fix them and re-run:${RESET}"
    echo "     bash ~/sarthi/scripts/first-time-auth.sh"
    echo ""
    echo "  sArthI will work partially — features requiring failed auths won't function."
fi
echo ""
