#!/usr/bin/env bash
# ============================================================
# sArthI Installer — install.sh
#
# One-liner bootstrap. Clones the sArthI repo and runs setup.
#
# Usage (run in terminal — NOT inside Wibey):
#
#   git clone https://gecgithub01.walmart.com/WITDnA/sarthi.git ~/sarthi && bash ~/sarthi/install.sh
#
# Uses your existing git credential helper (gh auth) — no token flag needed.
# Requires Walmart network or VPN.
#
# Or if you already have the repo cloned:
#   bash ~/sarthi/install.sh
#
# Requirements:
#   - macOS (Apple Silicon or Intel)
#   - Walmart network or VPN connected
#   - Internet access to gecgithub01.walmart.com
#
# This script will:
#   1. Check/install prerequisites (git, bun, Node.js, Python 3)
#   2. Check/install Wibey CLI (if not present)
#   3. Clone WITDnA/sarthi → ~/sarthi (or pull if already cloned)
#   4. Run ~/sarthi/setup.sh (installs everything + triggers auth wizard)
# ============================================================

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}✅ $1${RESET}"; }
warn() { echo -e "${YELLOW}⚠️  $1${RESET}"; }
err()  { echo -e "${RED}❌ $1${RESET}"; exit 1; }
info() { echo -e "${BLUE}ℹ️  $1${RESET}"; }

SARTHI_DIR="$HOME/sarthi"
GEC_HOST="gecgithub01.walmart.com"
SARTHI_REPO="WITDnA/sarthi"
WIBEY_CLI_REPO="genaica/wibey-cli"
ARTIFACTORY_NPM="https://npm.ci.artifacts.walmart.com/artifactory/api/npm/npme-npm"
NEXUS_PYPI="https://repository.cache.walmart.com/repository/pypi-proxy/simple/"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  sArthI Installer"
echo "  Self-healing Autonomous Runtime Troubleshooting &"
echo "  Health Intelligence for Walmart INTLDLDAT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  This script runs in your terminal (not inside Wibey)."
echo "  Estimated time: 5-15 minutes (includes auth setup)."
echo ""

# ── PREREQ 1: macOS check ─────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
    err "sArthI currently supports macOS only. Linux support coming soon."
fi
ok "macOS: $(sw_vers -productVersion)"

# ── PREREQ 2: Walmart network ─────────────────────────────────
info "Checking Walmart network connectivity..."
if curl -sf --max-time 5 "https://$GEC_HOST" -o /dev/null 2>/dev/null; then
    ok "Walmart network: reachable"
else
    warn "Cannot reach $GEC_HOST — are you on Walmart network or VPN?"
    echo "  Connect to Walmart VPN and retry."
    echo "  If on VPN and still failing, check: curl -v https://$GEC_HOST"
    exit 1
fi

# ── PREREQ 3: git ─────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    err "git not found. Install Xcode Command Line Tools: xcode-select --install"
fi
ok "git: $(git --version | cut -d' ' -f3)"

# ── PREREQ 4: Python 3 ────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    err "python3 not found. Install Python 3.10+ from https://www.python.org/downloads/ or Walmart Artifactory."
fi
PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
if python3 -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
    ok "Python: $PYTHON_VER"
else
    warn "Python $PYTHON_VER found — Python 3.10+ recommended"
fi

# ── PREREQ 5: bun ─────────────────────────────────────────────
BUN_BIN=$(command -v bun 2>/dev/null || echo "$HOME/.local/bin/bun")
if [[ -x "$BUN_BIN" ]]; then
    ok "bun: $("$BUN_BIN" --version 2>/dev/null)"
else
    info "bun not found — installing..."
    # Walmart Artifactory bun install (uses npm global install)
    if command -v npm &>/dev/null; then
        npm install -g bun --registry "$ARTIFACTORY_NPM" 2>/dev/null && ok "bun: installed via npm" || \
        { warn "bun install via npm failed"; info "Install bun manually: curl -fsSL https://bun.sh/install | bash"; }
    else
        warn "npm not found — cannot auto-install bun"
        info "Install Node.js 22+ first, then: npm install -g bun --registry $ARTIFACTORY_NPM"
    fi
fi

