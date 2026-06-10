---
name: "sar-fix"
key: "sar-fix"
description: "Interactive fix orchestrator for ALL manual_review.json items (Pattern D, E, F). Routes by type: Pattern E → code fix via sar-propose-fix + sar-pr. Pattern F (hudi_sync_failure) → deep investigation via child DAG + Spark driver log + definitive GCS repair. Pattern D → GCS state check + Airflow action. Investigation order: Airflow log → Spark/env log → code fix (last resort)."
allowed-tools: [Read, Write, Bash]
mcp-tools:
  - mcp__sarthi-airflow-read__get_task_instances   # fetch child DAG failed tasks
  - mcp__sarthi-airflow-read__get_task_log         # fetch child DAG / Spark task log
  - mcp__sarthi-airflow-read__get_dag_runs         # find child DAG run_id
  - mcp__sarthi-gcp__dataproc_fetch_driver_log     # fetch Spark driver log from GCS
  - mcp__sarthi-gcp__gcs_ls                        # list Hudi metadata partition files
  - mcp__sarthi-gcp__gcs_stat                      # confirm file size (corrupt = < 100 bytes)
  - mcp__sarthi-gcp__hudi_timeline                 # check Hudi commit history
  - mcp__sarthi-airflow-ops__clear_task_with_deps  # re-queue after repair
  - mcp__sarthi-airflow-ops__set_dag_run_state     # re-queue parent DAG run
  - mcp__sarthi-git__git_get_file                  # verify staged fix exists in repo
  - mcp__sarthi-bq__bq_schema                     # confirm schema during review if needed
metadata:
  author: "akiran"
  version: "2.0.0"
  part-of: "sarthi"
  status: "active"
---

# sar-fix — Interactive Fix Orchestrator

## Purpose
User-initiated resolution skill for ALL items in manual_review.json.
NOT wired into check.sh — always invoked manually after check.sh writes manual_review.json.

Investigation order (ALWAYS follow this — code fix is LAST):
```
1. Airflow task log (already in manual_review item)
2. Child DAG task log (if operator == TriggerDagRunOperator)
3. Spark driver log from GCS (if Dataproc job failure found)
4. Environment/infrastructure repair (GCS delete, metadata repair, cluster action)
5. Code fix via sar-propose-fix + sar-pr  ← LAST RESORT only
```

Route by type:
```
code_or_data_error  →  STEP E path (sar-propose-fix → review → sar-pr)
hudi_sync_failure   →  STEP F path (child DAG → Spark log → GCS repair → clear task)
dependency_failure  →  STEP D path (gcs_stat → clear if present / wait if absent)
```

## STRICT TOOL RULES
- ONLY use the MCP tools listed in `mcp-tools` above plus Read/Write/Bash
- NEVER use raw `git`, `gh`, `curl` CLI commands
- Bash: for reading JSON files, diffing, timestamps, mkdir, and `gsutil rm` (GCS repair, after user approval)
- Sub-skills (sar-propose-fix, sar-pr) handle all GitHub MCP calls for code fixes

---

## STEP 1 — Load manual_review.json and select item

```bash
cat ~/.wibey/agents/sarthi/manual_review.json
```

Show ALL items (not just Pattern E):
```
Found <N> items in manual_review.json:
  [1] [E] DAG: <dag_id> | Task: <task_id> | <reason_short>
  [2] [F] DAG: <dag_id> | Task: <task_id> | <reason_short>
  [3] [D] DAG: <dag_id> | Task: <task_id> | <reason_short>
Which item to fix? (enter number, or 'list' to see full details)
```

If empty, print and stop:
```
✅ No items in manual_review.json — nothing to fix.
   Run check.sh first if you expect failures.
```

Route the selected item:
- `type == "code_or_data_error"` → go to STEP 2 then STEP E
- `type == "hudi_sync_failure"`  → go to STEP 2 then STEP F
- `type == "dependency_failure"` → go to STEP 2 then STEP D

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

## STEP F — Hudi sync / metadata corruption investigation and repair

**Only reached when `type == "hudi_sync_failure"`.**

### F1 — Resolve child DAG indirection (if operator == TriggerDagRunOperator)

When the Airflow task log only says "child DAG <child_dag_id> failed with state failed",
the real error is in the child DAG. Follow the chain:

```
Call mcp__sarthi-airflow-read__get_dag_runs:
  env_name: <same as parent>
  dag_id:   <child_dag_id>   ← extract from log: "child DAG <child_dag_id> failed"
  limit:    3

Find the run_id whose execution_date is closest to the parent run's execution_date.
Save as child_run_id.
```

