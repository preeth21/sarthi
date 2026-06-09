"""
sarthi-git MCP stdio server — GitHub/GEC Git tools for sArthI.

Wraps the `gh` CLI which is already authenticated to gecgithub01.walmart.com
via keyring (akiran). No additional auth setup needed — uses the same gh token
that `gh auth status --hostname gecgithub01.walmart.com` shows as active.

Tools:
  git_get_file        — Read a file from any repo/branch at gecgithub01.walmart.com
  git_list_dir        — List files/dirs at a path in a repo
  git_search_code     — Search for a string across a repo's code
  git_get_pr          — Get PR details (description, status, diff summary)
  git_list_prs        — List open PRs for a repo
  git_create_pr       — Create a PR (requires write access)
  git_get_commit      — Get details of a specific commit

Default hostname: gecgithub01.walmart.com (Walmart GEC GitHub)
All tools accept an optional `hostname` param to target github.com if needed.

Auth: gh CLI keyring token. On auth failure returns {"error": "auth_expired"}.

CRITICAL: stdout is JSON-RPC. ALL diagnostic output → sys.stderr. NEVER use print() to stdout.
"""

import sys
import os
import json
import argparse
import subprocess
import base64
from pathlib import Path

DEFAULT_HOSTNAME = "gecgithub01.walmart.com"

def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)

def _gh(args: list[str], hostname: str = DEFAULT_HOSTNAME, timeout: int = 30) -> tuple[int, str, str]:
    """Run a gh CLI command. Returns (returncode, stdout, stderr)."""
    cmd = ["gh"] + args + ["--hostname", hostname]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except FileNotFoundError:
        return -1, "", "gh CLI not found — install via: brew install gh or check PATH"

def _is_auth_error(stderr: str) -> bool:
    return any(p in stderr.lower() for p in [
        "authentication", "401", "not logged in", "token", "credentials",
        "permission denied", "403", "requires authentication"
    ])

def _repo_flag(org: str, repo: str) -> str:
    return f"{org}/{repo}"


# ── Tools ─────────────────────────────────────────────────────────────────────

def tool_git_get_file(args: dict) -> dict:
    """
    Read a file from a GitHub repo.

    Args:
      org       (str, required) — GitHub org/owner e.g. WITDnA
      repo      (str, required) — repo name e.g. intl_dp_afaas_image
      path      (str, required) — file path e.g. include/config/et360_ca_project_config.json
      ref       (str, optional) — branch/tag/commit (default: main)
      hostname  (str, optional) — GitHub hostname (default: gecgithub01.walmart.com)
    """
    org      = args.get("org", "").strip()
    repo     = args.get("repo", "").strip()
    path     = args.get("path", "").strip()
    ref      = args.get("ref", "main").strip()
    hostname = args.get("hostname", DEFAULT_HOSTNAME).strip()

    if not all([org, repo, path]):
        return {"error": "org, repo, and path are required"}

    rc, stdout, stderr = _gh([
        "api", f"repos/{org}/{repo}/contents/{path}?ref={ref}",
    ], hostname=hostname, timeout=30)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": f"Run: gh auth login --hostname {hostname}"}
        return {"error": "git_get_file_failed", "detail": stderr[:500] or stdout[:200]}

    try:
        data = json.loads(stdout)
        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        else:
            content = data.get("content", "")
        return {
            "path":     data.get("path"),
            "sha":      data.get("sha"),
            "size":     data.get("size"),
            "html_url": data.get("html_url"),
            "content":  content,
        }
    except (json.JSONDecodeError, Exception) as e:
        return {"error": "parse_failed", "detail": str(e), "raw": stdout[:500]}


