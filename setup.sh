#!/usr/bin/env bash
# ~/sarthi/setup.sh — One-command install for sArthI
# Self-healing Autonomous Runtime Troubleshooting & Health Intelligence
# Usage: cd ~/sarthi && bash setup.sh
# Requires: macOS, Walmart network/VPN, Wibey CLI installed

set -euo pipefail

SARTHI_VERSION="1.0.0"
SARTHI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIBEY_DIR="$HOME/.wibey"
VERSION_FILE="$WIBEY_DIR/.sarthi-version"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}✅ $1${RESET}"; }
warn() { echo -e "${YELLOW}⚠️  $1${RESET}"; }
err()  { echo -e "${RED}❌ $1${RESET}"; }
info() { echo -e "${BLUE}ℹ️  $1${RESET}"; }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  sArthI Setup  (${SARTHI_VERSION})"
echo "  Self-healing Autonomous Runtime Troubleshooting &"
echo "  Health Intelligence"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ─────────────────────────────────────────────
# STEP 1 — Check prerequisites
# ─────────────────────────────────────────────
echo "STEP 1 — Checking prerequisites..."

if ! command -v wibey &>/dev/null; then
    err "Wibey CLI not found."
    echo "      Install at: https://wibey.walmart.com/cli (Walmart network required)"
    exit 1
fi
ok "Wibey CLI: $(wibey --version 2>/dev/null || echo 'found')"

if ! command -v python3 &>/dev/null; then
    err "python3 not found. Required for ServiceNow CRQ scripts."
    exit 1
fi
ok "Python: $(python3 --version)"

if command -v gh &>/dev/null; then
    ok "gh CLI: $(gh --version | head -1)"
else
    warn "gh CLI not found. sar-pr will not work. Install from Walmart Artifactory or GEC GitHub."
fi

if command -v gcloud &>/dev/null; then
    ok "gcloud: found"
else
    warn "gcloud not found. BigQuery tools will not work."
fi

# ─────────────────────────────────────────────
# STEP 2 — Create ~/.wibey directories
# ─────────────────────────────────────────────
echo ""
echo "STEP 2 — Creating ~/.wibey directories..."
mkdir -p "$WIBEY_DIR/commands" "$WIBEY_DIR/skills" "$WIBEY_DIR/agents" "$WIBEY_DIR/knowledge" \
    "$WIBEY_DIR/knowledge/crqs" "$WIBEY_DIR/knowledge/crq-references" \
    "$WIBEY_DIR/sarthi/history" "$WIBEY_DIR/crq" "$WIBEY_DIR/sarthi"
ok "Directories ready"

# Seed sarthi-owned config and cookies (owned by sarthi, not prod-monitor)
LEGACY_MONITOR="$WIBEY_DIR/prod-monitor"
SARTHI_STATE="$WIBEY_DIR/sarthi"

if [ ! -f "$SARTHI_STATE/config.yaml" ]; then
    if [ -f "$LEGACY_MONITOR/config.yaml" ]; then
        cp "$LEGACY_MONITOR/config.yaml" "$SARTHI_STATE/config.yaml"
        ok "Seeded: sarthi/config.yaml (from prod-monitor)"
    else
        warn "sarthi/config.yaml not seeded — no source found. Add env URLs manually."
    fi
else
    info "Skipped: sarthi/config.yaml (already exists)"
fi

if [ ! -f "$SARTHI_STATE/cookies.txt" ]; then
    if [ -f "$LEGACY_MONITOR/cookies.txt" ]; then
        cp "$LEGACY_MONITOR/cookies.txt" "$SARTHI_STATE/cookies.txt"
        ok "Seeded: sarthi/cookies.txt (from prod-monitor)"
    else
        warn "sarthi/cookies.txt not seeded — no active session. Run: python3 $WIBEY_DIR/sarthi/headless-refresh.py"
    fi
else
    info "Skipped: sarthi/cookies.txt (already exists — not overwriting live session)"
fi

if [ ! -f "$SARTHI_STATE/session.json" ]; then
    if [ -f "$LEGACY_MONITOR/session.json" ]; then
        cp "$LEGACY_MONITOR/session.json" "$SARTHI_STATE/session.json"
        ok "Seeded: sarthi/session.json (from prod-monitor)"
    else
        warn "sarthi/session.json not seeded — run headless-refresh once to create it"
    fi
