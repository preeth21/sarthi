---
name: "sar-triagent"
key: "sar-triagent"
description: "sArthI SRE investigation skill — the primary escalation path for complex, multi-system incidents. Routes to TRIAGENT (70+ SRE tools: Kafka lag, Kubernetes ops across 30+ clusters, certificate monitoring, change correlation, topology mapping, multi-cloud infrastructure, Health & Wellness domain). Call this when sarthi's local MCPs are insufficient."
allowed-tools: [mcp__plugin__wibey_wibey-core-mcp__triagent]
metadata:
  author: "sarthi"
  version: "1.0.0"
  part-of: "sarthi"
  status: "active"
  wraps: ["TRIAGENT"]
  triagent-peers: ["PulseMetrics", "T12R", "Public Cloud AI", "Topology", "Change", "H&W", "LOBO", "AgentK"]
---

# sar-triagent — SRE Incident Investigation Skill

## Purpose

The highest-capability investigation skill in sArthI. Routes to TRIAGENT — Walmart's
unified SRE platform with 70+ tools, 8 peer agents, and coverage across:
- 30+ WCNP clusters (read + ops)
- Kafka consumer lag analysis
- Certificate monitoring and expiry prediction
- Change/deployment correlation (ServiceNow + SeedBees)
- Service topology mapping
- Multi-cloud infrastructure (GCP + Azure)
- Database health (CosmosDB, Azure SQL, Cassandra, Redis)
- Health & Wellness domain (55K+ pharmacy VMs, HIPAA clusters)
- Anomaly detection and root cause correlation

## When to Use

Prefer sar-triagent over local sarthi MCPs when:
- Incident spans multiple systems (Kafka + WCNP + DB simultaneously)
- Root cause unknown and requires broad correlation
- Standard sarthi MCP tools returned insufficient data
- Certificate expiry suspected across fleet
- Change correlation needed (who deployed what, when)
- HIPAA or Health & Wellness workloads involved
- Multi-cluster WCNP investigation needed (>1 cluster)
- Historical anomaly pattern analysis needed

**When NOT to use sar-triagent:**
- Simple Airflow DAG status check → use sarthi-airflow-read MCP
- BigQuery query → use sarthi-bq MCP
- GCS file check → use sarthi-gcp MCP
- Single-cluster WCNP pod check → use sarthi-wcnp MCP
- Git file lookup → use sarthi-git MCP

## How to Invoke

### 1. Incident investigation (primary use case)

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__triagent
Prompt template:
  "Investigate incident: <incident_title>.
   Service: <service_name>.
   Affected systems: <list all — WCNP cluster, Kafka topics, DB, etc.>.
   Symptoms: <describe in detail — error messages, metrics, user impact>.
   Time of first occurrence: <timestamp or 'approximately <time>'>.
   What we've already checked: <sarthi MCP findings if any>.
   Investigate: root cause, blast radius, contributing changes.
   Return: root cause hypothesis (ranked by confidence), timeline,
           recommended immediate action, recommended permanent fix."
```

### 2. Kafka consumer lag (multi-cluster or unknown cluster)

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__triagent
Prompt template:
  "Investigate Kafka consumer lag for <consumer_group>.
   Topic: <topic or 'all topics'>.
   Cluster: <cluster or 'discover — group may be on multiple clusters'>.
   Current lag: <lag value or 'unknown'>.
   Time window: last <N> hours.
   Return: lag trend, consumer health, rebalance history, recommended action."
```

### 3. Service health check

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__triagent
Prompt template:
  "Check health of service <service_name>.
   Namespace: <namespace>.
   Cluster(s): <cluster or 'all prod clusters'>.
   Check: pod health, error rates, latency percentiles, recent deployments,
          certificate expiry, dependency health.
   Return: health score, any anomalies, top risk factor."
```

### 4. Change correlation

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__triagent
Prompt template:
  "Correlate changes with incident for service <service_name>.
   Incident start: <timestamp>.
   Check ServiceNow CRQs, SeedBees deployments, KITT config changes, 
   and infra changes in the 2 hours before the incident.
   Return: timeline of changes, which change is most likely correlated, confidence."
```

### 5. Certificate monitoring

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__triagent
Prompt template:
  "Check certificate expiry for service <service_name> or namespace <namespace>.
   Cluster: <cluster or 'all prod clusters'>.
   Alert threshold: certificates expiring within <N> days.
   Return: certificates found, expiry dates, renewal priority, renewal steps."
```

### 6. Database health

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__triagent
Prompt template:
  "Check health of <CosmosDB | Azure SQL | Cassandra | Redis> database <db_name>.
   Connection string / endpoint: <endpoint or 'discover for service <service>'>.
   Symptoms: <high latency | connection failures | throttling | data inconsistency>.
   Return: health metrics, anomalies, root cause, recommended fix."
```

## Input Parameters

```yaml
service_name: string     # Service under investigation
incident_title: string   # Brief incident description
affected_systems: list   # Systems involved (WCNP, Kafka, DB, etc.)
symptoms: string         # Detailed symptom description
incident_start: string   # Timestamp or approximate time
prior_findings: string   # What sarthi MCPs already found (optional)
task_type: enum          # incident | kafka_lag | health_check | change_correlation | cert_check | db_health
time_window_hours: int   # Default: 6
```

## Output Contract

TRIAGENT returns rich structured responses. Expect:
- Root cause hypothesis with confidence ranking
- Incident timeline
- Blast radius assessment
- Immediate action items
- Permanent fix recommendation
- Escalation path if unresolved

## Design Rules

- Pass ALL available context — TRIAGENT uses everything you give it
- Include prior_findings from sarthi MCPs to avoid re-fetching the same data
- Never assume what TRIAGENT can/cannot access — it has 70+ tools
- For mutations (restart, scale, rollback), TRIAGENT will propose but always confirm with user

## Integration with sar-investigate / sar-resolve

sar-investigate escalates to sar-triagent when:
- Confidence score from local MCP analysis < 70%
- Multiple systems affected simultaneously
- Incident duration > SLA threshold from team-config.yaml
- Standard investigation pattern yielded no root cause

sar-resolve escalates here when:
- Fix requires cross-system coordination
- Rollback across multiple clusters needed

## Verified State

- TRIAGENT: **verified reachable and live** (tested this session — responded in ~27s, 42k tokens)
- Kafka tools: in scope per agent description
- Kubernetes (30+ WCNP clusters): in scope — may have broader cluster access than sarthi-wcnp
- Azure SQL / CosmosDB / Redis: in scope
- H&W domain (HIPAA): in scope — use only if your team has H&W access