# ── PREREQ 6: gh CLI ──────────────────────────────────────────
if command -v gh &>/dev/null; then
    ok "gh CLI: $(gh --version | head -1)"
    if ! gh auth status --hostname "$GEC_HOST" &>/dev/null 2>&1; then
        info "gh CLI found but not authenticated to $GEC_HOST"
        info "Running: gh auth login --hostname $GEC_HOST --web"
        gh auth login --hostname "$GEC_HOST" --web 2>&1 || warn "gh auth failed — continuing (can auth later)"
    fi
else
    warn "gh CLI not found — needed for sarthi-git MCP and sar-pr skill"
    info "Install from Walmart Artifactory (ask your team for the internal URL)"
    info "Or install manually: https://cli.github.com"
    info "Continuing without gh — sArthI core features still work"
fi

# ── PREREQ 7: Wibey CLI ───────────────────────────────────────
echo ""
echo "Checking Wibey CLI..."
if command -v wibey &>/dev/null; then
    ok "Wibey CLI: $(wibey --version 2>/dev/null | head -1 || echo 'found')"
else
    warn "Wibey CLI not found."
    echo ""
    echo "  sArthI is a Wibey plugin — Wibey CLI is required."
    echo "  Installing Wibey CLI from GEC GitHub..."
    echo ""

    WIBEY_DIR_INSTALL="$HOME/.wibey-cli-src"
    if git clone "https://$GEC_HOST/$WIBEY_CLI_REPO.git" "$WIBEY_DIR_INSTALL" 2>&1; then
        cd "$WIBEY_DIR_INSTALL"
        if command -v bun &>/dev/null || [[ -x "$BUN_BIN" ]]; then
            BIN="${BUN_BIN:-bun}"
            "$BIN" install 2>/dev/null && bash scripts/setup-local 2>/dev/null && \
                ok "Wibey CLI: installed" || warn "Wibey install failed — check $WIBEY_DIR_INSTALL"
        else
            warn "bun not available — cannot finish Wibey install"
            info "Manually: cd $WIBEY_DIR_INSTALL && bun install && bash scripts/setup-local"
        fi
        cd - > /dev/null
    else
        warn "Could not clone Wibey CLI — check gh auth for $GEC_HOST"
        echo "  Manual: git clone https://$GEC_HOST/$WIBEY_CLI_REPO.git && cd wibey-cli && bash scripts/setup-local"
    fi

    # Re-check
    if ! command -v wibey &>/dev/null; then
        warn "Wibey CLI still not found after install attempt."
        echo "  Continuing — sArthI files will be installed but Wibey must be available to use them."
    fi
fi

# ── CLONE / UPDATE SARTHI REPO ────────────────────────────────
echo ""
echo "Setting up ~/sarthi..."

if [[ -d "$SARTHI_DIR/.git" ]]; then
    info "~/sarthi already exists — pulling latest..."
    cd "$SARTHI_DIR"
    git pull --ff-only origin main 2>&1 && ok "~/sarthi: updated to latest" || \
        warn "git pull failed — local changes may conflict. Using existing version."
    cd - > /dev/null
elif [[ -d "$SARTHI_DIR" ]] && [[ "$(ls -A "$SARTHI_DIR")" ]]; then
    warn "~/sarthi exists but is not a git repo — using as-is"
    info "To get updates: rm -rf ~/sarthi && re-run this installer"
else
    # Fresh clone
    info "Cloning WITDnA/sarthi → ~/sarthi..."

    GH_TOKEN=""
    if command -v gh &>/dev/null; then
        GH_TOKEN=$(gh auth token --hostname "$GEC_HOST" 2>/dev/null || echo "")
    fi

    if [[ -n "$GH_TOKEN" ]]; then
        CLONE_URL="https://${GH_TOKEN}@${GEC_HOST}/${SARTHI_REPO}.git"
    else
        CLONE_URL="https://${GEC_HOST}/${SARTHI_REPO}.git"
    fi

    if git clone "$CLONE_URL" "$SARTHI_DIR" 2>&1; then
        ok "~/sarthi: cloned successfully"
    else
        err "Failed to clone $SARTHI_REPO. Check VPN + GEC GitHub access."
    fi
fi

# ── RUN SETUP.SH ─────────────────────────────────────────────
echo ""
echo "Running sArthI setup..."
echo ""

if [[ -f "$SARTHI_DIR/setup.sh" ]]; then
    bash "$SARTHI_DIR/setup.sh"
else
    err "setup.sh not found in $SARTHI_DIR — clone may have failed."
fi
