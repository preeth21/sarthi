#!/usr/bin/env python3
"""
sarthi-snow-auth — ServiceNow session refresh MCP server.

Single tool: refresh_session
  Runs ~/.wibey/crq/extract_snow_session.py in a subprocess (non-blocking asyncio),
  streams stderr to the MCP server's stderr, returns structured result.

Why separate from sarthi-snow?
  Same pattern as sarthi-airflow-auth: keeps auth distinct from data tools,
  lets skills call refresh independently, avoids blocking data tools during the
  ~30s Playwright browser flow.

Session lifetime: ~8h. Typical cron: every 6h.

CLI test mode:
  python3 server.py --test refresh_session '{}'

CRITICAL: stdout is JSON-RPC. ALL logs → sys.stderr. NEVER use print().
"""

import sys
import os
import json
import asyncio
import argparse
import time

REFRESH_SCRIPT = os.path.expanduser("~/.wibey/crq/extract_snow_session.py")
SESSION_FILE   = os.path.expanduser("~/.wibey/snow-session.json")


def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)


async def run_refresh() -> dict:
    """Run extract_snow_session.py as async subprocess."""
    if not os.path.exists(REFRESH_SCRIPT):
        return {
            "status":  "error",
            "message": f"Refresh script not found: {REFRESH_SCRIPT}",
            "fix":     "Ensure ~/.wibey/crq/extract_snow_session.py exists (part of lakey/crq tooling)",
        }

    log(f"[sarthi-snow-auth] Starting ServiceNow session refresh…")
    start = time.monotonic()

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, REFRESH_SCRIPT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        return {"status": "error", "message": f"Failed to start refresh script: {e}"}

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    async def drain(stream, lines):
        async for raw in stream:
            line = raw.decode("utf-8", errors="replace").rstrip()
            lines.append(line)
            log(f"[extract_snow_session] {line}")

    await asyncio.gather(
        drain(proc.stdout, stdout_lines),
        drain(proc.stderr, stderr_lines),
    )
    await proc.wait()

    elapsed = round(time.monotonic() - start, 1)
    all_output = stdout_lines + stderr_lines

    if proc.returncode != 0:
        error_line = next(
            (l for l in reversed(all_output) if l.strip()),
            "Refresh script exited non-zero.",
        )
        return {
            "status":           "error",
            "returncode":       proc.returncode,
            "duration_seconds": elapsed,
            "message":          error_line,
        }

    # Verify session file was written and check its timestamp
    session_exists = os.path.exists(SESSION_FILE)
    extracted_at = None
    if session_exists:
        try:
            with open(SESSION_FILE) as f:
                sess = json.load(f)
            extracted_at = sess.get("extracted_at")
        except Exception:
            pass

    # Extract cookie count from output if present
    cookie_count = None
    for line in reversed(all_output):
        if "cookie" in line.lower() and any(c.isdigit() for c in line):
            tokens = line.split()
            for i, t in enumerate(tokens):
                if "cookie" in t.lower() and i > 0:
                    try:
                        cookie_count = int(tokens[i - 1])
                        break
                    except ValueError:
                        pass
            if cookie_count is not None:
                break

    return {
        "status":           "ok",
        "duration_seconds": elapsed,
        "session_file":     SESSION_FILE,
        "session_exists":   session_exists,
        "extracted_at":     extracted_at,
        "cookie_count":     cookie_count,
    }


# ── Tool definition ───────────────────────────────────────────────────────────
TOOLS = {
    "refresh_session": {
        "fn": lambda args: asyncio.get_event_loop().run_until_complete(run_refresh()),
        "description": (
            "Refresh the ServiceNow session cookie by running extract_snow_session.py "
            "(headless Playwright browser flow — Walmart AD SSO). "
            "Call this when a sarthi-snow tool returns {\"error\": \"session_expired\"}. "
            "Takes ~30 seconds. Session lasts ~8 hours."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
}


# ── MCP JSON-RPC dispatcher ───────────────────────────────────────────────────
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
            "serverInfo": {"name": "sarthi-snow-auth", "version": "1.0.0"},
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
            result = asyncio.run(run_refresh())
            return ok({"content": [{"type": "text", "text": json.dumps(result, indent=2)}]})
        except Exception as e:
            log(f"ERROR in {tool_name}: {e}")
            return err(-32603, str(e))

    if method == "ping":
        return ok({})

    return err(-32601, f"Method not found: {method}")


def run_stdio():
    log("sarthi-snow-auth MCP server starting (stdio)")
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


def run_test(args_json: str):
    result = asyncio.run(run_refresh())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="sarthi-snow-auth MCP server")
    parser.add_argument("--test", action="store_true", help="Run refresh and print result")
    parsed = parser.parse_args()

    if parsed.test:
        run_test("{}")
    else:
        run_stdio()
