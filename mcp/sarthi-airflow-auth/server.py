#!/usr/bin/env python3
"""
sarthi-airflow-auth — Airflow session refresh MCP server.

Single tool: refresh_session
  Runs ~/sarthi/scripts/headless-refresh.py in a subprocess (non-blocking asyncio),
  streams stderr to the MCP server's stderr, returns structured result.

Why a separate server?
  sarthi-airflow exposes read-only Airflow tools. Keeping auth as a distinct MCP
  server (a) lets skills declare it in allowed-tools independently, (b) avoids
  blocking the airflow tool event loop during the ~15s Playwright refresh, and
  (c) makes the reauth pattern reusable across any sarthi skill.

Config: same YAML as sarthi-airflow.
  Priority: --config arg > AIRFLOW_MCP_CONFIG env var > ~/.config/airflow-mcp/config.yaml

CLI test mode:
  python3 server.py --test refresh_session '{}'
  python3 server.py --test refresh_session '{"env_name": "CA-ET360-PROD"}'

CRITICAL: stdout is JSON-RPC. ALL logs → sys.stderr. NEVER use print().
"""

import sys
import os
import json
import asyncio
import argparse
import time
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

# ── config path resolution ─────────────────────────────────────────────────────
DEFAULT_CONFIG = os.path.expanduser("~/.config/airflow-mcp/config.yaml")
REFRESH_SCRIPT = os.path.expanduser("~/sarthi/scripts/headless-refresh.py")

def resolve_config_path(cli_arg=None):
    """Priority: --config arg > AIRFLOW_MCP_CONFIG env var > default."""
    if cli_arg:
        return os.path.expanduser(cli_arg)
    env = os.environ.get("AIRFLOW_MCP_CONFIG", "").strip()
    if env:
        return os.path.expanduser(env)
    return DEFAULT_CONFIG

_cfg = [resolve_config_path()]

def get_config_path() -> str:
    return _cfg[0]


# ── stderr logger (NEVER stdout) ───────────────────────────────────────────────
def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)


# ── refresh implementation ─────────────────────────────────────────────────────
async def run_refresh(env_name: str | None = None) -> dict:
    """
    Run headless-refresh.py as an async subprocess.
    Streams stderr lines to our stderr for visibility.
    Returns structured result dict.
    """
    if not os.path.exists(REFRESH_SCRIPT):
        return {
            "status":  "error",
            "message": f"Refresh script not found: {REFRESH_SCRIPT}",
        }

    cmd = [sys.executable, REFRESH_SCRIPT]
    env = dict(os.environ)
    env["AIRFLOW_MCP_CONFIG"] = get_config_path()

    log(f"[sarthi-airflow-auth] Starting refresh (env_filter={env_name or 'all'})")
    start = time.monotonic()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except Exception as e:
        return {"status": "error", "message": f"Failed to start refresh script: {e}"}

    stdout_lines = []
    stderr_lines = []

    async def drain_stream(stream, lines, label):
        async for raw in stream:
            line = raw.decode("utf-8", errors="replace").rstrip()
            lines.append(line)
            log(f"[headless-refresh] {line}")

    await asyncio.gather(
        drain_stream(proc.stdout, stdout_lines, "stdout"),
        drain_stream(proc.stderr, stderr_lines, "stderr"),
    )
    await proc.wait()

    elapsed = round(time.monotonic() - start, 1)
    all_output = stderr_lines + stdout_lines

    if proc.returncode != 0:
        # Surface last meaningful error line
        error_line = next(
            (l for l in reversed(all_output) if l.strip() and not l.startswith("[headless")),
            "Refresh script exited non-zero."
        )
        return {
            "status":           "error",
            "returncode":       proc.returncode,
            "duration_seconds": elapsed,
            "message":          error_line,
        }

    # Parse cookie count from output: "✅ Refreshed — N cookies saved."
    # Line format: "✅ Refreshed — 53 cookies saved."
    cookies_written = None
    for line in reversed(all_output):
        if "cookies saved" in line:
            try:
                # Split on whitespace, find the token before "cookies"
                tokens = line.split()
                idx = next(i for i, t in enumerate(tokens) if t == "cookies")
                cookies_written = int(tokens[idx - 1])
            except (StopIteration, IndexError, ValueError):
                pass
            break

    # Verify cookies file was written
    cookies_file = os.path.join(os.path.dirname(get_config_path()), "cookies.txt")
    cookies_exist = os.path.exists(cookies_file)

    return {
        "status":           "ok",
        "duration_seconds": elapsed,
        "cookies_written":  cookies_written,
        "cookies_file":     cookies_file,
        "cookies_exist":    cookies_exist,
    }


