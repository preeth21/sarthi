---
name: "sar-fix"
key: "sar-fix"
description: "Interactive fix orchestrator for Pattern E (code_or_data_error) items from manual_review.json. Builds an envelope, calls sar-propose-fix to stage the fix, leads an interactive review loop with the user, then calls sar-pr to raise the Pull Request."
allowed-tools: [Read, Write, Bash]
mcp-tools:
  - mcp__sarthi-git__git_get_file           # verify staged fix exists in repo
  - mcp__sarthi-bq__bq_schema              # confirm schema during review if needed
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "active"
---

# sar-fix — Interactive Fix Orchestrator

## Purpose
Bridges the gap between `check.sh` detecting a Pattern E failure and a merged PR fix.
It is the user-facing entry point — invoked as `/sar-fix` after check.sh beeps.

Flow:
```
/sar-fix
  → build envelope from manual_review.json
  → call sar-propose-fix  (fetch source, generate fix, stage locally)
  → interactive review loop  (user approves or requests changes)
  → call sar-pr  (create branch → commit → open PR)
```

NOT wired into check.sh — this is always user-initiated.

## STRICT TOOL RULES
- ONLY use the MCP tools listed in `mcp-tools` above plus Read/Write/Bash
- NEVER use raw `git`, `gh`, `curl` CLI commands
- Sub-skills (sar-propose-fix, sar-pr) handle all GitHub and BQ MCP calls
- Bash: ONLY for reading JSON files, diffing, timestamps, mkdir
- Do NOT call sarthi-airflow-ops tools — this skill does not touch Airflow state

---

## STEP 1 — Load manual_review.json

```bash
cat ~/.wibey/agents/sarthi/manual_review.json
```

Filter items where `type == "code_or_data_error"` (Pattern E).

If empty: print and stop:
```
✅ No Pattern E items in manual_review.json — nothing to fix.
   Run check.sh first if you expect failures.
```

If multiple items: list them and ask user to pick:
```
Found <N> code/data error items:
  [1] DAG: <dag_id_1> | Task: <task_id_1> | <reason_short>
  [2] DAG: <dag_id_2> | Task: <task_id_2> | <reason_short>
Which item to fix? (enter number)
```

If one item: proceed automatically, print which item is being fixed.

---

## STEP 2 — Check for existing in-progress fix

```bash
KEY="<dag_id>__<task_id>__<run_id_short>"
ls ~/sarthi/knowledge/proposed-prs/$KEY/meta.json 2>/dev/null
```

If exists:
```bash
cat ~/sarthi/knowledge/proposed-prs/$KEY/meta.json
```

Based on `status`:
- `in_progress` → "A fix is already staged for this item. Resume review? (yes/no)"
  - yes → skip to STEP 4 (review loop)
  - no  → delete the folder and regenerate
- `approved`    → "Fix already approved. Raise the PR now? (yes/no)"
  - yes → skip to STEP 5 (call sar-pr)
- `done`        → "PR already raised: <pr_url>. Nothing to do."
  - stop
- `manual_required` → show manual instructions from summary.md and stop

---

## STEP 3 — Build envelope and call sar-propose-fix

Load the DAG entry from config.yaml matching the `dag_id`:

```bash
python3 -c "
import yaml, json, sys
with open('/Users/akiran/.wibey/sarthi/config.yaml') as f:
    cfg = yaml.safe_load(f)
dag_id = sys.argv[1]
for env in cfg.get('environments', []):
    for dag in env.get('dags', []):
        if dag.get('id') == dag_id:
            print(json.dumps({'env': env, 'dag': dag}))
            sys.exit(0)
print('null')
" "<dag_id>"
```

Build the envelope:
```json
{
  "source": {
    "channel": "manual_review",
    "id":      "<KEY>",
    "replyable": false
  },
  "intent": {
    "type":    "bugfix",
    "summary": "<item.reason>"
  },
  "context": {
    "manual_review_item": { ...full item... },
    "config_dag_entry":   { ...dag entry from config.yaml, or null if not found... }
  },
  "artifacts": [],
  "flags": {
    "dry_run":    false,
    "auto_reply": false
  }
}
```

