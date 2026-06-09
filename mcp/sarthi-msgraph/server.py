"""
sarthi-msgraph MCP stdio server — Microsoft Graph email + Teams tools for sArthI.

Wraps ~/.wibey/skills/msgraph/scripts/mail.ts and teams.ts as MCP tools.
Subprocess to existing TypeScript — does NOT reimplement Graph API calls.

Tools:
  mail_list                — List inbox/folder messages
  mail_get                 — Get a single message by ID
  mail_search              — Search messages by query
  mail_create_draft        — Create an Outlook draft (never sends; supports TO/CC/attachments)
  mail_send                — Send an email (gated by send_allowed flag)
  mail_reply               — Reply to a message (gated by send_allowed flag)
  teams_list_teams         — List joined Teams
  teams_list_channels      — List channels in a team
  teams_list_channel_messages — Get recent messages from a channel
  teams_send_channel_message  — Post to a channel (gated by send_allowed flag)
  teams_send_direct_message   — Send a DM to a user (gated by send_allowed flag)

Auth:
  Primary token store: macOS Keychain, service "wibey.msgraph" (written by auth.ts via keystore.sh).
  Fallback: ~/.wibey/msgraph_tokens.json (written only when Keychain unavailable).
  On auth failure → returns {"error": "auth_expired", "fix": "Run /msgraph login interactively"}
  NEVER calls auth.ts login — that opens a browser and will hang cron/non-interactive runs.

CRITICAL: stdout is JSON-RPC. ALL diagnostic output → sys.stderr. NEVER use print() to stdout.
"""

import sys
import os
import json
import subprocess
import argparse
from pathlib import Path

def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)

MSGRAPH_DIR = Path.home() / ".wibey" / "skills" / "msgraph" / "scripts"
MAIL_TS = MSGRAPH_DIR / "mail.ts"
TEAMS_TS = MSGRAPH_DIR / "teams.ts"
TOKENS_FILE = Path.home() / ".wibey" / "msgraph_tokens.json"  # FILE FALLBACK ONLY — primary storage is macOS Keychain (service: wibey.msgraph). auth.ts writes to Keychain first via keystore.sh; this file is only written when Keychain is unavailable.
TIMEOUT = 30

