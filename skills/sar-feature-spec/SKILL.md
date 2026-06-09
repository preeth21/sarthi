---
name: "sar-feature-spec"
key: "sar-feature-spec"
description: "sArthI's feature design skill. Given a Jira story or free-text feature request, produces a complete technical specification: table schema, DAG graph, operator selection, market scope, SLA, and estimated effort. Output feeds directly into sar-scaffold."
allowed-tools: [Read, Glob, Grep]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "placeholder"
---

# sar-feature-spec — Feature Technical Specification Writer

## Purpose
When a new pipeline feature is requested, sArthI designs it properly before
anyone writes a line of code. This skill produces a technical spec that answers:
What tables? What DAG shape? Which operators? Which markets? What SLA?

## Status: PLACEHOLDER

## TODO — implement:

- [ ] Read `envelope.source.fetched_content` (Jira story description or free-text)
- [ ] Look up similar existing pipelines in `~/.wibey/knowledge/dags/` for patterns to follow
- [ ] Read `~/.wibey/knowledge/operator-catalog.json` to identify which Airflow operators apply
- [ ] Read `~/.wibey/knowledge/environments.json` for BigQuery project and dataset naming conventions
- [ ] Produce tech spec covering:
  - **Table design**: schema, partitioning, clustering, project.dataset.table name
  - **DAG structure**: task graph (sequence, parallel branches, sensors)
  - **Operators**: which operator type for each task and why
  - **Market scope**: which geos (ca, mx, ww) and any market-specific variations
  - **SLA**: expected run time, acceptable delay before alert
  - **Estimated effort**: story points or days
- [ ] Add spec to `envelope.artifacts[]`

## Spec output format (markdown)
```markdown
## Feature Spec: <feature name>

### Jira: <KEY>
### Market scope: <ca | mx | ca+mx | ww>

### Table Design
| Table | Schema | Partition | Cluster |
|-------|--------|-----------|---------|
| project.dataset.table_name | field1 STRING, field2 DATE | DATE | field1 |

### DAG Structure
dag_id: <name>_dag
schedule: <cron>
tasks:
  - sensor_upstream → extract → transform → load → validate

### Operators
- sensor_upstream: ExternalTaskSensor (wait for upstream dag)
- extract: BigQueryOperator
- transform: BigQueryOperator (or DataprocOperator if heavy)
- load: BigQueryToBigQueryOperator
- validate: PythonOperator (row count check)

### SLA
Expected run time: ~45 min
Alert if exceeds: 90 min
Downstream consumers: <list>

### Estimated Effort
<N> story points / <N> days
```

## Expected output
- `envelope.artifacts` updated with `{ type: "spec", content: "<markdown spec>", dag_id: "<proposed_dag_id>" }`
