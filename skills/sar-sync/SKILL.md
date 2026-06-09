---
name: "sar-sync"
key: "sar-sync"
description: "sArthI's team knowledge sync skill. Pulls latest from the sarthi GEC GitHub repo, copies improved knowledge files (resolution patterns, DAG registry, team config) back to the repo, shows a diff, and lets you push team-shareable improvements. Called via /sarthi sync shortcut."
allowed-tools: [Read, Bash, Write]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "placeholder"
---

# sar-sync — Team Knowledge Sync

## Purpose
sArthI learns from every incident it resolves. This skill propagates those learnings
(new resolution patterns, updated team config, improved DAG registry) back to the
shared repo so the whole team benefits from sArthI getting smarter.

## Status: PLACEHOLDER

## TODO — implement:

- [ ] Pull latest from `gecgithub01.walmart.com/WITDnA/sarthi` (main branch)
- [ ] Copy updated knowledge files from `~/.wibey/knowledge/` → `~/sarthi/knowledge/`
  - resolution-patterns.json (updated by sar-resolve after novel fixes)
  - team.json (if new members added locally)
  - channels.json (if new channel IDs added locally)
- [ ] Show diff summary of what changed
- [ ] Ask user: "Push these knowledge updates to the team repo? [y/N]"
- [ ] If yes: `git commit -m "chore: sync knowledge updates from <user> session"` and push

## Sync rules
- NEVER overwrite knowledge files in the direction repo → local without showing diff first
- NEVER push secrets or personal tokens (snow-session.json, auth tokens, cookies)
- Only push files in `knowledge/` — never push `~/.wibey/crq/` session state

## Knowledge files that ARE safe to sync
```
knowledge/resolution-patterns.json   ← sArthI learns from novel fixes
knowledge/team.json                  ← new team members
knowledge/channels.json              ← new Teams/Slack channel IDs
knowledge/dags/                      ← new DAG registry entries
knowledge/crq-references/            ← updated CRQ field reference JSONs
```

## Knowledge files that are NEVER synced
```
~/.wibey/snow-session.json           ← personal ServiceNow session
~/.wibey/crq/chrome_profile/         ← browser auth state
~/.wibey/skills/msgraph/.*token*     ← Microsoft auth tokens
```

## Expected output
- Sync diff shown to user
- Optional push to GEC GitHub repo
- `envelope.artifacts` updated with `{ type: "sync", pushed: true/false, files_updated: [...] }`
