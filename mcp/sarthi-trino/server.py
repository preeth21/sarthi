#!/usr/bin/env python3
"""
sarthi-trino — Walmart Data Discovery Trino/Hudi MCP server.

Wraps Dengy's hive_explorer CLI (~/.dengy/app/tools/hive_explorer/hive.py)
as sarthi MCP tools so skills can query Hudi/Hive tables on
presto-datadiscovery.walmart.com without a separate Spark/Dataproc job.

Tools:
  trino_list_catalogs      — list available catalogs
  trino_list_schemas       — list schemas in a catalog
  trino_list_tables        — list tables in a schema
  trino_describe_table     — column names + types for a table
  trino_get_table_ddl      — full DDL including GCS LOCATION
  trino_execute_query      — run a SELECT (read-only, safety-checked by dengy)
  trino_preview_table      — first N rows of a table (smart column projection)
  trino_search_tables      — find tables by name pattern
  trino_search_columns     — find columns by name pattern
  trino_set_credentials    — store DD_PASSWORD in macOS Keychain for this session
  trino_check_credentials  — verify credentials are available

Auth:
  Priority: Keychain → DD_PASSWORD env var → prompt (interactive --test mode only)
  Keychain service: "sarthi-trino"  account: "<wmt_username>"
  Store once with: trino_set_credentials or python3 server.py --set-password

CLI test mode:
  python3 server.py --test trino_list_catalogs '{}'
  python3 server.py --test trino_execute_query '{"sql": "SELECT 1"}'
  python3 server.py --set-password          # interactive one-time keychain setup

CRITICAL: stdout is JSON-RPC. ALL logs → sys.stderr. NEVER use print().

Why subprocess (not direct import)?
  Shelling to ~/.dengy/venv/bin/python3 hive.py inherits dengy's venv,
  SSL bypass, and safety guard (SELECT-only). Importing directly couples
  sarthi's runtime to dengy's internals and breaks on dengy updates.
"""

import sys
import os
import json
import asyncio
import argparse
import subprocess
import time

# ── paths ──────────────────────────────────────────────────────────────────────
DENGY_PYTHON  = os.path.expanduser("~/.dengy/venv/bin/python3")
HIVE_CLI      = os.path.expanduser("~/.dengy/app/tools/hive_explorer/hive.py")
KEYCHAIN_SVC  = "sarthi-trino"
DEFAULT_USER  = os.environ.get("DD_USERNAME", "") or os.environ.get("USER", "akiran")
TIMEOUT       = 60  # seconds per Trino call


# ── stderr logger (NEVER stdout) ───────────────────────────────────────────────
def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)


# ── keychain helpers ───────────────────────────────────────────────────────────
def _keychain_get(username: str) -> str | None:
    """Read DD_PASSWORD from macOS Keychain. Returns None if not stored."""
    try:
        import keyring
        return keyring.get_password(KEYCHAIN_SVC, username)
    except Exception:
        pass
    # Fallback: security CLI (macOS built-in, no keyring package needed)
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SVC,
             "-a", username, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        pw = r.stdout.strip()
        return pw if pw else None
    except Exception:
        return None


