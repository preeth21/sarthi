---
name: "sar-propose-fix"
key: "sar-propose-fix"
description: "Reads a manual_review.json code_or_data_error item, fetches the original source from GEC GitHub, generates a minimal targeted fix, validates it against BigQuery schema, and stages it locally under ~/sarthi/knowledge/proposed-prs/."
allowed-tools: [Read, Write, Bash]
mcp-tools:
  - mcp__sarthi-git__git_get_file           # fetch original source from GEC GitHub
  - mcp__sarthi-git__git_search_code        # locate file by dag_id / task keyword
  - mcp__sarthi-git__git_list_dir           # browse repo structure
  - mcp__sarthi-bq__bq_schema              # validate column fix against real BQ table
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "active"
---

# sar-propose-fix — Targeted Code Fix Proposer

## Purpose
Given a `code_or_data_error` (Pattern E) item from `manual_review.json`, this skill
fetches the original failing source file from GEC GitHub, generates a minimal fix,
validates it against the real BigQuery schema, and writes a staged fix under
`~/sarthi/knowledge/proposed-prs/<key>/` with status `in_progress`.

Operates on RESOURCE FILES in GEC GitHub (SQL, config YAML, Python logic files).
DAG Python files that are image-baked or not in Git fall back to manual fix guidance.

## STRICT TOOL RULES
- ONLY use the MCP tools listed in `mcp-tools` above plus Read/Write/Bash
- NEVER use raw `git`, `gh`, `curl` CLI commands
- NEVER access external URLs directly
- Bash: ONLY for local diff generation (`diff -u`), mkdir, timestamp generation
- All GitHub operations → sarthi-git MCP tools only
- All BQ validation → sarthi-bq MCP tools only

---

## STEP 1 — Receive envelope

Expect an `envelope` dict (passed by sar-fix) with:
```json
{
  "source": {"channel": "manual_review", "id": "<key>"},
  "intent": {"type": "bugfix", "summary": "<reason from manual_review>"},
  "context": {
    "manual_review_item": { ...full item from manual_review.json... },
    "config_dag_entry":   { ...matching DAG entry from config.yaml, or null... }
  },
  "artifacts": [],
  "flags": {"dry_run": false}
}
```

Extract from envelope:
- `item`       = `envelope.context.manual_review_item`
- `dag_entry`  = `envelope.context.config_dag_entry` (may be null)
- `dag_id`     = `item.dag_id`
- `task_id`    = `item.task_id`
- `run_id`     = `item.run_id`
- `log`        = `item.log_snippet`
- `reason`     = `item.reason`

---

## STEP 2 — Look up resolution pattern

Read `~/sarthi/knowledge/resolution-patterns.json`.
Match the item's `log` and `reason` against each pattern's `match_criteria` (substring match).
Identify the `pattern_id` (e.g. `E-bq-column-not-found`).

Tag the envelope:
```json
{
  "context": {
    "pattern_id":             "<matched pattern_id or null>",
    "auto_resolve_certified": <bool from registry>,
    "proposed_resolution":    "<proposed_resolution text from registry, if set>"
  }
}
```

If no pattern matches: `pattern_id = "E-unknown"`, `auto_resolve_certified = false`.

Use `proposed_resolution` from the registry to guide Step 5 fix generation if set.

---

## STEP 3 — Locate the source file

### 3a — Check config_dag_entry for source_repo
If `dag_entry` is set and `dag_entry.source_repo` is set:
- Parse `org`, `repo` from `source_repo` (format: `"org/repo"`)
- Use `source_path` from `dag_entry` as the directory to browse
- Call `mcp__sarthi-git__git_list_dir` with `org`, `repo`, `path=source_path`
- Identify the most likely file based on `task_id` and keywords in `log`
- NOTE: `dag_class: "simulator"` in dag_entry is reporting metadata only — follow exactly the same code path as any real DAG

### 3b — Search by keyword if no source_repo
If `dag_entry` has no `source_repo`:
- Extract a search term from `log` — SQL table name (backtick-quoted), function name, or column name
- Call `mcp__sarthi-git__git_search_code` with `org="WITDnA"`, the team's default repo,
  and `query=<extracted term>`
- Pick the best result (highest score, .sql or .py file)

