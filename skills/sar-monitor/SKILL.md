---
name: "sar-monitor"
key: "sar-monitor"
description: "sArthI's health pulse check. Scans production AFaaS DAG run status, surfaces failures, delays, and SLA breaches, then generates a structured health report. The primary skill behind /sarthi monitor and the sarthi-agent morning cron."
allowed-tools: [Read, mcp__sarthi-airflow-read__list_dags, mcp__sarthi-airflow-read__list_dag_runs_batch, mcp__sarthi-airflow-read__get_dag_runs, mcp__sarthi-airflow-read__get_task_instances, mcp__sarthi-airflow-read__get_task_log, mcp__sarthi-airflow-read__get_dag_topology, mcp__sarthi-airflow-auth__refresh_session]
metadata:
  author: "akiran"
  version: "1.1.0"
  part-of: "sarthi"
  status: "active"
---

# sar-monitor — Production Runtime Health Monitor

## Purpose
sArthI's continuous health pulse. Polls Airflow for DAG run status across all
watched environments, identifies failures, SLA breaches, and stuck runs, then
packages findings into a structured health report that `sar-reply` can post to
Teams or attach to Jira tickets.

## Invocation

Called automatically by `/sarthi monitor` and `sarthi-agent --monitor`.
Can also be invoked standalone: `/sar-monitor`

Optional envelope input:
```json
{
  "flags": {
    "env_filter": "CA-ET360-PROD",
    "subject_area": "ET360 CA",
    "include_logs": true
  }
}
```

## Execution Steps

### Step 1 — Discover DAGs
Call `mcp__sarthi-airflow-read__list_dags` with optional env_filter or subject_area from
`envelope.flags` (if provided). This returns all DAGs from config.yaml.

```
tool: mcp__sarthi-airflow-read__list_dags
args: { "env_name": "<from flags, or empty for all>", "subject_area": "<from flags, or empty>" }
```

If result contains `"error": "config_unavailable"`, stop and return:
```json
{ "error": "config_unavailable", "message": "~/.wibey/sarthi/config.yaml not found" }
```

### Step 2 — Fetch latest DAG runs (batch — 1 call per env)
Call `mcp__sarthi-airflow-read__list_dag_runs_batch` once per environment (or once for all
environments if no env_filter is set). This uses the Airflow batch endpoint
`POST /dags/~/dagRuns/list` and returns all DAG runs in a single API call per env —
equivalent to what prod-monitor's run.py does, not 1 call per DAG.

```
tool: mcp__sarthi-airflow-read__list_dag_runs_batch
args: { "env_name": "<from flags, or omit for all>", "runs_per_dag": 3 }
```

The response is a `dag_runs` map: `dag_id → { latest_run, recent_runs, env_name }`.
`auth_failures` lists any environments where the session was expired.

**Call budget: 1 call per active environment (13 envs = 13 calls), not 1 per DAG.**

If any env appears in `auth_failures`, attempt automatic recovery **once**:

1. Call `mcp__sarthi-airflow-auth__refresh_session` with `{"env_name": "<env_name>"}`.
2. If refresh returns `{"status": "ok"}`, retry `list_dag_runs_batch` for that env only.
3. If refresh fails or retry still returns `session_expired`, record the env in `auth_failures`
   and continue — do not abort the entire run.

Surface unrecovered failures as:
```
⚠️  Cookie auth expired for <env_name> — auto-refresh failed. Run: python3 ~/sarthi/scripts/headless-refresh.py
```

> `get_dag_runs` (single-DAG) is still available for ad-hoc lookups but MUST NOT be
> used in the monitoring loop — it generates 1 call per DAG (94+ calls vs 13).

### Step 3 — Classify each DAG
For each DAG's most recent run, classify using the table below.
**Also check `recent_runs` (last 3 runs)**: if the latest run is `success` but any
of the previous 2 runs was `failed`, add a `⚠️  flapping` flag — do NOT suppress it
as healthy. Flapping DAGs are unreliable even when they appear green.

| Condition | Label |
|-----------|-------|
| state == "success" AND no recent failures | ✅ healthy |
| state == "success" AND any of last 3 runs failed | ⚠️  flapping |
| state == "failed" | ❌ failed |
| state == "running" AND age > SLA threshold | ⚠️  sla_breach |
| state == "running" AND age <= SLA threshold | 🔄 running |
| state == "queued" AND age > 30 min | ⚠️  stuck |
| no runs found | ❓ no_data |