def tool_git_list_dir(args: dict) -> dict:
    """
    List files and directories at a path in a GitHub repo.

    Args:
      org       (str, required) — GitHub org/owner
      repo      (str, required) — repo name
      path      (str, optional) — directory path (default: root)
      ref       (str, optional) — branch/tag/commit (default: main)
      hostname  (str, optional) — GitHub hostname
    """
    org      = args.get("org", "").strip()
    repo     = args.get("repo", "").strip()
    path     = args.get("path", "").strip()
    ref      = args.get("ref", "main").strip()
    hostname = args.get("hostname", DEFAULT_HOSTNAME).strip()

    if not all([org, repo]):
        return {"error": "org and repo are required"}

    api_path = f"repos/{org}/{repo}/contents/{path}" if path else f"repos/{org}/{repo}/contents"

    rc, stdout, stderr = _gh([
        "api", f"{api_path}?ref={ref}",
    ], hostname=hostname, timeout=30)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": f"Run: gh auth login --hostname {hostname}"}
        return {"error": "git_list_dir_failed", "detail": stderr[:500]}

    try:
        items = json.loads(stdout)
        if not isinstance(items, list):
            # Single file returned (path pointed to a file)
            return {"type": "file", "path": items.get("path"), "size": items.get("size")}
        return {
            "path":  path or "/",
            "ref":   ref,
            "items": [
                {
                    "name": i["name"],
                    "type": i["type"],  # "file" or "dir"
                    "path": i["path"],
                    "size": i.get("size"),
                }
                for i in items
            ],
            "count": len(items),
        }
    except (json.JSONDecodeError, Exception) as e:
        return {"error": "parse_failed", "detail": str(e), "raw": stdout[:500]}


def tool_git_search_code(args: dict) -> dict:
    """
    Search for a string pattern across a repo's code.

    Args:
      org       (str, required) — GitHub org/owner
      repo      (str, required) — repo name
      query     (str, required) — search string
      hostname  (str, optional) — GitHub hostname
    """
    org      = args.get("org", "").strip()
    repo     = args.get("repo", "").strip()
    query    = args.get("query", "").strip()
    hostname = args.get("hostname", DEFAULT_HOSTNAME).strip()

    if not all([org, repo, query]):
        return {"error": "org, repo, and query are required"}

    rc, stdout, stderr = _gh([
        "api", f"search/code?q={query}+repo:{org}/{repo}",
    ], hostname=hostname, timeout=30)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": f"Run: gh auth login --hostname {hostname}"}
        return {"error": "git_search_failed", "detail": stderr[:500]}

    try:
        data = json.loads(stdout)
        results = [
            {"path": i.get("path"), "url": i.get("html_url"), "score": i.get("score")}
            for i in data.get("items", [])
        ]
        return {"query": query, "repo": f"{org}/{repo}", "results": results, "count": data.get("total_count", len(results))}
    except (json.JSONDecodeError, Exception) as e:
        return {"error": "parse_failed", "detail": str(e), "raw": stdout[:500]}


def tool_git_get_pr(args: dict) -> dict:
    """
    Get details of a pull request.

    Args:
      org       (str, required) — GitHub org/owner
      repo      (str, required) — repo name
      pr_number (int, required) — PR number
      hostname  (str, optional) — GitHub hostname
    """
    org       = args.get("org", "").strip()
    repo      = args.get("repo", "").strip()
    pr_number = args.get("pr_number")
    hostname  = args.get("hostname", DEFAULT_HOSTNAME).strip()

    if not all([org, repo, pr_number]):
        return {"error": "org, repo, and pr_number are required"}

    rc, stdout, stderr = _gh([
        "pr", "view", str(pr_number),
        "--repo", _repo_flag(org, repo),
        "--json", "number,title,state,body,author,createdAt,mergedAt,headRefName,baseRefName,url,reviews,files",
    ], hostname=hostname, timeout=30)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": f"Run: gh auth login --hostname {hostname}"}
        return {"error": "git_get_pr_failed", "detail": stderr[:500]}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        return {"error": "parse_failed", "detail": str(e), "raw": stdout[:500]}


def tool_git_list_prs(args: dict) -> dict:
    """
    List open pull requests for a repo.

    Args:
      org       (str, required) — GitHub org/owner
      repo      (str, required) — repo name
      state     (str, optional) — open | closed | merged (default: open)
      limit     (int, optional) — max PRs to return (default: 20)
      hostname  (str, optional) — GitHub hostname
    """
    org      = args.get("org", "").strip()
    repo     = args.get("repo", "").strip()
    state    = args.get("state", "open").strip()
    limit    = int(args.get("limit", 20))
    hostname = args.get("hostname", DEFAULT_HOSTNAME).strip()

    if not all([org, repo]):
        return {"error": "org and repo are required"}

    rc, stdout, stderr = _gh([
        "pr", "list",
        "--repo", _repo_flag(org, repo),
        "--state", state,
        "--limit", str(limit),
        "--json", "number,title,state,author,createdAt,headRefName,url",
    ], hostname=hostname, timeout=30)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": f"Run: gh auth login --hostname {hostname}"}
        return {"error": "git_list_prs_failed", "detail": stderr[:500]}

    try:
        prs = json.loads(stdout)
        return {"repo": f"{org}/{repo}", "state": state, "prs": prs, "count": len(prs)}
    except json.JSONDecodeError as e:
        return {"error": "parse_failed", "detail": str(e), "raw": stdout[:500]}