def _keychain_set(username: str, password: str) -> bool:
    """Store DD_PASSWORD in macOS Keychain. Returns True on success."""
    try:
        import keyring
        keyring.set_password(KEYCHAIN_SVC, username, password)
        return True
    except Exception:
        pass
    try:
        # Delete existing entry first (security add-generic-password fails if exists)
        subprocess.run(
            ["security", "delete-generic-password", "-s", KEYCHAIN_SVC, "-a", username],
            capture_output=True, timeout=5,
        )
        r = subprocess.run(
            ["security", "add-generic-password", "-s", KEYCHAIN_SVC,
             "-a", username, "-w", password],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _resolve_credentials(username: str) -> tuple[str, str] | None:
    """
    Resolve (username, password) for Trino BasicAuth.
    Priority: DD_PASSWORD env → Keychain → None (never prompt in MCP server mode)
    """
    pw = os.environ.get("DD_PASSWORD", "").strip()
    if pw:
        return username, pw
    pw = _keychain_get(username)
    if pw:
        return username, pw
    return None


# ── hive_explorer subprocess runner ───────────────────────────────────────────
def _run_hive(cmd_args: list[str], username: str, password: str) -> dict:
    """
    Run a hive_explorer CLI command and return parsed JSON.
    Raises RuntimeError if the command fails or returns non-JSON.
    """
    if not os.path.exists(DENGY_PYTHON):
        return {"error": "dengy_not_installed", "detail": f"{DENGY_PYTHON} not found. Run: curl -sSL https://prod.agent.dengy.walmart.com/install | bash"}
    if not os.path.exists(HIVE_CLI):
        return {"error": "hive_cli_not_found", "detail": f"{HIVE_CLI} not found. Dengy may need updating."}

    env = {
        **os.environ,
        "DD_USERNAME": username,
        "DD_PASSWORD": password,
        "DENGY_VERIFY_SSL": "false",
        "REQUESTS_CA_BUNDLE": "",
        "CURL_CA_BUNDLE": "",
    }

    cmd = [DENGY_PYTHON, HIVE_CLI] + cmd_args
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT, env=env,
        )
        out = r.stdout.strip()
        if not out:
            err = r.stderr.strip()[:500]
            return {"error": "empty_output", "stderr": err, "returncode": r.returncode}
        return json.loads(out)
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "detail": f"Trino query timed out after {TIMEOUT}s"}
    except json.JSONDecodeError as e:
        return {"error": "json_parse", "detail": str(e), "raw": r.stdout[:500]}
    except Exception as e:
        return {"error": "subprocess_error", "detail": str(e)}


def _with_creds(username: str, fn):
    """Resolve credentials and call fn(username, password), or return auth error."""
    creds = _resolve_credentials(username)
    if not creds:
        return {
            "error": "no_credentials",
            "detail": (
                f"DD_PASSWORD not set and no Keychain entry found for '{username}'. "
                f"Run: python3 {__file__} --set-password  to store once in Keychain."
            ),
        }
    return fn(*creds)


# ── tool implementations ───────────────────────────────────────────────────────

def tool_trino_check_credentials(args: dict) -> dict:
    username = args.get("username", DEFAULT_USER)
    creds = _resolve_credentials(username)
    keychain_stored = _keychain_get(username) is not None
    env_set = bool(os.environ.get("DD_PASSWORD", "").strip())
    return {
        "username":        username,
        "credentials_available": creds is not None,
        "source":          ("env" if env_set else "keychain" if keychain_stored else "none"),
        "keychain_stored": keychain_stored,
        "dd_password_env": env_set,
        "dengy_python_exists": os.path.exists(DENGY_PYTHON),
        "hive_cli_exists": os.path.exists(HIVE_CLI),
    }


def tool_trino_set_credentials(args: dict) -> dict:
    """Store DD_PASSWORD in macOS Keychain. Called once by user, never in production flow."""
    username = args.get("username", DEFAULT_USER)
    password = args.get("password", "").strip()
    if not password:
        return {"error": "password_required", "detail": "Provide 'password' field with your WMT AD password."}
    ok = _keychain_set(username, password)
    if ok:
        return {
            "status":   "stored",
            "username": username,
            "keychain": KEYCHAIN_SVC,
            "note":     "Password stored in macOS Keychain. Future calls to sarthi-trino will use it automatically.",
        }
    return {"error": "keychain_write_failed", "detail": "Could not write to Keychain. Try running with --set-password interactively."}


def tool_trino_list_catalogs(args: dict) -> dict:
    username = args.get("username", DEFAULT_USER)
    return _with_creds(username, lambda u, p: _run_hive(["list-catalogs"], u, p))


def tool_trino_list_schemas(args: dict) -> dict:
    catalog  = args.get("catalog", "hive")
    username = args.get("username", DEFAULT_USER)
    return _with_creds(username, lambda u, p: _run_hive(["list-schemas", "--catalog", catalog], u, p))