SLA threshold default: 90 minutes (configurable per DAG via config.yaml `sla_minutes` field).

### Step 4 — Drill into failures
For each DAG classified as `failed`:

1. Call `mcp__sarthi-airflow-read__get_task_instances` for the failed run_id.
2. Find the first task with `state == "failed"`.
3. Call `mcp__sarthi-airflow-read__get_task_log` for that task (try_number from task instance,
   max_lines=100).
4. Extract the last error line (look for "ERROR", "Exception", "Traceback" in the log).

If `envelope.flags.include_logs == false`, skip step 3-4 and set `error_snippet: null`.

### Step 5 — Build health report artifact

```json
{
  "type": "monitor-report",
  "checked_at": "<ISO timestamp>",
  "environment_filter": "<filter used or 'all'>",
  "summary": {
    "total_watched": 96,
    "healthy": 90,
    "failed": 3,
    "flapping": 2,
    "sla_breached": 1,
    "stuck": 0,
    "no_data": 2
  },
  "failures": [
    {
      "env_name": "CA-ET360-PROD",
      "dag_id": "INTLDLDAT-CAWM-ET360-BQ-DATA-LOAD",
      "label": "ET360 CA BQ Data Load",
      "run_id": "scheduled__2024-01-15T00:00:00+00:00",
      "failed_task": "load_bq_table",
      "error_snippet": "google.api_core.exceptions.NotFound: 404 Table not found",
      "started_at": "2024-01-15T00:02:31+00:00"
    }
  ],
  "sla_breaches": [
    {
      "env_name": "MX-ET360-PROD",
      "dag_id": "INTLDLDAT-MXWM-ET360-BQ-DATA-LOAD",
      "label": "ET360 MX BQ Data Load",
      "run_id": "scheduled__2024-01-15T00:00:00+00:00",
      "current_state": "running",
      "started_at": "2024-01-15T00:01:12+00:00",
      "delay_minutes": 102
    }
  ],
  "auth_failures": ["STAGING-ET360"],
  "report_md": "<formatted markdown — see template below>"
}
```

### Step 6 — Generate report_md

Use this template:

```
## 🔍 sArthI Health Report — <date>

**Environments checked:** <N> | **DAGs watched:** <total>

| Status | Count |
|--------|-------|
| ✅ Healthy | <N> |
| ❌ Failed | <N> |
| ⚠️  Flapping | <N> |
| ⚠️  SLA Breach | <N> |
| 🔄 Running | <N> |
| ❓ No Data | <N> |

### ❌ Failures
<for each failure:>
**<env_name> / <label>** (`<dag_id>`)
- Run: `<run_id>`
- Failed task: `<failed_task>`
- Error: `<error_snippet>`
- Started: <started_at>

### ⚠️  Flapping (latest success but recent failures)
<for each flapping dag:>
**<env_name> / <label>** (`<dag_id>`) — latest run succeeded but had failures in last 3 runs

### ⚠️  SLA Breaches
<for each sla_breach:>
**<env_name> / <label>** — running for <delay_minutes> min (SLA: 90 min)

### 🔐 Auth Failures (session refresh needed)
<list of env_names with auth_failure>
```

### Step 7 — Update envelope

```json
{
  "artifacts": [{ "type": "monitor-report", ...report object... }],
  "plan": {
    "next_skill": "sar-reply",
    "reason": "post health report to configured Teams channel"
  }
}
```

If there are no failures and no SLA breaches, set:
```json
{ "plan": { "next_skill": null, "reason": "all systems healthy — no action needed" } }
```

## Integration with sarthi-agent morning cron

When invoked headlessly via `sarthi-agent --monitor --auto-reply`:
1. sar-monitor produces the report artifact
2. sar-summary condenses it to ≤ 5 bullet points
3. sar-reply posts to `channels.teams.et360-alerts`

No human action required.

## Config reference

Config is read by the Airflow MCP server from `~/.wibey/sarthi/config.yaml`.
The sar-monitor skill never reads config directly — it uses MCP tools only.

Optional per-DAG config fields (in config.yaml):
```yaml
dags:
  - id: "INTLDLDAT-CAWM-ET360-BQ-DATA-LOAD"
    label: "ET360 CA BQ Data Load"
    subject_area: "ET360 CA"
    sla_minutes: 120   # override default 90 min SLA
```
