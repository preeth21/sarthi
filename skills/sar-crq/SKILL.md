---
name: "sar-crq"
key: "sar-crq"
description: "sArthI's change management skill. Generates and submits a ServiceNow Change Request (CRQ) draft with correct INTL-ET360 field values. Uses vendored snow_client.py + extract_snow_session.py via Bash — no MCP server needed. Receives all context from the envelope."
allowed-tools: [Read, Bash, Write, mcp__sarthi-snow__get_crq, mcp__sarthi-snow__parse_crq_file, mcp__sarthi-snow__create_crq_draft, mcp__sarthi-snow-auth__refresh_session]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "implemented"
---

# sar-crq — Change Request Generator

## Auth approach (no MCP needed)

`wibey-core-mcp` does NOT expose a ServiceNow CRQ write tool.
All SNOW interaction goes via Bash using the vendored Python scripts.

Auth chain:
1. `~/.wibey/crq/extract_snow_session.py` → Playwright/Chromium → Walmart AD SSO
   → saves `~/.wibey/crq/chrome_profile` + `~/.wibey/snow-session.json` (3 cookies)
2. `~/.wibey/crq/snow_client.py` → loads cookies → preflight GET for `X-UserToken` header
   → all API calls use `Cookie` + `X-UserToken`
3. Session expires ~8h → 401 detected → auto-re-triggers extract_snow_session.py

Scripts are vendored in `~/sarthi/scripts/crq/` and symlinked to `~/.wibey/crq/` by setup.sh.
This ensures they survive `~/.wibey` wipes and new machine setups.

One hard limitation: adding approvers requires browser automation — ServiceNow ACL
blocks REST writes to `sysapproval_approver` table. Handled inside snow_client.py
automatically after CRQ creation (adds Swaroop YS s0s07p0 as approver).

## Reference files

| File | Role |
|---|---|
| `~/.wibey/knowledge/crq-references/functional-CHG3978198-INTL-ET360.json` | **Field VALUES** — copy verbatim into every new CRQ payload |
| `~/.wibey/knowledge/crq-references/quality-CHG3943471-structure.json` | **Section STRUCTURE only** — writing template, never copy field values |

Both files are vendored in `~/sarthi/knowledge/crq-references/` and seeded by setup.sh.

---

## STEP 1 — Runtime dependency guard

```bash
NEXUS="https://repository.cache.walmart.com/repository/pypi-proxy/simple/"

pkg_import_name() {
    case "$1" in
        pyyaml)        echo "yaml" ;;
        pycryptodome)  echo "Crypto" ;;
        *)             echo "$1" ;;
    esac
}

MISSING_PKGS=()
for pypi_pkg in requests playwright pyyaml pycryptodome; do
    import_name="$(pkg_import_name "$pypi_pkg")"
    if ! python3 -c "import $import_name" 2>/dev/null; then
        MISSING_PKGS+=("$pypi_pkg")
    fi
done

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "📦 Installing missing Python packages via Walmart Nexus: ${MISSING_PKGS[*]}"
    pip install "${MISSING_PKGS[@]}" --index-url "$NEXUS" -q --no-input
    if [ $? -ne 0 ]; then
        echo "❌ Failed to install: ${MISSING_PKGS[*]}. Check Walmart VPN/network."
        exit 1
    fi
    echo "✅ Packages installed"
fi

# Check Playwright Chromium browser
if ! python3 -c "
from playwright.sync_api import sync_playwright
p = sync_playwright().start()
try:
    _ = p.chromium.executable_path
    print('ok')
except Exception:
    print('missing')
finally:
    p.stop()
" 2>/dev/null | grep -q "ok"; then
    echo "🌐 Installing Playwright Chromium (~100MB, one-time)..."
    python3 -m playwright install chromium
    if [ $? -ne 0 ]; then
        echo "❌ Playwright Chromium install failed. Run: python3 -m playwright install chromium"
        exit 1
    fi
fi

# Check snow_client.py exists (vendored + symlinked by setup.sh)
if [ ! -f "$HOME/.wibey/crq/snow_client.py" ]; then
    echo "❌ snow_client.py not found at ~/.wibey/crq/. Run: bash ~/sarthi/setup.sh"
    exit 1
fi

echo "✅ All CRQ dependencies present"
```