If operator is NOT TriggerDagRunOperator (task is itself the Hudi/Spark task):
- Skip F1, use the item's dag_id/run_id/task_id directly → go to F2

### F2 — Find the failed Spark/Hudi task in the child DAG

```
Call mcp__sarthi-airflow-read__get_task_instances:
  env_name:   <env>
  dag_id:     <child_dag_id>
  dag_run_id: <child_run_id>

Filter: state == "failed"
Pick the first failed task — typically a DataprocSubmitJobOperator or SparkSubmitOperator.
Save as spark_task_id.
```

### F3 — Fetch the Spark task log

```
Call mcp__sarthi-airflow-read__get_task_log:
  env_name:   <env>
  dag_id:     <child_dag_id>
  dag_run_id: <child_run_id>
  task_id:    <spark_task_id>
  try_number: 1
```

Scan the log for the deepest exception:
- `NumberFormatException: For input string: ""` + `getFileVersionFromLog` → **F-hudi-metadata-corrupt** — go to F4
- `HoodieException` / `InstantNotFoundException` / `CONCURRENT_WRITES` → **F-hudi-sync** — go to F6
- `java.lang.OutOfMemoryError` / `ExecutorLostFailure` → **transient Spark** — go to F7
- Other Spark exception → show the exception, ask user to classify, stop

Also extract from the Spark log:
- Driver log GCS path (pattern: `gs://.../.../driveroutput` or similar in "applicationReport")
- Hudi table GCS path (pattern: `gs://<bucket>/<path>/.hoodie/`)

### F4 — Deep investigation: F-hudi-metadata-corrupt

When the error is `NumberFormatException: For input string: ""` in `getFileVersionFromLog`:

**F4a — Fetch driver log for exact file path (if GCS path found in step F3):**
```
Call mcp__sarthi-gcp__dataproc_fetch_driver_log:
  gcs_path: <driver_log_gcs_path>
```
Scan for the full stack trace — look for the corrupt filename in the exception:
e.g. `ERROR HoodieLogFile: Failed to get log version from file: .log.`

**F4b — List the Hudi metadata partition:**
```
Call mcp__sarthi-gcp__gcs_ls:
  path: gs://<bucket>/<table_path>/.hoodie/metadata/<partition>/

If metadata path is unknown, try common partitions:
  gs://<bucket>/<table_path>/.hoodie/metadata/record_index/
  gs://<bucket>/<table_path>/.hoodie/metadata/files/
  gs://<bucket>/<table_path>/.hoodie/metadata/column_stats/
```

**F4c — Identify the corrupt file:**
A corrupt log filename has an EMPTY version segment. Normal: `.log.1_0-X-Y`. Corrupt: `.log.` or `.log.._X-Y` (version part is empty string or missing integer).

**F4d — Confirm it is small:**
```
Call mcp__sarthi-gcp__gcs_stat:
  path: gs://<bucket>/<table_path>/.hoodie/metadata/<partition>/<candidate_filename>
```
If size < 100 bytes → confirmed corrupt. Show to user:
```
─────────────────────────────────────────────────────
  Corrupt Hudi metadata file identified:
  Path: gs://<full_path>/<filename>
  Size: <N> bytes  ← should be 0–100 for a corrupt file
  Error: NumberFormatException: For input string: "" in getFileVersionFromLog
  
  This file has an empty version string in its log filename.
  Hudi cannot parse it, causing all reads of this metadata partition to fail.

  Safe to delete: YES (Hudi metadata table self-heals on next write)
  ⚠️  NEVER delete from .hoodie/timeline/ or .hoodie/metadata/.files/
  
  Proposed action:
    gsutil rm gs://<full_path>/<filename>
    Then: clear_task_with_deps on <spark_task_id> + re-queue <parent_dag_id>

  Approve? [y/n]
─────────────────────────────────────────────────────
```

**F4e — On approval, execute:**
```bash
gsutil rm "gs://<full_path>/<corrupt_filename>"
```

Then call:
```
mcp__sarthi-airflow-ops__clear_task_with_deps:
  env_name: <env>
  dag_id:   <child_dag_id>
  run_id:   <child_run_id>
  task_id:  <spark_task_id>

mcp__sarthi-airflow-ops__set_dag_run_state:
  env_name: <env>
  dag_id:   <parent_dag_id>
  run_id:   <parent_run_id>
  state:    queued
```

Print:
```
✅ Corrupt file deleted. Task cleared. Parent DAG re-queued.
   Monitor: check.sh should report this DAG clean on next run.
```
Stop.

