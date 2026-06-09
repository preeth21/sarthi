---
name: "sar-kafka"
key: "sar-kafka"
description: "sArthI Kafka skill — investigates Kafka consumer lag, topic health, and pipeline failures. Routes to TRIAGENT (Kafka lag analysis, anomaly detection) and WIBEY-PIPELINE-TROUBLESHOOTER-AGENT (pipeline/topic config issues). No sarthi MCP for Kafka exists — this skill is the integration point."
allowed-tools: [mcp__plugin__wibey_wibey-core-mcp__triagent, mcp__plugin__wibey_wibey-core-mcp__wibey_pipeline_troubleshooter_agent]
metadata:
  author: "sarthi"
  version: "1.0.0"
  part-of: "sarthi"
  status: "active"
  wraps: ["TRIAGENT", "WIBEY-PIPELINE-TROUBLESHOOTER-AGENT"]
---

# sar-kafka — Kafka Investigation Skill

## Purpose

Investigate Kafka consumer lag, topic health, consumer group state, and pipeline
failures related to Kafka. Routes to the appropriate A2A agent based on task type.

No sarthi local MCP for Kafka. This skill is the sArthI integration point for all
Kafka concerns.

## When to Use

Call this skill when:
- Consumer group is lagging or stalled
- A pipeline is not consuming messages
- Topic throughput looks anomalous
- Need to check Kafka cluster health
- A DAG or data pipeline is blocked waiting on Kafka messages

## Routing Logic

| Task type | Agent to call |
|-----------|--------------|
| Consumer lag, anomaly detection, SRE investigation | TRIAGENT |
| Pipeline failure, Concord/LooperPro build blocked on Kafka | WIBEY-PIPELINE-TROUBLESHOOTER-AGENT |
| Topic config, broker health, offset reset questions | TRIAGENT |

## How to Invoke

### 1. Consumer lag investigation

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__triagent
Prompt template:
  "Investigate Kafka consumer lag for consumer group <group_name>.
   Cluster: <cluster_name or 'unknown — please discover'>.
   Topic(s): <topic or 'all topics for this group'>.
   Time window: last <N> hours.
   Symptoms: <describe what the user reported>.
   Check: lag trend, consumer health, any recent rebalances, broker anomalies.
   Return: root cause hypothesis, lag numbers, recommended action."
```

### 2. Topic health check

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__triagent
Prompt template:
  "Check health of Kafka topic <topic_name> on cluster <cluster>.
   Check: partition count, replication factor, leader distribution,
   under-replicated partitions, message rate anomalies.
   Return: health verdict, any issues found, recommended action."
```

### 3. Pipeline blocked on Kafka

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wibey_pipeline_troubleshooter_agent
Prompt template:
  "Pipeline <pipeline_name> appears blocked waiting on Kafka topic <topic>.
   Consumer group: <group>.
   Last successful run: <timestamp or 'unknown'>.
   Error: <error message if any>.
   Investigate: whether consumer is connected, offset position, recent failures.
   Return: root cause, remediation steps."
```

## Input Parameters (when called by sar-investigate or sar-resolve)

```yaml
consumer_group: string          # Kafka consumer group name
topic: string                   # Topic name (optional — agent will discover)
cluster: string                 # Kafka cluster name (optional)
time_window_hours: int          # Default: 6
symptoms: string                # Free-text description of observed issue
task_type: enum                 # lag | topic_health | pipeline_blocked
```

## Output Contract

The skill returns the agent's response verbatim. Expect:
- Root cause hypothesis
- Lag numbers / offset positions
- Recommended action (immediate + long-term)
- Escalation path if agent cannot resolve

## Design Rules

- Do NOT hardcode cluster names, topic names, or consumer group names
- Always pass symptoms in plain English — the agent reasons from context
- If cluster is unknown, say so in the prompt — TRIAGENT will discover it
- Never assume lag is "normal" without asking the agent

## Integration with sar-investigate / sar-resolve

sar-investigate calls this skill when:
- Airflow task log mentions "kafka", "consumer", "lag", "offset"
- Pipeline SLA breach detected and upstream is a Kafka topic
- TRIAGENT correlation surfaces Kafka as probable cause

sar-resolve calls this skill when:
- Recommended action is offset reset, consumer restart, or rebalance trigger

## Limitations (scaffolded — not yet verified end-to-end)

- TRIAGENT is verified reachable (tested this session)
- Kafka-specific TRIAGENT tools depend on TRIAGENT having access to your Kafka cluster
- If TRIAGENT returns "cluster not found", provide the cluster FQDN explicitly
- Offset reset is an ops mutation — confirm with user before executing
