---
name: "sar-wcnp-ops"
key: "sar-wcnp-ops"
description: "sArthI WCNP deep-ops skill — handles KITT config generation/updates, Helm deploy failures, Gatekeeper violations, CCM config changes, and Istio/latency/5xx anomalies. Complements sarthi-wcnp (which does read-only kubectl ops). Routes to WCNP-TROUBLESHOOTING-AGENT for KITT/Helm/CI-CD chain issues."
allowed-tools: [mcp__plugin__wibey_wibey-core-mcp__wcnp_troubleshooting_agent, mcp__plugin__wibey_sarthi-wcnp__wcnp_get_pods, mcp__plugin__wibey_sarthi-wcnp__wcnp_get_logs, mcp__plugin__wibey_sarthi-wcnp__wcnp_describe_pod, mcp__plugin__wibey_sarthi-wcnp__wcnp_get_events, mcp__plugin__wibey_sarthi-wcnp__wcnp_get_deployments]
metadata:
  author: "sarthi"
  version: "1.0.0"
  part-of: "sarthi"
  status: "active"
  wraps: ["WCNP-TROUBLESHOOTING-AGENT"]
  complements: ["sarthi-wcnp"]
---

# sar-wcnp-ops — WCNP Deep Ops Skill

## Purpose

Handles WCNP issues that go beyond raw kubectl reads — KITT config, Helm deploys,
Gatekeeper violations, CCM changes, and Istio anomalies.

**Division of responsibility:**

| Layer | Tool |
|-------|------|
| Raw kubectl (pods, logs, events, rollout restart, scale) | `sarthi-wcnp` MCP |
| KITT config, Helm failures, Gatekeeper, CCM, Istio/5xx | `sar-wcnp-ops` (this skill) |
| Concord → KITT deploy chain | `sar-concord` (routes here for KITT failures) |

## When to Use

- Helm UPGRADE FAILED during deployment
- Pod failing due to KITT misconfiguration (probes, resources, env)
- Gatekeeper policy violation blocking deployment
- CCM config change causing pod instability
- Istio / service mesh errors (503, mTLS failures)
- Need to generate or update a KITT YAML file
- OOMKill analysis requiring historical context
- NPD (Node Problem Detector) events causing pod evictions

## Routing Logic

All tasks → WCNP-TROUBLESHOOTING-AGENT

For raw pod/log inspection first, use sarthi-wcnp MCP tools, then pass findings
to WCNP-TROUBLESHOOTING-AGENT for deep analysis.

## How to Invoke

### 1. Helm deploy failure

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wcnp_troubleshooting_agent
Prompt template:
  "Helm deployment failed for application <app_name>.
   Namespace: <namespace>.
   Cluster: <cluster_name>.
   Error: <Helm UPGRADE FAILED message>.
   Recent pod events (from sarthi-wcnp): <paste wcnp_get_events output>.
   Investigate: Gatekeeper violations, resource quota, probe failures, image pull errors.
   Return: root cause, whether rollback happened, fix steps."
```

### 2. KITT config generation

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wcnp_troubleshooting_agent
Prompt template:
  "Generate a KITT configuration for a new deployment.
   Application: <app_name>.
   Namespace: <namespace>.
   Cluster: <cluster_name>.
   Requirements:
     - Replicas: <count>
     - Container image: <image_path>
     - Port: <port>
     - Resource requests/limits: <cpu/memory or 'use defaults'>
     - Health check path: <path or '/health'>
     - Any special config: <env vars, secrets, etc.>
   Return: complete KITT YAML, validation result, PR creation steps."
```

### 3. KITT config update

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wcnp_troubleshooting_agent
Prompt template:
  "Update KITT configuration for <app_name> in namespace <namespace>.
   Current issue: <describe problem — OOMKill, probe failing, etc.>.
   Desired change: <increase memory limit | fix probe path | add env var | etc.>.
   Repository: <kitt_repo_path or 'auto-discover'>.
   Return: proposed KITT diff, validation result, PR creation steps."
```

### 4. Gatekeeper violation

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wcnp_troubleshooting_agent
Prompt template:
  "Gatekeeper policy is blocking deployment of <app_name> in <namespace>/<cluster>.
   Violation message: <paste Gatekeeper error>.
   Explain the violated policy and provide the exact KITT/manifest change
   needed to comply. Return: policy name, what is wrong, fix diff."
```

### 5. Istio / 5xx investigation

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wcnp_troubleshooting_agent
Prompt template:
  "Service <service_name> in namespace <namespace> on cluster <cluster>
   is returning 5xx errors / Istio mTLS failures.
   Time window: last <N> hours.
   Pod events (from sarthi-wcnp): <paste relevant events>.
   Investigate: Istio sidecar state, destination rules, mTLS policy, service port config.
   Return: root cause, fix recommendation."
```

## Enrichment Pattern (use sarthi-wcnp first)

For best results, enrich WCNP-TROUBLESHOOTING-AGENT prompts with live kubectl data
from sarthi-wcnp MCP tools:

```
Step 1: Call sarthi-wcnp MCP tools to collect raw state:
  - wcnp_get_pods       → pod status snapshot
  - wcnp_get_events     → recent warning events
  - wcnp_get_logs       → last 100 lines of failing pod
  - wcnp_describe_pod   → full pod spec + conditions

Step 2: Paste this output into the WCNP-TROUBLESHOOTING-AGENT prompt context.
  The agent can then do deeper analysis without re-fetching the same data.
```

## Input Parameters

```yaml
app_name: string         # Application / deployment name
namespace: string        # WCNP namespace
cluster: string          # WCNP cluster name
task_type: enum          # helm_failure | kitt_generate | kitt_update | gatekeeper | istio | oomkill
error_message: string    # Error text if known
kubectl_context: string  # Raw output from sarthi-wcnp tools (optional enrichment)
```

## Output Contract

Returns agent response verbatim. Expect:
- Root cause analysis
- KITT YAML diff or full config (for generate/update tasks)
- PR creation steps (for config changes)
- Policy name + fix for Gatekeeper violations

## Design Rules

- Never hardcode namespace, cluster, or app names
- Use sarthi-wcnp for raw data collection; use this skill for analysis and config ops
- KITT mutations (config update, PR creation) require user confirmation
- Rollout restart after fix → use sarthi-wcnp wcnp_rollout_restart

## Integration with sar-investigate / sar-resolve

sar-investigate routes here when:
- Helm UPGRADE FAILED in ServiceNow incident
- OOMKill events detected by sarthi-wcnp
- Gatekeeper blocking a pipeline (from sar-concord)
- Istio 503 in service mesh

sar-resolve routes here when:
- Fix requires KITT config change + PR

## Limitations

- WCNP-TROUBLESHOOTING-AGENT needs access to your WCNP cluster
- sarthi-wcnp raw kubectl access currently blocked (network routing issue — see wcnp dev log)
- KITT PR creation is automated by the agent but requires GEC GitHub auth (sarthi-git)
