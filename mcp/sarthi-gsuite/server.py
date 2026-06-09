#!/usr/bin/env python3
"""
sarthi-gsuite MCP stdio server — GSuite/AD group lookup tools for sArthI.

Wraps the Walmart cloud-services GSuite API:
  https://cloud-services.wal-mart.com/api/gsuite/

Tools:
  gsuite_get_principal_groups — List all AD groups a principal belongs to
                                 (user email, service account, process ID, etc.)
  gsuite_get_group_members    — List all members of an AD group

Auth:
  gcloud ADC access token (gcloud auth print-access-token).
  No session file — tokens are fetched fresh per request via subprocess.
  On auth failure → returns {"error": "auth_expired"} with fix hint.

Network:
  Bypasses corporate proxy (ProxyHandler({})) — cloud-services.wal-mart.com
  is inside the Walmart network and handles TLS directly. The corporate proxy
  causes TLS resets for this host.

CRITICAL: stdout is JSON-RPC. ALL diagnostic output → sys.stderr. NEVER use print() to stdout.
"""

import sys
import os
import json
import argparse
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

# ── stderr logger ─────────────────────────────────────────────────────────────
def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)


# ── Constants ─────────────────────────────────────────────────────────────────
GSUITE_BASE = "https://cloud-services.wal-mart.com/api/gsuite"
USERS_API   = f"{GSUITE_BASE}/users/v1"
GROUPS_API  = f"{GSUITE_BASE}/groups/v1"
TIMEOUT     = 20


# ── Auth ──────────────────────────────────────────────────────────────────────
def _get_access_token() -> str | None:
    """Fetch a fresh gcloud access token via subprocess. Returns None on failure."""
    try:
        r = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return r.stdout.strip()
        log(f"gcloud auth failed: {r.stderr.strip()[:200]}")
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log(f"gcloud not available: {e}")
        return None


def auth_expired_error() -> dict:
    return {
        "error": "auth_expired",
        "message": "gcloud access token unavailable or expired.",
        "fix": "Run: gcloud auth login && gcloud auth application-default login",
    }


# ── HTTP helper ───────────────────────────────────────────────────────────────
def _get(url: str, token: str) -> tuple[int | None, dict | str]:
    """
    GET url with Bearer token. Bypasses corporate proxy (ProxyHandler({})).
    Returns (status_code, parsed_json_or_error_str).
    """
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    # Empty dict = no proxy. Required for cloud-services.wal-mart.com —
    # the corporate proxy causes TLS resets for this host.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, {"_raw": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw}
    except Exception as e:
        return None, str(e)


# ── Tool implementations ──────────────────────────────────────────────────────

def tool_gsuite_get_principal_groups(args: dict) -> dict:
    """
    List all AD groups a principal belongs to.

    Accepts any principal type:
      - User email:          john.doe@walmart.com
      - Service account:     svc-name@project.iam.gserviceaccount.com
      - Process/short ID:    abc123@email.wal-mart.com  or  abc123

    Args:
      principal  (str, required) — email, service account, or short ID
      expand     (bool, default true) — include full group metadata (name, description)
    """
    principal = args.get("principal", "").strip()
    if not principal:
        return {"error": "principal is required (email, service account, or short ID)"}

    expand = bool(args.get("expand", True))

    token = _get_access_token()
    if not token:
        return auth_expired_error()

    url = f"{USERS_API}/{urllib.request.quote(principal, safe='')}?expand={str(expand).lower()}"
    status, data = _get(url, token)

    if status is None:
        return {"error": "connection_failed", "detail": str(data)[:300]}
    if status == 401 or status == 403:
        return {
            "error": "auth_expired",
            "message": f"HTTP {status} from GSuite API — token may be expired or lack permissions.",
            "fix": "Run: gcloud auth login && gcloud auth application-default login",
        }
    if status == 404:
        return {"error": "not_found", "principal": principal, "detail": "Principal not found in GSuite directory."}
    if status != 200:
        return {"error": f"http_{status}", "detail": str(data)[:500]}

    groups = data.get("groups", [])
    return {
        "principal":       data.get("username", principal),
        "service_account": data.get("service_account", False),
        "valid":           data.get("valid", None),
        "cached":          data.get("_cached", False),
        "group_count":     len(groups),
        "groups":          groups,
    }


