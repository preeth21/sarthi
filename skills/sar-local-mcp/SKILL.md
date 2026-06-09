---
name: "sar-local-mcp"
key: "sar-local-mcp"
description: "Interactive generator for new sArthI local MCP servers. Uses AskUserQuestion to guide the user through server name, tools, auth archetype (with suggestions), and ops gating. Scaffolds ~/sarthi/mcp/sarthi-<name>/server.py, registers in sarthi-mcp-additions.json, injects into mcp.json, and smoke tests. No hardcoding — all logic comes from the user."
allowed-tools: [Read, Bash, Write, AskUserQuestion]
metadata:
  author: "akiran"
  version: "2.0.0"
  part-of: "sarthi"
  status: "active"
---

# sar-local-mcp — Interactive MCP Server Generator

## Purpose
Guide the user through creating a new sArthI MCP server.
Writes the server.py skeleton, registers it in sarthi-mcp-additions.json,
and runs inject-mcp.py to activate it. Smoke tests after every build.

## Walmart Network / Nexus Rule (ALWAYS apply)
**NEVER suggest downloading from public internet (brew, apt, curl from GitHub, etc.).**
All packages MUST go through Walmart's internal Artifactory (Nexus):

| Package type | Install command |
|---|---|
| Python packages | `pip install <pkg> --index-url https://repository.cache.walmart.com/repository/pypi-proxy/simple/` |
| Node/npm packages | `npm config set registry https://npm.ci.artifacts.walmart.com/artifactory/api/npm/npme-npm && npm install <pkg>` |
| Generic binaries | Check `https://repository.cache.walmart.com` or ask team for internal path |
| Managed tools (kubectl, sledge, gcloud, gh) | Ask for Walmart-internal Artifactory path — never suggest public install |

---

## STEP 0 — Orient

```
Read ~/sarthi/mcp/sarthi-mcp-additions.json
```

Tell the user which servers already exist. If the name they want already exists, ask if they want to extend it or create a new one.

---

## STEP 1 — Server identity (conversational)

Ask conversationally:
```
What should this server be called? (becomes sarthi-<name>)
What does it do in one sentence?
```

---

## STEP 2 — Tool list (conversational)

Ask:
```
List the tools you want. For each:
  - Name (e.g. get_pods, search_messages, run_query)
  - What API/command it wraps
  - Input parameters
  - What it returns
  - Read-only or mutation?
```

---

## STEP 3 — Auth archetype (AskUserQuestion)

**Before asking**, analyse the target system and suggest the most likely archetype.
Your suggestion logic:
- Target is a CLI binary already on the machine (kubectl, gh, aws, gcloud) → suggest A
- Target is a Walmart internal web API (ServiceNow, Airflow, internal REST) → suggest B
- Target wraps an existing Wibey skill that has its own auth (slack-api, msgraph) → suggest D
- Target uses cloud SDK credentials (GCP ADC, AWS profile, Azure CLI) → suggest C
- Target is a local tool or file-based operation → suggest C

Then use AskUserQuestion:

