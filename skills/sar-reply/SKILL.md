---
name: "sar-reply"
key: "sar-reply"
description: "Posts the sArthI resolution summary back to the original source channel. Routes by envelope.source.channel: Jira comment, Outlook reply, Teams post, Slack message. Channel-agnostic dispatcher — the final step in every skill chain."
allowed-tools: [Read, mcp__plugin__wibey_mcp-jira__add_comment, mcp__sarthi-msgraph__mail_reply, mcp__sarthi-msgraph__mail_send, mcp__sarthi-msgraph__teams_send_channel_message, mcp__sarthi-msgraph__teams_send_direct_message]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "placeholder"
---

# sar-reply — Channel Reply Dispatcher

## Purpose
Post the sArthI resolution summary back to the originating channel after all action skills complete.
Routes based on `envelope.source.channel` — the skill itself is channel-agnostic.

## Status: PLACEHOLDER

## TODO — implement:

### Route by envelope.source.channel:

**jira:**
```
mcp__plugin__wibey_mcp-jira__add_comment(
    issue_key = envelope.source.id,
    comment = envelope.artifacts[type=="summary"].text
)
```

**email:**
```
mcp__sarthi-msgraph__mail_reply(
    message_id = envelope.source.reply_context.message_id,
    body = envelope.artifacts[type=="summary"].text,
    reply_all = false
)
# Note: mail_reply requires MSGRAPH_SEND_ALLOWED=true in sarthi-msgraph env.
# If flags.auto_reply = false → show draft to user and confirm before calling.
```

**teams-channel:**
```
mcp__sarthi-msgraph__teams_send_channel_message(
    team_id = envelope.source.reply_context.team_id,
    channel_id = envelope.source.reply_context.channel_id,
    content = envelope.artifacts[type=="summary"].text,
    content_type = "text"
)
# Requires MSGRAPH_SEND_ALLOWED=true.
```

**teams-chat:**
```
mcp__sarthi-msgraph__teams_send_direct_message(
    user_email = envelope.source.reply_context.reply_to,
    content = envelope.artifacts[type=="summary"].text,
    content_type = "text"
)
# Requires MSGRAPH_SEND_ALLOWED=true.
```

**slack (FUTURE):**
```
# SLACK-TODO: slack_mcp.chat_postMessage(channel=..., thread_ts=..., text=...)
```

**freetext / not replyable:**
```
# Do nothing — summary was already shown in CLI by sar-summary
```

## Expected output
- Reply posted to source channel
- `envelope.artifacts` updated with `{ type: "reply-sent", channel: "...", timestamp: "..." }`