else
    info "Skipped: sarthi/session.json (already exists)"
fi

# Symlink headless-refresh script into ~/.wibey/sarthi/ for easy access
if [ -f "$SARTHI_ROOT/scripts/headless-refresh.py" ]; then
    ln -sf "$SARTHI_ROOT/scripts/headless-refresh.py" "$SARTHI_STATE/headless-refresh.py"
    ok "Linked: sarthi/headless-refresh.py"
fi

# ─────────────────────────────────────────────
# STEP 3 — Symlink commands
# ─────────────────────────────────────────────
echo ""
echo "STEP 3 — Symlinking commands..."
for src in "$SARTHI_ROOT/commands/"*.md; do
    fname="$(basename "$src")"
    dst="$WIBEY_DIR/commands/$fname"
    if [ -L "$dst" ]; then
        rm "$dst"
    elif [ -f "$dst" ]; then
        warn "Skipping $fname — non-symlink file exists at $dst (manual review needed)"
        continue
    fi
    ln -s "$src" "$dst"
    ok "Linked: commands/$fname"
done

# ─────────────────────────────────────────────
# STEP 4 — Symlink skills
# ─────────────────────────────────────────────
echo ""
echo "STEP 4 — Symlinking skills..."
for skill_dir in "$SARTHI_ROOT/skills/"/*/; do
    skill_name="$(basename "$skill_dir")"
    dst="$WIBEY_DIR/skills/$skill_name"
    if [ -L "$dst" ]; then
        rm "$dst"
    elif [ -d "$dst" ]; then
        warn "Skipping skill $skill_name — non-symlink directory exists (manual review needed)"
        continue
    fi
    ln -s "$skill_dir" "$dst"
    ok "Linked: skills/$skill_name/"
done

# ─────────────────────────────────────────────
# STEP 5 — Symlink agents
# ─────────────────────────────────────────────
echo ""
echo "STEP 5 — Symlinking agents..."
for src in "$SARTHI_ROOT/agents/"*.md; do
    [ -f "$src" ] || continue
    fname="$(basename "$src")"
    dst="$WIBEY_DIR/agents/$fname"
    if [ -L "$dst" ]; then rm "$dst"; fi
    ln -s "$src" "$dst"
    ok "Linked: agents/$fname"
done

# ─────────────────────────────────────────────
# STEP 6 — Seed knowledge files to ~/.wibey/knowledge/
# ─────────────────────────────────────────────
echo ""
echo "STEP 6 — Seeding knowledge files..."
for f in "$SARTHI_ROOT/knowledge/"*.json "$SARTHI_ROOT/knowledge/"*.yaml; do
    [ -f "$f" ] || continue
    fname="$(basename "$f")"
    dst="$WIBEY_DIR/knowledge/$fname"
    if [ ! -f "$dst" ]; then
        cp "$f" "$dst"
        ok "Seeded: knowledge/$fname"
    else
        info "Skipped: knowledge/$fname (already exists — not overwriting local data)"
    fi
done

# Also seed team-config.yaml into sarthi root (primary location read by MCP servers)
TEAM_CFG_SRC="$SARTHI_ROOT/knowledge/team-config.yaml"
TEAM_CFG_DST="$SARTHI_ROOT/knowledge/team-config.yaml"
if [ -f "$TEAM_CFG_DST" ]; then
    info "team-config.yaml: already exists — review and update for your team"
else
    cp "$TEAM_CFG_SRC" "$TEAM_CFG_DST" 2>/dev/null && ok "Seeded: knowledge/team-config.yaml" || \
        warn "team-config.yaml not found — create ~/sarthi/knowledge/team-config.yaml for team-specific settings"
fi
echo "      ℹ️  Edit ~/sarthi/knowledge/team-config.yaml to set your team's ServiceNow group, Jira project, etc."

# ─────────────────────────────────────────────
# STEP 6b — Symlink CRQ scripts (vendored in repo)
# ─────────────────────────────────────────────
echo ""
echo "STEP 6b — Symlinking CRQ scripts..."
CRQ_SCRIPTS_SRC="$SARTHI_ROOT/scripts/crq"
CRQ_SCRIPTS_DST="$WIBEY_DIR/crq"
for script in snow_client.py extract_snow_session.py; do
    src="$CRQ_SCRIPTS_SRC/$script"
    dst="$CRQ_SCRIPTS_DST/$script"
    if [ ! -f "$src" ]; then
        warn "CRQ script missing in repo: scripts/crq/$script — skipping"
        continue
    fi
    if [ -L "$dst" ]; then rm "$dst"; elif [ -f "$dst" ]; then
        mv "$dst" "$dst.bak-$(date +%Y%m%d)" && info "Backed up existing: $dst"
    fi
    ln -s "$src" "$dst"
    ok "Linked: crq/$script → scripts/crq/$script"
done

# ─────────────────────────────────────────────
# STEP 7 — Merge MCP config (non-destructive)
# Driven by sarthi-mcp-additions.json — no hardcoded server lists here.
# To add a new server: edit ~/sarthi/mcp/sarthi-mcp-additions.json, re-run setup.sh.
# ─────────────────────────────────────────────
echo ""
echo "STEP 7 — Checking MCP config..."
MCP_FILE="$WIBEY_DIR/mcp.json"
ADDITIONS="$SARTHI_ROOT/mcp/sarthi-mcp-additions.json"
INJECT_SCRIPT="$SARTHI_ROOT/scripts/inject-mcp.py"

if [ ! -f "$MCP_FILE" ]; then
    warn "~/.wibey/mcp.json not found — creating minimal config"
    echo '{"mcpServers":{}}' > "$MCP_FILE"
fi

if grep -q '"mcp-jira"' "$MCP_FILE" 2>/dev/null; then
    ok "mcp-jira: already registered in mcp.json"
else
    warn "mcp-jira not found in ~/.wibey/mcp.json"
    echo "      Run: wibey mcp add mcp-jira  (or check Wibey Web → MCP panel)"
fi

if ! command -v python3 &>/dev/null; then
    warn "sarthi MCP: cannot inject — python3 not found"
elif [ ! -f "$ADDITIONS" ]; then
    warn "sarthi-mcp-additions.json not found: $ADDITIONS"
else
    python3 "$INJECT_SCRIPT" "$MCP_FILE" "$ADDITIONS" --sarthi-root "$SARTHI_ROOT"
fi

# ── pyyaml check (required by sarthi-airflow-read MCP) ────────────────────────
echo ""
echo "STEP 7a — Checking sarthi MCP Python dependencies..."
NEXUS_PYPI_EARLY="https://repository.cache.walmart.com/repository/pypi-proxy/simple/"
for pypi_pkg in pyyaml requests; do
    import_name="$pypi_pkg"
    [ "$pypi_pkg" = "pyyaml" ] && import_name="yaml"
    if python3 -c "import $import_name" 2>/dev/null; then
        ok "Python pkg $pypi_pkg: installed"
    else
        warn "Python pkg $pypi_pkg: NOT installed — sarthi-airflow-read MCP will fail"
        echo "      Install (Walmart Nexus):"
        echo "        pip install $pypi_pkg --index-url $NEXUS_PYPI_EARLY -q"
    fi
done

# bigquery-explorer skill (used by sar-investigate, sar-resolve for BQ queries)
BQ_SKILL_DIR="$WIBEY_DIR/skills/bigquery-explorer"
BQ_LIB="$HOME/.local/lib/bigquery-explorer/node_modules/@google-cloud/bigquery"
if [ -d "$BQ_SKILL_DIR" ]; then
    ok "bigquery-explorer skill: installed"
    if [ -d "$BQ_LIB" ]; then
        ok "bigquery-explorer SDK: @google-cloud/bigquery installed"
    else
        warn "bigquery-explorer SDK: @google-cloud/bigquery NOT installed"
        echo "      Run: bash $BQ_SKILL_DIR/scripts/install-bigquery.sh"
        echo "      (Walmart network required)"
    fi
else
    warn "bigquery-explorer skill: NOT installed"
    echo "      Required for BQ queries in sar-investigate / sar-resolve."
    echo "      Install in a Wibey session: /skill-installer bigquery-explorer"
fi

# ─────────────────────────────────────────────
# STEP 7b — Check Wibey plugin dependencies
# ─────────────────────────────────────────────
echo ""
echo "STEP 7b — Checking Wibey plugin dependencies..."

# msgraph skill — needed for sar-inbox email/Teams reads and sar-reply
MSGRAPH_SCRIPTS="$WIBEY_DIR/skills/msgraph/scripts"
if [ -d "$WIBEY_DIR/skills/msgraph" ] && [ -f "$MSGRAPH_SCRIPTS/auth.ts" ]; then
    ok "msgraph skill: installed"
    # Check auth via auth.ts status (uses Keychain or msgraph_tokens.json)
    BUN_BIN=$(command -v bun 2>/dev/null || echo "$HOME/.local/bin/bun")
    if [ -f "$BUN_BIN" ] || command -v bun &>/dev/null; then
        AUTHED=$(NODE_PATH="$HOME/.local/lib/node_modules" "$BUN_BIN" "$MSGRAPH_SCRIPTS/auth.ts" status 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('authenticated',False)).lower())" 2>/dev/null)
        if [ "$AUTHED" = "true" ]; then
            USER=$(NODE_PATH="$HOME/.local/lib/node_modules" "$BUN_BIN" "$MSGRAPH_SCRIPTS/auth.ts" status 2>/dev/null \
                | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('user',{}).get('email',''))" 2>/dev/null)
            ok "msgraph auth: authenticated as $USER"
        else
            warn "msgraph auth: NOT authenticated"
            echo "      Run in a Wibey session: /msgraph login"
            echo "      Required for: sar-inbox email/Teams reads, sar-reply, sarthi-msgraph MCP"
        fi
    else
        warn "msgraph auth: cannot check — bun not found"
        echo "      Install bun: curl -fsSL https://bun.sh/install | bash"
    fi
else
    warn "msgraph skill: NOT installed"
    echo "      sar-inbox cannot read Outlook email or Teams messages without it."
    echo "      Install in a Wibey session: /skill-installer msgraph"
    echo "      Then run: /msgraph login"
fi

# mcp-jira plugin check
if wibey plugin list 2>/dev/null | grep -qi "jira"; then
    ok "mcp-jira plugin: registered"
else
    warn "mcp-jira plugin: not detected"
    echo "      sar-inbox cannot read Jira tickets without it."
    echo "      Enable at: https://wibey.walmart.com → Plugins → Jira"
fi

# ─────────────────────────────────────────────
# STEP 7c — Check CRQ (ServiceNow) dependencies
# ─────────────────────────────────────────────
echo ""
echo "STEP 7c — Checking CRQ (ServiceNow) dependencies..."

NEXUS_PYPI="https://repository.cache.walmart.com/repository/pypi-proxy/simple/"
CRQ_DIR="$HOME/.wibey/crq"
CRQ_OK=true

if [ -f "$CRQ_DIR/snow_client.py" ]; then
    ok "snow_client.py: found"
else
    warn "snow_client.py: NOT found at $CRQ_DIR/"
    echo "      It is vendored in this repo — run: bash setup.sh (STEP 6b will symlink it)"
    CRQ_OK=false
fi

pkg_import_name() {
    case "$1" in
        pyyaml)        echo "yaml" ;;
        pycryptodome)  echo "Crypto" ;;
        *)             echo "$1" ;;
    esac
}
# selenium — used by extract_snow_session.py (ServiceNow auth via headless/headed Chrome)
# playwright — used by headless-refresh.py (Airflow auth) and setup-session.py (first-time Airflow)
# Both are required. selenium ≠ playwright — checking both explicitly.
for pypi_pkg in requests selenium playwright pyyaml pycryptodome; do
    import_name="$(pkg_import_name "$pypi_pkg")"
    if python3 -c "import $import_name" 2>/dev/null; then
        ok "Python pkg $pypi_pkg ($import_name): installed"
    else
        warn "Python pkg $pypi_pkg: NOT installed"
        echo "      Install (Walmart Nexus — do NOT use pypi.org on Walmart network):"
        echo "        pip install $pypi_pkg --index-url $NEXUS_PYPI -q"
        CRQ_OK=false
    fi
done

# Playwright Chromium browser (used by headless-refresh.py and setup-session.py for Airflow auth)
if python3 -c "from playwright.sync_api import sync_playwright" 2>/dev/null; then
    CHROMIUM_OK=$(python3 -c "
from playwright.sync_api import sync_playwright
p = sync_playwright().start()
try:
    _ = p.chromium.executable_path
    print('ok')
except Exception:
    print('missing')
finally:
    p.stop()
" 2>/dev/null)
    if [ "$CHROMIUM_OK" = "ok" ]; then
        ok "Playwright Chromium: installed"
    else
        warn "Playwright Chromium browser: not installed"
        echo "      Installing Playwright Chromium..."
        if python3 -m playwright install chromium 2>/dev/null; then
            ok "Playwright Chromium: installed"
        else
            warn "Playwright Chromium install failed"
            echo "      Run manually: python3 -m playwright install chromium"
            CRQ_OK=false
        fi
    fi
else
    warn "Playwright: NOT installed"
    echo "      Run: pip install playwright --index-url $NEXUS_PYPI -q && python3 -m playwright install chromium"
    CRQ_OK=false
fi

# Google Chrome (required by selenium for ServiceNow auth)
if [ -d "/Applications/Google Chrome.app" ] || command -v google-chrome &>/dev/null || command -v chromium &>/dev/null; then
    ok "Google Chrome: installed (required for ServiceNow auth)"
else
    warn "Google Chrome: NOT found"
    echo "      Google Chrome is required for ServiceNow authentication."
    echo "      Download from: https://www.google.com/chrome/"
    echo "      (Download on personal network if internal Artifactory doesn't have it)"
    CRQ_OK=false
fi

# Seed CRQ reference files
CRQREF_DIR="$WIBEY_DIR/knowledge/crq-references"
CRQREF_SRC="$SARTHI_ROOT/knowledge/crq-references"
mkdir -p "$CRQREF_DIR"
for ref_file in functional-CHG3978198-INTL-ET360.json quality-CHG3943471-structure.json; do
    src="$CRQREF_SRC/$ref_file"
    dst="$CRQREF_DIR/$ref_file"
    if [ -f "$dst" ]; then
        ok "CRQ reference: $ref_file (already present)"
    elif [ -f "$src" ]; then
        cp "$src" "$dst"
        ok "CRQ reference: $ref_file (seeded from repo)"
    else
        warn "CRQ reference NOT found: $ref_file"
        echo "      Expected at: $src"
        CRQ_OK=false
    fi
done

SNOW_SESSION="$HOME/.wibey/snow-session.json"
if [ -f "$SNOW_SESSION" ]; then
    ok "ServiceNow session: found ($SNOW_SESSION)"
    echo "      ℹ️  Session expires ~8h."
    echo "         Auto-refresh: sarthi-snow-auth MCP tool refresh_session (calls extract_snow_session.py)"
    echo "         Cron (every 6h): python3 $CRQ_DIR/extract_snow_session.py >> ~/.wibey/sarthi/snow-auth.log 2>&1"
else
    warn "ServiceNow session: NOT authenticated"
    echo "      Run once (opens browser for Walmart AD SSO):"
    echo "        python3 $CRQ_DIR/extract_snow_session.py"
    echo "      After first login, sarthi-snow-auth MCP handles subsequent refreshes."
    CRQ_OK=false
fi

if [ "$CRQ_OK" = "true" ]; then
    ok "CRQ dependencies: all present ✅"
else
    warn "CRQ dependencies: some missing — sar-crq will not work until resolved (see above)"
    echo "      Optional cron to keep ServiceNow session fresh (add to crontab -e):"
    echo "        0 */6 * * * python3 $CRQ_DIR/extract_snow_session.py >> $HOME/.wibey/sarthi/snow-session-refresh.log 2>&1"