# send_allowed gates all write/send operations — avoids accidental emails in cron
SEND_ALLOWED = os.environ.get("MSGRAPH_SEND_ALLOWED", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def run_bun(script: Path, args: list[str]) -> dict:
    """
    Run a bun TypeScript script and return parsed JSON output.
    Returns {"error": "auth_expired", ...} on auth failures.
    Returns {"error": "script_error", ...} on non-zero exit with non-JSON output.
    """
    if not script.exists():
        return {"error": "msgraph_not_installed", "fix": "Run /skill-installer msgraph in Wibey"}

    # Note: tokens may be in macOS Keychain (primary) or msgraph_tokens.json (fallback).
    # Do NOT gate on file existence — auth.ts handles both paths and returns non-zero on failure.

    node_path = str(Path.home() / ".local" / "lib" / "node_modules")
    bun_paths = [
        "bun",
        str(Path.home() / ".local" / "bin" / "bun"),
        str(Path.home() / ".bun" / "bin" / "bun"),
    ]

    bun_bin = None
    for p in bun_paths:
        try:
            result = subprocess.run([p, "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                bun_bin = p
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    if bun_bin is None:
        return {"error": "bun_not_found", "fix": "Install bun: curl -fsSL https://bun.sh/install | bash"}

    cmd = [bun_bin, str(script)] + args
    env = os.environ.copy()
    env["NODE_PATH"] = node_path

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "detail": f"Script did not respond within {TIMEOUT}s"}
    except Exception as e:
        return {"error": "subprocess_error", "detail": str(e)}

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    if stderr:
        log(f"[sarthi-msgraph] stderr: {stderr[:500]}")

    if not stdout:
        if proc.returncode != 0:
            # Check for auth-related errors in stderr
            if "token" in stderr.lower() or "auth" in stderr.lower() or "401" in stderr or "expired" in stderr.lower():
                return {
                    "error": "auth_expired",
                    "fix": "Run /msgraph login interactively in Wibey to re-authenticate",
                    "detail": stderr[:300]
                }
            return {"error": "script_error", "exit_code": proc.returncode, "detail": stderr[:500]}
        return {"error": "empty_output"}

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # Sometimes the script returns non-JSON error messages
        if "token" in stdout.lower() or "login" in stdout.lower() or "auth" in stdout.lower():
            return {
                "error": "auth_expired",
                "fix": "Run /msgraph login interactively in Wibey to re-authenticate",
                "detail": stdout[:300]
            }
        return {"error": "json_parse_error", "raw": stdout[:500]}

    # Check for auth error in parsed JSON
    if isinstance(data, dict):
        err_msg = str(data.get("error", "")).lower()
        if "token" in err_msg or "auth" in err_msg or "expired" in err_msg or "unauthorized" in err_msg:
            return {
                "error": "auth_expired",
                "fix": "Run /msgraph login interactively in Wibey to re-authenticate",
                "detail": data.get("error", "")
            }

    return data


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_mail_list(args: dict) -> dict:
    """List inbox messages."""
    cmd_args = ["list"]
    if folder := args.get("folder"):
        cmd_args += ["--folder", folder]
    if limit := args.get("limit"):
        cmd_args += ["--limit", str(limit)]
    if args.get("unread"):
        cmd_args.append("--unread")
    return run_bun(MAIL_TS, cmd_args)


def tool_mail_get(args: dict) -> dict:
    """Get a single message by ID."""
    message_id = args.get("message_id", "")
    if not message_id:
        return {"error": "missing_required_field", "field": "message_id"}
    return run_bun(MAIL_TS, ["get", message_id])


def tool_mail_search(args: dict) -> dict:
    """Search messages by query string."""
    query = args.get("query", "")
    if not query:
        return {"error": "missing_required_field", "field": "query"}
    cmd_args = ["search", "--query", query]
    if limit := args.get("limit"):
        cmd_args += ["--limit", str(limit)]
    return run_bun(MAIL_TS, cmd_args)


def tool_mail_send(args: dict) -> dict:
    """Send an email. Gated by MSGRAPH_SEND_ALLOWED env var."""
    if not SEND_ALLOWED:
        return {
            "error": "send_not_allowed",
            "fix": "Set MSGRAPH_SEND_ALLOWED=true in sarthi-msgraph env config to enable sending",
            "note": "This gate prevents accidental emails from cron/automated runs"
        }
    to_raw = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    if not all([to_raw, subject, body]):
        return {"error": "missing_required_fields", "required": ["to", "subject", "body"]}
    # Support both single string and list of recipients
    to = ",".join(to_raw) if isinstance(to_raw, list) else to_raw
    cmd_args = ["send", "--to", to, "--subject", subject, "--body", body, "--confirm"]
    cc_raw = args.get("cc")
    if cc_raw:
        cc = ",".join(cc_raw) if isinstance(cc_raw, list) else cc_raw
        cmd_args += ["--cc", cc]
    if args.get("html"):
        cmd_args.append("--html")
    return run_bun(MAIL_TS, cmd_args)


def tool_mail_reply(args: dict) -> dict:
    """Reply to a message. Gated by MSGRAPH_SEND_ALLOWED."""
    if not SEND_ALLOWED:
        return {
            "error": "send_not_allowed",
            "fix": "Set MSGRAPH_SEND_ALLOWED=true in sarthi-msgraph env config to enable replies",
        }
    message_id = args.get("message_id", "")
    body = args.get("body", "")
    if not all([message_id, body]):
        return {"error": "missing_required_fields", "required": ["message_id", "body"]}
    cmd_args = ["reply", message_id, "--body", body, "--confirm"]
    if args.get("reply_all"):
        cmd_args.append("--reply-all")
    return run_bun(MAIL_TS, cmd_args)


def tool_teams_list_teams(args: dict) -> dict:
    """List joined Teams."""
    return run_bun(TEAMS_TS, ["list-teams"])


def tool_teams_list_channels(args: dict) -> dict:
    """List channels in a team."""
    team_id = args.get("team_id", "")
    if not team_id:
        return {"error": "missing_required_field", "field": "team_id"}
    return run_bun(TEAMS_TS, ["list-channels", team_id])


def tool_teams_list_channel_messages(args: dict) -> dict:
    """Get recent messages from a Teams channel."""
    team_id = args.get("team_id", "")
    channel_id = args.get("channel_id", "")
    if not all([team_id, channel_id]):
        return {"error": "missing_required_fields", "required": ["team_id", "channel_id"]}
    limit = str(args.get("limit", 20))
    return run_bun(TEAMS_TS, ["list-channel-messages", team_id, channel_id, limit])


def tool_teams_send_channel_message(args: dict) -> dict:
    """Post a message to a Teams channel. Gated by MSGRAPH_SEND_ALLOWED."""
    if not SEND_ALLOWED:
        return {
            "error": "send_not_allowed",
            "fix": "Set MSGRAPH_SEND_ALLOWED=true in sarthi-msgraph env config to enable sending",
        }
    team_id = args.get("team_id", "")
    channel_id = args.get("channel_id", "")
    content = args.get("content", "")
    if not all([team_id, channel_id, content]):
        return {"error": "missing_required_fields", "required": ["team_id", "channel_id", "content"]}
    content_type = args.get("content_type", "text")
    return run_bun(TEAMS_TS, ["send-channel-message", team_id, channel_id, content, content_type])


def tool_teams_send_direct_message(args: dict) -> dict:
    """Send a direct message to a user. Gated by MSGRAPH_SEND_ALLOWED."""
    if not SEND_ALLOWED:
        return {
            "error": "send_not_allowed",
            "fix": "Set MSGRAPH_SEND_ALLOWED=true in sarthi-msgraph env config to enable sending",
        }
    user_email = args.get("user_email", "")
    content = args.get("content", "")
    if not all([user_email, content]):
        return {"error": "missing_required_fields", "required": ["user_email", "content"]}
    content_type = args.get("content_type", "text")
    return run_bun(TEAMS_TS, ["send-direct-message", user_email, content, content_type])


def tool_create_draft(args: dict) -> dict:
    """
    Create an Outlook draft (never sends). Calls Graph API POST /me/messages directly.
    Token read order: macOS Keychain (wibey.msgraph) → TOKENS_FILE fallback.
    Returns the draft message ID on success.
    """
    subject = args.get("subject", "")
    body = args.get("body", "")
    to_list = args.get("to", [])

    if not subject or not body or not to_list:
        return {"error": "missing_required_fields", "required": ["to", "subject", "body"]}

    # --- Token resolution ---
    keystore_sh = MSGRAPH_DIR / "keystore.sh"
    access_token = None

    if keystore_sh.exists():
        try:
            r = subprocess.run(
                ["bash", str(keystore_sh), "get", "wibey.msgraph"],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0 and r.stdout.strip():
                raw = r.stdout.strip()
                try:
                    token_data = json.loads(raw)
                    access_token = token_data.get("accessToken") or token_data.get("access_token")
                except json.JSONDecodeError:
                    pass  # Not JSON — not a token blob
        except Exception:
            pass

    if not access_token and TOKENS_FILE.exists():
        try:
            token_data = json.loads(TOKENS_FILE.read_text())
            access_token = token_data.get("accessToken") or token_data.get("access_token")
        except Exception:
            pass

    if not access_token:
        return {
            "error": "auth_expired",
            "fix": "Run /msgraph login interactively in Wibey to re-authenticate",
            "detail": "No valid token found in Keychain (wibey.msgraph) or TOKENS_FILE fallback"
        }

    # --- Build Graph API payload ---
    def addr(email: str) -> dict:
        return {"emailAddress": {"address": email.strip()}}

    cc_list = args.get("cc", [])
    attachments_in = args.get("attachments", [])  # list of {"name": str, "content_type": str, "content_bytes_b64": str}

    message: dict = {
        "subject": subject,
        "body": {
            "contentType": "HTML" if args.get("html") else "Text",
            "content": body,
        },
        "toRecipients": [addr(e) for e in (to_list if isinstance(to_list, list) else [to_list])],
    }

    if cc_list:
        message["ccRecipients"] = [addr(e) for e in (cc_list if isinstance(cc_list, list) else [cc_list])]

    if attachments_in:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": a["name"],
                "contentType": a.get("content_type", "application/octet-stream"),
                "contentBytes": a["content_bytes_b64"],
            }
            for a in attachments_in
        ]

    # --- Call Graph API ---
    try:
        proc = subprocess.run(
            [
                "curl", "-s", "-X", "POST",
                "https://graph.microsoft.com/v1.0/me/messages",
                "-H", f"Authorization: Bearer {access_token}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(message),
            ],
            capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "detail": "Graph API did not respond within 30s"}
    except Exception as e:
        return {"error": "subprocess_error", "detail": str(e)}

    stdout = proc.stdout.strip()
    try:
        resp = json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "json_parse_error", "raw": stdout[:500]}

    if "error" in resp:
        err_code = resp["error"].get("code", "")
        err_msg = resp["error"].get("message", "")
        if "InvalidAuthenticationToken" in err_code or "401" in str(proc.returncode):
            return {
                "error": "auth_expired",
                "fix": "Run /msgraph login interactively in Wibey to re-authenticate",
                "detail": err_msg
            }
        return {"error": "graph_api_error", "code": err_code, "message": err_msg}

    return {
        "status": "draft_created",
        "draft_id": resp.get("id"),
        "subject": resp.get("subject"),
        "web_link": resp.get("webLink"),
    }


