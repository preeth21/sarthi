---
name: "sar-inbox"
key: "sar-inbox"
description: "Normalises any input channel (Jira, Outlook, Teams, Slack, free-text) into the sArthI envelope. Detects source, fetches content via MCP, classifies runtime intent (incident, bugfix, question, new-feature, crq, monitor), extracts entities."
allowed-tools: [Read, Bash, mcp__plugin__wibey_mcp-jira__get_issue_by_key_or_link, mcp__plugin__wibey_mcp-jira__jql_based_search, mcp__sarthi-msgraph__mail_get, mcp__sarthi-msgraph__mail_search, mcp__sarthi-msgraph__mail_list, mcp__sarthi-msgraph__teams_list_teams, mcp__sarthi-msgraph__teams_list_channels, mcp__sarthi-msgraph__teams_list_channel_messages]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
---

# sar-inbox — Input Channel Normaliser

## Purpose
Accept any input and produce a fully-populated **sArthI Envelope** that all downstream skills consume.

## Inputs (from caller)
- `input`  — the raw argument string passed to `/sarthi`
- `flags`  — `{ auto_reply, dry_run }` object

---

## STEP 0 — Initialise empty envelope

```json
{
  "source": {
    "channel": null,
    "id": null,
    "raw": "<input>",
    "replyable": false,
    "fetched_content": null
  },
  "intent": {
    "type": null,
    "summary": null,
    "entities": {
      "dag_id": null,
      "table": null,
      "env": null,
      "jira_key": null,
      "market": null
    }
  },
  "context": {
    "team_member": null,
    "lineage": {},
    "history": []
  },
  "artifacts": [],
  "plan": [],
  "flags": "<flags>",
  "error": null
}
```

Set `envelope.source.raw = input`.

---

## STEP 1 — Detect source channel

Work through these checks **in order** (first match wins):

### 1a. Explicit flags override everything
```
if input contains "--jira <KEY>":
    extract KEY
    channel = "jira"
    id = KEY

if input contains "--email <MESSAGE_ID>":
    extract MESSAGE_ID
    channel = "email"
    id = MESSAGE_ID

if input contains "--teams-channel <TEAM_ID> <CHANNEL_ID>":
    extract TEAM_ID and CHANNEL_ID
    channel = "teams-channel"
    id = TEAM_ID + "/" + CHANNEL_ID

if input contains "--teams-chat <CHAT_ID>":
    extract CHAT_ID
    channel = "teams-chat"
    id = CHAT_ID

# Slack is not yet connected — accept flag for future use
if input contains "--slack-ts <TS> --slack-channel <CHANNEL>":
    channel = "slack"
    id = CHANNEL + "/" + TS
    # FALL THROUGH to free-text — Slack MCP not yet registered
    # SLACK-TODO: when Slack MCP is available, fetch here
    channel = "freetext"
    id = null
```

### 1b. Pattern detection on raw text
```
if input matches /^[A-Z]+-\d+$/ (standalone Jira key):
    channel = "jira"
    id = input.trim()

elif input matches /[A-Z]+-\d+/ (Jira key embedded in text):
    extract first match as id
    channel = "jira"
    note: other text may provide context — keep full input as raw

elif input contains "From:" AND ("Subject:" OR "Sent:"):
    channel = "email-paste"  # user pasted an email, no live fetch possible
    id = null
    replyable = false

elif input contains ("Hi team" OR "Hi all" OR "@" with domain) AND length > 100:
    channel = "teams-paste"  # user pasted a Teams message
    id = null
    replyable = false

else:
    channel = "freetext"
    id = null
    replyable = false
```

Set `envelope.source.channel = channel` and `envelope.source.id = id`.

---

## STEP 2 — msgraph auth check (before any email/Teams fetch)

**No explicit auth check needed.** The `sarthi-msgraph` MCP server handles auth internally
and returns `{"error": "auth_expired"}` if the token is missing or expired. It NEVER
opens a browser — safe for cron and non-interactive runs.

If `channel` is one of `email`, `teams-channel`, `teams-chat`:
```
Any sarthi-msgraph tool call that returns {"error": "auth_expired"}:
    envelope.error = "Microsoft auth expired. Run /msgraph login interactively in Wibey once to re-authenticate."
    STOP
```

---

## STEP 3 — Fetch content (if live source)

### 3a. Jira
```
if channel == "jira":
    issue = mcp__plugin__wibey_mcp-jira__get_issue_by_key_or_link(key=id)
    envelope.source.fetched_content = {
        "key": issue.key,
        "summary": issue.summary,
        "description": issue.description,
        "status": issue.status,
        "assignee": issue.assignee,
        "labels": issue.labels,
        "comments": issue.comments[-3:]  # last 3 comments
    }
    envelope.source.replyable = true
```

### 3b. Outlook email

```
if channel == "email":
    result = mcp__sarthi-msgraph__mail_get(message_id=id)
    if result.error == "auth_expired": → envelope.error = result.fix; STOP
    envelope.source.fetched_content = {
        "subject": result.subject,
        "from": result.from,
        "to": result.toRecipients,
        "body": result.body.content,
        "received": result.receivedDateTime,
        "message_id": result.id
    }
    envelope.source.replyable = true
    envelope.source.reply_context = { "message_id": id, "reply_to": result.from }
```

If no `--email` flag but user says "email from X" or "latest email about Y":
```
    search_term = <extracted from input, e.g. "pipeline failure">
    result = mcp__sarthi-msgraph__mail_search(query=search_term, limit=3)
    if result.error == "auth_expired": → envelope.error = result.fix; STOP
    envelope.source.fetched_content = result.messages[0]
    envelope.source.replyable = true
    envelope.source.reply_context = { "message_id": result.messages[0].id }
```