def tool_trino_list_tables(args: dict) -> dict:
    schema   = args.get("schema", "")
    catalog  = args.get("catalog", "hive")
    username = args.get("username", DEFAULT_USER)
    if not schema:
        return {"error": "schema_required"}
    return _with_creds(username, lambda u, p: _run_hive(["list-tables", schema, "--catalog", catalog], u, p))


def tool_trino_describe_table(args: dict) -> dict:
    table    = args.get("table", "")
    schema   = args.get("schema", "")
    catalog  = args.get("catalog", "hive")
    username = args.get("username", DEFAULT_USER)
    if not table or not schema:
        return {"error": "table_and_schema_required"}
    return _with_creds(username, lambda u, p: _run_hive(
        ["describe-table", table, schema, "--catalog", catalog], u, p))


def tool_trino_get_table_ddl(args: dict) -> dict:
    table    = args.get("table", "")
    schema   = args.get("schema", "")
    catalog  = args.get("catalog", "hive")
    username = args.get("username", DEFAULT_USER)
    if not table or not schema:
        return {"error": "table_and_schema_required"}
    return _with_creds(username, lambda u, p: _run_hive(
        ["get-table-ddl", table, schema, "--catalog", catalog], u, p))


def tool_trino_execute_query(args: dict) -> dict:
    sql      = args.get("sql", "").strip()
    max_rows = str(args.get("max_results", 100))
    username = args.get("username", DEFAULT_USER)
    if not sql:
        return {"error": "sql_required"}
    return _with_creds(username, lambda u, p: _run_hive(
        ["execute-query", sql, "--max-results", max_rows], u, p))


def tool_trino_preview_table(args: dict) -> dict:
    table    = args.get("table", "")
    schema   = args.get("schema", "")
    catalog  = args.get("catalog", "hive")
    limit    = str(args.get("limit", 10))
    columns  = args.get("columns", "")
    username = args.get("username", DEFAULT_USER)
    if not table or not schema:
        return {"error": "table_and_schema_required"}
    cmd = ["preview-table", table, schema, "--limit", limit, "--catalog", catalog]
    if columns:
        cmd += ["--columns", columns]
    return _with_creds(username, lambda u, p: _run_hive(cmd, u, p))


def tool_trino_search_tables(args: dict) -> dict:
    pattern  = args.get("pattern", "")
    schema   = args.get("schema", "")
    catalog  = args.get("catalog", "hive")
    username = args.get("username", DEFAULT_USER)
    if not pattern or not schema:
        return {"error": "pattern_and_schema_required"}
    return _with_creds(username, lambda u, p: _run_hive(
        ["search-tables", pattern, schema, "--catalog", catalog], u, p))


def tool_trino_search_columns(args: dict) -> dict:
    pattern  = args.get("pattern", "")
    schema   = args.get("schema", "")
    catalog  = args.get("catalog", "hive")
    username = args.get("username", DEFAULT_USER)
    if not pattern or not schema:
        return {"error": "pattern_and_schema_required"}
    return _with_creds(username, lambda u, p: _run_hive(
        ["search-columns", pattern, schema, "--catalog", catalog], u, p))


def tool_trino_get_table_stats(args: dict) -> dict:
    table    = args.get("table", "")
    schema   = args.get("schema", "")
    catalog  = args.get("catalog", "hive")
    username = args.get("username", DEFAULT_USER)
    if not table or not schema:
        return {"error": "table_and_schema_required"}
    return _with_creds(username, lambda u, p: _run_hive(
        ["get-table-stats", table, schema, "--catalog", catalog], u, p))


