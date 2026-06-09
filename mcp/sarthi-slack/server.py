"""
sarthi-slack MCP stdio server — Walmart Enterprise Slack tools for sArthI.

Wraps the `slack-api` Wibey skill (gecgithub01.walmart.com/genaica/ai-registry-marketplace).
Auth: Playwright SSO bootstrap — captures xoxc token + fingerprint from Slack desktop session.
Cookies cached ~2h at ~/.wibey/slack-api-cookies.json (or ~/.claude/slack-api-cookies.json).

Auth pattern: Session-bootstrap (same pattern as sarthi-snow, but via Node.js/Playwright).
  - First-time: run reauth.js once — browser opens, user completes Walmart SSO
  - Auto-refresh: on cookie expiry the skill auto-reopens browser (~30 days TTL)
  - Session cache: <SKILL_DIR>/session.json (~2h TTL), auto-refreshed
  - On auth failure → returns {"error": "auth_expired", "detail": "..."}

Prerequisite (install once, via Walmart Artifactory npm registry):
  npm config set registry https://npm.ci.artifacts.walmart.com/artifactory/api/npm/npme-npm
  cd <slack-api skill dir> && npm install && node_modules/.bin/playwright install chromium
  node scripts/reauth.js   # opens browser for Walmart SSO — run once

Setup via /sar-setup: run /skill-installer slack-api then follow SKILL.md Step 1-2.

IMPORTANT — Node.js TLS patch required after skill install:
  After /skill-installer slack-api and npm install, patch api.js to use curl instead of
  Node fetch (Node.js rejects Walmart's enterprise TLS cert; curl uses system TLS which works):
  python3 ~/sarthi/scripts/patch-slack-api.py
  This patch is idempotent — safe to run multiple times.

Tools:
  slack_list_channels    — List channels from local cache (no API call)
  slack_get_messages     — Get recent messages from a channel (conversations.history)
  slack_get_thread       — Get thread replies (conversations.replies)
  slack_post_message     — Post to channel (requires SLACK_SEND_ALLOWED=true)
  slack_search_messages  — Full-text search across Slack (search.messages)
  slack_get_activity     — Get activity feed / mentions (activity.feed)

Config: SLACK_SEND_ALLOWED env var — set "true" to enable post_message (default: false)

CRITICAL: After slack_post_message returns ok:true — do NOT run any follow-up commands.
Any subsequent Bash invocation re-triggers the Wibey background task runner causing duplicate posts.

CRITICAL: stdout is JSON-RPC. ALL diagnostic output → sys.stderr. NEVER use print() to stdout.
"""

import sys
import os
import json
import argparse
import subprocess
from pathlib import Path

HOME = Path.home()
SLACK_SEND_ALLOWED = os.environ.get("SLACK_SEND_ALLOWED", "false").lower() == "true"


def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)


# ── Skill discovery ────────────────────────────────────────────────────────────

def _find_slack_api() -> Path | None:
    """Find api.js from the installed slack-api Wibey skill."""
    for search_root in [HOME / ".wibey", HOME / ".claude"]:
        for match in search_root.rglob("slack-api/scripts/api.js"):
            return match
    return None


def _check_skill() -> dict | None:
    """Check slack-api skill is installed and has deps. Returns error dict or None."""
    api_js = _find_slack_api()
    if not api_js:
        return {
            "error": "dependency_missing",
            "detail": (
                "slack-api skill not installed. Install it: "
                "In Wibey run: /skill-installer slack-api  "
                "Then set up: npm config set registry https://npm.ci.artifacts.walmart.com/artifactory/api/npm/npme-npm && "
                "cd ~/.wibey/skills/slack-api && npm install && node_modules/.bin/playwright install chromium && "
                "node scripts/reauth.js"
            ),
        }
    node_modules = api_js.parent.parent / "node_modules"
    if not node_modules.exists():
        return {
            "error": "dependency_missing",
            "detail": (
                f"slack-api skill found but npm deps not installed. Run: "
                f"npm config set registry https://npm.ci.artifacts.walmart.com/artifactory/api/npm/npme-npm && "
                f"cd {api_js.parent.parent} && npm install && node_modules/.bin/playwright install chromium && "
                f"node scripts/reauth.js"
            ),
        }
    return None