def tool_gsuite_get_group_members(args: dict) -> dict:
    """
    List all members of an AD group.

    Args:
      group   (str, required) — group email e.g. gcp-dev-mx-walmart-reader@walmart.com
      expand  (bool, default true) — include group metadata (name, description, memberCount)
      limit   (int, optional) — cap the returned member list (useful for large groups; 0 = all)
    """
    group = args.get("group", "").strip()
    if not group:
        return {"error": "group is required (full group email)"}

    expand = bool(args.get("expand", True))
    limit  = int(args.get("limit", 0))

    token = _get_access_token()
    if not token:
        return auth_expired_error()

    url = f"{GROUPS_API}/{urllib.request.quote(group, safe='')}?expand={str(expand).lower()}"
    status, data = _get(url, token)

    if status is None:
        return {"error": "connection_failed", "detail": str(data)[:300]}
    if status == 401 or status == 403:
        return {
            "error": "auth_expired",
            "message": f"HTTP {status} from GSuite API.",
            "fix": "Run: gcloud auth login && gcloud auth application-default login",
        }
    if status == 404:
        return {"error": "not_found", "group": group, "detail": "Group not found in GSuite directory."}
    if status != 200:
        return {"error": f"http_{status}", "detail": str(data)[:500]}

    member_list: list = data.get("member_list", [])
    group_data  = data.get("data", {})

    truncated = False
    if limit and limit > 0 and len(member_list) > limit:
        member_list = member_list[:limit]
        truncated = True

    result = {
        "group":              data.get("target_group", group),
        "valid":              data.get("valid", None),
        "cached":             data.get("_cached", False),
        "member_count":       len(data.get("member_list", [])),  # total before limit
        "returned_count":     len(member_list),
        "truncated":          truncated,
        "members":            member_list,
    }

    if group_data:
        result["group_info"] = {
            "name":                group_data.get("name"),
            "description":         group_data.get("description"),
            "direct_member_count": group_data.get("directMembersCount"),
            "admin_created":       group_data.get("adminCreated"),
            "id":                  group_data.get("id"),
        }

    return result


# ── MCP dispatcher ────────────────────────────────────────────────────────────
TOOLS = {
    "gsuite_get_principal_groups": {
        "fn":          tool_gsuite_get_principal_groups,
        "description": (
            "List all AD/GSuite groups a principal belongs to. "
            "Accepts any principal type: user email (john.doe@walmart.com), "
            "service account (svc@project.iam.gserviceaccount.com), "
            "or short process ID (abc123@email.wal-mart.com). "
            "Use to answer: 'What AD groups is this user/service account/process in?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "principal": {
                    "type":        "string",
                    "description": "Principal identifier: user email, service account email, or short process ID",
                },
                "expand": {
                    "type":        "boolean",
                    "description": "Include full group metadata — name, description (default true)",
                },
            },
            "required": ["principal"],
        },
    },
    "gsuite_get_group_members": {
        "fn":          tool_gsuite_get_group_members,
        "description": (
            "List all members of an AD/GSuite group. "
            "Returns users, service accounts, process IDs, and nested groups. "
            "Use to answer: 'Who/what has access via this AD group?' "
            "Supports limit to cap output for large groups (e.g. limit=50)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "group": {
                    "type":        "string",
                    "description": "Full group email e.g. gcp-dev-mx-walmart-reader@walmart.com",
                },
                "expand": {
                    "type":        "boolean",
                    "description": "Include group metadata — name, description, memberCount (default true)",
                },
                "limit": {
                    "type":        "integer",
                    "description": "Cap the returned member list (0 = all members, default 0). Useful for large groups.",
                },
            },
            "required": ["group"],
        },
    },
}


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
            "capabilities":    {"tools": {}},
            "serverInfo":      {"name": "sarthi-gsuite", "version": "1.0.0"},
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
        params    = req.get("params", {})
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
    log("sarthi-gsuite MCP server starting (stdio)")
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
    parser = argparse.ArgumentParser(description="sarthi-gsuite MCP server")
    parser.add_argument("--test", metavar="TOOL", help="Run a single tool and print result")
    parser.add_argument("args_json", nargs="?", default="{}", help="JSON args for --test mode")
    parsed = parser.parse_args()

    if parsed.test:
        run_test(parsed.test, parsed.args_json)
    else:
        run_stdio()