### F5 — If corrupt file not found or size >= 1KB

The file may not be the cause, or a different metadata partition is affected.
Show what was found and ask user:
```
Could not confirm corrupt file. Checked:
  <list of files checked with sizes>

Options:
  [1] Check a different metadata partition path (provide path)
  [2] Check hudi_timeline for commit state
  [3] Escalate — needs manual inspection
```

On [2]: Call `mcp__sarthi-gcp__hudi_timeline` on `<hudi_table_uri>`. Show result.
On [3]: Print instructions for manual GCS inspection and stop.

### F6 — Hudi-sync (concurrent writes / dirty markers)

When error is `HoodieException` / `InstantNotFoundException` / dirty markers:

```
Call mcp__sarthi-gcp__hudi_timeline:
  table_uri: <hudi_table_uri>
```

- Last commit < 24h ago AND no dirty markers → safe to clear + retry:
  ```
  mcp__sarthi-airflow-ops__clear_task_with_deps (spark_task_id in child DAG)
  mcp__sarthi-airflow-ops__set_dag_run_state queued (parent DAG run)
  ```
- Dirty markers present OR last commit > 24h → show timeline summary and instruct:
  ```
  Hudi table has dirty markers or stale commit.
  Manual cleanup required before retry:
    gsutil rm gs://<table>/.hoodie/.temp/<marker_files>
  Then clear the task.
  Approve marker cleanup? [y/n]
  ```

### F7 — Transient Spark failure

OOM / ExecutorLostFailure / resource exhaustion. No repair needed — just retry:
```
mcp__sarthi-airflow-ops__clear_task_with_deps (spark_task_id in child DAG)
mcp__sarthi-airflow-ops__set_dag_run_state queued (parent DAG run)
```
Print: "✅ Transient Spark failure — task cleared and re-queued."
Stop.

---

## STEP D — GCS sensor dependency check

**Only reached when `type == "dependency_failure"`.**

```
Call mcp__sarthi-gcp__gcs_stat:
  path: <item.gcs_path>
```

- File PRESENT (size > 0) → stale sensor, safe to clear:
  ```
  mcp__sarthi-airflow-ops__clear_task_with_deps
  mcp__sarthi-airflow-ops__set_dag_run_state queued
  ```
  Print: "✅ Done file present — sensor timing issue. Task cleared."

- File ABSENT (not found) → upstream not delivered:
  Print:
  ```
  ❌ Done file still absent: <gcs_path>
  No Airflow action taken — clearing would just re-fail.
  Wait for upstream to deliver the file, then run /sar-fix again.
  ```

- gcs_path is null (item.gcs_path == null) → cannot check:
  Print: "gcs_path not in manual_review item — check config.yaml gcs_done_file for <dag_id>"
  Show config.yaml lookup instructions. Stop.

---

## STEP E — Code/data fix path (Pattern E only, code fix is LAST RESORT)

**Only reached when `type == "code_or_data_error"` and `operator != "TriggerDagRunOperator"`.**

If `operator == "TriggerDagRunOperator"`: re-route to STEP F (code errors in child DAGs need
deep investigation first — the real error may be Spark/env, not code).

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
/sar-fix                          # show all manual_review.json items, user picks one
/sar-fix list                     # list all items with pattern type
```

## PATTERN ROUTING SUMMARY

```
manual_review.json item
  │
  ├── type == "code_or_data_error"
  │     └── operator == TriggerDagRunOperator? → STEP F (investigate child DAG first)
  │     └── otherwise                          → STEP E (code fix: sar-propose-fix → sar-pr)
  │
  ├── type == "hudi_sync_failure"
  │     └── STEP F1 (child DAG) → F2 (spark task) → F3 (spark log)
  │           ├── NumberFormatException+getFileVersionFromLog → F4 (GCS delete corrupt file)
  │           ├── HoodieException/dirty markers               → F6 (hudi_timeline + marker cleanup)
  │           └── OOM/transient                               → F7 (clear + retry)
  │
  └── type == "dependency_failure"
        └── STEP D (gcs_stat → clear if present / wait if absent)
```

## KEY INVARIANTS
- Code fix (sar-propose-fix → PR) is ALWAYS the last option, never the first
- investigate.md never fetches Spark logs — that's sar-fix's job (user-initiated, not on hot path)
- `gsutil rm` requires explicit user approval — always show exact path and size before running
- Child DAG indirection is bounded: at most 2 hops (parent → child → Spark task). No recursive chaining.
- dag_class in config.yaml (e.g. "simulator") is metadata only — NEVER a branch condition in this skill
