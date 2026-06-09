---
name: "sar-looper"
key: "sar-looper"
description: "sArthI LooperPro skill — investigates LooperPro CI build failures, pipeline status, and test results. Routes to WIBEY-PIPELINE-TROUBLESHOOTER-AGENT which has native LooperPro coverage. No sarthi local MCP for Looper."
allowed-tools: [mcp__plugin__wibey_wibey-core-mcp__wibey_pipeline_troubleshooter_agent]
metadata:
  author: "sarthi"
  version: "1.0.0"
  part-of: "sarthi"
  status: "active"
  wraps: ["WIBEY-PIPELINE-TROUBLESHOOTER-AGENT"]
---

# sar-looper — LooperPro CI Investigation Skill

## Purpose

Investigate LooperPro CI/CD build failures, pipeline status, test failures,
and deployment gate blocks. Routes exclusively to WIBEY-PIPELINE-TROUBLESHOOTER-AGENT
which has native LooperPro tooling.

No sarthi local MCP for LooperPro. This skill is the sArthI integration point.

## When to Use

- LooperPro build failed or is stuck
- Need build logs for a specific run
- Test stage failing in LooperPro pipeline
- Sonar/Snyk gate blocking the build
- Need to understand why the last N builds failed
- LooperPro → WCNP deploy triggered but status unknown

## Routing Logic

All tasks → WIBEY-PIPELINE-TROUBLESHOOTER-AGENT

WIBEY-PIPELINE-TROUBLESHOOTER-AGENT explicitly lists LooperPro as a covered platform
alongside Concord and OneOps.

## How to Invoke

### 1. Build failure investigation

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wibey_pipeline_troubleshooter_agent
Prompt template:
  "Investigate LooperPro build failure.
   Repository: <repo_name> (GEC GitHub: gecgithub01.walmart.com/<org>/<repo>).
   Build ID or URL: <build_id or looper_url>.
   Branch: <branch_name>.
   Stage that failed: <stage name or 'unknown'>.
   Error: <error message if visible>.
   Retrieve build logs and identify root cause.
   Return: failed stage, error, root cause hypothesis, fix recommendation."
```

### 2. Build status check

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wibey_pipeline_troubleshooter_agent
Prompt template:
  "Check status of LooperPro pipeline for repository <repo_name>.
   Branch: <branch>.
   Return: last 3 build statuses, current build state, any active failures."
```

### 3. Test failure analysis

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wibey_pipeline_troubleshooter_agent
Prompt template:
  "LooperPro build <build_id> failed at test stage.
   Repository: <repo_name>.
   Retrieve test results and identify failing tests.
   Check: unit test failures, integration test failures, flaky test patterns.
   Return: failing test names, failure messages, whether failures are new or recurring."
```

### 4. Gate block investigation

```
Use tool: mcp__plugin__wibey_wibey-core-mcp__wibey_pipeline_troubleshooter_agent
Prompt template:
  "LooperPro build for <repo_name> is blocked by a quality/security gate.
   Build ID: <build_id>.
   Gate type: <Sonar | Snyk | Gatekeeper | unknown>.
   Retrieve gate results and explain what needs to be fixed.
   Return: gate violations, severity, required fix, bypass eligibility."
```

## Input Parameters

```yaml
repo_name: string        # Repository name (org/repo format)
build_id: string         # LooperPro build ID or URL (optional)
branch: string           # Git branch (default: main)
stage: string            # Failed pipeline stage (optional)
error_message: string    # Error if already known (optional)
task_type: enum          # build_failure | status_check | test_failure | gate_block
```

## Output Contract

Returns agent response verbatim. Expect:
- Build status and failed stage
- Log excerpt at point of failure
- Root cause hypothesis
- Fix recommendation (code change, config fix, gate exemption request)

## Design Rules

- Never hardcode repo names, build IDs, or org names
- Always pass the repo as `org/repo` format for GEC GitHub
- If build_id unknown, ask user for the LooperPro URL
- Gate bypasses are mutations — confirm with user before executing

## Integration with sar-investigate / sar-resolve

sar-investigate routes to sar-looper when:
- ServiceNow incident mentions "LooperPro", "looper", "build failed"
- Code review completed but CI is red blocking merge
- Deployment blocked due to CI gate failure

sar-resolve routes here when:
- Fix requires re-triggering a LooperPro build
- Gate exemption request needs to be filed

## Limitations

- Build log retrieval depends on WIBEY-PIPELINE-TROUBLESHOOTER-AGENT having
  LooperPro API access for your org
- Build re-trigger (mutation) requires user confirmation
- If LooperPro URL structure has changed, update the prompt with the current URL pattern