```
AskUserQuestion([{
  question: "How should sarthi-<name> authenticate? Here's my suggestion based on your target: <explain why>",
  header: "Auth pattern",
  multiSelect: false,
  options: [
    {
      label: "A — CLI-wrapper (like sarthi-git / sarthi-wcnp)",
      description: "Wraps an already-authed binary (gh, kubectl, gcloud, aws). On auth failure returns auth_expired with hint to run the auth command. No sarthi-managed session. Best for: kubectl, gh, gcloud, aws, sledge.",
      preview: "# Auth check pattern:\nif not shutil.which('kubectl'):\n    return {\"error\": \"dependency_missing\"}\n\nrc, out, err = _run_cmd(['kubectl', 'cluster-info'])\nif 'Unauthorized' in err:\n    return {\"error\": \"auth_expired\", \"detail\": \"Run: sledge connect <cluster>\"}"
    },
    {
      label: "B — Web-session (like sarthi-snow)",
      description: "Target is a web API using session cookies/tokens. Session stored at ~/.wibey/sarthi/<name>-session.json. On 401 returns session_expired. Gets a companion -auth server with a refresh_session tool. Best for: ServiceNow, Airflow, Walmart internal REST APIs.",
      preview: "# Session load pattern:\ndef _load_session():\n    path = Path.home()/'.wibey/sarthi/<name>-session.json'\n    if not path.exists(): return None\n    return json.loads(path.read_text())\n\n# On 401:\nreturn {\"error\": \"session_expired\",\n        \"detail\": \"Run refresh_session tool\"}"
    },
    {
      label: "C — Ambient / no managed auth (like sarthi-gcp / sarthi-bq)",
      description: "Relies on existing credentials: gcloud ADC, env vars, token files, AWS profiles. Checks the credential exists and returns a clear error if not. Best for: gcloud ADC, AWS SDK, local tools, file-based operations.",
      preview: "# Ambient auth check:\ndef _check_auth():\n    r = subprocess.run(['gcloud','auth','list'],\n                       capture_output=True, text=True)\n    if 'No credentialed accounts' in r.stdout:\n        return {\"error\": \"auth_expired\",\n                \"detail\": \"Run: gcloud auth application-default login\"}\n    return None"
    },
    {
      label: "D — Skill-wrapper (like sarthi-slack)",
      description: "Wraps an existing Wibey skill that manages its own auth (slack-api, msgraph, etc.). Delegates auth to the skill — no separate session management. Server discovers the skill at runtime and returns dependency_missing if not installed.",
      preview: "# Skill discovery:\ndef _find_skill_api():\n    for root in [Path.home()/'.wibey', Path.home()/'.claude']:\n        for m in root.rglob('<skill>/scripts/api.js'):\n            return m\n    return None\n\n# If not found:\nreturn {\"error\": \"dependency_missing\",\n        \"detail\": \"Install: /skill-installer <skill-name>\"}"
    },
    {
      label: "E — Token file (like a simple API key)",
      description: "API key or long-lived token stored at ~/.wibey/sarthi/<name>-token.json. User provides the token once; server reads it on every call. Best for: simple REST APIs with static API keys, bearer tokens with manual rotation.",
      preview: "# Token load:\nTOKEN_FILE = Path.home()/'.wibey/sarthi/<name>-token.json'\n\ndef _load_token():\n    if not TOKEN_FILE.exists(): return None\n    return json.loads(TOKEN_FILE.read_text()).get('token')\n\n# On missing/invalid:\nreturn {\"error\": \"auth_expired\",\n        \"detail\": f\"Create {TOKEN_FILE}: echo '{{\\\"token\\\": \\\"YOUR-KEY\\\"}}' > {TOKEN_FILE}\"}"
    }
  ]
}])
```

After the user picks, ask any archetype-specific follow-up questions conversationally.

---

## STEP 4 — Required binaries (AskUserQuestion if CLI-wrapper/skill-wrapper)

Only ask this if archetype is A or D. For others, derive from context.

If archetype A:
```
AskUserQuestion([{
  question: "What CLI binary does this server wrap?",
  header: "Required binary",
  multiSelect: false,
  options: [
    { label: "kubectl",  description: "Kubernetes CLI — Walmart Artifactory install" },
    { label: "gh",       description: "GitHub CLI — Walmart Artifactory install" },
    { label: "gcloud",   description: "Google Cloud SDK — Walmart Artifactory install" },
    { label: "aws",      description: "AWS CLI — Walmart Artifactory install" },
    { label: "Other",    description: "I'll specify the binary name and install path" }
  ]
}])
```

---

## STEP 5 — Ops guard (AskUserQuestion)

```
AskUserQuestion([{
  question: "Should any tools require explicit permission to run mutations?",
  header: "Ops gating",
  multiSelect: false,
  options: [
    {
      label: "Read-only only — no mutations (Recommended for new servers)",
      description: "All tools are read-only. Safe default — add ops tools later when tested."
    },
    {
      label: "Read + ops with flag gate (like Airflow/WCNP)",
      description: "Mutation tools require ops_allowed: true in a config file. Prevents accidental prod mutations."
    },
    {
      label: "All tools unrestricted",
      description: "No gating — all tools run without restriction. Only use for dev/non-prod servers."
    }
  ]
}])
```

---

## STEP 6 — Generate server.py

Using all collected answers, write `~/sarthi/mcp/sarthi-<name>/server.py`.

### Mandatory skeleton elements:
- Module docstring with: server name, auth pattern chosen, tools list, config/token file path, required binaries
- `log()` → sys.stderr (NEVER print to stdout)
- Auth implementation matching chosen archetype (patterns above)
- For archetype A/D: `_check_dependencies()` with `shutil.which()` probe BEFORE any subprocess
- Tool functions with error handling:
  - Missing params → `{"error": "<param> is required"}`
  - Auth/dep failure → appropriate error key (`auth_expired`, `dependency_missing`, `session_expired`)
  - Command/API failure → `{"error": "<verb>_failed", "detail": stderr[:500]}`
- `TOOLS` dict with `fn`, `description`, `inputSchema` per tool
- `handle_request()` JSON-RPC dispatcher (exact pattern from sarthi-bq/sarthi-wcnp)
- `run_stdio()` loop
- `run_test()` — `python3 server.py --test <tool> '<json>'`
- `if __name__ == "__main__":` argparse block

### Auth skeleton by archetype:

