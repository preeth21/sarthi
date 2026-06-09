#!/usr/bin/env python3
"""
sarthi-snow-ad MCP stdio server — ServiceNow AD Group Request Automation.

Wraps the servicenow-ad-automation Selenium scripts to raise AD group membership
requests via the Walmart ServiceNow portal. Supports all four scenarios:

Tools:
  ad_group_add_user        — Add 1 user to 1 group
  ad_group_add_multi_user  — Add N users to 1 group (one SNOW request)
  ad_group_add_multi_group — Add 1 user to N groups (one SNOW request per user)
  ad_group_smart           — Auto-select optimal strategy for N users × N groups
  ad_group_dry_run         — Dry-run any of the above (navigates but does not submit)

Auth:
  Uses the existing Chrome profile at ~/sarthi/scripts/crq/chrome_profile (same
  profile used for ServiceNow session extraction). If the profile has an active
  Walmart AD session, no manual login is needed. Otherwise a Chrome window opens
  and the user completes SSO once.

Requirements:
  - Google Chrome installed
  - selenium + webdriver-manager Python packages
  - ~/sarthi/scripts/snow-ad-automation/ scripts present

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

SARTHI_ROOT = Path(os.environ.get("SARTHI_ROOT", Path.home() / "sarthi"))
AD_AUTO_DIR = SARTHI_ROOT / "scripts" / "snow-ad-automation"
DEFAULT_JUSTIFICATION = "Requested via sArthI automation"


def _run_ad_script(script_name: str, groups: list, users: list, justification: str, dry_run: bool = False) -> dict:
    """Run a snow-ad-automation script as subprocess. Returns result dict."""
    script_path = AD_AUTO_DIR / script_name
    if not script_path.exists():
        return {
            "error": "script_not_found",
            "path": str(script_path),
            "fix": f"Ensure ~/sarthi/scripts/snow-ad-automation/{script_name} exists"
        }

    # Build venv python path
    venv_python = AD_AUTO_DIR / ".venv" / "bin" / "python3"
    python_bin = str(venv_python) if venv_python.exists() else sys.executable

    cmd = [
        python_bin, str(script_path),
        "--groups", ",".join(groups),
        "--users", ",".join(users),
        "--justification", justification,
    ]
    if dry_run:
        cmd.append("--dry-run")

    log(f"[sarthi-snow-ad] Running: {' '.join(cmd[:4])} ...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(AD_AUTO_DIR),
            timeout=300  # 5 min max
        )
        success = result.returncode == 0
        output = (result.stdout + result.stderr).strip()

        return {
            "status": "success" if success else "failed",
            "returncode": result.returncode,
            "dry_run": dry_run,
            "script": script_name,
            "groups": groups,
            "users": users,
            "output": output[-3000:] if len(output) > 3000 else output,  # cap output
            "note": "Dry run — no SNOW request submitted" if dry_run else
                    "SNOW request submitted. Check ServiceNow portal for confirmation." if success else
                    "Script failed — see output for details"
        }
    except subprocess.TimeoutExpired:
        return {
            "error": "timeout",
            "detail": "Script ran for >5 minutes — Chrome window may be waiting for manual SSO",
            "fix": "Ensure Chrome window is visible and complete Walmart AD login"
        }
    except Exception as e:
        return {"error": "subprocess_failed", "detail": str(e)}


def _check_prereqs() -> dict | None:
    """Check Chrome + selenium are available. Returns error dict or None."""
    # Check selenium
    try:
        import selenium  # noqa
    except ImportError:
        return {
            "error": "selenium_not_installed",
            "fix": "pip install selenium --index-url https://repository.cache.walmart.com/repository/pypi-proxy/simple/"
        }

    # Check Chrome
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ]
    if not any(Path(p).exists() for p in chrome_paths):
        return {
            "error": "chrome_not_found",
            "fix": "Install Google Chrome from https://www.google.com/chrome/"
        }

    # Check scripts dir
    if not AD_AUTO_DIR.exists():
        return {
            "error": "snow_ad_scripts_not_found",
            "path": str(AD_AUTO_DIR),
            "fix": "Run setup.sh to install sArthI — scripts/snow-ad-automation/ must exist"
        }
    return None


def tool_ad_group_add_user(args: dict) -> dict:
    """
    Add a single user to a single AD group via ServiceNow.

    Args:
      group         (str, required) — AD group name e.g. "gcp-intl-dl-ca-et360-prod-highsecure-read"
      user          (str, required) — Walmart username/ldap e.g. "akiran"
      justification (str, optional) — Business reason (default: "Requested via sArthI automation")
      dry_run       (bool, optional) — Navigate but do not submit (default false)
    """
    err = _check_prereqs()
    if err:
        return err

    group = args.get("group", "").strip()
    user = args.get("user", "").strip()
    if not group or not user:
        return {"error": "group and user are required"}

    justification = args.get("justification", DEFAULT_JUSTIFICATION).strip()
    dry_run = bool(args.get("dry_run", False))

    return _run_ad_script("ad_group_request.py", [group], [user], justification, dry_run)


def tool_ad_group_add_multi_user(args: dict) -> dict:
    """
    Add multiple users to a single AD group in one ServiceNow request.

    Args:
      group         (str, required)  — AD group name
      users         (list, required) — List of usernames to add
      justification (str, optional)  — Business reason
      dry_run       (bool, optional) — Navigate but do not submit
    """
    err = _check_prereqs()
    if err:
        return err

    group = args.get("group", "").strip()
    users_raw = args.get("users", [])
    if isinstance(users_raw, str):
        users = [u.strip() for u in users_raw.split(",") if u.strip()]
    else:
        users = [str(u).strip() for u in users_raw if str(u).strip()]

    if not group or not users:
        return {"error": "group (string) and users (list) are required"}

    justification = args.get("justification", DEFAULT_JUSTIFICATION).strip()
    dry_run = bool(args.get("dry_run", False))

    return _run_ad_script("ad_group_request_multi_user.py", [group], users, justification, dry_run)


def tool_ad_group_add_multi_group(args: dict) -> dict:
    """
    Add a single user to multiple AD groups (one SNOW request per user).

    Args:
      user          (str, required)  — Username/ldap to add
      groups        (list, required) — List of AD group names
      justification (str, optional)  — Business reason
      dry_run       (bool, optional) — Navigate but do not submit
    """
    err = _check_prereqs()
    if err:
        return err

    user = args.get("user", "").strip()
    groups_raw = args.get("groups", [])
    if isinstance(groups_raw, str):
        groups = [g.strip() for g in groups_raw.split(",") if g.strip()]
    else:
        groups = [str(g).strip() for g in groups_raw if str(g).strip()]

    if not user or not groups:
        return {"error": "user (string) and groups (list) are required"}

    justification = args.get("justification", DEFAULT_JUSTIFICATION).strip()
    dry_run = bool(args.get("dry_run", False))

    return _run_ad_script("ad_group_multi_group.py", groups, [user], justification, dry_run)


def tool_ad_group_smart(args: dict) -> dict:
    """
    Smart AD group request — auto-selects optimal strategy for N users × N groups.

    Strategy:
      users > groups → Multi-User (iterate over groups, all users each time)
      groups > users → Multi-Group (iterate over users, all groups each time)
      equal          → Multi-Group

    This minimises the number of ServiceNow browser sessions needed.

    Args:
      groups        (list, required) — AD group name(s)
      users         (list, required) — Username(s)/ldaps
      justification (str, optional)  — Business reason
      dry_run       (bool, optional) — Navigate but do not submit
    """
    err = _check_prereqs()
    if err:
        return err

    groups_raw = args.get("groups", [])
    users_raw = args.get("users", [])

    if isinstance(groups_raw, str):
        groups = [g.strip() for g in groups_raw.split(",") if g.strip()]
    else:
        groups = [str(g).strip() for g in groups_raw if str(g).strip()]

    if isinstance(users_raw, str):
        users = [u.strip() for u in users_raw.split(",") if u.strip()]
    else:
        users = [str(u).strip() for u in users_raw if str(u).strip()]

    if not groups or not users:
        return {"error": "groups (list) and users (list) are required"}

    justification = args.get("justification", DEFAULT_JUSTIFICATION).strip()
    dry_run = bool(args.get("dry_run", False))

    # Decide strategy
    if len(users) > len(groups):
        strategy = "multi_user"
        script = "run_smart.sh"
        note = f"Multi-User strategy: {len(groups)} SNOW session(s) — all {len(users)} users per group"
    else:
        strategy = "multi_group"
        script = "run_smart.sh"
        note = f"Multi-Group strategy: {len(users)} SNOW session(s) — all {len(groups)} groups per user"

    # run_smart.sh is a bash wrapper — use it directly
    smart_script = AD_AUTO_DIR / "run_smart.sh"
    if not smart_script.exists():
        return {"error": "run_smart.sh not found", "path": str(smart_script)}

    cmd = [
        "bash", str(smart_script),
        "--groups", ",".join(groups),
        "--users", ",".join(users),
        "--justification", justification,
    ]
    if dry_run:
        cmd.append("--dry-run")

    log(f"[sarthi-snow-ad] Smart strategy: {strategy} | cmd: {' '.join(cmd[:4])} ...")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                cwd=str(AD_AUTO_DIR), timeout=600)
        output = (result.stdout + result.stderr).strip()
        return {
            "status": "success" if result.returncode == 0 else "failed",
            "strategy": strategy,
            "note": note,
            "dry_run": dry_run,
            "groups": groups,
            "users": users,
            "output": output[-3000:] if len(output) > 3000 else output,
        }
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "detail": "Smart script ran >10 minutes"}
    except Exception as e:
        return {"error": "subprocess_failed", "detail": str(e)}


# ── MCP dispatcher ────────────────────────────────────────────────────────────
TOOLS = {
    "ad_group_add_user": {
        "fn": tool_ad_group_add_user,
        "description": "Add a single user to a single ServiceNow AD group. Opens Chrome for Walmart SSO if needed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "group":         {"type": "string", "description": "AD group name e.g. gcp-intl-dl-ca-et360-prod-highsecure-read"},
                "user":          {"type": "string", "description": "Walmart username/ldap e.g. akiran"},
                "justification": {"type": "string", "description": "Business reason (optional)"},
                "dry_run":       {"type": "boolean", "description": "Navigate but do not submit (default false)"},
            },
            "required": ["group", "user"],
        },
    },
    "ad_group_add_multi_user": {
        "fn": tool_ad_group_add_multi_user,
        "description": "Add multiple users to a single AD group in one ServiceNow request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "group":         {"type": "string", "description": "AD group name"},
                "users":         {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}], "description": "List of usernames/ldaps to add"},
                "justification": {"type": "string", "description": "Business reason (optional)"},
                "dry_run":       {"type": "boolean", "description": "Navigate but do not submit"},
            },
            "required": ["group", "users"],
        },
    },
    "ad_group_add_multi_group": {
        "fn": tool_ad_group_add_multi_group,
        "description": "Add a single user to multiple AD groups (one ServiceNow request per user).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user":          {"type": "string", "description": "Walmart username/ldap"},
                "groups":        {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}], "description": "List of AD group names"},
                "justification": {"type": "string", "description": "Business reason (optional)"},
                "dry_run":       {"type": "boolean", "description": "Navigate but do not submit"},
            },
            "required": ["user", "groups"],
        },
    },
    "ad_group_smart": {
        "fn": tool_ad_group_smart,
        "description": (
            "Smart AD group request for N users × N groups. "
            "Auto-selects optimal strategy (multi-user vs multi-group) to minimise browser sessions. "
            "users > groups → Multi-User. groups > users → Multi-Group."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "groups":        {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}], "description": "AD group name(s)"},
                "users":         {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}], "description": "Username(s)/ldaps"},
                "justification": {"type": "string", "description": "Business reason (optional)"},
                "dry_run":       {"type": "boolean", "description": "Navigate but do not submit"},
            },
            "required": ["groups", "users"],
        },
    },
}


def handle_request(req: dict) -> dict:
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
            "serverInfo": {"name": "sarthi-snow-ad", "version": "1.0.0"},
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
    log("sarthi-snow-ad MCP server starting (stdio)")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def run_test(tool_name: str, args_json: str):
    if tool_name not in TOOLS:
        print(f"Unknown tool: {tool_name}. Available: {', '.join(TOOLS.keys())}")
        sys.exit(1)
    args = json.loads(args_json) if args_json else {}
    result = TOOLS[tool_name]["fn"](args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="sarthi-snow-ad MCP server")
    parser.add_argument("--test", metavar="TOOL", help="Run a single tool and print result")
    parser.add_argument("args_json", nargs="?", default="{}", help="JSON args for --test mode")
    parsed = parser.parse_args()
    if parsed.test:
        run_test(parsed.test, parsed.args_json)
    else:
        run_stdio()