def tool_git_create_pr(args: dict) -> dict:
    """
    Create a pull request.

    Args:
      org        (str, required) — GitHub org/owner
      repo       (str, required) — repo name
      title      (str, required) — PR title
      body       (str, required) — PR description
      head       (str, required) — source branch
      base       (str, optional) — target branch (default: main)
      hostname   (str, optional) — GitHub hostname
    """
    org      = args.get("org", "").strip()
    repo     = args.get("repo", "").strip()
    title    = args.get("title", "").strip()
    body     = args.get("body", "").strip()
    head     = args.get("head", "").strip()
    base     = args.get("base", "main").strip()
    hostname = args.get("hostname", DEFAULT_HOSTNAME).strip()

    if not all([org, repo, title, body, head]):
        return {"error": "org, repo, title, body, and head are required"}

    rc, stdout, stderr = _gh([
        "pr", "create",
        "--repo", _repo_flag(org, repo),
        "--title", title,
        "--body", body,
        "--head", head,
        "--base", base,
    ], hostname=hostname, timeout=60)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": f"Run: gh auth login --hostname {hostname}"}
        return {"error": "git_create_pr_failed", "detail": stderr[:500]}

    return {"ok": True, "url": stdout.strip()}


def tool_git_get_commit(args: dict) -> dict:
    """
    Get details of a specific commit.

    Args:
      org       (str, required) — GitHub org/owner
      repo      (str, required) — repo name
      sha       (str, required) — commit SHA (full or short)
      hostname  (str, optional) — GitHub hostname
    """
    org      = args.get("org", "").strip()
    repo     = args.get("repo", "").strip()
    sha      = args.get("sha", "").strip()
    hostname = args.get("hostname", DEFAULT_HOSTNAME).strip()

    if not all([org, repo, sha]):
        return {"error": "org, repo, and sha are required"}

    rc, stdout, stderr = _gh([
        "api", f"repos/{org}/{repo}/commits/{sha}",
    ], hostname=hostname, timeout=30)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": f"Run: gh auth login --hostname {hostname}"}
        return {"error": "git_get_commit_failed", "detail": stderr[:500]}

    try:
        data = json.loads(stdout)
        commit = data.get("commit", {})
        return {
            "sha":     data.get("sha"),
            "message": commit.get("message", ""),
            "author":  commit.get("author", {}),
            "date":    commit.get("author", {}).get("date"),
            "url":     data.get("html_url"),
            "files":   [
                {"filename": f["filename"], "status": f["status"],
                 "additions": f["additions"], "deletions": f["deletions"]}
                for f in data.get("files", [])
            ],
        }
    except (json.JSONDecodeError, Exception) as e:
        return {"error": "parse_failed", "detail": str(e), "raw": stdout[:500]}


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS = {
    "git_get_file": {
        "fn": tool_git_get_file,
        "description": "Read a file from a GitHub/GEC repo. Returns decoded content. Default hostname: gecgithub01.walmart.com.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org":      {"type": "string", "description": "GitHub org/owner e.g. WITDnA"},
                "repo":     {"type": "string", "description": "Repo name e.g. intl_dp_afaas_image"},
                "path":     {"type": "string", "description": "File path e.g. include/config/et360_ca_project_config.json"},
                "ref":      {"type": "string", "description": "Branch/tag/commit SHA (default: main)"},
                "hostname": {"type": "string", "description": "GitHub hostname (default: gecgithub01.walmart.com)"},
            },
            "required": ["org", "repo", "path"],
        },
    },
    "git_list_dir": {
        "fn": tool_git_list_dir,
        "description": "List files and directories at a path in a GitHub/GEC repo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org":      {"type": "string", "description": "GitHub org/owner"},
                "repo":     {"type": "string", "description": "Repo name"},
                "path":     {"type": "string", "description": "Directory path (default: root)"},
                "ref":      {"type": "string", "description": "Branch/tag/commit (default: main)"},
                "hostname": {"type": "string", "description": "GitHub hostname (default: gecgithub01.walmart.com)"},
            },
            "required": ["org", "repo"],
        },
    },
    "git_search_code": {
        "fn": tool_git_search_code,
        "description": "Search for a string pattern across a GitHub/GEC repo's code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org":      {"type": "string", "description": "GitHub org/owner"},
                "repo":     {"type": "string", "description": "Repo name"},
                "query":    {"type": "string", "description": "Search string"},
                "hostname": {"type": "string", "description": "GitHub hostname (default: gecgithub01.walmart.com)"},
            },
            "required": ["org", "repo", "query"],
        },
    },
    "git_get_pr": {
        "fn": tool_git_get_pr,
        "description": "Get pull request details including title, body, status, and changed files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org":       {"type": "string",  "description": "GitHub org/owner"},
                "repo":      {"type": "string",  "description": "Repo name"},
                "pr_number": {"type": "integer", "description": "PR number"},
                "hostname":  {"type": "string",  "description": "GitHub hostname (default: gecgithub01.walmart.com)"},
            },
            "required": ["org", "repo", "pr_number"],
        },
    },
    "git_list_prs": {
        "fn": tool_git_list_prs,
        "description": "List pull requests for a repo (open/closed/merged).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org":      {"type": "string",  "description": "GitHub org/owner"},
                "repo":     {"type": "string",  "description": "Repo name"},
                "state":    {"type": "string",  "description": "open | closed | merged (default: open)"},
                "limit":    {"type": "integer", "description": "Max PRs to return (default: 20)"},
                "hostname": {"type": "string",  "description": "GitHub hostname (default: gecgithub01.walmart.com)"},
            },
            "required": ["org", "repo"],
        },
    },
    "git_create_pr": {
        "fn": tool_git_create_pr,
        "description": "Create a pull request on a GitHub/GEC repo. Requires write access.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org":      {"type": "string", "description": "GitHub org/owner"},
                "repo":     {"type": "string", "description": "Repo name"},
                "title":    {"type": "string", "description": "PR title"},
                "body":     {"type": "string", "description": "PR description (markdown)"},
                "head":     {"type": "string", "description": "Source branch name"},
                "base":     {"type": "string", "description": "Target branch (default: main)"},
                "hostname": {"type": "string", "description": "GitHub hostname (default: gecgithub01.walmart.com)"},
            },
            "required": ["org", "repo", "title", "body", "head"],
        },
    },
    "git_get_commit": {
        "fn": tool_git_get_commit,
        "description": "Get details of a specific commit including changed files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org":      {"type": "string", "description": "GitHub org/owner"},
                "repo":     {"type": "string", "description": "Repo name"},
                "sha":      {"type": "string", "description": "Commit SHA (full or short)"},
                "hostname": {"type": "string", "description": "GitHub hostname (default: gecgithub01.walmart.com)"},
            },
            "required": ["org", "repo", "sha"],
        },
    },
}


