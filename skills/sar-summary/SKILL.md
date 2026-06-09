---
name: "sar-summary"
key: "sar-summary"
description: "sArthI's reporting skill. Formats all envelope.artifacts into a clear, human-readable health and resolution report — what was investigated, what actions were taken, links to PRs/CRQs, and any remaining manual steps. Saves to sarthi history and feeds sar-reply."
allowed-tools: [Read, Write]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "placeholder"
---

# sar-summary — Health & Resolution Report Generator

## Purpose
sArthI always closes the loop. After every skill chain, this skill assembles
a complete summary of what happened — so the team has a record, and so `sar-reply`
has content to post back to the originating channel.

## Status: PLACEHOLDER

## TODO — implement:

- [ ] Read `envelope.artifacts[]` — all actions and findings produced by the chain
- [ ] Read `envelope.intent` — what was the original request
- [ ] Format into a structured summary covering:
  - **What triggered this** — source channel, Jira key or description
  - **What sArthI found** — investigation findings, root cause hypothesis
  - **Actions taken** — PRs merged, CRQs raised, tasks cleared, backfills triggered
  - **Links** — PR URL, CRQ number, Jira ticket
  - **Remaining manual steps** — what still needs a human (e.g., set CRQ dates, approve PR)
  - **Reply channel** — where sArthI will post this summary
- [ ] Save summary to `~/.wibey/sarthi/history/<ISO-date>-<jira-key>.md`
- [ ] Add summary text to `envelope.artifacts[]`

## Summary output format (markdown)
```markdown
## sArthI Report — <date>

**Source:** <channel> / <id>
**Intent:** <incident | bugfix | new-feature | question>
**Summary:** <one-line>

### Findings
- <finding 1>
- <finding 2>
Root cause: <hypothesis>

### Actions Taken
- ✅ <action 1> — <detail>
- ✅ <action 2> — <detail>

### Artifacts
- PR: <URL>
- CRQ: <CHG_NUMBER> — <ServiceNow URL>
- Jira: <KEY>

### Remaining Steps (manual)
- ☐ <step 1>
- ☐ <step 2>
```

## Expected output
- `envelope.artifacts` updated with:
```json
{
  "type": "summary",
  "text": "<markdown summary>",
  "saved_to": "~/.wibey/sarthi/history/<filename>.md"
}
```
- Summary printed to user in the CLI before `sar-reply` posts it
