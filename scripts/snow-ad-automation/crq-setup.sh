#!/usr/bin/env bash
# crq-setup.sh — One-time setup for /crq-generator command
# Run this once before using /crq-generator for the first time.
# Safe to re-run: checks each step before doing it.

set -e
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✅ $1${RESET}"; }
warn() { echo -e "  ${YELLOW}⚠️  $1${RESET}"; }
info() { echo -e "  ${CYAN}ℹ  $1${RESET}"; }
err()  { echo -e "  ${RED}❌ $1${RESET}"; }
hdr()  { echo -e "\n${BOLD}$1${RESET}"; echo "  ──────────────────────────────────────"; }

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_PYTHON="${HOME}/.dengy/venv/bin/python3"
SYSTEM_PYTHON=$(which python3 2>/dev/null || echo "")
PYTHON="${VENV_PYTHON:-$SYSTEM_PYTHON}"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║     CRQ Generator — First-Time Setup         ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo ""
info "This script sets up dependencies for /crq-generator."
info "It is safe to re-run — each step is skipped if already done."

# ──────────────────────────────────────────────────────────────────────────────
hdr "Step 1: Python Dependencies"

check_python_deps() {
    "$PYTHON" -c "import selenium, requests" 2>/dev/null
}

if check_python_deps; then
    ok "selenium + requests already installed"
else
    warn "Installing selenium and requests..."
    "$PYTHON" -m pip install selenium requests -q
    if check_python_deps; then
        ok "Installed successfully"
    else
        err "Installation failed. Try manually: pip install selenium requests"
        exit 1
    fi
fi

# ──────────────────────────────────────────────────────────────────────────────
hdr "Step 2: GitHub PAT (Classic)"

if [ -n "$GECGITHUB_PAT" ]; then
    ok "GECGITHUB_PAT is set in current shell"
else
    warn "GECGITHUB_PAT is not set."
    echo ""
    echo "  To create a GitHub PAT:"
    echo "    1. Go to: https://gecgithub01.walmart.com/settings/tokens"
    echo "    2. Click 'Generate new token (classic)'"
    echo "    3. Select scopes: repo, read:org"
    echo "    4. Copy the token"
    echo ""
    read -rp "  Paste your GitHub PAT here (or press Enter to skip): " pat_input
    if [ -n "$pat_input" ]; then
        SHELL_RC=""
        if [ -f "$HOME/.zshrc" ]; then SHELL_RC="$HOME/.zshrc"
        elif [ -f "$HOME/.bashrc" ]; then SHELL_RC="$HOME/.bashrc"
        elif [ -f "$HOME/.bash_profile" ]; then SHELL_RC="$HOME/.bash_profile"
        fi
        if [ -n "$SHELL_RC" ]; then
            if grep -q "GECGITHUB_PAT" "$SHELL_RC" 2>/dev/null; then
                warn "GECGITHUB_PAT already in $SHELL_RC — update it manually if needed"
            else
                echo "export GECGITHUB_PAT=$pat_input" >> "$SHELL_RC"
                ok "Added to $SHELL_RC"
                info "Run: source $SHELL_RC"
            fi
        else
            warn "Could not find shell rc file. Add manually:"
            info "export GECGITHUB_PAT=$pat_input"
        fi
        export GECGITHUB_PAT="$pat_input"
    else
        warn "Skipped. Set GECGITHUB_PAT in your shell profile before using /crq-generator."
    fi
fi

# ──────────────────────────────────────────────────────────────────────────────
hdr "Step 3: ServiceNow Session"

SESSION_FILE="$HOME/.wibey/snow-session.json"

check_session_alive() {
    if [ ! -f "$SESSION_FILE" ]; then return 1; fi
    "$PYTHON" - <<'PYEOF' 2>/dev/null
import json, sys
try:
    import requests
    requests.packages.urllib3.disable_warnings()
    from pathlib import Path
    s = json.loads(Path.home().joinpath('.wibey/snow-session.json').read_text())
    r = requests.get(
        'https://walmartglobal.service-now.com/api/now/table/change_request',
        headers={'Cookie': s['cookie_header'], 'Accept': 'application/json'},
        params={'sysparm_limit': 1, 'sysparm_fields': 'number'},
        verify=False, timeout=10
    )
    sys.exit(0 if r.status_code == 200 else 1)
except Exception:
    sys.exit(1)
PYEOF
}

if check_session_alive; then
    ok "ServiceNow session is alive"
else
    if [ -f "$SESSION_FILE" ]; then
        warn "Session file exists but is stale (expired). Re-extracting..."
    else
        info "No session file found. Starting first-time ServiceNow SSO..."
    fi
    echo ""
    echo "  What will happen:"
    echo "    - Chrome will open and navigate to ServiceNow"
    echo "    - Complete SSO/MFA login (one time only)"
    echo "    - Session is saved to ~/.wibey/snow-session.json"
    echo "    - Future runs reuse this session automatically"
    echo ""

    # Handle Chrome singleton lock
    SINGLETON="$SCRIPT_DIR/chrome_profile/SingletonLock"
    if [ -f "$SINGLETON" ]; then
        warn "Removing stale Chrome SingletonLock..."
        rm -f "$SCRIPT_DIR/chrome_profile/Singleton"*
    fi

    echo "  Press Enter to open Chrome for ServiceNow SSO, or Ctrl+C to skip..."
    read -r _

    "$PYTHON" "$SCRIPT_DIR/extract_snow_session.py"

    if check_session_alive; then
        ok "ServiceNow session extracted and verified"
    else
        err "Session extraction failed or session not alive."
        info "Try manually: python3 $SCRIPT_DIR/extract_snow_session.py"
    fi
fi

# ──────────────────────────────────────────────────────────────────────────────
hdr "Step 4: End-to-End Verification"

"$PYTHON" "$SCRIPT_DIR/snow_client.py" get CHG3978198 2>&1 | grep -E "✅|❌|Found|Unauthorized" | head -3 && \
    ok "ServiceNow API working — can read CRQs" || \
    warn "ServiceNow API check inconclusive. Run: python3 $SCRIPT_DIR/snow_client.py get CHG3978198"

# ──────────────────────────────────────────────────────────────────────────────
hdr "Optional: Cron Session Refresh"
echo ""
echo "  ServiceNow cookies expire in ~1 hour."
echo "  To refresh automatically every 45 minutes, add to crontab:"
echo ""
echo "    */45 * * * * $PYTHON $SCRIPT_DIR/extract_snow_session.py >> ~/.wibey/snow-session-refresh.log 2>&1"
echo ""
read -rp "  Add cron refresh now? [y/N]: " cron_input
if [[ "$cron_input" =~ ^[Yy]$ ]]; then
    CRON_LINE="*/45 * * * * $PYTHON $SCRIPT_DIR/extract_snow_session.py >> $HOME/.wibey/snow-session-refresh.log 2>&1"
    if crontab -l 2>/dev/null | grep -q "extract_snow_session"; then
        ok "Cron entry already exists"
    else
        (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
        ok "Cron refresh added (every 45 minutes)"
    fi
else
    info "Skipped. Run manually when needed: python3 $SCRIPT_DIR/extract_snow_session.py"
fi

# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║           Setup Complete ✅                   ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo ""
echo "  You can now use /crq-generator in Wibey:"
echo ""
echo "    /crq-generator https://gecgithub01.walmart.com/ORG/REPO/pull/123"
echo ""