Call sub-skill `sar-propose-fix` with this envelope.
Receive back updated envelope with `artifacts[0].status = "in_progress"`.

---

## STEP 4 — Interactive review loop

Read and show the staged fix:
```bash
# Show the diff
diff -u ~/sarthi/knowledge/proposed-prs/$KEY/original.* \
        ~/sarthi/knowledge/proposed-prs/$KEY/proposed.* \
  | head -80

# Show the summary
cat ~/sarthi/knowledge/proposed-prs/$KEY/summary.md
```

Present to user:
```
─────────────────────────────────────────────────────
  Proposed fix for: <dag_id> / <task_id>
─────────────────────────────────────────────────────
<diff output>
─────────────────────────────────────────────────────
<summary.md content>
─────────────────────────────────────────────────────

Options:
  [a] Approve — raise PR as-is
  [e] Edit    — describe the change you want
  [v] Verify  — re-check BQ schema for the proposed SQL
  [x] Abandon — discard this fix
```

### On "approve":
Update `meta.json` status → `"approved"` using Write tool.
Update `envelope.artifacts[0].status = "approved"`.
Proceed to STEP 5.

### On "edit — describe change":
User provides natural language change (e.g. "rename item_id to item_nbr, not remove it").
Re-read `original.<ext>` and `proposed.<ext>`.
Apply the user's requested change to `proposed.<ext>`.
Write updated `proposed.<ext>` using Write tool.
Regenerate `fix.diff`:
```bash
diff -u ~/sarthi/knowledge/proposed-prs/$KEY/original.* \
        ~/sarthi/knowledge/proposed-prs/$KEY/proposed.*  \
  > ~/sarthi/knowledge/proposed-prs/$KEY/fix.diff
```
Update `summary.md` to reflect the revised fix.
Loop back to top of STEP 4 — show updated diff.

### On "verify":
Re-call `mcp__sarthi-bq__bq_schema` with the table from `log_snippet`.
Show schema columns alongside the proposed SQL.
Ask: "Does the proposed fix use the correct column? (yes to approve / edit to change)"

### On "abandon":
```bash
# Update status only — keep files for reference
```
Update `meta.json` status → `"abandoned"`.
Print: "Fix abandoned. Files kept at ~/sarthi/knowledge/proposed-prs/<KEY>/"
Stop.

---

## STEP 5 — Call sar-pr

Call sub-skill `sar-pr` with updated envelope (artifacts[0].status = "approved").
Receive back envelope with PR URL in artifacts.

Print final confirmation (sar-pr prints its own output — no duplication needed).

---

## STEP 6 — Certify pattern for auto-resolve (optional, post-approval)

After a successful fix is approved and PR raised, offer:
```
This fix resolved a 'E-bq-column-not-found' pattern.
That pattern is NOT yet certified for auto-resolve (auto_resolve_certified: false).

Should sArthI propose this fix automatically next time without human review?
  [y] Yes — promote this pattern (update resolution-patterns.json)
  [n] No  — keep requiring human approval
```

If yes:
- Read `~/sarthi/knowledge/resolution-patterns.json`
- Find the matching `pattern_id` entry
- Update: `"auto_resolve_certified": true`, `"certified_by": "<user>"`, `"certified_at": "<date>"`
- Write back using Write tool
- Print: "✅ Pattern promoted. Future occurrences will propose fix automatically."

If no: skip silently.

⚠️ SAFETY: NEVER set `auto_resolve: true` — that controls routing to actions.json for
executor.py (Airflow ops). Code fixes (resolution_type=code_fix) ALWAYS go through
manual_review.json + sar-fix, regardless of certification. Certification only means
"propose the fix automatically" — human still approves before PR is raised.

---

## USAGE EXAMPLES

```
/sar-fix                          # fix first Pattern E item in manual_review.json
/sar-fix review                   # same — alias
/sar-fix list                     # list all items in manual_review.json (all patterns)
```