fi

# ─────────────────────────────────────────────
# STEP 7c2 — Slack API patch (curl TLS fix)
# ─────────────────────────────────────────────
echo ""
echo "STEP 7c2 — Checking slack-api TLS patch..."
SLACK_API_JS=$(find "$WIBEY_DIR" "$HOME/.claude" -path "*/slack-api/scripts/api.js" 2>/dev/null | head -1)
if [ -z "$SLACK_API_JS" ]; then
    info "slack-api skill not installed — skipping TLS patch (run /skill-installer slack-api to install)"
elif grep -q "Patched by ~/sarthi/scripts/patch-slack-api.py" "$SLACK_API_JS" 2>/dev/null; then
    ok "slack-api TLS patch: already applied"
else
    warn "slack-api TLS patch: not applied — Node.js fetch fails with Walmart enterprise TLS cert"
    echo "      Applying patch..."
    if python3 "$SARTHI_ROOT/scripts/patch-slack-api.py" 2>/dev/null; then
        ok "slack-api TLS patch: applied successfully"
    else
        warn "slack-api TLS patch: failed — run manually: python3 $SARTHI_ROOT/scripts/patch-slack-api.py"
    fi
fi

# ─────────────────────────────────────────────
# STEP 7d — WCNP tools (kubectl + sledge)
# ─────────────────────────────────────────────
echo ""
echo "STEP 7d — Checking WCNP tools (kubectl + sledge)..."

