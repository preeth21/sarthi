#!/usr/bin/env python3
"""
sarthi-bq MCP stdio server — BigQuery tools for sArthI.

Wraps the existing bigquery-explorer Wibey skill scripts (TypeScript/Bun).
Does NOT reimplement BQ logic — delegates to the scripts already installed at
BQ_SCRIPTS_DIR (default: ~/.wibey/skills/bigquery-explorer/scripts/).

Auth: gcloud ADC (same as bigquery-explorer skill). The skill's setup.ts handles
browser OAuth — this MCP never invokes it. On missing/expired auth, tools return
{"error": "auth_expired"} cleanly so cron jobs can detect and skip gracefully.

Tools:
  bq_query           — Run a SELECT query (SELECT-only enforced by execute-query.ts)
  bq_schema          — Get schema for a table
  bq_list_tables     — List tables in a dataset
  bq_list_datasets   — List datasets in a project
  bq_search_tables   — Search tables by name pattern

Cost guard: BQ_MAX_BYTES_BILLED env var (default 1GB). Queries exceeding this
are cancelled by BigQuery automatically.

CRITICAL: stdout is JSON-RPC. ALL diagnostic output → sys.stderr. NEVER use print() to stdout.
"""

import sys
import os
import json
import argparse
import subprocess
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────
HOME = Path.home()
BQ_SCRIPTS_DIR = Path(os.environ.get(
    "BQ_SCRIPTS_DIR",
    HOME / ".wibey" / "skills" / "bigquery-explorer" / "scripts"
))
# Max bytes billed per query — prevents runaway costs in cron. ~1GB default.
MAX_BYTES_BILLED = int(os.environ.get("BQ_MAX_BYTES_BILLED", str(1024 * 1024 * 1024)))

# ── stderr logger ─────────────────────────────────────────────────────────────
def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)


# ── Bun runner ────────────────────────────────────────────────────────────────
def _bun_path() -> str:
    """Find bun binary."""
    for candidate in [
        "/usr/local/bin/bun",
        str(HOME / ".local" / "bin" / "bun"),
        "/opt/homebrew/bin/bun",
    ]:
        if Path(candidate).exists():
            return candidate
    return "bun"  # fallback to PATH


def _run_bun_script(script: str, args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """
    Run a bigquery-explorer TypeScript script via bun.
    Returns (returncode, stdout, stderr).
    Script path is resolved relative to BQ_SCRIPTS_DIR.
    """
    script_path = BQ_SCRIPTS_DIR / script
    if not script_path.exists():
        return -1, "", f"Script not found: {script_path} — is bigquery-explorer skill installed? Run /sar-setup"

    cmd = [_bun_path(), str(script_path)] + args
    # NODE_PATH for the bigquery SDK installed alongside the skill
    node_path = str(HOME / ".local" / "lib" / "bigquery-explorer" / "node_modules")
    env = {**os.environ, "NODE_PATH": node_path}

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except FileNotFoundError as e:
        return -1, "", f"bun not found: {e} — install bun or set PATH"
    except Exception as e:
        return -1, "", str(e)


def _is_auth_error(stderr: str) -> bool:
    """Detect auth errors from bigquery-explorer scripts."""
    markers = [
        "not authenticated",
        "auth_expired",
        "authentication",
        "application default credentials",
        "Could not load the default credentials",
        "verifyAuthForOperation",
        "gcloud auth",
        "No credentials",
        "UNAUTHENTICATED",
    ]
    low = stderr.lower()
    return any(m.lower() in low for m in markers)


# ── Tool implementations ──────────────────────────────────────────────────────

def tool_bq_query(args: dict) -> dict:
    """
    Run a SELECT query against BigQuery.

    SELECT-only enforced by execute-query.ts — DML/DDL blocked.
    Results capped at max_results rows (default 100, max 1000).
    Cost cap: BQ_MAX_BYTES_BILLED env var (default 1GB).

    Args:
      query       (str, required)  — SQL SELECT query
      project     (str, required)  — GCP billing project ID
      max_results (int, default 100) — max rows to return
      no_save     (bool, default true) — don't save to local CSV file
    """
    query = args.get("query", "").strip()
    project = args.get("project", "").strip()
    if not query:
        return {"error": "query is required"}
    if not project:
        return {"error": "project is required — GCP billing project ID"}

    max_results = int(args.get("max_results", 100))
    no_save = bool(args.get("no_save", True))
    preview_rows = args.get("preview_rows")  # optional — defaults to DEFAULT_PREVIEW_ROWS in script

    script_args = [query, "--project", project, "--max-results", str(max_results)]
    if preview_rows is not None:
        script_args += ["--preview-rows", str(int(preview_rows))]
    if no_save:
        script_args.append("--no-save")

    rc, stdout, stderr = _run_bun_script("execute-query.ts", script_args, timeout=120)

    if rc != 0:
        if _is_auth_error(stderr):
            return {
                "error": "auth_expired",
                "detail": "BigQuery ADC not configured. Run: gcloud auth application-default login",
                "hint": "In Wibey: run /sar-setup to check all auth status",
            }
        # Try to parse structured error from stderr
        try:
            err_obj = json.loads(stderr)
            return {"error": "bq_query_failed", "detail": err_obj}
        except Exception:
            pass
        return {"error": "bq_query_failed", "detail": stderr[:500] or "unknown error"}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "parse_failed", "raw": stdout[:500]}


