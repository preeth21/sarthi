---
name: "sar-resolve"
key: "sar-resolve"
description: "sArthI's self-healing executor. Acts on findings from sar-investigate to clear failed tasks, re-queue runs, trigger backfills, or apply known configuration fixes. Confirms actions with the user unless flags.auto_reply = true. Updates resolution-patterns.json with novel fixes for future autonomous healing."
allowed-tools: [Read, Bash, mcp__sarthi-airflow-ops__clear_task, mcp__sarthi-airflow-ops__clear_task_with_deps, mcp__sarthi-airflow-ops__set_dag_run_state, mcp__sarthi-airflow-ops__trigger_dag_run, mcp__sarthi-airflow-ops__get_dag_run_state, mcp__sarthi-airflow-ops__poll_task, mcp__sarthi-airflow-auth__refresh_session]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "placeholder"
---

# sar-resolve — Self-Healing Incident Resolver

## Purpose
sArthI's hands. After `sar-investigate` identifies root cause, this skill executes
the resolution — clearing failed tasks, triggering backfills, patching config,
or escalating when no automated fix applies. It is the "self-healing" in sArthI's
name.

## Status: PLACEHOLDER

## TODO — implement:

- [ ] Read `envelope.context.investigation` (findings from sar-investigate)
- [ ] Determine resolution action from root_cause_hypothesis:
  - `clear_task` — clear the failed task and re-run
  - `set_run_queued` — reset the DAG run to queued state
  - `backfill` — trigger a date-range backfill
  - `config_fix` — apply a known config patch (delegate to sar-propose-fix)
  - `escalate` — no automated fix available; surface for human action
- [ ] If `flags.auto_reply = false`: present proposed actions to user and ask to confirm
- [ ] Execute approved actions via sarthi-airflow-ops MCP (built: clear_task, set_dag_run_state, trigger_dag_run, poll_task)
- [ ] If novel fix: append new pattern to `~/.wibey/knowledge/resolution-patterns.json`
- [ ] Update `envelope.artifacts[]` with actions taken
- [ ] Set `envelope.context.resolution` with outcome

## Resolution decision tree

```
if investigation.confidence == "high" AND pattern matched:
    action = pattern.recommended_action
elif investigation.root_cause_hypothesis contains "missing upstream":
    action = "wait_for_upstream" or "trigger_upstream_dag"
elif investigation.root_cause_hypothesis contains "config":
    action = "config_fix" → delegate to sar-propose-fix
elif investigation.confidence == "low":
    action = "escalate"
    generate Jira comment with findings
else:
    action = "clear_task" (safe default for transient failures)
```

## Airflow actions (via sarthi-airflow-ops MCP — built and registered)
Prefer MCP tools over direct curl. On `session_expired` → call `mcp__sarthi-airflow-auth__refresh_session` then retry.

```
# Clear failed task
mcp__sarthi-airflow-ops__clear_task(dag_id=dag_id, run_id=run_id, task_id=failed_task)

# Clear task + all downstream dependencies
mcp__sarthi-airflow-ops__clear_task_with_deps(dag_id=dag_id, run_id=run_id, task_id=failed_task)

# Set run to queued
mcp__sarthi-airflow-ops__set_dag_run_state(dag_id=dag_id, run_id=run_id, state="queued")

# Trigger new run
mcp__sarthi-airflow-ops__trigger_dag_run(dag_id=dag_id)

# Poll task until terminal state
mcp__sarthi-airflow-ops__poll_task(dag_id=dag_id, run_id=run_id, task_id=task_id)
```

NOTE: ops tools require `ops_allowed: true` for the target env in `~/.wibey/sarthi/config.yaml`.
Mutation tools will return `{"error": "ops_not_allowed"}` if the flag is not set.

## Expected output

```json
{
  "envelope.context.resolution": {
    "action_taken": "clear_task | backfill | config_fix | escalate",
    "dag_retriggered": true,
    "actions_detail": ["<action 1>", "<action 2>"],
    "status": "resolved | in-progress | escalated"
  }
}
```
- `envelope.artifacts` updated with `{ type: "resolution", actions: [...], status: "..." }`
