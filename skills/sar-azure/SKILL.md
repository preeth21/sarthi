---
name: "sar-azure"
key: "sar-azure"
description: "sArthI public cloud skill — investigates Azure and GCP cloud resource issues. Routes to PUBLIC-CLOUD-AI (Azure resource inventory, GCP inventory) and TRIAGENT (multi-cloud infrastructure correlation, Azure SQL, CosmosDB, Redis health). No sarthi local MCP for Azure/GCP public cloud ops."
allowed-tools: [mcp__plugin__wibey_wibey-core-mcp__public_cloud_ai, mcp__plugin__wibey_wibey-core-mcp__triagent, mcp__plugin__wibey_sarthi-gcp__gcs_ls, mcp__plugin__wibey_sarthi-gcp__dataproc_list, mcp__plugin__wibey_sarthi-bq__bq_list_datasets]
metadata:
  author: "sarthi"
  version: "1.0.0"
  part-of: "sarthi"
  status: "active"
  wraps: ["PUBLIC-CLOUD-AI", "TRIAGENT"]
  note: "Azure inventory: PUBLIC-CLOUD-AI (coming soon per agent description). GCP inventory: PUBLIC-CLOUD-AI now. GCP data ops: use sarthi-gcp + sarthi-bq MCPs directly."
---

# sar-azure — Public Cloud Investigation Skill

## Purpose

Investigate Azure and GCP cloud resource issues: inventory, health, database problems,
network anomalies, and cost anomalies.

**Important scope note from PUBLIC-CLOUD-AI agent:**
> "GCP inventory available now. Azure inventory coming soon."

For GCP data operations (GCS, Dataproc, BigQuery), use sarthi-gcp and sarthi-bq MCPs
directly — they are faster and more specific.

## When to Use

- Azure resource health or availability issue
- GCP cloud inventory lookup (projects, VMs, networks, IAM)
- Azure SQL / CosmosDB / Redis health investigation
- Multi-cloud resource correlation (e.g., Azure + GCP both involved)
- Cloud resource quota or capacity issue
- Azure networking / VNet / NSG connectivity problem

## Routing Logic

| Task type | Agent |
|-----------|-------|
| Azure resource inventory, health, networking | PUBLIC-CLOUD-AI |
| GCP cloud inventory (non-data: VMs, networks, IAM) | PUBLIC-CLOUD-AI |
| Azure SQL, CosmosDB, Redis, multi-cloud correlation | TRIAGENT |
| GCS, Dataproc, BigQuery data ops | Use sarthi-gcp / sarthi-bq MCPs directly |
| GCP Dataproc cluster health | sarthi-gcp MCP → dataproc_describe |

## How to Invoke

### 1. Azure resource investigation

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__public_cloud_ai
Prompt template:
  "Investigate Azure resource issue.
   Subscription: <subscription_name or ID or 'unknown'>.
   Resource group: <resource_group or 'unknown'>.
   Resource type: <VM | App Service | SQL | CosmosDB | AKS | VNet | etc.>.
   Resource name: <name or 'discover for app <app_name>'>.
   Issue: <describe — unavailable, high latency, quota exceeded, etc.>.
   Time window: last <N> hours.
   Return: resource health status, recent events, root cause, remediation steps."
```

### 2. GCP cloud inventory

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__public_cloud_ai
Prompt template:
  "List GCP resources for project <project_id or 'discover for team <team>'>. 
   Resource type: <VMs | networks | IAM | quotas | all>.
   Return: inventory summary, any anomalies, resource health."
```

### 3. Azure database health (SQL / CosmosDB / Redis)

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__triagent
Prompt template:
  "Investigate Azure database health.
   Database type: <Azure SQL | CosmosDB | Redis | Cassandra>.
   Resource: <resource_name or endpoint>.
   Subscription / Resource group: <values or 'discover'>.
   Symptoms: <high latency | connection failures | throttling | replication lag>.
   Time window: last <N> hours.
   Return: health metrics, anomalies, root cause hypothesis, recommended fix."
```

### 4. Multi-cloud correlation

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__triagent
Prompt template:
  "Service <service_name> spans Azure (<Azure resource>) and GCP (<GCP resource>).
   Incident: <describe symptoms>.
   Investigate both cloud layers for correlated anomalies, network issues,
   or cascading failures between the two clouds.
   Return: timeline of events across both clouds, likely originating layer, fix."
```

### 5. GCP data operations (redirect to sarthi MCPs)

```
For GCS operations:    use sarthi-gcp MCP → gcs_ls, gcs_stat, gcs_cat
For Dataproc:          use sarthi-gcp MCP → dataproc_list, dataproc_describe
For BigQuery:          use sarthi-bq MCP  → bq_query, bq_schema, bq_list_tables
```

## Input Parameters

```yaml
cloud: enum              # azure | gcp | multi-cloud
resource_type: string    # VM | SQL | CosmosDB | Redis | AKS | VNet | GCS | etc.
resource_name: string    # Resource identifier (optional — agent will discover)
subscription: string     # Azure subscription (optional)
project_id: string       # GCP project ID (optional)
symptoms: string         # Free-text issue description
time_window_hours: int   # Default: 6
task_type: enum          # health | inventory | database | network | correlation
```

## Output Contract

Returns agent response verbatim. Expect:
- Resource inventory or health status
- Anomaly timeline
- Root cause hypothesis
- Remediation steps (with Azure Portal / gcloud commands as appropriate)

## Design Rules

- Never hardcode subscription IDs, resource group names, or project IDs
- For GCP data ops, always prefer sarthi-gcp / sarthi-bq MCPs (faster, scoped)
- Azure inventory is "coming soon" per PUBLIC-CLOUD-AI — if it returns no results, note this limitation
- Cloud mutations (VM restart, scaling) require user confirmation

## Integration with sar-investigate / sar-resolve

sar-investigate routes here when:
- Incident mentions Azure, CosmosDB, Redis, "cloud resource"
- GCP quota exceeded (for non-data resources)
- Multi-cloud latency spike

sar-resolve routes here when:
- Fix requires Azure resource modification
- GCP quota increase request

## Current State

- PUBLIC-CLOUD-AI: **reachable** (schema loaded, not smoke-tested for Azure)
- TRIAGENT: **verified reachable** (tested this session — Azure SQL/CosmosDB/Redis in scope)
- Azure inventory: **coming soon** per PUBLIC-CLOUD-AI agent description
- GCP data ops: **verified** via sarthi-gcp + sarthi-bq MCPs