def _auth_expired_error() -> dict:
    return {
        "error": "auth_expired",
        "detail": (
            "Slack session expired or not set up. Run: "
            "cd ~/.wibey/skills/slack-api && node scripts/reauth.js  "
            "(opens browser for Walmart SSO — complete login, cookies saved automatically)"
        ),
    }


# ── Node.js runner ────────────────────────────────────────────────────────────

def _run_slack(method: str, params: dict | None = None, timeout: int = 30) -> dict:
    """Call slack-api skill via Node.js. Returns parsed JSON result."""
    dep_err = _check_skill()
    if dep_err:
        return dep_err

    api_js = _find_slack_api()
    cmd = ["node", str(api_js), method]
    if params:
        cmd.append(json.dumps(params))

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(api_js.parent.parent))
        stdout = r.stdout.strip()
        stderr = r.stderr.strip()

        if r.returncode == 2:
            # Exit code 2 = AUTH_EXPIRED (handled automatically by skill — browser opens)
            return _auth_expired_error()

        if r.returncode != 0:
            if "AUTH_EXPIRED" in stderr or "auth_expired" in stderr.lower():
                return _auth_expired_error()
            if "Connect Timeout" in stderr or "ECONNREFUSED" in stderr or "fetch failed" in stderr:
                return {
                    "error": "network_unreachable",
                    "detail": (
                        "Cannot reach walmart.enterprise.slack.com — this endpoint requires "
                        "Walmart internal network routing. Your machine may need a different "
                        "VPN profile or must be on Walmart's internal network. "
                        "Ask your team how they access the Slack enterprise grid from a laptop."
                    ),
                }
            return {"error": "slack_failed", "detail": (stderr or stdout)[:500]}

        if not stdout:
            return {"error": "slack_empty_response", "detail": stderr[:300]}

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return {"error": "parse_failed", "raw": stdout[:500]}

        if not data.get("ok", True):  # some methods don't have ok field
            err = data.get("error", "unknown")
            if err in ("invalid_auth", "not_authed", "token_revoked", "account_inactive", "AUTH_EXPIRED"):
                return _auth_expired_error()
            return {"error": "slack_api_error", "slack_error": err, "detail": str(data)[:300]}

        return data

    except subprocess.TimeoutExpired:
        return {"error": "slack_timeout", "detail": f"Slack API call timed out after {timeout}s"}
    except FileNotFoundError:
        return {"error": "dependency_missing", "detail": "node not found — install Node.js 18+"}
    except Exception as e:
        return {"error": "slack_error", "detail": str(e)[:300]}


# ── Tools ─────────────────────────────────────────────────────────────────────

def tool_slack_list_channels(args: dict) -> dict:
    """
    List Slack channels from local cache (no API call — fast).
    Cache populated on first bootstrap or by refresh.

    Args:
      name_filter (str, optional) — filter by channel name substring
      refresh     (bool, optional) — force refresh from Slack API (default false)
    """
    name_filter = args.get("name_filter", "").strip().lower()
    refresh = bool(args.get("refresh", False))

    method = "channels.refresh" if refresh else "channels.list"
    data = _run_slack(method, timeout=120 if refresh else 15)
    if "error" in data:
        return data

    channels = data.get("channels", [])
    if name_filter:
        channels = [c for c in channels if name_filter in c.get("name", "").lower()]

    return {"channels": channels, "count": len(channels)}


