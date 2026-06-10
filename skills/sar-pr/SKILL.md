---
name: "sar-pr"
key: "sar-pr"
description: "Takes a staged proposed-fix from sar-propose-fix, creates a branch, commits the fixed file via sarthi-git MCP (no local clone), and raises a GEC GitHub Pull Request. Updates meta.json status to 'done'. User merges the PR manually."
allowed-tools: [Read, Write, Bash]
mcp-tools:
  - mcp__sarthi-git__git_create_branch           # create fix branch from main
  - mcp__sarthi-git__git_create_or_update_file   # commit the fixed file (sha-aware)
  - mcp__sarthi-git__git_create_pr               # open the PR
  - mcp__sarthi-git__git_get_file                # re-fetch current blob sha (staleness check)
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "active"
---

# sar-pr — Pull Request Creator

## Purpose
Takes an approved proposed-fix from `sar-propose-fix` (via envelope.artifacts),
creates a feature branch in GEC GitHub, commits the fixed file using the GitHub
Contents API (no local clone needed), and opens a Pull Request.

The user reviews and merges the PR manually in GEC GitHub.
This skill NEVER merges — it only opens the PR.

## STRICT TOOL RULES
- ONLY use the MCP tools listed in `mcp-tools` above plus Read/Write/Bash
- NEVER use raw `git`, `gh`, `curl` CLI commands — ALL git ops via sarthi-git MCP only
- Bash: ONLY for reading/writing meta.json and generating timestamps
- NO local git clone, checkout, add, commit, or push
- NO direct GitHub web UI navigation

---

## STEP 1 — Receive envelope

Expect `envelope` from sar-fix (post-approval):
```json
{
  "context": {
    "manual_review_item": { ...item... },
    "config_dag_entry":   { ...entry... }
  },
  "artifacts": [
    {
      "type":        "proposed-fix",
      "key":         "<KEY>",
      "local_path":  "~/sarthi/knowledge/proposed-prs/<KEY>/",
      "source_repo": "<org/repo>",
      "source_path": "<file path in repo>",
      "file_sha":    "<blob sha>",
      "status":      "approved"
    }
  ]
}
```

Read artifact where `type == "proposed-fix"` and `status == "approved"`.
If none found: stop — "No approved fix in envelope. Run /sar-fix first."

Load local files using Read tool:
- `~/sarthi/knowledge/proposed-prs/<KEY>/meta.json`
- `~/sarthi/knowledge/proposed-prs/<KEY>/proposed.<ext>`
- `~/sarthi/knowledge/proposed-prs/<KEY>/summary.md`

---

## STEP 2 — Determine branch name

Format: `fix/sarthi-<dag_slug>-<YYYYMMDD>`
- `dag_slug` = last hyphen-segment of `dag_id`, lowercased, max 30 chars
- Example: `fix/sarthi-et360-bq-data-load-20260610`
- If > 60 chars total: truncate `dag_slug`

---

## STEP 3 — Create the branch

Parse `org` and `repo` from `meta.json.source_repo` (format: `"org/repo"`).

Call `mcp__sarthi-git__git_create_branch`:
```
org:      <org>
repo:     <repo>
branch:   <branch from Step 2>
from_ref: main
```

On `branch_exists` error: append `-2`, `-3` and retry (max 3 attempts).

---

## STEP 4 — Staleness check on blob sha

The `file_sha` in `meta.json` was captured at propose-fix time. If the file on
main has since been updated by someone else, that sha is stale and the PUT will fail.

Call `mcp__sarthi-git__git_get_file`:
```
org:  <org>
repo: <repo>
path: <source_path>
ref:  main
```

If returned `sha` differs from `meta.json.file_sha`:
```
⚠️  File updated on main since fix was staged.
    Staged sha:  <meta sha>
    Current sha: <fresh sha>
    Regenerate the fix? (yes to re-run /sar-fix, no to proceed with fresh sha)
```
Use the FRESH sha for Step 5 regardless.

---

## STEP 5 — Commit the fixed file

Call `mcp__sarthi-git__git_create_or_update_file`:
```
org:     <org>
repo:    <repo>
path:    <source_path>
content: <full content of proposed.<ext>>
message: "fix(<dag_slug>): <first-line fix description from summary.md>

Auto-proposed by sArthI. Review and merge manually.
DAG: <dag_id>
Task: <task_id>"
branch:  <branch from Step 3>
sha:     <fresh sha from Step 4>
```

On `sha_required_or_mismatch`: re-fetch sha once and retry.

---

## STEP 6 — Open the Pull Request

Build PR body from `summary.md` sections:
```markdown
## What broke
<from summary.md>

## Fix applied
<from summary.md>

## BQ schema validation
<from summary.md or "N/A">

## Review checklist
- [ ] Fix is correct and minimal
- [ ] No unrelated changes  
- [ ] Tested in DEV after merge

---
🤖 Auto-proposed by sArthI | DAG: `<dag_id>` | Task: `<task_id>`
```

Call `mcp__sarthi-git__git_create_pr`:
```
org:   <org>
repo:  <repo>
title: "fix(<dag_slug>): <reason — max 60 chars>"
body:  <PR body above>
head:  <branch from Step 3>
base:  main
```

---

## STEP 7 — Update meta.json and envelope

Read `~/sarthi/knowledge/proposed-prs/<KEY>/meta.json`.
Update fields and write back using Write tool:
```json
{
  "status":      "done",
  "pr_url":      "<url from git_create_pr>",
  "approved_at": "<ISO timestamp>"
}
```

Add to `envelope.artifacts[]`:
```json
{
  "type":   "pr",
  "url":    "<PR url>",
  "branch": "<branch>",
  "key":    "<KEY>"
}
```

Print:
```
✅ Pull Request created:
   <PR url>

   Branch: <branch>
   File:   <source_repo>/<source_path>

   ➡️  Review the diff in GEC GitHub and merge when ready.
      sArthI will NOT auto-merge.
```

Return updated envelope.
