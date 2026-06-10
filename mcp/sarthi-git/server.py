"""
sarthi-git MCP stdio server — GitHub/GEC Git tools for sArthI.

Wraps the `gh` CLI which is already authenticated to gecgithub01.walmart.com
via keyring (akiran). No additional auth setup needed — uses the same gh token
that `gh auth status --hostname gecgithub01.walmart.com` shows as active.

Tools:
  git_get_file               — Read a file from any repo/branch at gecgithub01.walmart.com
  git_list_dir               — List files/dirs at a path in a repo
  git_search_code            — Search for a string across a repo's code
  git_get_pr                 — Get PR details (description, status, diff summary)
  git_list_prs               — List open PRs for a repo
  git_create_pr              — Create a PR (requires write access)
  git_get_commit             — Get details of a specific commit
  git_create_branch          — Create a new branch from an existing ref (write)
  git_create_or_update_file  — Create or update a single file via PUT /contents (write)
                               IMPORTANT: pass current file sha when updating an existing file.

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
    """
    Run a gh CLI command. Returns (returncode, stdout, stderr).

    `gh api` accepts --hostname; `gh pr create/view/list` does NOT — for those
    we pass GH_HOST env var instead. We always set GH_HOST so both paths work.
    """
    cmd = ["gh"] + args
    # api subcommand supports --hostname; pr/issue subcommands use GH_HOST env
    if args and args[0] == "api":
        cmd += ["--hostname", hostname]
    env = {**os.environ, "GH_HOST": hostname}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
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


def tool_git_create_branch(args: dict) -> dict:
    """
    Create a new branch from an existing ref (branch/tag/SHA).

    Args:
      org       (str, required) — GitHub org/owner
      repo      (str, required) — repo name
      branch    (str, required) — new branch name e.g. fix/sarthi-et360-item-id-20260610
      from_ref  (str, optional) — source branch/tag/SHA (default: main)
      hostname  (str, optional) — GitHub hostname
    """
    org      = args.get("org", "").strip()
    repo     = args.get("repo", "").strip()
    branch   = args.get("branch", "").strip()
    from_ref = args.get("from_ref", "main").strip()
    hostname = args.get("hostname", DEFAULT_HOSTNAME).strip()

    if not all([org, repo, branch]):
        return {"error": "org, repo, and branch are required"}

    # Resolve from_ref to a SHA
    rc, stdout, stderr = _gh([
        "api", f"repos/{org}/{repo}/git/ref/heads/{from_ref}",
    ], hostname=hostname, timeout=30)

    if rc != 0:
        # Maybe from_ref is already a full SHA — try as commit directly
        rc2, stdout2, stderr2 = _gh([
            "api", f"repos/{org}/{repo}/commits/{from_ref}",
        ], hostname=hostname, timeout=30)
        if rc2 != 0:
            if _is_auth_error(stderr):
                return {"error": "auth_expired", "detail": f"Run: gh auth login --hostname {hostname}"}
            return {"error": "resolve_ref_failed", "detail": f"Could not resolve '{from_ref}': {stderr[:300]}"}
        try:
            sha = json.loads(stdout2).get("sha", "")
        except Exception:
            return {"error": "parse_failed", "detail": stdout2[:300]}
    else:
        try:
            sha = json.loads(stdout).get("object", {}).get("sha", "")
        except Exception:
            return {"error": "parse_failed", "detail": stdout[:300]}

    if not sha:
        return {"error": "no_sha", "detail": f"Could not extract SHA from ref '{from_ref}'"}

    # Create the branch
    rc, stdout, stderr = _gh([
        "api", "-X", "POST",
        f"repos/{org}/{repo}/git/refs",
        "-f", f"ref=refs/heads/{branch}",
        "-f", f"sha={sha}",
    ], hostname=hostname, timeout=30)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": f"Run: gh auth login --hostname {hostname}"}
        if "already exists" in stderr.lower() or "422" in stderr:
            return {"error": "branch_exists", "detail": f"Branch '{branch}' already exists in {org}/{repo}"}
        return {"error": "git_create_branch_failed", "detail": stderr[:500]}

    try:
        data = json.loads(stdout)
        return {
            "ok":     True,
            "branch": branch,
            "ref":    data.get("ref"),
            "sha":    data.get("object", {}).get("sha", "")[:12],
            "url":    f"https://{hostname}/{org}/{repo}/tree/{branch}",
        }
    except Exception as e:
        return {"error": "parse_failed", "detail": str(e), "raw": stdout[:300]}


def tool_git_create_or_update_file(args: dict) -> dict:
    """
    Create or update a single file in a repo via the GitHub Contents API (PUT).

    To UPDATE an existing file you MUST provide `sha` (the blob SHA of the
    current file — obtained from git_get_file). Without sha the API returns 422.
    To CREATE a new file omit sha (or pass null).

    Args:
      org       (str, required) — GitHub org/owner
      repo      (str, required) — repo name
      path      (str, required) — file path in repo e.g. sql/et360/item_load.sql
      content   (str, required) — full new file content (plain text, not base64)
      message   (str, required) — commit message
      branch    (str, required) — branch to commit to (must exist — use git_create_branch first)
      sha       (str, optional) — current file blob SHA (required when updating, omit when creating)
      hostname  (str, optional) — GitHub hostname
    """
    org      = args.get("org", "").strip()
    repo     = args.get("repo", "").strip()
    path     = args.get("path", "").strip()
    content  = args.get("content", "")
    message  = args.get("message", "").strip()
    branch   = args.get("branch", "").strip()
    sha      = args.get("sha", "").strip()   # blob sha of existing file — required for updates
    hostname = args.get("hostname", DEFAULT_HOSTNAME).strip()

    if not all([org, repo, path, content, message, branch]):
        return {"error": "org, repo, path, content, message, and branch are required"}

    # GitHub Contents API requires content base64-encoded
    content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")

    gh_args = [
        "api", "-X", "PUT",
        f"repos/{org}/{repo}/contents/{path}",
        "-f", f"message={message}",
        "-f", f"content={content_b64}",
        "-f", f"branch={branch}",
    ]
    if sha:
        gh_args += ["-f", f"sha={sha}"]

    rc, stdout, stderr = _gh(gh_args, hostname=hostname, timeout=30)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": f"Run: gh auth login --hostname {hostname}"}
        if "sha" in stderr.lower() or "422" in stderr:
            return {
                "error": "sha_required_or_mismatch",
                "detail": (
                    "File already exists — provide its current blob sha (from git_get_file .sha). "
                    f"Raw: {stderr[:300]}"
                ),
            }
        return {"error": "git_create_or_update_file_failed", "detail": stderr[:500]}

    try:
        data = json.loads(stdout)
        commit = data.get("commit", {})
        file_data = data.get("content", {})
        return {
            "ok":         True,
            "path":       file_data.get("path", path),
            "sha":        file_data.get("sha", ""),     # new blob sha after commit
            "commit_sha": commit.get("sha", "")[:12],
            "commit_url": commit.get("html_url", ""),
            "branch":     branch,
            "html_url":   file_data.get("html_url", ""),
        }
    except Exception as e:
        return {"error": "parse_failed", "detail": str(e), "raw": stdout[:300]}


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
    "git_create_branch": {
        "fn": tool_git_create_branch,
        "description": (
            "Create a new branch in a GEC GitHub repo from an existing ref (branch name, tag, or SHA). "
            "Use before git_create_or_update_file — the target branch must exist. "
            "Returns error 'branch_exists' if the branch already exists."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "org":      {"type": "string", "description": "GitHub org/owner"},
                "repo":     {"type": "string", "description": "Repo name"},
                "branch":   {"type": "string", "description": "New branch name e.g. fix/sarthi-et360-item-id-20260610"},
                "from_ref": {"type": "string", "description": "Source branch/tag/SHA to branch from (default: main)"},
                "hostname": {"type": "string", "description": "GitHub hostname (default: gecgithub01.walmart.com)"},
            },
            "required": ["org", "repo", "branch"],
        },
    },
    "git_create_or_update_file": {
        "fn": tool_git_create_or_update_file,
        "description": (
            "Create or update a single file in a GEC GitHub repo (PUT /contents). "
            "IMPORTANT: when updating an existing file you MUST supply `sha` — the blob SHA "
            "returned by git_get_file. Without it the API returns 422. "
            "To create a new file omit sha. Branch must already exist (use git_create_branch first)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "org":      {"type": "string", "description": "GitHub org/owner"},
                "repo":     {"type": "string", "description": "Repo name"},
                "path":     {"type": "string", "description": "File path in repo e.g. sql/et360/item_load.sql"},
                "content":  {"type": "string", "description": "Full new file content (plain text — auto base64-encoded)"},
                "message":  {"type": "string", "description": "Commit message"},
                "branch":   {"type": "string", "description": "Branch to commit to (must exist)"},
                "sha":      {"type": "string", "description": "Current blob SHA from git_get_file (required when updating existing file)"},
                "hostname": {"type": "string", "description": "GitHub hostname (default: gecgithub01.walmart.com)"},
            },
            "required": ["org", "repo", "path", "content", "message", "branch"],
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
            "serverInfo": {"name": "sarthi-git", "version": "1.1.0"},
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