def tool_slack_get_messages(args: dict) -> dict:
    """
    Get recent messages from a Slack channel.

    Args:
      channel (str, required) — channel ID (C0123...) or name (general, #general)
      limit   (int, optional) — number of messages (default 20, max 200)
      oldest  (str, optional) — Unix timestamp — only messages after this
      latest  (str, optional) — Unix timestamp — only messages before this
    """
    channel = args.get("channel", "").strip()
    if not channel:
        return {"error": "channel is required"}

    limit = min(int(args.get("limit", 20)), 200)
    params: dict = {"channel": channel, "limit": str(limit)}

    oldest = args.get("oldest", "").strip()
    latest = args.get("latest", "").strip()
    if oldest:
        params["oldest"] = oldest
    if latest:
        params["latest"] = latest

    # Resolve channel name to ID if not already an ID
    if not channel.startswith("C") or len(channel) < 8:
        resolve = _run_slack("channel.resolve", {"name": channel.lstrip("#")}, timeout=15)
        if "error" in resolve:
            return resolve
        params["channel"] = resolve.get("id", channel)

    data = _run_slack("conversations.history", params, timeout=30)
    if "error" in data:
        return data

    messages = data.get("messages", [])
    return {
        "channel": channel,
        "messages": [
            {
                "ts":          m.get("ts"),
                "user":        m.get("user") or m.get("bot_id", ""),
                "text":        m.get("text", ""),
                "reply_count": m.get("reply_count", 0),
                "thread_ts":   m.get("thread_ts"),
            }
            for m in messages
        ],
        "count": len(messages),
        "has_more": data.get("has_more", False),
    }


def tool_slack_get_thread(args: dict) -> dict:
    """
    Get replies in a Slack thread.

    Args:
      channel (str, required) — channel ID or name
      ts      (str, required) — parent message timestamp (thread_ts)
    """
    channel = args.get("channel", "").strip()
    ts = args.get("ts", "").strip()
    if not channel or not ts:
        return {"error": "channel and ts are required"}

    if not channel.startswith("C") or len(channel) < 8:
        resolve = _run_slack("channel.resolve", {"name": channel.lstrip("#")}, timeout=15)
        if "error" in resolve:
            return resolve
        channel = resolve.get("id", channel)

    data = _run_slack("conversations.replies", {"channel": channel, "ts": ts}, timeout=30)
    if "error" in data:
        return data

    return {
        "channel": channel,
        "thread_ts": ts,
        "messages": [
            {"ts": m.get("ts"), "user": m.get("user", ""), "text": m.get("text", "")}
            for m in data.get("messages", [])
        ],
    }


def tool_slack_post_message(args: dict) -> dict:
    """
    Post a message to a Slack channel.
    Requires SLACK_SEND_ALLOWED=true in the sarthi-slack MCP server env.

    IMPORTANT: After this returns ok:true — do NOT run any follow-up commands.
    Any subsequent Bash invocation re-triggers Wibey's background task runner
    causing duplicate posts.

    Args:
      channel   (str, required) — channel name or ID
      text      (str, required) — message text (Slack mrkdwn: *bold*, <url|text>)
      thread_ts (str, optional) — reply in thread (parent message ts)
    """
    if not SLACK_SEND_ALLOWED:
        return {
            "error": "send_not_allowed",
            "detail": (
                "Posting to Slack is disabled. Set SLACK_SEND_ALLOWED=true in the "
                "sarthi-slack MCP server env config in mcp.json to enable."
            ),
        }

    channel = args.get("channel", "").strip()
    text = args.get("text", "").strip()
    if not channel:
        return {"error": "channel is required"}
    if not text:
        return {"error": "text is required"}

    thread_ts = args.get("thread_ts", "").strip()
    params: dict = {"channel": channel, "text": text}
    if thread_ts:
        params["thread_ts"] = thread_ts

    data = _run_slack("chat.postMessage", params, timeout=30)
    if "error" in data:
        return data

    return {
        "ok": True,
        "channel": data.get("channel"),
        "ts": data.get("ts"),
        "note": "Message posted. Check Slack to confirm — do not retry.",
    }


def tool_slack_search_messages(args: dict) -> dict:
    """
    Search Slack messages by keyword.
    Supports Slack search syntax: after:YYYY-MM-DD, before:YYYY-MM-DD, in:#channel, from:@user.

    Args:
      query (str, required) — search query (e.g. "DAG failed after:2026-06-01 in:#alerts")
      count (int, optional) — max results (default 20)
    """
    query = args.get("query", "").strip()
    if not query:
        return {"error": "query is required"}

    count = min(int(args.get("count", 20)), 100)
    data = _run_slack("search.messages", {"query": query, "count": str(count)}, timeout=45)
    if "error" in data:
        return data

    matches = data.get("matches", [])
    return {
        "query": query,
        "total": data.get("total", len(matches)),
        "results": [
            {
                "channel":    m.get("channel", ""),
                "channel_id": m.get("channelId", ""),
                "ts":         m.get("ts"),
                "user":       m.get("user", ""),
                "text":       m.get("text", ""),
                "permalink":  m.get("permalink", ""),
            }
            for m in matches
        ],
        "count": len(matches),
    }