def tool_bq_schema(args: dict) -> dict:
    """
    Get the schema for a BigQuery table.

    Args:
      table    (str, required)   — table name (without dataset prefix)
      dataset  (str, required)   — dataset name
      project  (str, optional)   — GCP project ID (uses ADC default if omitted)
    """
    table = args.get("table", "").strip()
    dataset = args.get("dataset", "").strip()
    if not table:
        return {"error": "table is required"}
    if not dataset:
        return {"error": "dataset is required"}

    project = args.get("project", "").strip()
    script_args = [table, dataset]
    if project:
        script_args.append(project)

    rc, stdout, stderr = _run_bun_script("get-table-schema.ts", script_args, timeout=30)

    if rc != 0:
        if _is_auth_error(stderr):
            return {
                "error": "auth_expired",
                "detail": "BigQuery ADC not configured. Run: gcloud auth application-default login",
            }
        return {"error": "bq_schema_failed", "detail": stderr[:500] or stdout[:500]}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "parse_failed", "raw": stdout[:500]}


def tool_bq_list_tables(args: dict) -> dict:
    """
    List tables in a BigQuery dataset.

    Args:
      dataset  (str, required)  — dataset name
      project  (str, optional)  — GCP project ID (uses ADC default if omitted)
    """
    dataset = args.get("dataset", "").strip()
    if not dataset:
        return {"error": "dataset is required"}

    project = args.get("project", "").strip()
    script_args = [dataset]
    if project:
        script_args += ["--project", project]

    rc, stdout, stderr = _run_bun_script("list-tables.ts", script_args, timeout=30)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": "Run: gcloud auth application-default login"}
        return {"error": "bq_list_tables_failed", "detail": stderr[:500] or stdout[:500]}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "parse_failed", "raw": stdout[:500]}


def tool_bq_list_datasets(args: dict) -> dict:
    """
    List datasets in a GCP project.

    Args:
      project  (str, optional)  — GCP project ID (uses ADC default if omitted)
    """
    project = args.get("project", "").strip()
    script_args = []
    if project:
        script_args += ["--project", project]

    rc, stdout, stderr = _run_bun_script("list-datasets.ts", script_args, timeout=30)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": "Run: gcloud auth application-default login"}
        return {"error": "bq_list_datasets_failed", "detail": stderr[:500] or stdout[:500]}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "parse_failed", "raw": stdout[:500]}


