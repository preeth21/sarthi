---
name: "sar-concord"
key: "sar-concord"
description: "sArthI Concord skill — investigates Concord CI/CD pipeline failures, process status, and flow execution logs. Routes to WIBEY-PIPELINE-TROUBLESHOOTER-AGENT (primary) and WCNP-TROUBLESHOOTING-AGENT (for KITT/Helm failures originating in Concord). No sarthi local MCP for Concord."
allowed-tools: [mcp__plugin__wibey_wibey-core-mcp__wibey_pipeline_troubleshooter_agent, mcp__plugin__wibey_wibey-core-mcp__wcnp_troubleshooting_agent]
metadata:
  author: "sarthi"
  version: "1.0.0"
  part-of: "sarthi"
  status: "active"
  wraps: ["WIBEY-PIPELINE-TROUBLESHOOTER-AGENT", "WCNP-TROUBLESHOOTING-AGENT"]
---

# sar-concord — Concord CI/CD Investigation Skill

## Purpose

Investigate Concord pipeline failures, process status, flow logs, and deployment
failures triggered through Concord. Also handles Concord → KITT → WCNP deploy chains.

No sarthi local MCP for Concord. This skill is the sArthI integration point.

## When to Use

- Concord process is stuck, failed, or in an unexpected state
- Deployment triggered by Concord failed at Helm/KITT stage
- Need to retrieve Concord process logs by process ID or URL
- Flow execution timed out or retrying in a loop
- Concord triggered a WCNP rollout that failed

## Routing Logic

| Task type | Agent |
|-----------|-------|
| Process status, flow logs, failure root cause | WIBEY-PIPELINE-TROUBLESHOOTER-AGENT |
| KITT/Helm UPGRADE FAILED from Concord deploy | WCNP-TROUBLESHOOTING-AGENT |
| Gatekeeper block on Concord pipeline | WCNP-TROUBLESHOOTING-AGENT |
| Concord trigger questions, flow debugging | WIBEY-PIPELINE-TROUBLESHOOTER-AGENT |

## How to Invoke

### 1. Process failure investigation

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wibey_pipeline_troubleshooter_agent
Prompt template:
  "Investigate Concord process failure.
   Process ID: <process_id> (or URL: <concord_url>/process/<id>).
   Organization: <org_name or 'unknown'>.
   Project: <project_name or 'unknown'>.
   Symptoms: <describe failure — timeout, exception, step name>.
   Retrieve process logs and identify root cause.
   Return: failed step, error message, root cause hypothesis, recommended fix."
```

### 2. KITT/Helm deploy failure from Concord

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wcnp_troubleshooting_agent
Prompt template:
  "A Concord pipeline triggered a WCNP deployment that failed.
   Application: <app_name>.
   Namespace: <namespace>.
   Cluster: <cluster_name>.
   Error: <Helm UPGRADE FAILED message or 'check recent events'>.
   Check: pod events, Helm release state, Gatekeeper violations, KITT config.
   Return: root cause, whether rollback happened, fix recommendation."
```

### 3. Concord process status check

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wibey_pipeline_troubleshooter_agent
Prompt template:
  "Check status of Concord process <process_id or URL>.
   Return: current status, last completed step, any errors, estimated completion."
```

## Input Parameters

```yaml
process_id: string       # Concord process UUID or URL
org_name: string         # Concord organization (optional)
project_name: string     # Concord project name (optional)
app_name: string         # Application being deployed (optional)
namespace: string        # WCNP namespace (for KITT failures)
cluster: string          # WCNP cluster (for KITT failures)
symptoms: string         # Free-text failure description
task_type: enum          # process_failure | kitt_failure | status_check | trigger
```

## Output Contract

Returns agent response verbatim. Expect:
- Process status and failed step
- Root cause hypothesis
- Log excerpt at point of failure
- Recommended action (retry, config fix, escalate)

## Design Rules

- Never hardcode org names, project names, or Concord URLs
- Always pass the process ID or URL — agents can retrieve logs directly from it
- For KITT failures, always include namespace + cluster — WCNP agent needs them
- If process_id unknown, ask the user or search Concord UI

## Integration with sar-investigate / sar-resolve

sar-investigate routes to sar-concord when:
- Airflow task calls a Concord flow and the flow fails
- ServiceNow incident mentions "Concord", "KITT", or "Helm UPGRADE FAILED"
- Deploy pipeline SLA breached

sar-resolve routes here when:
- Fix requires re-triggering a Concord flow
- KITT config update needed after failure

## Limitations

- Process log retrieval depends on WIBEY-PIPELINE-TROUBLESHOOTER-AGENT having
  Concord API access for your organization
- If org/project unknown, the agent may need disambiguation
- Concord trigger (mutation) requires user confirmation before executing