def tool_slack_get_activity(args: dict) -> dict:
    """
    Get Slack activity feed — mentions, reactions, thread replies directed at you.

    Args:
      limit (int, optional) — max items (default 20)
    """
    limit = min(int(args.get("limit", 20)), 100)
    data = _run_slack("activity.feed", {"limit": str(limit)}, timeout=30)
    if "error" in data:
        return data

    return {
        "items": data.get("items", []),
        "count": len(data.get("items", [])),
        "next_cursor": data.get("next_cursor"),
    }


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS = {
    "slack_list_channels": {
        "fn": tool_slack_list_channels,
        "description": "List Slack channels from local cache. Optionally filter by name or force refresh from API.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name_filter": {"type": "string",  "description": "Filter by channel name substring"},
                "refresh":     {"type": "boolean", "description": "Force refresh from Slack API (default false)"},
            },
        },
    },
    "slack_get_messages": {
        "fn": tool_slack_get_messages,
        "description": "Get recent messages from a Slack channel. Supports channel name or ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string",  "description": "Channel name (general, #alerts) or ID (C0123...)"},
                "limit":   {"type": "integer", "description": "Number of messages (default 20, max 200)"},
                "oldest":  {"type": "string",  "description": "Unix timestamp — only messages after this"},
                "latest":  {"type": "string",  "description": "Unix timestamp — only messages before this"},
            },
            "required": ["channel"],
        },
    },
    "slack_get_thread": {
        "fn": tool_slack_get_thread,
        "description": "Get all replies in a Slack thread.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name or ID"},
                "ts":      {"type": "string", "description": "Parent message timestamp (thread_ts)"},
            },
            "required": ["channel", "ts"],
        },
    },
    "slack_post_message": {
        "fn": tool_slack_post_message,
        "description": "Post a message to a Slack channel. Requires SLACK_SEND_ALLOWED=true in server env. After ok:true do NOT retry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel":   {"type": "string", "description": "Channel name or ID"},
                "text":      {"type": "string", "description": "Message text (Slack mrkdwn: *bold*, <url|text>)"},
                "thread_ts": {"type": "string", "description": "Reply in thread — parent message timestamp"},
            },
            "required": ["channel", "text"],
        },
    },
    "slack_search_messages": {
        "fn": tool_slack_search_messages,
        "description": "Search Slack messages. Supports: after:YYYY-MM-DD, before:YYYY-MM-DD, in:#channel, from:@user.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",  "description": "Search query e.g. 'DAG failed after:2026-06-01 in:#alerts'"},
                "count": {"type": "integer", "description": "Max results (default 20)"},
            },
            "required": ["query"],
        },
    },
    "slack_get_activity": {
        "fn": tool_slack_get_activity,
        "description": "Get Slack activity feed — mentions, reactions, thread replies directed at you.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max items (default 20)"},
            },
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
            "serverInfo": {"name": "sarthi-slack", "version": "2.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return ok({"tools": [
            {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
            for name, spec in TOOLS.items()
        ]})

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
    log("sarthi-slack MCP server starting (stdio)")
    log(f"SLACK_SEND_ALLOWED: {SLACK_SEND_ALLOWED}")
    slack_api = _find_slack_api()
    log(f"slack-api skill: {slack_api or 'NOT FOUND — run /skill-installer slack-api'}")
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
    parser = argparse.ArgumentParser(description="sarthi-slack MCP server — Walmart Slack tools")
    parser.add_argument("--test", metavar="TOOL", help="Run a single tool and print result")
    parser.add_argument("args_json", nargs="?", default="{}", help="JSON args for --test mode")
    parsed = parser.parse_args()

    if parsed.test:
        run_test(parsed.test, parsed.args_json)
    else:
        run_stdio()