### 3c — No git source fallback
If `dag_entry.deployment_type` is `"image-baked"` or no file found after search:
```
⚠️  No git-tracked source file found for this DAG.
    DAG:    <dag_id>
    Task:   <task_id>
    Error:  <reason>
    Action: Locate the SQL/config file manually, apply the fix, and redeploy.
```
Write `meta.json` with `status: "manual_required"` and stop.

---

## STEP 4 — Fetch original file

Call `mcp__sarthi-git__git_get_file`:
```
org:  <org>
repo: <repo>
path: <located file path>
ref:  main
```

Store the returned `sha` field — this is the blob SHA required by sar-pr when
committing the updated file. Loss of this sha causes a 422 error.

---

## STEP 5 — Validate with BigQuery schema (sql_error class)

If `log` contains a BQ table reference (backtick-quoted `project.dataset.table`):
1. Extract `project`, `dataset`, `table` from the log
2. Call `mcp__sarthi-bq__bq_schema` with `table`, `dataset`, `project`
3. Compare the failing column name (from log) against returned schema columns
4. Determine: renamed, dropped, or misspelled?
5. Record the correct column name or removal decision

If no BQ table in log: skip this step, proceed with log analysis only.

---

## STEP 5 — Generate the minimal fix

Analyse original content + log + reason + BQ schema finding together.
Generate a ONE targeted change — no rewrites, no reformatting:
- Correct the column name / SQL expression
- Remove the invalid reference if column was dropped
- Add a comment above the changed line:
  `# sArthI fix: <one-line reason> (<YYYY-MM-DD>)`
- Preserve all existing indentation, style, and surrounding code exactly

---

## STEP 6 — Stage locally

```bash
KEY="<dag_id>__<task_id>__<run_id_short>"
# run_id_short = first 20 chars of run_id, replace / and : with -
mkdir -p ~/sarthi/knowledge/proposed-prs/$KEY
```

Write these files using the Write tool:

**`original.<ext>`** — exact content from Step 3 (unchanged)

**`proposed.<ext>`** — fixed content from Step 5

**`summary.md`** — structured markdown:
```markdown
# Fix Summary: <dag_id> / <task_id>

## What broke
<reason from manual_review.json>

## Error
<log_snippet>

## Root cause
<analysis — column dropped/renamed/misspelled + BQ schema evidence>

## Fix applied
<one-line description of the change>

## Files changed
- `<source_repo>/<source_path>` — <what changed>

## BQ schema validation
<result from bq_schema or "N/A — no BQ table in log">
```

**`meta.json`**:
```json
{
  "key":                    "<KEY>",
  "dag_id":                 "<dag_id>",
  "task_id":                "<task_id>",
  "run_id":                 "<run_id>",
  "env_name":               "<env_name>",
  "dag_class":              "<dag_class from config or null>",
  "source_repo":            "<org/repo>",
  "source_path":            "<path in repo>",
  "file_sha":               "<blob sha from git_get_file>",
  "pattern_id":             "<matched pattern_id>",
  "auto_resolve_certified": false,
  "status":                 "in_progress",
  "created":                "<ISO timestamp>",
  "approved_at":            null,
  "pr_url":                 null
}
```

Generate the diff:
```bash
diff -u ~/sarthi/knowledge/proposed-prs/$KEY/original.<ext> \
        ~/sarthi/knowledge/proposed-prs/$KEY/proposed.<ext> \
  > ~/sarthi/knowledge/proposed-prs/$KEY/fix.diff
```

---

## STEP 7 — Update envelope and return

Add to `envelope.artifacts[]`:
```json
{
  "type":         "proposed-fix",
  "key":          "<KEY>",
  "local_path":   "~/sarthi/knowledge/proposed-prs/<KEY>/",
  "source_repo":  "<org/repo>",
  "source_path":  "<path in repo>",
  "file_sha":     "<blob sha>",
  "status":       "in_progress"
}
```

Print summary to user:
```
✅ Fix staged:
   Path:     ~/sarthi/knowledge/proposed-prs/<KEY>/
   Original: original.<ext>
   Proposed: proposed.<ext>
   Diff:     fix.diff
   Status:   in_progress

Review with /sar-fix
```

Return updated envelope.