---

## STEP 2 — Check ServiceNow session alive

```bash
SESSION_CHECK=$(python3 ~/.wibey/crq/snow_client.py get CHG3978198 2>&1)
if echo "$SESSION_CHECK" | grep -qi "401\|unauthorized\|session expired\|login"; then
    echo "🔐 ServiceNow session expired — opening browser for re-authentication..."
    python3 ~/.wibey/crq/extract_snow_session.py
    if [ $? -ne 0 ]; then
        echo "❌ ServiceNow authentication failed or was cancelled"
        exit 1
    fi
    echo "✅ ServiceNow auth refreshed"
else
    echo "✅ ServiceNow session alive"
fi
```

---

## STEP 3 — Read reference files

```bash
cat ~/.wibey/knowledge/crq-references/functional-CHG3978198-INTL-ET360.json
cat ~/.wibey/knowledge/crq-references/quality-CHG3943471-structure.json
```

From functional ref — use these field values verbatim:
- assignment_group = "INTL-ET360"
- u_primary_escalation_group = "INTL-ET360"
- u_secondary_escalation_group = "INTL-ET360"
- u_change_manager_group = "Change Managers - US"
- type = "normal", category = "application", impact = "3"
- u_market = "Home Office"
- cmdb_ci = "International Datalake"
- u_affected_application = "International Datalake"
- u_ci_class_name = "Business Application"
- u_change_classification = "software"
- u_reason_for_install = "enhancement"
- u_testing_completed = "yes"
- u_type_of_testing_completed = "technical_testing,functional_testing"
- cab_required = "false", state = "-5"

From quality ref — use ONLY section structure (never copy field values):
- description: What is the change? → Components → • What? → • Why? → Criticality → 4 risk questions
- implementation: 1. Code Deployment → 2. DAG Triggering → 3. Post-deploy validation
- validation: numbered DAG run + change-specific assertions
- backout: Criteria → Code Backout → Re-run impacted DAG

---

## STEP 4 — Extract context

If called from envelope (via /sarthi command chain):
```
pr_url     = envelope.artifacts[type=="pr"].url          (may be multiple)
jira_key   = envelope.intent.entities.jira_key
dag_ids    = envelope.intent.entities.dag_id
market     = envelope.intent.entities.market  ("ca" | "mx" | "ca,mx")
resolution = envelope.context.investigation.root_cause_hypothesis
```

If called standalone — ask user for: PR URL(s), Jira key, DAG IDs, market, one-line summary.

Market → u_affected_geos mapping:
- "ca"    → "CA"
- "mx"    → "MX"
- "ca,mx" → "CA + MX"

---

## STEP 5 — Build CRQ text file

Determine slug and path:
```bash
JIRA_LOWER=$(echo "<JIRA_KEY>" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
SLUG="$(date +%Y-%m-%d)-${JIRA_LOWER}-<2-3-word-summary>"
CRQ_FILE="$HOME/.wibey/knowledge/crqs/$SLUG.txt"
mkdir -p "$HOME/.wibey/knowledge/crqs"
```

Write the CRQ txt using this exact format (snow_client.py parses it by section headers):

