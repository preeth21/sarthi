---
name: "sar-investigate"
key: "sar-investigate"
description: "sArthI's core diagnostic engine. Investigates a runtime incident, DAG failure, or platform bug by querying Airflow for run logs, checking BigQuery for data anomalies, tracing upstream lineage dependencies, and matching against known resolution patterns. Populates envelope.context.investigation with findings."
allowed-tools: [Read, Bash, mcp__sarthi-airflow-read__list_dags, mcp__sarthi-airflow-read__get_dag_runs, mcp__sarthi-airflow-read__get_task_instances, mcp__sarthi-airflow-read__get_task_log, mcp__sarthi-airflow-read__get_dag_topology, mcp__sarthi-airflow-auth__refresh_session, mcp__sarthi-gcp__gcs_ls, mcp__sarthi-gcp__gcs_stat, mcp__sarthi-gcp__gcs_cat, mcp__sarthi-gcp__hudi_timeline, mcp__sarthi-gcp__dataproc_fetch_driver_log, mcp__plugin__wibey_mcp-jira__get_issue_by_key_or_link, mcp__plugin__wibey_mcp-jira__jql_based_search]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "placeholder"
---

# sar-investigate — Incident & Bug Investigator

## Purpose
sArthI's diagnostic brain. Given an incident or bug in the envelope, this skill
performs a multi-source investigation to identify root cause, upstream dependencies,
and similar past resolutions — so that `sar-resolve` and `sar-propose-fix` can act
with confidence rather than guesswork.

## Status: PLACEHOLDER

## TODO — implement:

- [ ] Read `envelope.intent.entities` (dag_id, table, env, market)
- [ ] Query Airflow MCP for recent run status and failed task logs
  - Use `mcp__sarthi-airflow-read__get_dag_runs` + `mcp__sarthi-airflow-read__get_task_log`
  - On session_expired → `mcp__sarthi-airflow-auth__refresh_session` then retry
- [ ] Query BigQuery for row counts / data anomalies on the affected table
- [ ] Look up lineage in `~/.wibey/knowledge/lineage/` for upstream dependencies
- [ ] Search `~/.wibey/knowledge/resolution-patterns.json` for known fix patterns
- [ ] Search Jira for related open or recently resolved tickets (mcp-jira jql_based_search)
- [ ] Populate `envelope.context.investigation` with structured findings
- [ ] Add investigation summary to `envelope.artifacts[]`

## Expected inputs
- `envelope` with `intent.type = "incident" | "bugfix"`
- `envelope.intent.entities.dag_id` or `.table` populated by sar-inbox

## Expected output

```json
{
  "envelope.context.investigation": {
    "findings": ["<finding 1>", "<finding 2>"],
    "root_cause_hypothesis": "<1-sentence hypothesis>",
    "affected_components": ["<dag_id>", "<table>"],
    "upstream_deps": ["<upstream dag or table>"],
    "similar_past_incidents": [
      { "jira_key": "ET360-NNN", "resolution": "<how it was fixed>" }
    ],
    "confidence": "high | medium | low"
  }
}
```

## Investigation phases (in order)

1. **Runtime state** — What is Airflow showing for this DAG right now?
2. **Log analysis** — Which task failed, what was the error message?
3. **Data check** — Is the target table missing rows or has stale data?
4. **Lineage trace** — Did an upstream dependency fail first?
5. **Pattern match** — Have we seen this before? What fixed it last time?
6. **Jira scan** — Any open tickets describing the same symptoms?

## Airflow MCP (built — use these)
`sarthi-airflow-read` MCP is registered and active. Use MCP tools instead of Bash:
```
mcp__sarthi-airflow-read__get_dag_runs(dag_id=dag_id, limit=5)
mcp__sarthi-airflow-read__get_task_log(dag_id=dag_id, run_id=run_id, task_id=failed_task)
mcp__sarthi-airflow-read__get_task_instances(dag_id=dag_id, run_id=run_id)
```
If MCP returns `session_expired` → call `mcp__sarthi-airflow-auth__refresh_session` then retry.

## GCP MCP (built — use these)
`sarthi-gcp` MCP is registered and active. Use for GCS/Hudi/Dataproc investigation:
```
mcp__sarthi-gcp__hudi_timeline(table_path="gs://bucket/path/to/hudi/table")
mcp__sarthi-gcp__dataproc_fetch_driver_log(cluster="cluster-name", job_id="job-id")
mcp__sarthi-gcp__gcs_ls(uri="gs://bucket/path/")
mcp__sarthi-gcp__gcs_cat(uri="gs://bucket/path/file.json")
```