def tool_refresh_auth(args: dict) -> dict:
    """
    Trigger msgraph re-authentication in a detached terminal process.
    Opens a browser window for Walmart AD SSO + MFA. Returns immediately —
    does NOT wait for completion (login takes ~30s of user interaction).

    After completing login in the browser, mail/teams tools will work again.
    Root cause: Walmart Azure AD issues SPA-bound tokens (AADSTS9002327) —
    server-side refresh is blocked by policy. Re-login is required ~every 24h.
    """
    auth_ts = Path.home() / ".wibey" / "skills" / "msgraph" / "scripts" / "auth.ts"
    if not auth_ts.exists():
        return {"error": "msgraph_not_installed", "fix": "Run /skill-installer msgraph in Wibey"}

    node_path = str(Path.home() / ".local" / "lib" / "node_modules")
    bun_paths = ["bun", str(Path.home() / ".local" / "bin" / "bun"), str(Path.home() / ".bun" / "bin" / "bun")]
    bun_bin = None
    for p in bun_paths:
        try:
            r = subprocess.run([p, "--version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                bun_bin = p
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    if bun_bin is None:
        return {"error": "bun_not_found"}

    env = os.environ.copy()
    env["NODE_PATH"] = node_path

    try:
        # Detached — don't wait. Login opens a browser and takes ~30s of user interaction.
        subprocess.Popen(
            [bun_bin, str(auth_ts), "login"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {
            "status": "login_started",
            "message": "Browser opened for Walmart AD authentication. Complete MFA, then retry your mail/teams request.",
            "note": "Root cause: Walmart Azure AD blocks server-side token refresh (AADSTS9002327). Re-login required ~every 24h.",
        }
    except Exception as e:
        return {"error": "launch_failed", "detail": str(e)}


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS = {
    "mail_list": {
        "fn": tool_mail_list,
        "description": "List inbox or folder messages. Returns message summaries with IDs for mail_get.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Folder name (inbox, sentitems, deleteditems). Default: inbox"},
                "limit": {"type": "integer", "description": "Max messages to return. Default: 10"},
                "unread": {"type": "boolean", "description": "Filter to unread messages only"},
            },
        },
    },
    "mail_get": {
        "fn": tool_mail_get,
        "description": "Get full content of a single email message by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Message ID from mail_list or mail_search"},
            },
            "required": ["message_id"],
        },
    },
    "mail_search": {
        "fn": tool_mail_search,
        "description": "Search emails by keyword or phrase. Useful for finding Airflow alerts, incidents, or notifications.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g. 'Airflow DAG failed', 'pipeline error')"},
                "limit": {"type": "integer", "description": "Max results. Default: 10"},
            },
            "required": ["query"],
        },
    },
    "mail_send": {
        "fn": tool_mail_send,
        "description": "Send an email. Requires MSGRAPH_SEND_ALLOWED=true env var (safety gate for cron).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {
                    "oneOf": [
                        {"type": "string", "description": "Single recipient email"},
                        {"type": "array", "items": {"type": "string"}, "description": "List of recipient emails"},
                    ],
                    "description": "TO recipient(s)"
                },
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body (plain text or HTML)"},
                "cc": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "CC recipient(s) — optional"
                },
                "html": {"type": "boolean", "description": "Set true if body is HTML"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    "mail_reply": {
        "fn": tool_mail_reply,
        "description": "Reply to an email. Requires MSGRAPH_SEND_ALLOWED=true env var.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Message ID to reply to"},
                "body": {"type": "string", "description": "Reply body text"},
                "reply_all": {"type": "boolean", "description": "Reply-all if true, reply-to-sender if false"},
            },
            "required": ["message_id", "body"],
        },
    },
    "teams_list_teams": {
        "fn": tool_teams_list_teams,
        "description": "List all Microsoft Teams the user has joined. Returns team IDs needed for channel operations.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    "teams_list_channels": {
        "fn": tool_teams_list_channels,
        "description": "List channels in a Teams team. Returns channel IDs for teams_list_channel_messages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string", "description": "Team GUID from teams_list_teams"},
            },
            "required": ["team_id"],
        },
    },
    "teams_list_channel_messages": {
        "fn": tool_teams_list_channel_messages,
        "description": "Get recent messages from a Teams channel. Use for monitoring team notifications and incident alerts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string", "description": "Team GUID from teams_list_teams"},
                "channel_id": {"type": "string", "description": "Channel GUID from teams_list_channels"},
                "limit": {"type": "integer", "description": "Number of messages to return. Default: 20"},
            },
            "required": ["team_id", "channel_id"],
        },
    },
    "teams_send_channel_message": {
        "fn": tool_teams_send_channel_message,
        "description": "Post a message to a Teams channel. Requires MSGRAPH_SEND_ALLOWED=true env var.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string", "description": "Team GUID"},
                "channel_id": {"type": "string", "description": "Channel GUID"},
                "content": {"type": "string", "description": "Message content"},
                "content_type": {"type": "string", "description": "text or html. Default: text"},
            },
            "required": ["team_id", "channel_id", "content"],
        },
    },
    "teams_send_direct_message": {
        "fn": tool_teams_send_direct_message,
        "description": "Send a direct message to a user by email. Requires MSGRAPH_SEND_ALLOWED=true env var.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_email": {"type": "string", "description": "Recipient Walmart email address"},
                "content": {"type": "string", "description": "Message content"},
                "content_type": {"type": "string", "description": "text or html. Default: text"},
            },
            "required": ["user_email", "content"],
        },
    },
    "mail_create_draft": {
        "fn": tool_create_draft,
        "description": (
            "Create an Outlook draft message (never sends). "
            "Reads token from macOS Keychain (wibey.msgraph) first, falls back to msgraph_tokens.json. "
            "Returns draft_id + web_link on success. "
            "Supports multiple TO/CC recipients and file attachments (base64-encoded)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {
                    "oneOf": [
                        {"type": "string", "description": "Single recipient email"},
                        {"type": "array", "items": {"type": "string"}, "description": "List of recipient emails"},
                    ],
                    "description": "TO recipient(s)"
                },
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body (plain text or HTML)"},
                "cc": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "CC recipient(s) — optional"
                },
                "html": {"type": "boolean", "description": "Set true if body is HTML. Default: false"},
                "attachments": {
                    "type": "array",
                    "description": "File attachments (optional)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Filename shown in email"},
                            "content_type": {"type": "string", "description": "MIME type (e.g. application/sql, text/plain)"},
                            "content_bytes_b64": {"type": "string", "description": "Base64-encoded file content"},
                        },
                        "required": ["name", "content_bytes_b64"],
                    },
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    "refresh_auth": {
        "fn": tool_refresh_auth,
        "description": "Re-authenticate with Microsoft 365. Opens browser for Walmart AD SSO + MFA. Call this when mail_list/mail_get/teams tools return auth_expired. Completes in ~30s after user interaction in browser.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
}


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------

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
            "serverInfo": {"name": "sarthi-msgraph", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        tools_list = [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["inputSchema"],
            }
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
    log("sarthi-msgraph MCP server starting (stdio)")
    log(f"  send_allowed={SEND_ALLOWED}, msgraph_dir={MSGRAPH_DIR}")
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
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as e:
        print(f"Invalid JSON args: {e}")
        sys.exit(1)
    result = TOOLS[tool_name]["fn"](args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="sarthi-msgraph MCP server")
    parser.add_argument("--test", metavar="TOOL", help="Run a single tool and print result")
    parser.add_argument("args_json", nargs="?", default="{}", help="JSON args for --test mode")
    parsed = parser.parse_args()

    if parsed.test:
        run_test(parsed.test, parsed.args_json)
    else:
        run_stdio()
