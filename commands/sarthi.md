---
name: sarthi
description: |
  sArthI — Self-healing Autonomous Runtime Troubleshooting & Health Intelligence.
  Accepts a Jira key, Teams/email thread, Slack message, or free-text description
  and orchestrates a chain of action skills to detect, investigate, and resolve
  runtime incidents, health breaches, and platform issues autonomously.
  Installed via: cd ~/sarthi && bash setup.sh  (symlinks to ~/.wibey/commands/)
allowed-tools: [Skill, Read]
argument-hint: "<jira-key | 'email' | 'teams' | 'slack' | free-text> [--auto-reply] [--dry-run]"
---

# /sarthi — sArthI: Self-healing Autonomous Runtime Troubleshooting & Health Intelligence

Parse FLAGS from ARGUMENTS:
- `--auto-reply`  → reply to source channel without asking
- `--dry-run`     → plan the skill chain but do not execute
- `sync`          → shortcut: skip inbox, call Skill(sar-sync) directly
- `setup`         → shortcut: skip inbox, call Skill(sar-setup) directly
- `monitor`       → shortcut: skip inbox, call Skill(sar-monitor) directly

---

## Inter-Skill Envelope (contract between all skills)

Every skill receives and returns a JSON object with this shape.
Skills MUST pass the envelope forward; they add to it, never replace it.

```json
{
  "source": {
    "channel": "jira | teams | email | slack | freetext",
    "id":      "<jira-key | message-id | thread-ts | null>",
    "raw":     "<original text>",
    "replyable": true
  },
  "intent": {
    "type": "bugfix | new-feature | question | incident | crq | sync | monitor | unknown",
    "summary": "<one-line description>",
    "entities": {
      "dag_id": "<if present>",
      "table":  "<if present>",
      "env":    "prod | staging | dev"
    }
  },
  "context": {
    "team_member": "<from team.json>",
    "lineage":     {},
    "history":     []
  },
  "artifacts": [],
  "plan": [],
  "flags": {
    "auto_reply": false,
    "dry_run": false
  }
}
```

---

## STEP 0 — First-run detection & shortcuts

```
# First-run auto-detect
AUTH_SENTINEL = Read("~/.wibey/sarthi/.auth-complete")
if AUTH_SENTINEL is missing or contains "failed":
    Tell user:
      "Welcome to sArthI! It looks like this is your first time.
       Before I can help, please run the installer in your terminal:

         git clone https://gecgithub01.walmart.com/WITDnA/sarthi.git ~/sarthi && bash ~/sarthi/install.sh

       This takes ~15 minutes (includes Wibey setup + 6 one-time auth logins).
       Once done, restart Wibey and type /custom/sarthi again."
    STOP

# Shortcuts (subcommands)
if ARGUMENTS starts with "sync":
    Skill(sar-sync)
    STOP

if ARGUMENTS starts with "setup":
    Skill(sar-setup)
    STOP

if ARGUMENTS starts with "monitor":
    Skill(sar-monitor)
    STOP
```

---

## STEP 1 — Read team context

```
Read ~/.wibey/knowledge/team.json
Read ~/.wibey/knowledge/environments.json
```

---

## STEP 2 — Normalise input → envelope (sar-inbox)

Pass ARGUMENTS and FLAGS to sar-inbox.

```
envelope = Skill(sar-inbox, input=ARGUMENTS, flags=FLAGS)
```

`sar-inbox` will:
- Detect source channel from the input:
  - `[A-Z]+-\d+` pattern → pull full ticket via mcp-jira
  - `--email` or `--teams` hint → pull thread via msgraph skill
  - `--slack` hint → pull thread via Slack MCP (when available)
  - Otherwise → treat as free-text, `source.replyable = false`
- Classify intent type and extract entities (DAG name, table, environment)
- Return the populated envelope

---

## STEP 3 — Plan the skill chain (sar-plan)

For known intents, use the hardcoded chains below.
For `unknown` intent or when `envelope.intent.entities` suggests multiple issues,
call `sar-plan` to dynamically produce the skill sequence:

```
if envelope.intent.type == "unknown" or envelope.plan is empty:
    envelope = Skill(sar-plan, envelope=envelope)
```

**Hardcoded chains (skip sar-plan for these):**

| intent.type    | Skill chain                                                    |
|----------------|----------------------------------------------------------------|
| `incident`     | sar-investigate → sar-resolve → sar-crq → sar-reply           |
| `bugfix`       | sar-investigate → sar-propose-fix → sar-pr → sar-reply        |
| `new-feature`  | sar-feature-spec → sar-scaffold → sar-pr → sar-reply          |
| `question`     | sar-answer → sar-reply                                         |
| `crq`          | sar-crq → sar-reply                                            |
| `monitor`      | sar-monitor → sar-reply                                        |

---

## STEP 4 — Execute skill chain

Execute each skill in `envelope.plan` sequentially.
Each skill receives the full envelope and returns an updated envelope.

```
for skill_name in envelope.plan:
    if FLAGS.dry_run:
        print("Would call: " + skill_name)
        continue
    envelope = Skill(skill_name, envelope=envelope)
    if envelope.error:
        print("❌ " + skill_name + " failed: " + envelope.error)
        STOP and ask user how to proceed
```

---

## STEP 5 — Summarise (sar-summary)

```
envelope = Skill(sar-summary, envelope=envelope)
```

Present the summary to the user. Show:
- What was done (artifacts produced: PRs, CRQs, fixes)
- Any remaining manual steps
- Source channel that will receive the reply

---

## STEP 6 — Reply to source channel (sar-reply)

```
if envelope.source.replyable:
    if FLAGS.auto_reply:
        Skill(sar-reply, envelope=envelope)
    else:
        Ask: "Reply to {envelope.source.channel} ({envelope.source.id})? [y/N]"
        if yes:
            Skill(sar-reply, envelope=envelope)
```

`sar-reply` routes by `envelope.source.channel`:
- `jira`   → add comment via mcp-jira
- `teams`  → reply to thread via msgraph skill
- `email`  → send reply via msgraph skill
- `slack`  → post to thread via Slack MCP

---

## ERROR HANDLING

| Condition                          | Action                                                  |
|------------------------------------|---------------------------------------------------------|
| sar-inbox returns unknown intent   | Call sar-plan; surface plan to user for confirmation    |
| Any skill returns envelope.error   | Pause chain; show error; ask user to continue or abort  |
| Source channel is not replyable    | Skip STEP 6 silently                                    |
| --dry-run set                      | Print plan only; skip all Skill() calls after sar-inbox |
