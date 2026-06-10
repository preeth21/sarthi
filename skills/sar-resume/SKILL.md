---
name: "sar-resume"
key: "sar-resume"
description: "sArthI development context loader. Call at the start of any new Wibey session to restore full sArthI project awareness — architecture, file map, skill status, current dev state, and known issues. Eliminates the need to re-read files from scratch."
allowed-tools: [Read, Bash]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "active"
---

# sar-resume — sArthI Development Context Loader

## Purpose
Loads complete sArthI project context into a fresh Wibey session so development
can resume immediately without re-reading dozens of files or reconstructing state.
Run this at the start of any new session working on sArthI.

## Usage
```
/sar-resume
```
Or via /sarthi: `/sarthi resume`

---

## STEP 1 — Read project state

Read these files and build context (do NOT print raw content — synthesise):

```
Read ~/sarthi/knowledge/known-issues.json
Read ~/sarthi/knowledge/team.json
Read ~/sarthi/knowledge/environments.json
```

Then check dev-log for latest findings:
```bash
ls -t ~/sarthi/knowledge/dev-log/*.md 2>/dev/null | head -5
```
Read the most recent dev-log file (latest by date).

---

## STEP 2 — Check runtime state

```bash
# Most recent check.sh run
ls -t ~/.wibey/agents/sarthi/logs/run-*.log 2>/dev/null | head -1

# Current state files
for f in report.json actions.json manual_review.json; do
  path="~/.wibey/agents/sarthi/$f"
  if [ -f "$path" ]; then
    echo "=== $f ==="
    cat "$path"
  else
    echo "=== $f: not present ==="
  fi
done

# Session freshness
stat -f "%Sm %N" -t "%Y-%m-%d %H:%M" ~/.wibey/sarthi/cookies.txt 2>/dev/null
stat -f "%Sm %N" -t "%Y-%m-%d %H:%M" ~/.wibey/sarthi/session.json 2>/dev/null
```

---

## STEP 3 — Synthesise and print context report

Print a compact context block:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  sArthI Dev Context — <today's date>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROJECT LAYOUT
  ~/sarthi/                     → source repo (setup.sh, mcp/, skills/, knowledge/)
  ~/.wibey/agents/sarthi/       → runtime agent (check.sh, fetcher.py, investigate.md, executor.py)
  ~/.wibey/sarthi/              → runtime data (config.yaml, cookies.txt, session.json)
  ~/.wibey/sarthi/reports/      → HTML monitor reports
  ~/.wibey/sarthi/history/ops.jsonl  → ops audit log

SKILL STATUS
  ✅ Active:      sar-monitor, sar-setup, sar-crq, sar-fix, sar-propose-fix, sar-pr
                  sar-azure, sar-concord, sar-kafka, sar-looper, sar-triagent,
                  sar-wcnp-ops, sar-resume, sar-sync, sar-local-mcp
  🔧 Partial:     sar-inbox (Slack TODO), sar-reply (Teams thread TODO)
  ⏳ Placeholder: sar-investigate, sar-resolve, sar-plan, sar-answer,
                  sar-feature-spec, sar-scaffold, sar-summary

FIX PIPELINE (user-initiated, post check.sh beep)
  /sar-fix
    → sar-propose-fix  (fetch source via sarthi-git, generate fix, bq_schema validate)
    → interactive review loop  (user approves / edits)
    → sar-pr  (git_create_branch + git_create_or_update_file + git_create_pr)
  Fix stored at: ~/sarthi/knowledge/proposed-prs/<dag_id>__<task_id>__<run_id>/
  Status flow:   in_progress → approved → done | manual_required | abandoned

MCP SERVERS (13 registered, all ~/sarthi/mcp/)
  sarthi-airflow-read   read-only DAG/task/log queries          auth: cookies.txt
  sarthi-airflow-ops    clear_task, trigger, set_state          ops_allowed:true envs only
  sarthi-airflow-auth   headless Playwright session refresh     ~84s
  sarthi-snow           CRQ/incident/RITM tools                 auth: ~/.wibey/snow-session.json
  sarthi-snow-auth      ServiceNow session refresh              PingFed SSO
  sarthi-snow-ad        AD group request automation             ServiceNow portal
  sarthi-msgraph        email + Teams (10 tools, cron-safe)     auth: msgraph_tokens.json
  sarthi-gcp            GCS ls/cat/stat, Dataproc, Hudi         gcloud ADC
  sarthi-bq             BigQuery SELECT (1GB cap)               gcloud ADC
  sarthi-git            9 tools: read + write (v1.1.0)          gh CLI keyring
                          NEW: git_create_branch, git_create_or_update_file
  sarthi-gsuite         AD group lookups (principal↔groups)     gcloud ADC
  sarthi-slack          Slack read/post (6 tools)               Playwright SSO
  sarthi-wcnp           Kubernetes/WCNP ops                     sledge

AUTONOMOUS PIPELINE (check.sh)
  Stage 1: fetcher.py       → calls list_dag_runs_batch → writes report.json
  Stage 2: investigate.md   → AI classifies failures → writes actions.json + manual_review.json
  Stage 3: executor.py      → executes actions from actions.json
  Patterns: A=transient, B=dataproc-deleted, C=teardown, D=gcs-sensor, E=code/data, F=hudi
  NOTE: investigate.md is a HEADLESS agent prompt in ~/.wibey/agents/sarthi/ (not a skill)