# ── JSON-RPC stdio loop ────────────────────────────────────────────────────────

def handle_request(req: dict) -> dict | None:
    method = req.get("method", "")
    req_id = req.get("id")

    def ok(result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sarthi-git", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        tools_list = [
            {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
            for name, spec in TOOLS.items()
        ]
        return ok({"tools": tools_list})

    if method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        if tool_name not in TOOLS:
            return err(-32601, f"Unknown tool: {tool_name}")
        try:
            result = TOOLS[tool_name]["fn"](tool_args)
            return ok({"content": [{"type": "text", "text": json.dumps(result, indent=2)}]})
        except Exception as e:
            log(f"ERROR in {tool_name}: {e}")
            return err(-32603, str(e))

    if method == "ping":
        return ok({})

    return err(-32601, f"Method not found: {method}")


def run_stdio():
    log("sarthi-git MCP server starting (stdio)")
    log(f"Default hostname: {DEFAULT_HOSTNAME}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            log(f"WARN: invalid JSON: {e}")
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def run_test(tool_name: str, args_json: str):
    """CLI test mode: python3 server.py --test <tool> '<json args>'"""
    if tool_name not in TOOLS:
        print(f"Unknown tool: {tool_name}")
        print(f"Available: {', '.join(TOOLS.keys())}")
        sys.exit(1)
    try:
        tool_args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as e:
        print(f"Invalid JSON args: {e}")
        sys.exit(1)
    result = TOOLS[tool_name]["fn"](tool_args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="sarthi-git MCP server — GitHub/GEC Git tools")
    parser.add_argument("--test", metavar="TOOL", help="Run a single tool and print result")
    parser.add_argument("args_json", nargs="?", default="{}", help="JSON args for --test mode")
    parsed = parser.parse_args()

    if parsed.test:
        run_test(parsed.test, parsed.args_json)
    else:
        run_stdio()
