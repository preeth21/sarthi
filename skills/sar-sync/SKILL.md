---
name: "sar-sync"
key: "sar-sync"
description: "Sync local ~/sarthi with WITDnA/sarthi on GEC GitHub. Pulls latest skills/fixes/MCPs from the team repo, shows what changed, and optionally pushes local knowledge improvements back so the whole team benefits. Use when you want to get latest updates or share what you've learned."
allowed-tools: [Read, Bash, Write]
metadata:
  author: "akiran"
  version: "2.0.0"
  part-of: "sarthi"
  status: "active"
---

# sar-sync — sArthI Team Knowledge Sync

## Purpose
Keep `~/sarthi` in sync with `gecgithub01.walmart.com/WITDnA/sarthi`:
- **Pull** latest skills, MCP fixes, and knowledge improvements from the team repo
- **Push** local knowledge updates (resolution patterns, team.json, channels) back to share with the team

## Step-by-step instructions

### Step 1 — Check current state
Run:
```bash
cd ~/sarthi && git status && git log --oneline origin/main..HEAD 2>/dev/null | head -10
```
Report: any local uncommitted changes, and any local commits not yet pushed.

### Step 2 — Check what's available upstream
```bash
cd ~/sarthi && git fetch origin && git log --oneline HEAD..origin/main | head -20
```
Show the user what commits are available to pull. If nothing, say "Already up to date."

### Step 3 — Pull if there are upstream changes
```bash
cd ~/sarthi && git pull --ff-only origin main
```
- If fast-forward succeeds: show what changed (`git diff HEAD~N --stat`)
- If it fails due to local changes: show the conflict, ask user whether to stash or skip

### Step 4 — Re-apply setup if MCP/skills changed
Check if the pull brought new MCP servers, skills, or commands:
```bash
cd ~/sarthi && git diff HEAD~1 --name-only 2>/dev/null | grep -E "^(mcp/|skills/|commands/|agents/)"
```
If yes, re-run setup to symlink/inject:
```bash
bash ~/sarthi/setup.sh 2>&1 | grep -E "✅|⚠️|STEP" | head -30
```

### Step 5 — Check for local knowledge improvements to push back
```bash
cd ~/sarthi && git diff --stat knowledge/ 2>/dev/null
```
Show the user what local knowledge files have changed. Ask: "Push these to the team repo?"

**Safe to push:**
- `knowledge/team.json` — new team members
- `knowledge/channels.json` — new channel IDs
- `knowledge/environments.json` — new env URLs
- `knowledge/crq-references/` — updated CRQ references
- `knowledge/known-issues.json` — new known issues

**NEVER push:**
- `~/.wibey/snow-session.json` — personal auth session
- `~/.wibey/crq/chrome_profile/` — browser cookies
- `~/.wibey/skills/msgraph/` — auth tokens
- `scripts/crq/chrome_profile/` — gitignored, but double-check

### Step 6 — Commit and push if user confirms
```bash
cd ~/sarthi
git add knowledge/
git commit -m "chore: sync knowledge updates from $(git config user.name) session

🌀 Magic applied with Wibey CLI 🪄 (https://wibey.walmart.com/cli)
Co-Authored-By: Wibey CLI <genai-coding-assistants@walmart.com>"
git push origin main
```

## Output to user
- Summary: N commits pulled, M files updated
- List of knowledge files pushed (if any)
- Whether Wibey needs to be restarted (if new MCPs were pulled)

## Rules
1. NEVER push secrets, sessions, or auth tokens
2. NEVER force-push — only fast-forward
3. NEVER auto-resolve merge conflicts — always ask the user
4. ALWAYS show diff before pushing and get user confirmation
5. If `~/sarthi` has no git remote, say: "~/sarthi is not connected to a git repo. Run install.sh to clone from WITDnA/sarthi."