# ── tool wrapper ──────────────────────────────────────────────────────────────
async def tool_refresh_session(args: dict) -> dict:
    """
    Refresh the Airflow session cookies by running headless-refresh.py.

    Accepts optional env_name for targeted refresh (informational — headless-refresh
    always refreshes all clusters configured in config.yaml, so partial refresh
    is not supported at the script level).
    """
    env_name = args.get("env_name", "").strip() or None
    return await run_refresh(env_name)


TOOLS = {
    "refresh_session": {
        "fn": tool_refresh_session,
        "description": (
            "Refresh expired Airflow session cookies by running the headless browser refresh. "
            "Call this when a sarthi-airflow tool returns {\"error\": \"session_expired\"}. "
            "Takes ~15 seconds. Refreshes all configured clusters."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "env_name": {
                    "type":        "string",
                    "description": "Optional: environment name that triggered the session_expired error. Informational only — all clusters are refreshed.",
                },
            },
        },
    },
}


# ── MCP stdio server ───────────────────────────────────────────────────────────
async def run_mcp_server():
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        import mcp.types as types
    except ImportError as e:
        log(f"ERROR: mcp package not available: {e}")
        log("Install: pip install mcp")
        sys.exit(1)

    server = Server("sarthi-airflow-auth")
    log(f"sarthi-airflow-auth MCP server starting — config: {get_config_path()}")

    @server.list_tools()
    async def handle_list_tools():
        return [
            types.Tool(name=name, description=meta["description"], inputSchema=meta["inputSchema"])
            for name, meta in TOOLS.items()
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict):
        log(f"tool_call: {name} args={json.dumps(arguments)}")
        if name not in TOOLS:
            return [types.TextContent(type="text", text=json.dumps({
                "error": "unknown_tool", "tool": name, "available": list(TOOLS.keys()),
            }))]
        try:
            result = await TOOLS[name]["fn"](arguments or {})
        except Exception as e:
            log(f"ERROR in tool {name}: {e}")
            result = {"error": "tool_exception", "message": str(e)}
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    async with stdio_server() as (read_stream, write_stream):
        log("sarthi-airflow-auth MCP server ready (stdio)")
        await server.run(read_stream, write_stream, server.create_initialization_options())


# ── CLI test mode ─────────────────────────────────────────────────────────────
async def run_cli_test_async(tool_name: str, args_json: str):
    if tool_name not in TOOLS:
        log(f"Unknown tool '{tool_name}'. Available: {', '.join(TOOLS.keys())}")
        sys.exit(1)
    try:
        tool_args = json.loads(args_json)
    except json.JSONDecodeError as e:
        log(f"Invalid JSON args: {e}")
        sys.exit(1)
    log(f"--- Testing tool: {tool_name} ---")
    result = await TOOLS[tool_name]["fn"](tool_args)
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    sys.stdout.flush()


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="sArthI Airflow session refresh MCP server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Config resolution: --config > AIRFLOW_MCP_CONFIG env var > ~/.config/airflow-mcp/config.yaml\n\n"
            "Test examples:\n"
            "  python3 server.py --test refresh_session '{}'\n"
            "  python3 server.py --test refresh_session '{\"env_name\": \"CA-ET360-PROD\"}'\n"
        ),
    )
    ap.add_argument("--config", metavar="PATH",
                    help="Path to config YAML (overrides AIRFLOW_MCP_CONFIG env var)")
    ap.add_argument("--test", nargs=2, metavar=("TOOL", "JSON_ARGS"),
                    help="CLI test mode: run a single tool and print JSON result to stdout")
    parsed = ap.parse_args()

    _cfg[0] = resolve_config_path(parsed.config)

    # Warn clearly if falling back to the default path — catches missing env var
    # in shell test runs before it silently writes cookies to the wrong location.
    if _cfg[0] == DEFAULT_CONFIG and not os.path.exists(DEFAULT_CONFIG):
        import sys
        print(
            f"\n⚠️  WARNING: AIRFLOW_MCP_CONFIG not set and default path does not exist:\n"
            f"   {DEFAULT_CONFIG}\n"
            f"   Cookies will be written to the wrong location.\n"
            f"   Fix: export AIRFLOW_MCP_CONFIG=~/.wibey/sarthi/config.yaml\n"
            f"   Or:  AIRFLOW_MCP_CONFIG=~/.wibey/sarthi/config.yaml python3 server.py ...\n",
            file=sys.stderr
        )

    if parsed.test:
        asyncio.run(run_cli_test_async(parsed.test[0], parsed.test[1]))
    else:
        asyncio.run(run_mcp_server())