# Detect OS/arch for kubectl download
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
[ "$ARCH" = "x86_64" ] && ARCH="amd64"
[ "$ARCH" = "aarch64" ] && ARCH="arm64"
[ "$ARCH" = "arm64" ] && ARCH="arm64"
KUBECTL_ARTIFACTORY="https://generic.ci.artifacts.walmart.com/artifactory/dl-k8s-io-generic-release-remote"
SLEDGE_WMLINK="http://wmlink.wal-mart.com/getSledgeCore"

if command -v kubectl &>/dev/null; then
    ok "kubectl: $(kubectl version --client --short 2>/dev/null | head -1 || echo 'found')"
else
    warn "kubectl: NOT installed"
    echo "      Installing kubectl from Walmart Artifactory..."
    KUBECTL_VERSION=$(curl -sf "${KUBECTL_ARTIFACTORY}/release/stable.txt" 2>/dev/null || echo "")
    # Get version — check HTTP status explicitly
    KUBECTL_VERSION_HTTP=$(curl -sf -o /tmp/kubectl-stable.txt -w "%{http_code}" \
        "${KUBECTL_ARTIFACTORY}/release/stable.txt" 2>/dev/null)
    KUBECTL_VERSION=$(cat /tmp/kubectl-stable.txt 2>/dev/null | tr -d '[:space:]')
    rm -f /tmp/kubectl-stable.txt

    if [ -n "$KUBECTL_VERSION" ] && [ "$KUBECTL_VERSION_HTTP" = "200" ]; then
        KUBECTL_URL="${KUBECTL_ARTIFACTORY}/release/${KUBECTL_VERSION}/bin/${OS}/${ARCH}/kubectl"
        echo "      Version: $KUBECTL_VERSION  OS: $OS  Arch: $ARCH"
        KUBECTL_DL_HTTP=$(curl -fsSL "$KUBECTL_URL" -o /tmp/kubectl -w "%{http_code}" 2>/dev/null)
        if [ "$KUBECTL_DL_HTTP" = "200" ] && [ -s /tmp/kubectl ]; then
            chmod +x /tmp/kubectl
            mkdir -p "$HOME/.local/bin"
            mv /tmp/kubectl "$HOME/.local/bin/kubectl"
            if command -v kubectl &>/dev/null; then
                ok "kubectl: installed $(kubectl version --client --short 2>/dev/null | head -1)"
            else
                warn "kubectl: downloaded to ~/.local/bin/kubectl but not in PATH"
                echo "      Add to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
            fi
        else
            warn "kubectl: download returned HTTP $KUBECTL_DL_HTTP from $KUBECTL_URL"
            echo "      Manual: curl -LO ${KUBECTL_URL} && chmod +x kubectl && mv kubectl ~/.local/bin/"
        fi
    elif [ "$KUBECTL_VERSION_HTTP" = "502" ] || [ "$KUBECTL_VERSION_HTTP" = "503" ]; then
        warn "kubectl: Artifactory returned HTTP $KUBECTL_VERSION_HTTP (server-side error)"
        echo "      Try again later. Manual when available:"
        echo "        KUBECTL_VERSION=\$(curl -sf ${KUBECTL_ARTIFACTORY}/release/stable.txt)"
        echo "        curl -LO ${KUBECTL_ARTIFACTORY}/release/\${KUBECTL_VERSION}/bin/${OS}/${ARCH}/kubectl"
        echo "        chmod +x kubectl && mv kubectl ~/.local/bin/"
    else
        warn "kubectl: could not reach Artifactory (HTTP $KUBECTL_VERSION_HTTP)"
        echo "      Manual: KUBECTL_VERSION=\$(curl -sf ${KUBECTL_ARTIFACTORY}/release/stable.txt)"
        echo "              curl -LO ${KUBECTL_ARTIFACTORY}/release/\${KUBECTL_VERSION}/bin/${OS}/${ARCH}/kubectl"
        echo "              chmod +x kubectl && mv kubectl ~/.local/bin/"
    fi