def tool_bq_search_tables(args: dict) -> dict:
    """
    Search BigQuery tables by name pattern across datasets.

    Args:
      pattern  (str, required)  — table name pattern (substring or glob)
      project  (str, optional)  — GCP project ID (uses ADC default if omitted)
      dataset  (str, optional)  — limit search to one dataset
    """
    pattern = args.get("pattern", "").strip()
    if not pattern:
        return {"error": "pattern is required"}

    project = args.get("project", "").strip()
    dataset = args.get("dataset", "").strip()

    script_args = [pattern]
    if project:
        script_args += ["--project", project]
    if dataset:
        script_args += ["--dataset", dataset]

    rc, stdout, stderr = _run_bun_script("search-tables.ts", script_args, timeout=60)

    if rc != 0:
        if _is_auth_error(stderr):
            return {"error": "auth_expired", "detail": "Run: gcloud auth application-default login"}
        return {"error": "bq_search_failed", "detail": stderr[:500] or stdout[:500]}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "parse_failed", "raw": stdout[:500]}


# ── MCP dispatcher ────────────────────────────────────────────────────────────
TOOLS = {
    "bq_query": {
        "fn": tool_bq_query,
        "description": "Run a SELECT query against BigQuery. SELECT-only enforced — DML/DDL blocked. Returns preview rows + schema + bytes billed. Use preview_rows to control how many rows appear inline (default 100).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":       {"type": "string",  "description": "SQL SELECT query"},
                "project":     {"type": "string",  "description": "GCP billing project ID e.g. wmt-bfdms-intldlcaprod"},
                "max_results":  {"type": "integer", "description": "Max rows to fetch from BQ (default 100, max 1000)"},
                "preview_rows": {"type": "integer", "description": "Max rows returned inline in the response (default 100). Increase when you need more rows without saving to CSV."},
                "no_save":      {"type": "boolean", "description": "Don't save results to local CSV (default true)"},
            },
            "required": ["query", "project"],
        },
    },
    "bq_schema": {
        "fn": tool_bq_schema,
        "description": "Get the full schema (columns, types, modes) for a BigQuery table.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table":   {"type": "string", "description": "Table name"},
                "dataset": {"type": "string", "description": "Dataset name"},
                "project": {"type": "string", "description": "GCP project ID (uses ADC default if omitted)"},
            },
            "required": ["table", "dataset"],
        },
    },
    "bq_list_tables": {
        "fn": tool_bq_list_tables,
        "description": "List all tables in a BigQuery dataset.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Dataset name"},
                "project": {"type": "string", "description": "GCP project ID (uses ADC default if omitted)"},
            },
            "required": ["dataset"],
        },
    },
    "bq_list_datasets": {
        "fn": tool_bq_list_datasets,
        "description": "List all datasets in a GCP project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GCP project ID (uses ADC default if omitted)"},
            },
        },
    },
    "bq_search_tables": {
        "fn": tool_bq_search_tables,
        "description": "Search BigQuery tables by name pattern. Useful for discovery when dataset/table name is not known exactly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string",  "description": "Table name pattern (substring or glob)"},
                "project": {"type": "string",  "description": "GCP project ID (uses ADC default if omitted)"},
                "dataset": {"type": "string",  "description": "Limit search to this dataset (optional)"},
            },
            "required": ["pattern"],
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
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sarthi-bq", "version": "1.0.0"},
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
    log("sarthi-bq MCP server starting (stdio)")
    log(f"BQ_SCRIPTS_DIR: {BQ_SCRIPTS_DIR}")
    log(f"BQ_MAX_BYTES_BILLED: {MAX_BYTES_BILLED:,} bytes")
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
    parser = argparse.ArgumentParser(description="sarthi-bq MCP server")
    parser.add_argument("--test", metavar="TOOL", help="Run a single tool and print result")
    parser.add_argument("args_json", nargs="?", default="{}", help="JSON args for --test mode")
    parsed = parser.parse_args()

    if parsed.test:
        run_test(parsed.test, parsed.args_json)
    else:
        run_stdio()
