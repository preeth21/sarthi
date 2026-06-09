---
name: "sar-scaffold"
key: "sar-scaffold"
description: "sArthI's pipeline scaffolding skill. Takes a feature spec from sar-feature-spec and generates a complete, ready-to-commit pipeline: YAML config, DAG Python file, test stub, and README — all following INTLDLDAT naming and structural conventions."
allowed-tools: [Read, Write, Bash]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "placeholder"
---

# sar-scaffold — Pipeline Scaffolder

## Purpose
sArthI's pipeline factory. Given a technical spec, this skill generates every file
needed to bootstrap a new pipeline — so developers start with working structure
rather than a blank file.

## Status: PLACEHOLDER

## TODO — implement:

- [ ] Read `envelope.artifacts[type=="spec"]` for the feature spec from sar-feature-spec
- [ ] Read `~/.wibey/knowledge/repo-registry.json` to find the target pipeline repo path
- [ ] Generate files following INTLDLDAT conventions:
  - `pipelines/<dag_id>.yaml` — pipeline YAML config
  - `dags/<dag_id>.py` — Airflow DAG Python file
  - `tests/test_<dag_id>.py` — test stub
  - `docs/<dag_id>.md` — pipeline README
- [ ] Write generated files to a local branch checkout directory
- [ ] Add generated file paths to `envelope.artifacts[]`

## File generation rules
- DAG Python: use existing pipeline files as templates — never invent new patterns
- YAML: follow the schema in `~/.wibey/knowledge/pipeline-yaml-schema.json`
- Tests: stub with one smoke test (DAG loads without errors) + one data test
- README: auto-fill from spec (table, schedule, SLA, owners)

## Operator to code mapping
| Operator type | Python class |
|---|---|
| BigQuery SQL | BigQueryOperator |
| BQ to BQ copy | BigQueryToBigQueryOperator |
| External sensor | ExternalTaskSensor |
| Python logic | PythonOperator |
| Dataproc | DataprocSubmitJobOperator |

## Expected output
- `envelope.artifacts` updated with:
```json
{
  "type": "scaffold",
  "dag_id": "<dag_id>",
  "files": [
    "pipelines/<dag_id>.yaml",
    "dags/<dag_id>.py",
    "tests/test_<dag_id>.py",
    "docs/<dag_id>.md"
  ],
  "branch": "feat/<jira-key>-<dag_id>"
}
```