fi

if command -v sledge &>/dev/null; then
    ok "sledge: found at $(which sledge)"
else
    warn "sledge: NOT installed"
    SLEDGE_VERSION="0.18.4"
    SLEDGE_OS="$(uname | tr 'A-Z' 'a-z')"
    SLEDGE_ARTIFACTORY="https://mvn.ci.artifacts.walmart.com/artifactory/wce-mvn/com/walmartlabs/containers/sledge-plugins/${SLEDGE_OS}/sledge/${SLEDGE_VERSION}/sledge-${SLEDGE_VERSION}-amd64.tar.gz"
    mkdir -p "$HOME/.sledge/bin"
    echo "      Downloading sledge ${SLEDGE_VERSION} from Walmart Artifactory..."
    SLEDGE_TGZ=$(mktemp)
    SLEDGE_HTTP_CODE=$(curl --silent --fail --noproxy ".walmart.com" -L "$SLEDGE_ARTIFACTORY" -o "$SLEDGE_TGZ" -w "%{http_code}" 2>/dev/null)
    if [ "$SLEDGE_HTTP_CODE" = "200" ] && [ -s "$SLEDGE_TGZ" ]; then
        tar -C "$HOME/.sledge/bin" -xzf "$SLEDGE_TGZ" 2>/dev/null
        rm -f "$SLEDGE_TGZ"
        # Add to PATH for this session
        export PATH="$PATH:$HOME/.sledge/bin"
        # Add to shell rc if not already present
        for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
            if [ -f "$rc" ] && ! grep -q "sledge:binary path" "$rc"; then
                printf '\n#sledge:binary path\nexport SLEDGE_BIN="${HOME}/.sledge/bin"\nexport PATH="${PATH}:${SLEDGE_BIN}"\n' >> "$rc"
            fi
        done
        # Configure git credentials for sledge plugin system (uses gh token)
        if command -v gh &>/dev/null; then
            GH_TOKEN=$(gh auth token --hostname gecgithub01.walmart.com 2>/dev/null || echo "")
            GH_USER=$(gh api user --hostname gecgithub01.walmart.com --jq .login 2>/dev/null || echo "")
            if [ -n "$GH_TOKEN" ] && [ -n "$GH_USER" ]; then
                git config --global "url.https://${GH_USER}:${GH_TOKEN}@gecgithub01.walmart.com/.insteadOf" "https://gecgithub01.walmart.com/" 2>/dev/null || true
            fi
        fi
        # Initialize sledge plugins
        export SLEDGE_BOOTSTRAP="Y"
        sledge version &>/dev/null && ok "sledge: installed v${SLEDGE_VERSION}" || \
            warn "sledge: installed but plugin init failed — run 'sledge connect' once to initialize"
    elif [ "$SLEDGE_HTTP_CODE" = "502" ] || [ "$SLEDGE_HTTP_CODE" = "503" ]; then
        rm -f "$SLEDGE_TGZ"
        warn "sledge: Artifactory returned HTTP $SLEDGE_HTTP_CODE (server-side error — not a VPN issue)"
        echo "      Try again later. Direct URL: $SLEDGE_ARTIFACTORY"
    else
        rm -f "$SLEDGE_TGZ"
        warn "sledge: download failed (HTTP $SLEDGE_HTTP_CODE)"
        echo "      Manual: curl --noproxy '.walmart.com' -L '$SLEDGE_ARTIFACTORY' | tar -C ~/.sledge/bin -xz"
        echo "      Then: export PATH=\"\$PATH:\$HOME/.sledge/bin\""
    fi
