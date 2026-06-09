---
name: "sar-plan"
key: "sar-plan"
description: "sArthI's dynamic reasoning engine. When intent is unknown or input contains multiple interleaved issues, this skill analyses the envelope and constructs an ordered sar-* skill chain. For multi-issue inputs it can split into sub-envelopes. Always presents the plan to the user for confirmation before returning."
allowed-tools: [Read]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "placeholder"
---

# sar-plan — Dynamic Skill Chain Planner

## Purpose
sArthI's reasoning layer for ambiguous or multi-issue inputs. When `/sarthi`
encounters `intent.type == "unknown"` or detects that the input spans multiple
distinct problems, this skill reasons about what needs to happen and produces a
concrete, ordered skill plan.

## Status: PLACEHOLDER

## TODO — implement:

- [ ] Read full envelope (intent, entities, source content, raw text)
- [ ] Reason about what actions are needed using the intent signals
- [ ] Produce `envelope.plan` = ordered list of `sar-*` skill names
- [ ] If ambiguous: present plan to user and ask for confirmation before returning
- [ ] For multi-issue inputs: split into sub-envelopes (one per distinct issue)
- [ ] Update `envelope.intent.type` if reasoning clarified it

## Plan construction logic

```
Read envelope.source.fetched_content
Read envelope.intent.entities

if multiple DAG IDs detected with errors:
    → split into N sub-envelopes, each with intent.type = "incident"
    → each runs: sar-investigate → sar-resolve → sar-crq → sar-reply

if text has both "new feature" and "existing DAG failing":
    → plan = [sar-investigate, sar-resolve, sar-feature-spec, sar-scaffold, sar-pr, sar-reply]

if intent clues point to crq but no PR URL found yet:
    → plan = [sar-pr, sar-crq, sar-reply]

if completely opaque:
    → show user: "I'm not sure what to do. Is this an (a) incident, (b) feature request, (c) question?"
    → wait for user selection, then set plan accordingly
```

## Known patterns to handle
- "Two DAGs failed overnight" → two parallel `incident` chains
- "We need to add CA data to the backfeed" → `new-feature` chain
- "Something is wrong with the pipeline" → investigate first, then plan
- "Can you raise a CRQ for the PR I just merged?" → `crq` chain only

## Expected inputs
- `envelope` with `intent.type = "unknown"` or complex multi-issue content

## Expected output
- `envelope.plan = ["sar-investigate", "sar-resolve", "sar-crq", "sar-reply"]` (example)
- `envelope.intent.type` updated to best-fit classification