**A — CLI-wrapper:**
```python
import shutil
REQUIRED_BINARIES = {"<binary>": "<Artifactory install hint>"}

def _check_dependencies():
    missing = [{"binary": b, "install": h}
               for b, h in REQUIRED_BINARIES.items() if not shutil.which(b)]
    if missing:
        return {"error": "dependency_missing", "missing": missing,
                "detail": f"Install: {', '.join(m['binary'] for m in missing)}"}
    return None

def _auth_error(err: str) -> dict:
    try:
        p = json.loads(err)
        if p.get("error") == "dependency_missing": return p
    except: pass
    return {"error": "auth_expired", "detail": err}
```

**B — Web-session:**
```python
SESSION_FILE = Path(os.environ.get("SESSION_FILE",
    str(Path.home()/".wibey/sarthi/<name>-session.json")))

def _load_session():
    if not SESSION_FILE.exists(): return None
    try: return json.loads(SESSION_FILE.read_text())
    except: return None

def _session_expired_error():
    return {"error": "session_expired",
            "detail": "Call refresh_session tool or run the manual refresh command."}
```

**C — Ambient:**
```python
def _check_auth():
    # Check ambient credential exists
    # e.g. gcloud: subprocess check, ADC file check, env var check
    return None  # or {"error": "auth_expired", "detail": "..."}
```

**D — Skill-wrapper:**
```python
def _find_skill():
    for root in [Path.home()/".wibey", Path.home()/".claude"]:
        for m in root.rglob("<skill>/scripts/api.js"):
            return m
    return None

def _check_skill():
    if not _find_skill():
        return {"error": "dependency_missing",
                "detail": "Install: /skill-installer <skill-name>  then run setup steps"}
    return None
```

**E — Token file:**
```python
TOKEN_FILE = Path(os.environ.get("TOKEN_FILE",
    str(Path.home()/".wibey/sarthi/<name>-token.json")))

def _load_token():
    if not TOKEN_FILE.exists(): return None
    try: return json.loads(TOKEN_FILE.read_text()).get("token")
    except: return None

def _auth_error():
    return {"error": "auth_expired",
            "detail": f"Create token file: echo '{{\"token\": \"YOUR-KEY\"}}' > {TOKEN_FILE}"}
```

---

## STEP 7 — If archetype B: generate companion auth server

Write `~/sarthi/mcp/sarthi-<name>-auth/server.py` with ONE tool: `refresh_session`.
Pattern: asyncio subprocess, same as sarthi-snow-auth.
Ask the user: "What command refreshes the session? (e.g. python3 extract_session.py)"

---

## STEP 8 — Register in sarthi-mcp-additions.json

Add entry with:
- `${SARTHI_ROOT}` for server.py path, `${HOME}` for home paths
- `_comment` describing the server and auth pattern
- `_requires_binaries` (archetype A/D only)
- `_auth_steps` — exact one-time commands to run after install
- `_install_note` for any non-binary deps (pip packages, npm installs)

---

## STEP 9 — Inject and smoke test

```bash
python3 ~/sarthi/scripts/inject-mcp.py \
    ~/.wibey/mcp.json \
    ~/sarthi/mcp/sarthi-mcp-additions.json \
    --sarthi-root ~/sarthi

python3 ~/sarthi/mcp/sarthi-<name>/server.py --test <first_tool> '{}'
```

**Always run the smoke test and report the result.** Expected outcomes:
- `{"error": "dependency_missing", ...}` → binary not installed, correct
- `{"error": "auth_expired", ...}` or `{"error": "session_expired", ...}` → auth not done, correct
- Actual data → auth was already configured, working immediately

---

## STEP 10 — Summary

```
✅ sarthi-<name> created  (auth: <archetype label>)

Files:
  ~/sarthi/mcp/sarthi-<name>/server.py
  (~/sarthi/mcp/sarthi-<name>-auth/server.py — if archetype B)

Registered in mcp.json + .mcp.json.

Auth setup (one-time):
  <exact steps from user's answers, Nexus URLs included>

After auth:
  Restart Wibey → sarthi-<name> goes live
  Test: python3 ~/sarthi/mcp/sarthi-<name>/server.py --test <tool> '{...}'
  In Wibey: mcp__plugin__wibey_sarthi-<name>__<tool_name>
```

---

## Design principles

1. **No hardcoding** — tool names, commands, URLs, binary names all come from the user
2. **AskUserQuestion** — use it for auth archetype, binary selection, ops gating. Previews show real code patterns so the user understands what they're choosing
3. **Suggest before asking** — analyse the target system, state your recommendation and why, then present options
4. **Always smoke test** — run `--test` after every build, report result, explain what it means
5. **Nexus always** — every install hint uses Walmart Artifactory, never public internet
6. **inject-mcp.py** — registration never touches hardcoded lists
7. **Companion auth server** — archetype B always gets a `-auth` companion