fi

# Check if WCNP clusters are connected (if kubectl+sledge both present)
if command -v kubectl &>/dev/null && command -v sledge &>/dev/null; then
    WCNP_CFG="$WIBEY_DIR/sarthi/wcnp-clusters.yaml"
    if [ -f "$WCNP_CFG" ]; then
        python3 - "$WCNP_CFG" <<'WCNP_CHECK'
import sys, os
try:
    import yaml
    cfg = yaml.safe_load(open(sys.argv[1]))
except ImportError:
    print("      ℹ️  pyyaml not installed — skipping cluster context check")
    sys.exit(0)
import subprocess
clusters = cfg.get("clusters", [])
for c in clusters:
    name = c.get("name", "")
    r = subprocess.run(["kubectl", "config", "get-contexts", "--no-headers", "-o", "name"],
                       capture_output=True, text=True)
    contexts = r.stdout.strip().splitlines()
    connected = any(name in ctx for ctx in contexts)
    if connected:
        print(f"      ✅  {name}: kubeconfig context found")
    else:
        print(f"      ⚠️   {name}: not connected — run: sledge connect {name}")
WCNP_CHECK
    fi
fi

# ─────────────────────────────────────────────
# STEP 8 — Validate GEC GitHub token
# ─────────────────────────────────────────────
echo ""
echo "STEP 8 — Validating GitHub token..."
if grep -q "gecgithub01.walmart.com" "$HOME/.gitconfig" 2>/dev/null; then
    ok "GEC GitHub token: found in ~/.gitconfig"