# ── tool registry ─────────────────────────────────────────────────────────────
TOOLS = {
    "trino_check_credentials": {
        "fn": tool_trino_check_credentials,
        "description": (
            "Check if Trino (Data Discovery) credentials are available. "
            "Shows whether DD_PASSWORD is set via env or Keychain. "
            "Always call this first before using other trino_* tools."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "WMT username (default: current OS user)"},
            },
        },
    },
    "trino_set_credentials": {
        "fn": tool_trino_set_credentials,
        "description": (
            "Store your WMT AD password in macOS Keychain for sarthi-trino. "
            "One-time setup — all future trino_* calls use it automatically. "
            "NEVER store this in a file or environment variable."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["password"],
            "properties": {
                "username": {"type": "string", "description": "WMT username (default: current OS user)"},
                "password": {"type": "string", "description": "Your WMT AD password"},
            },
        },
    },
    "trino_list_catalogs": {
        "fn": tool_trino_list_catalogs,
        "description": "List all available Trino catalogs on presto-datadiscovery.walmart.com (e.g. hive, hudi, system).",
        "inputSchema": {"type": "object", "properties": {"username": {"type": "string"}}},
    },
    "trino_list_schemas": {
        "fn": tool_trino_list_schemas,
        "description": "List schemas in a Trino catalog. Use catalog='hive' for Hudi/Hive tables.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "catalog":  {"type": "string", "description": "Catalog name (default: hive)"},
                "username": {"type": "string"},
            },
        },
    },
    "trino_list_tables": {
        "fn": tool_trino_list_tables,
        "description": "List tables in a Trino schema. Use to find the Hudi table name for a given schema.",
        "inputSchema": {
            "type": "object",
            "required": ["schema"],
            "properties": {
                "schema":   {"type": "string", "description": "Schema/database name"},
                "catalog":  {"type": "string", "description": "Catalog name (default: hive)"},
                "username": {"type": "string"},
            },
        },
    },
    "trino_describe_table": {
        "fn": tool_trino_describe_table,
        "description": "Get column names and data types for a Trino/Hudi table. Essential before writing queries.",
        "inputSchema": {
            "type": "object",
            "required": ["table", "schema"],
            "properties": {
                "table":    {"type": "string", "description": "Table name"},
                "schema":   {"type": "string", "description": "Schema/database name"},
                "catalog":  {"type": "string", "description": "Catalog name (default: hive)"},
                "username": {"type": "string"},
            },
        },
    },
    "trino_get_table_ddl": {
        "fn": tool_trino_get_table_ddl,
        "description": (
            "Get full CREATE TABLE DDL for a Trino table. "
            "Includes GCS LOCATION, Hudi table properties (type=COPY_ON_WRITE/MERGE_ON_READ), "
            "and partition columns. Critical for confirming the correct GCS path for a table."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["table", "schema"],
            "properties": {
                "table":    {"type": "string"},
                "schema":   {"type": "string"},
                "catalog":  {"type": "string"},
                "username": {"type": "string"},
            },
        },
    },
    "trino_execute_query": {
        "fn": tool_trino_execute_query,
        "description": (
            "Execute a SELECT query against Trino. Read-only — INSERT/UPDATE/DELETE/DROP are blocked. "
            "Supports Hudi, Hive, and system tables. "
            "Always LIMIT your query — unfiltered Hudi scans are slow. "
            "Use trino_describe_table first to know partition columns."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["sql"],
            "properties": {
                "sql":         {"type": "string", "description": "SELECT query to execute"},
                "max_results": {"type": "integer", "description": "Max rows to return (default 100, max 10000)"},
                "username":    {"type": "string"},
            },
        },
    },
    "trino_preview_table": {
        "fn": tool_trino_preview_table,
        "description": (
            "Preview first N rows of a Trino/Hudi table. "
            "Smarter than SELECT * — projects only first 20 columns to avoid Hudi timeout. "
            "Use 'columns' param to specify which columns to include."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["table", "schema"],
            "properties": {
                "table":    {"type": "string"},
                "schema":   {"type": "string"},
                "catalog":  {"type": "string"},
                "limit":    {"type": "integer", "description": "Rows to return (default 10)"},
                "columns":  {"type": "string", "description": "Comma-separated column names to include"},
                "username": {"type": "string"},
            },
        },
    },
    "trino_search_tables": {
        "fn": tool_trino_search_tables,
        "description": "Search for tables by name pattern (SQL LIKE) within a schema. Use '%rtn_order_line%' to find return order line tables.",
        "inputSchema": {
            "type": "object",
            "required": ["pattern", "schema"],
            "properties": {
                "pattern":  {"type": "string", "description": "SQL LIKE pattern e.g. '%rtn_order%'"},
                "schema":   {"type": "string"},
                "catalog":  {"type": "string"},
                "username": {"type": "string"},
            },
        },
    },
    "trino_search_columns": {
        "fn": tool_trino_search_columns,
        "description": "Search for columns by name pattern across all tables in a schema. Useful for finding which Hudi tables contain a specific field.",
        "inputSchema": {
            "type": "object",
            "required": ["pattern", "schema"],
            "properties": {
                "pattern":  {"type": "string", "description": "SQL LIKE pattern e.g. '%order_id%'"},
                "schema":   {"type": "string"},
                "catalog":  {"type": "string"},
                "username": {"type": "string"},
            },
        },
    },
    "trino_get_table_stats": {
        "fn": tool_trino_get_table_stats,
        "description": "Get row count (COUNT(*)) for a Trino/Hudi table. Counts only committed snapshot rows.",
        "inputSchema": {
            "type": "object",
            "required": ["table", "schema"],
            "properties": {
                "table":    {"type": "string"},
                "schema":   {"type": "string"},
                "catalog":  {"type": "string"},
                "username": {"type": "string"},
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
        sys.exit(1)

    server = Server("sarthi-trino")
    log(f"sarthi-trino MCP server starting — user: {DEFAULT_USER}")
    log(f"  Trino host: presto-datadiscovery.walmart.com:8443")
    log(f"  Dengy CLI: {HIVE_CLI}")
    creds = _resolve_credentials(DEFAULT_USER)
    if not creds:
        log(f"  ⚠️  No credentials found. Run: python3 {__file__} --set-password")

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
            result = TOOLS[name]["fn"](arguments or {})
        except Exception as e:
            log(f"ERROR in tool {name}: {e}")
            result = {"error": "tool_exception", "message": str(e)}
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    async with stdio_server() as (read_stream, write_stream):
        log("sarthi-trino MCP server ready (stdio)")
        await server.run(read_stream, write_stream, server.create_initialization_options())


# ── CLI test + setup modes ─────────────────────────────────────────────────────
async def run_cli_test(tool_name: str, args_json: str):
    if tool_name not in TOOLS:
        log(f"Unknown tool '{tool_name}'. Available: {', '.join(TOOLS.keys())}")
        sys.exit(1)
    try:
        tool_args = json.loads(args_json)
    except json.JSONDecodeError as e:
        log(f"Invalid JSON args: {e}")
        sys.exit(1)
    log(f"--- Testing tool: {tool_name} ---")
    result = TOOLS[tool_name]["fn"](tool_args)
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    sys.stdout.flush()


def run_set_password():
    """Interactive one-time keychain setup. Run from shell, not via MCP."""
    import getpass
    username = os.environ.get("DD_USERNAME", "") or os.environ.get("USER", "")
    print(f"sarthi-trino — Keychain credential setup")
    print(f"  Service: {KEYCHAIN_SVC}")
    print(f"  User: {username}")
    print()
    pw = getpass.getpass("WMT AD password (hidden): ")
    if not pw.strip():
        print("ERROR: empty password, aborted.")
        sys.exit(1)
    ok = _keychain_set(username, pw.strip())
    if ok:
        print(f"✅ Password stored in Keychain for '{username}'.")
        print(f"   sarthi-trino will use it automatically going forward.")
    else:
        print("❌ Keychain write failed. Try: security add-generic-password -s sarthi-trino -a <username> -w")
        sys.exit(1)


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="sArthI Trino/Hudi MCP server (Walmart Data Discovery)")
    ap.add_argument("--set-password", action="store_true",
                    help="Interactive one-time: store WMT AD password in macOS Keychain")
    ap.add_argument("--test", nargs=2, metavar=("TOOL", "JSON_ARGS"),
                    help="CLI test mode: run a single tool and print JSON result to stdout")
    parsed = ap.parse_args()

    if parsed.set_password:
        run_set_password()
    elif parsed.test:
        asyncio.run(run_cli_test(parsed.test[0], parsed.test[1]))
    else:
        asyncio.run(run_mcp_server())
