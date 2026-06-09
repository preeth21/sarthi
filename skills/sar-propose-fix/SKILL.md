---
name: "sar-propose-fix"
key: "sar-propose-fix"
description: "sArthI's code repair specialist. Given investigation findings, locates the relevant pipeline file (DAG Python, YAML config, SQL template), generates the minimal targeted fix, and writes it to knowledge/proposed-prs/ for sar-pr to commit. Does NOT apply the fix directly — sar-pr handles all git operations."
allowed-tools: [Read, Glob, Grep, Write]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "placeholder"
---

# sar-propose-fix — Targeted Code Fix Proposer

## Purpose
When investigation reveals a code or config defect, sArthI generates a precise,
minimal fix — not a rewrite. This skill reads the relevant file, understands the
exact change needed, and writes a proposed diff that `sar-pr` can commit and push.

## Status: PLACEHOLDER

## TODO — implement:

- [ ] Read `envelope.context.investigation.root_cause_hypothesis`
- [ ] Locate the relevant file:
  - Pipeline YAML: `<repo>/pipelines/<dag_id>.yaml` or similar
  - DAG Python: `<repo>/dags/<dag_id>.py`
  - SQL template: `<repo>/sql/<template>.sql`
  - Config file: `<repo>/config/<env>.yaml`
- [ ] Generate the minimal fix — one change only, no unrelated modifications
- [ ] Write proposed diff to `~/.wibey/knowledge/proposed-prs/<jira-key>/`
- [ ] Populate `envelope.artifacts[]` with the proposed change

## Fix generation principles
- Minimal blast radius — change only what root cause requires
- Preserve existing code style, indentation, and patterns
- Include a comment explaining WHY the change was made (reference Jira key)
- If ambiguous: propose two options and ask user which to apply

## File output format
```
~/.wibey/knowledge/proposed-prs/<jira-key>/
  ├── fix.diff          # unified diff format
  ├── fix-summary.md    # what changed and why
  └── files/            # full modified file copies (for sar-pr to apply)
      └── <filename>
```

## Expected inputs
- `envelope` with `intent.type = "bugfix"`
- `envelope.context.investigation` populated by sar-investigate

## Expected output
- `envelope.artifacts` updated with:
```json
{
  "type": "proposed-fix",
  "jira_key": "<KEY>",
  "path": "~/.wibey/knowledge/proposed-prs/<jira-key>/",
  "diff": "<unified diff>",
  "files_modified": ["<path/to/file>"]
}
```