else
    warn "GEC GitHub token not configured"
    echo "      Add to ~/.gitconfig:"
    echo '      [url "https://YOUR_TOKEN@gecgithub01.walmart.com/"]'
    echo '          insteadOf = https://gecgithub01.walmart.com/'
    echo "      Generate token at: https://gecgithub01.walmart.com/settings/tokens"
    echo "      Scopes needed: repo, read:org"
fi

# ─────────────────────────────────────────────
# STEP 9 — Write version file
# ─────────────────────────────────────────────
echo "$SARTHI_VERSION" > "$VERSION_FILE"
ok "Version file written: $VERSION_FILE ($SARTHI_VERSION)"

# ─────────────────────────────────────────────
# STEP 10 — First-time authentication setup
# ─────────────────────────────────────────────
echo ""
echo "STEP 10 — Authentication Setup..."
AUTH_COMPLETE="$WIBEY_DIR/sarthi/.auth-complete"
FIRST_TIME_AUTH="$SARTHI_ROOT/scripts/first-time-auth.sh"

if [ -f "$AUTH_COMPLETE" ] && ! grep -q "failed" "$AUTH_COMPLETE" 2>/dev/null; then
    ok "Auth: already complete ($(cat "$AUTH_COMPLETE" | cut -d' ' -f1))"
    info "Re-run auth anytime: bash ~/sarthi/scripts/first-time-auth.sh --force"
else
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────┐"
    echo "  │  First-time authentication required.                    │"
    echo "  │  6 browser windows will open — one for each service.    │"
    echo "  │  Each requires your Walmart credentials (SSO/MFA).      │"
    echo "  │  Total time: ~10 minutes.                               │"
    echo "  └─────────────────────────────────────────────────────────┘"
    echo ""
    if [ -f "$FIRST_TIME_AUTH" ]; then
        bash "$FIRST_TIME_AUTH"
    else
        warn "first-time-auth.sh not found at $FIRST_TIME_AUTH"
        echo "      Run manually: bash ~/sarthi/scripts/first-time-auth.sh"
    fi
fi

# ─────────────────────────────────────────────
# DONE
# ─────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}  sArthI installed successfully!${RESET}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Next steps:"
echo "  1. Start a new Wibey session (close terminal + reopen, then: wibey)"
echo "  2. Run health check: /sar-setup"
echo "  3. Try sArthI: /sarthi"
echo ""
echo "  Available commands:"
echo "  /sarthi                     → main assistant"
echo "  /sarthi monitor             → DAG health dashboard"
echo "  /sarthi sync                → sync team knowledge"
echo "  /sar-setup                  → check all dependencies"
echo ""
