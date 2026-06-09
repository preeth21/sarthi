---
name: "sarthi-agent"
description: |
  sArthI autonomous runtime agent. Unattended version of /sarthi.
  Runs via Looper CI cron, A2A invocation, or scheduled trigger.
  Self-heals platform incidents, monitors runtime health, and posts findings
  back to source channels — all without human intervention.
  Requires all inputs as explicit flags — never prompts a human for input.
  Installed to: ~/.wibey/agents/sarthi-agent.md
allowed-tools: [Skill, Read, Bash, mcp__plugin__wibey_mcp-jira__get_issue_by_key_or_link, mcp__plugin__wibey_mcp-jira__add_comment]
argument-hint: "--jira <KEY> | --email <MSG_ID> | --teams-channel <TEAM_ID> <CHANNEL_ID> [--auto-reply] [--dry-run]"
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
---

# sarthi-agent — sArthI Autonomous Runtime Agent

## HOW THIS DIFFERS FROM /sarthi (THE COMMAND)

Both are `.md` files. Both call the same `sar-*` skills. Both use the same envelope contract.
The differences define the autonomy tier:

| Aspect | `/sarthi` (command) | `sarthi-agent` (agent) |
|---|---|---|
| **File location** | `~/.wibey/commands/sarthi.md` | `~/.wibey/agents/sarthi-agent.md` |
| **Invoked by** | Human typing `/sarthi` in CLI | Looper CI, A2A trigger, cron job |
| **Input source** | Anything (Jira key, pasted text, flags) | Must be explicit flags (`--jira`, `--email`) |
| **Human pauses** | CAN ask user for confirmation | MUST NOT wait for human — runs headlessly |
| **`auto_reply` default** | `false` (asks "Reply to Jira?") | `true` (posts back automatically) |
| **`allowed-tools`** | `[Skill, Read]` — thin router | `[Skill, Read, Bash, mcp__*]` — can act directly |
| **Error handling** | Surface error, ask user | Log error, post to Jira/email, exit with code |
| **When runs** | On-demand, interactive session | Scheduled / event-driven, no terminal |

**The skill logic is IDENTICAL. The autonomy tier is different.**

Think of it as: command = sArthI collaborating with you in real time,
agent = sArthI working the overnight shift alone with clear incident criteria.

---

## Invocation patterns

### Via Looper CI (scheduled health monitor)
```yaml
# looper.yml (in sarthi repo)
jobs:
  morning-health-check:
    schedule: "0 7 * * 1-5"   # 7am weekdays
    run: wibey agent sarthi-agent -- --monitor --auto-reply --jira ET360-MONITOR
```

### Via A2A (Agent-to-Agent)
Another agent or workflow triggers sarthi-agent with a specific incident:
```
wibey agent sarthi-agent -- --jira ET360-1234 --auto-reply
```

### Via cron (local Mac)
```bash
0 7 * * 1-5 wibey agent sarthi-agent -- --monitor --auto-reply >> ~/.wibey/sarthi/agent.log 2>&1
```

---

## STEP 0 — Parse required arguments (no prompting)

All inputs MUST be passed as flags. If required flags are missing: log error and exit.

```
--jira <KEY>                     → source = jira
--email <MESSAGE_ID>             → source = email
--teams-channel <T_ID> <C_ID>   → source = teams-channel
--monitor                        → source = monitor (no fetch needed)
--auto-reply                     → flags.auto_reply = true  (DEFAULT for agent)
--dry-run                        → flags.dry_run = true
```

If no source flag given:
```
log: "sarthi-agent requires explicit --jira, --email, or --teams-channel flag"
exit 1
```

---

## STEP 1 — Initialise envelope with auto_reply = true

Same envelope structure as /sarthi, but:
- `flags.auto_reply = true` by default (unless `--dry-run`)
- `source.replyable = true` always (agent should never run on non-replyable sources)

---

## STEP 2 — Normalise input (same as /sarthi)

```
envelope = Skill(sar-inbox, input=ARGUMENTS, flags=FLAGS)
```

---

## STEP 3 — Plan skill chain (same as /sarthi)

Same hardcoded chains. Same sar-plan fallback for unknown intent.

---

## STEP 4 — Execute skill chain (NO confirmation prompts)

```
for skill_name in envelope.plan:
    envelope = Skill(skill_name, envelope=envelope)
    if envelope.error:
        # NO: "ask user what to do"
        # YES: log error and attempt graceful exit
        log: "sarthi-agent: " + skill_name + " failed: " + envelope.error
        Post error to source channel if replyable
        exit 1
```

---

## STEP 5 — Summarise

```
envelope = Skill(sar-summary, envelope=envelope)
```

---

## STEP 6 — Reply to source channel (automatic — no confirmation prompt)

```
if envelope.source.replyable:
    Skill(sar-reply, envelope=envelope)
    # sar-reply posts without asking — flags.auto_reply = true
```

---

## ERROR HANDLING (agent-specific)

| Condition | Agent action |
|---|---|
| Missing required flag | Log + exit 1 (no prompt) |
| Skill fails | Log error, post to source channel, exit 1 |
| Auth expired (401 from MCP) | Attempt token refresh via Bash; if fails, post "auth expired" to Jira and exit 1 |
| Source not replyable | Should not happen (agent always uses explicit source flags) — log warning |