```
CHG[NUMBER]

Number:                CHG[NUMBER]
Requested by:          akiran@walmart.com
Opened by:             akiran@walmart.com
Change Owner:          akiran
Change Owner Group:    INTL-ET360
Risk:                  [Low / Moderate / High]
Machine Learning Score:[Low / Moderate / High]
Impact:                3 - Moderate
CAB required:          false
Impacted GEOs:         [CA / MX / CA + MX]
Business Unit:         Home Office
Type:                  Normal
Model:                 Normal
Reason for install:    Enhancement
Category:              Application
Affected CI Class:     Business Application
Affected application:  International Datalake
Primary CI:            International Datalake
Assigned DR Tier:      Tier 2 (Essential)
Primary Escalation:    INTL-ET360
Secondary Escalation:  INTL-ET360
Change Classification: Software
Has testing completed: Yes
Type of Testing:       Technical Testing, Functional Testing

Planned start date:    [DD-MM-YYYY HH:MM:SS]
Planned end date:      [DD-MM-YYYY HH:MM:SS]

─────────────────────────────────────────────────────────────────────────────
Summary
─────────────────────────────────────────────────────────────────────────────
[GEO] ET360 | [Topic] | [brief description — max 120 chars]

─────────────────────────────────────────────────────────────────────────────
Description
─────────────────────────────────────────────────────────────────────────────
What is the change?
[1-2 sentences. State what changed and include all PR URLs and Jira ticket.]

Components to be Deployed:
Airflow DAGs: [dag_id_1, dag_id_2 — or "None" if no DAG change]

Jira: https://jira.walmart.com/browse/[JIRA_KEY]
PR: [PR URL 1]
PR: [PR URL 2 if applicable]

• What?
  1. [filename or component] — [specific change]
  2. [filename or component] — [specific change]

• Why?
  [Root cause sentence]. [Impact on downstream consumers / business metric].

Reason for Criticality: [System] is the source of truth for [business purpose] used by [Finance / Operations / etc.].

1. Describe how testing has reduced risk: [method + env + what was validated]
2. Describe how deployment minimizes risk and blast radius: [scope + additive vs destructive + blast radius]
3. Describe production validation: Post-deploy — [action], [validate row counts / confirm data correctness].
4. Describe rollback steps (L2 executable): Revert PR #[NUMBER] in [repo] via GitHub "Revert" button, merge revert PR, redeploy, re-run impacted DAG.

─────────────────────────────────────────────────────────────────────────────
Implementation plan
─────────────────────────────────────────────────────────────────────────────
1. Code Deployment:
   Merge the PR below. After merge, changes are deployed via automated
   Concord deployment pipeline.
   [PR URL 1]
   [PR URL 2 if applicable]

   Alerting/Monitoring: Automated. Monitor Concord deployment status in
   the [repo-name] pipeline.

2. DAG Triggering:
   Trigger the following Airflow DAG in AFaaS prod and monitor the run:
   [dag_id — or omit if no DAG change]

3. Post-deploy validation:
   Run QA job in prod env to check syntax and confirm row counts (see
   Validation Plan below).

─────────────────────────────────────────────────────────────────────────────
Validation plan
─────────────────────────────────────────────────────────────────────────────
1. DAG Run Validation:
   Confirm [dag_id] completes successfully in AFaaS prod with no task failures.

2. [Change 1] Validation:
   Query [table_name (project.dataset.table format)]
   and confirm [specific assertion].
   Verify row counts are consistent with expected [metric].

─────────────────────────────────────────────────────────────────────────────
Backout plan
─────────────────────────────────────────────────────────────────────────────
Criteria for backout:

1. Concord deployment pipeline failure for PR #[NUMBER].
2. [dag_id] fails in production after triggering.
3. Data validation not met — row counts in [table] do not reflect expected [metric].

Describe the steps to take to roll back (L2 executable):

1. Code Backout:
   a) Go to PR #[NUMBER] on gecgithub01.walmart.com, click "Revert" in the
      Conversation tab. This creates a new Revert PR.
   b) Verify the Revert PR performs the exact opposite of the merged PR.
      Get it reviewed and merged.
   [PR URL 1]

2. Re-run impacted DAG:
   After revert is deployed, re-trigger the affected [DAG name]
   to restore the prior state of [table].
```

---

## STEP 6 — Submit CRQ draft to ServiceNow