SIMULATOR (for testing the pipeline)
  DAG:  INTLDLDAT-ET360-SIMULATOR-TEST-DAG  ENV: ET360-CL-DEV
  GCS:  gs://wmt-intl-dp-etrans-360-dev-resources/ET360/s0d0gak/pipeline-resources/simulator-test/sim.done
  Run:  python3 ~/.wibey/agents/sarthi/simulator.py --scenario <NAME>
  Scenarios: gcs_absent✅  gcs_present✅(fixed Jun8)  sql_error✅(validated Jun10)
             timeout⏳  consecutive⏳
  Fixtures: ~/sarthi/tests/simulator-fixtures/  (SQL fixtures for sar-fix end-to-end testing)
  NOTE: _sensor_fn ignores fail_at_task conf — only _make_task_fn tasks respond to it.
        gcs_present uses sim.task_a (not sim.sensor) for injected failure.

KNOWN ISSUES
  ISSUE-001: msgraph asks login every session → sar-setup Step 3 auto-migrates tokens
  ISSUE-002: ServiceNow 401 → sarthi-snow-auth auto-refreshes
  ISSUE-003: Airflow session_expired → call mcp__sarthi-airflow-auth__refresh_session
  ISSUE-004: MCP servers missing → bash ~/sarthi/setup.sh
  ISSUE-005: bigquery-explorer missing → sar-setup Step 2 installs
  ISSUE-006: msgraph blocks cron → sarthi-msgraph MCP never calls auth.ts login

RUNTIME STATE
  <insert from STEP 2 checks>

LATEST DEV LOG
  <insert from most recent dev-log file>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## STEP 4 — Check if Airflow session is fresh

```bash
COOKIE_AGE=$(python3 -c "
import os, datetime
path = os.path.expanduser('~/.wibey/sarthi/cookies.txt')
if os.path.exists(path):
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    age_h = (datetime.datetime.now() - mtime).total_seconds() / 3600
    print(f'{age_h:.1f}')
else:
    print('missing')
" 2>/dev/null)
echo "Airflow session age: ${COOKIE_AGE}h"
```

If age > 8h or missing:
```
⚠️  Airflow session is stale (${COOKIE_AGE}h old).
    To refresh before running simulator or check.sh:
    Use: mcp__sarthi-airflow-auth__refresh_session
    Or:  python3 ~/sarthi/scripts/headless-refresh.py  (~84s, opens browser)
```

---

## STEP 5 — Suggest next actions

Based on state files and dev-log, suggest what to work on next:

- If `manual_review.json` has items → "There are N unresolved manual_review items from the last check.sh run"
- If `report.json` has failures → "Last fetch found N failures — investigate.md may need re-running"
- If latest dev-log mentions ⏳ scenarios → "Scenarios not yet tested: sql_error, timeout, consecutive"
- If sar-investigate is still placeholder → "Next big milestone: implement sar-investigate SKILL.md"
- Otherwise → "Project state looks clean"

---

## Architecture Quick Reference

### Skill chain (normal incident flow)
```
/sarthi <input>
  → sar-inbox      (normalise input → envelope)
  → sar-plan       (determine skill chain)
  → sar-investigate (query Airflow/BQ/GCS for root cause)
  → sar-resolve    (execute fix via ops MCP)
  → sar-crq        (generate ServiceNow CRQ if needed)
  → sar-summary    (format report)
  → sar-reply      (post to Jira/Teams/email)
```

### Autonomous pipeline (check.sh, runs hourly via cron)
```
fetcher.py
  → list_dag_runs_batch (1 API call per env)
  → get_task_instances + get_task_log for each failed DAG
  → log fallback: get_dag_run_conf → mail_search → "[log unavailable]"
  → writes report.json

investigate.md (Wibey AI)
  → reads report.json
  → classifies each failure into Pattern A/B/C/D/E/F
  → writes actions.json + manual_review.json

executor.py
  → reads actions.json
  → calls sarthi-airflow-ops MCP for each action
  → beeps if manual_review.json has items
```

### Envelope contract
```json
{
  "source":   { "channel", "id", "raw", "replyable" },
  "intent":   { "type", "summary", "entities" },
  "context":  { "team_member", "lineage", "history" },
  "artifacts": [],
  "plan":     [],
  "flags":    { "auto_reply", "dry_run" }
}
```

### Key files quick reference
```
~/sarthi/setup.sh                           installer (idempotent)
~/sarthi/mcp/sarthi-*/server.py             MCP servers
~/sarthi/skills/sar-*/SKILL.md              skill definitions
~/sarthi/knowledge/known-issues.json        FAQ / troubleshooting
~/sarthi/knowledge/dev-log/                 session findings (this dir)
~/.wibey/sarthi/config.yaml                 Airflow environments + cookies config
~/.wibey/sarthi/cookies.txt                 Airflow session (expires ~8h)
~/.wibey/sarthi/session.json                Airflow session metadata
~/.wibey/agents/sarthi/check.sh             3-stage autonomous pipeline
~/.wibey/agents/sarthi/fetcher.py           Stage 1: fetch failures
~/.wibey/agents/sarthi/investigate.md       Stage 2: AI classify
~/.wibey/agents/sarthi/executor.py          Stage 3: execute actions
~/.wibey/agents/sarthi/simulator.py         test harness
~/.wibey/agents/sarthi/report.json          output: failures found
~/.wibey/agents/sarthi/actions.json         output: auto-actions
~/.wibey/agents/sarthi/manual_review.json   output: items needing human
~/.wibey/agents/sarthi/logs/                per-run check.sh logs
~/.wibey/sarthi/reports/                    HTML health reports
~/.wibey/sarthi/history/ops.jsonl           ops audit trail
```