### 3c. Teams channel

```
if channel == "teams-channel":
    [team_id, channel_id] = id.split("/")
    result = mcp__sarthi-msgraph__teams_list_channel_messages(team_id=team_id, channel_id=channel_id, limit=5)
    if result.error == "auth_expired": → envelope.error = result.fix; STOP
    relevant = result.messages[0]
    envelope.source.fetched_content = {
        "team_id": team_id,
        "channel_id": channel_id,
        "message": relevant.body.content,
        "from": relevant.from.user.displayName,
        "timestamp": relevant.createdDateTime,
        "message_id": relevant.id
    }
    envelope.source.replyable = true
    envelope.source.reply_context = {
        "team_id": team_id,
        "channel_id": channel_id,
        "content_type": "text"
    }
    # NOTE: Teams thread replies are NOT fetchable. Top-level only (TEAMS-THREAD-TODO).
```

### 3d. Teams chat / DM

```
if channel == "teams-chat":
    # /me/chats requires tenant admin consent — not available at Walmart.
    # Fall back to freetext with a note.
    envelope.source.channel = "freetext"
    envelope.source.replyable = false
    envelope.source.fetched_content = envelope.source.raw
    Add note to envelope.artifacts: "⚠️ Teams DM/chat list requires tenant admin consent — used raw text instead"
```

### 3e. Slack (FUTURE — not yet implemented)
```
if channel == "slack":
    # Slack MCP not registered in ~/.wibey/mcp.json
    # SLACK-TODO: when registered, use:
    #   slack_mcp.conversations_replies(channel=channel_id, ts=ts)
    envelope.source.channel = "freetext"
    envelope.source.replyable = false
    envelope.source.fetched_content = envelope.source.raw
    Add note to envelope.artifacts: "⚠️ Slack MCP not configured — used raw text"
```

### 3f. Pasted content (email-paste, teams-paste, freetext)
```
envelope.source.fetched_content = envelope.source.raw
envelope.source.replyable = false
```

---

## STEP 4 — Classify intent and extract entities

Using `envelope.source.fetched_content` as the text to analyse:

### Intent classification rules (apply in order, first match wins)

| Signal | intent.type |
|---|---|
| Jira status is "In Progress" / "Open" AND labels contain "bug" or "defect" | `bugfix` |
| Subject/summary contains "incident" / "failure" / "DAG failed" / "SLA breach" | `incident` |
| Jira issue type is "Story" or "Feature" OR contains "implement" / "build" / "create" | `new-feature` |
| Contains "CRQ" / "change request" / "change window" | `crq` |
| Contains "?" and no DAG/table error signals | `question` |
| `/sarthi monitor` subcommand detected | `monitor` |
| DAG name or table name present with error keywords | `incident` |
| None of the above | `unknown` |

### Entity extraction
Look for and set in `envelope.intent.entities`:

```
dag_id:  any string matching "dag_id=" or "<word>_dag" or "DAG: <name>" patterns
table:   any fully-qualified table reference (project.dataset.table or schema.table)
env:     "prod" | "staging" | "dev" from context clues
jira_key: the Jira key if source was jira
market:  "ca" | "mx" | "sa" | "cl" | "ww" from context
```

Set:
```
envelope.intent.type = <classified type>
envelope.intent.summary = <one-line description of the issue>
envelope.intent.entities = <extracted entities>
```

---

## STEP 5 — Load team context

```
Read ~/.wibey/knowledge/team.json
```

Find the entry matching the current user (from `git config user.email` or `$USER`).
Set `envelope.context.team_member = { name, email, market_focus, role }`.

---

## STEP 6 — Set replyable and validate

Final checks:
```
if channel in ["jira", "email", "teams-channel", "teams-chat"]:
    envelope.source.replyable = true

if envelope.intent.type is null:
    envelope.intent.type = "unknown"

if envelope.source.fetched_content is null:
    envelope.error = "Could not fetch content from channel: " + channel
```

---

## STEP 7 — Return envelope

Return the fully-populated envelope to the caller (`/sarthi` command).

---

## Channel Support Matrix

| Channel | Read | Reply | Notes |
|---|---|---|---|
| Jira | ✅ live via mcp-jira | ✅ comment | Full issue + comments |
| Outlook email | ✅ live via msgraph | ✅ reply | Requires msgraph auth |
| Teams channel | ✅ live via msgraph | ✅ post | Top-level only; no thread replies (TEAMS-THREAD-TODO) |
| Teams chat/DM | ✅ live via msgraph | ✅ DM | List chats endpoint |
| Slack | ❌ no MCP | ❌ | Falls back to freetext; SLACK-TODO |
| Email paste | ✅ parsed from text | ❌ | No live send possible |
| Teams paste | ✅ parsed from text | ❌ | No live send possible |
| Free text | ✅ raw | ❌ | Always works |
| ServiceNow incident | 🔄 via wibey-core-mcp | 🔄 | Add --snow-inc <INC> flag: SNOW-TODO |

---

## Extension Points

To add a new channel:
1. Add detection in STEP 1 (new `elif` branch)
2. Add fetch logic in STEP 3 (new `if channel == "X":` block)
3. Register the channel's MCP in `~/sarthi/mcp/sarthi-mcp-additions.json`
4. Update the Channel Support Matrix above
5. Add the MCP tool name to this skill's `allowed-tools` frontmatter

The envelope contract does not change — downstream skills are channel-agnostic.