```bash
echo "📤 Submitting CRQ draft to ServiceNow..."
RESULT=$(python3 ~/.wibey/crq/snow_client.py create "$CRQ_FILE" 2>&1)
echo "$RESULT"

CHG_NUMBER=$(echo "$RESULT" | grep -oE 'CHG[0-9]+' | head -1)
SYS_ID=$(echo "$RESULT" | python3 -c "import sys,json,re; d=sys.stdin.read(); m=re.search(r'sys_id[=:\"]+([a-f0-9]{32})', d); print(m.group(1) if m else '')" 2>/dev/null)

if [ -z "$CHG_NUMBER" ]; then
    if echo "$RESULT" | grep -qi "401\|unauthorized"; then
        echo "🔐 Session expired during create — re-authenticating..."
        python3 ~/.wibey/crq/extract_snow_session.py
        RESULT=$(python3 ~/.wibey/crq/snow_client.py create "$CRQ_FILE" 2>&1)
        echo "$RESULT"
        CHG_NUMBER=$(echo "$RESULT" | grep -oE 'CHG[0-9]+' | head -1)
    fi
fi

if [ -z "$CHG_NUMBER" ]; then
    echo "❌ CRQ submission failed — no CHG number in output. Check session and retry."
    exit 1
fi

echo "✅ CRQ created: $CHG_NUMBER"
# snow_client.py automatically adds Swaroop YS (s0s07p0) as approver
```

---

## STEP 7 — Generate HTML preview and open in browser

Generate preview at `~/.wibey/knowledge/crqs/$SLUG-preview.html` substituting real values.

```bash
open "$HOME/.wibey/knowledge/crqs/$SLUG-preview.html"
open "https://walmartglobal.service-now.com/nav_to.do?uri=change_request.do?sys_id=$SYS_ID"
```

---

## STEP 8 — Update envelope and report

Append to `envelope.artifacts`:
```json
{
  "type": "crq",
  "number": "<CHG_NUMBER>",
  "url": "https://walmartglobal.service-now.com/nav_to.do?uri=change_request.do?sys_id=<SYS_ID>",
  "saved_to": "~/.wibey/knowledge/crqs/<SLUG>.txt",
  "state": "Draft (-5) — user must set dates and submit for approval in ServiceNow UI"
}
```

Print summary:
```
─────────────────────────────────────────────────────────────────────────────
✅ CRQ SUBMITTED AS DRAFT
─────────────────────────────────────────────────────────────────────────────
CHG #   : <CHG_NUMBER>  →  https://walmartglobal.service-now.com/...
Summary : <SHORT_DESCRIPTION>
GEOs    : <GEOS>
Jira    : <JIRA_KEY>
PRs     : <PR_URLS>
DAGs    : <DAG_IDS>
File    : ~/.wibey/knowledge/crqs/<SLUG>.txt

Preview opened in browser (HTML + ServiceNow tab)

⚠️  Auto-filled by ServiceNow: Risk · Impact · VP Approval chain
✅  Approver: Swaroop YS (s0s07p0) added automatically by snow_client.py
☐  Fill in ServiceNow: Planned start/end dates
☐  Submit for approval when ready (from ServiceNow UI)
─────────────────────────────────────────────────────────────────────────────
```

---

## Persistence guarantee

- Scripts vendored in `~/sarthi/scripts/crq/` → symlinked to `~/.wibey/crq/` by `setup.sh`
- Reference JSONs vendored in `~/sarthi/knowledge/crq-references/` → seeded by `setup.sh`
- `setup.sh` creates `~/.wibey/knowledge/crqs/` output dir
- Running `bash ~/sarthi/setup.sh` on any session/machine restores everything

## Optional cron — keep session fresh
```bash
# Refresh every 6 hours (session lasts ~8h):
0 */6 * * * python3 ~/.wibey/crq/extract_snow_session.py >> ~/.wibey/sarthi/snow-session-refresh.log 2>&1
```
