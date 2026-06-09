#!/usr/bin/env python3
"""
Airflow MCP stdio server — generic local MCP server for Apache Airflow / Astronomer.

Exposes 5 read-only tools over stdin/stdout (JSON-RPC) so any MCP-compatible
client (Wibey, Claude Desktop, etc.) can query Airflow REST API without
deploying any infrastructure.

Configuration:
  Set AIRFLOW_MCP_CONFIG env var to your config YAML path, or pass --config.
  Default: ~/.config/airflow-mcp/config.yaml

  Example config YAML:
    environments:
      - name: production
        url: "https://your-airflow-host.example.com"
        dags:
          - id: "my_dag_id"
            label: "My DAG"
            tags: ["etl", "daily"]
            sla_minutes: 90        # optional — used by monitors
            refresh_command: "python3 /path/to/refresh-session.py"  # optional

  Auth: cookie-based (MozillaCookieJar).
    Default cookies file: same directory as config.yaml → cookies.txt
    Override per-environment: cookies_file: /path/to/cookies.txt

Usage (Wibey mcp.json):
  {
    "airflow-mcp": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/server.py"],
      "env": {"AIRFLOW_MCP_CONFIG": "/path/to/config.yaml"}
    }
  }

CLI test mode:
  python3 server.py --test list_dags '{}'
  python3 server.py --config /path/to/config.yaml --test get_dag_runs '{"env_name": "production", "dag_id": "my_dag_id"}'

CRITICAL: stdout is JSON-RPC. ALL logs → sys.stderr. NEVER use print().
"""

import sys
import os
import json
import asyncio
import argparse
import warnings
from http.client import HTTPSConnection
from urllib.parse import urlparse
import http.cookiejar

warnings.filterwarnings("ignore", category=DeprecationWarning)

# ── config path resolution ────────────────────────────────────────────────────
DEFAULT_CONFIG = os.path.expanduser("~/.config/airflow-mcp/config.yaml")

def resolve_config_path(cli_arg=None):
    """Priority: --config arg > AIRFLOW_MCP_CONFIG env var > default."""
    if cli_arg:
        return os.path.expanduser(cli_arg)
    env = os.environ.get("AIRFLOW_MCP_CONFIG", "").strip()
    if env:
        return os.path.expanduser(env)
    return DEFAULT_CONFIG

TIMEOUT = 12  # HTTP timeout per request

# Config path resolved at import time from env var.
# --config CLI arg overrides by mutating this list (avoids Python global scoping issues).
_cfg = [resolve_config_path()]

def get_config_path() -> str:
    return _cfg[0]


# ── stderr logger (NEVER stdout) ──────────────────────────────────────────────
def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)


# ── config loader ─────────────────────────────────────────────────────────────
_config_cache = None

def load_config():
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    try:
        import yaml
    except ImportError:
        log("ERROR: PyYAML not installed. Run: pip install pyyaml")
        return None
    if not os.path.exists(get_config_path()):
        log(f"ERROR: Config not found at {get_config_path()}")
        log(f"  Set AIRFLOW_MCP_CONFIG env var or pass --config to point to your config YAML.")
        return None
    with open(get_config_path()) as f:
        cfg = yaml.safe_load(f)
    # Basic validation
    envs = cfg.get("environments", [])
    for i, env in enumerate(envs):
        for required in ("name", "url"):
            if not env.get(required):
                log(f"ERROR: environments[{i}] missing required field '{required}' in {get_config_path()}")
                return None
        for j, dag in enumerate(env.get("dags", [])):
            if not dag.get("id"):
                log(f"ERROR: environments[{i}].dags[{j}] missing required field 'id' in {get_config_path()}")
                return None
    _config_cache = cfg
    return cfg


def cookies_path_for_env(env: dict) -> str:
    """
    Resolve the cookies file for an environment.
    Priority: env.cookies_file > same dir as config.yaml/cookies.txt
    """
    if env.get("cookies_file"):
        return os.path.expanduser(env["cookies_file"])
    return os.path.join(os.path.dirname(get_config_path()), "cookies.txt")


# ── HTTP helpers ───────────────────────────────────────────────────────────────
def load_cookies_header(cookies_file: str) -> str:
    jar = http.cookiejar.MozillaCookieJar(cookies_file)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as e:
        log(f"WARN: Could not load cookies from {cookies_file}: {e}")
        return ""
    return "; ".join(f"{c.name}={c.value}" for c in jar)


def http_get(url, cookie_header, accept="application/json"):
    try:
        parsed = urlparse(url)
        conn   = HTTPSConnection(parsed.netloc, timeout=TIMEOUT)
        path   = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        conn.request("GET", path, headers={"Cookie": cookie_header, "Accept": accept})
        resp = conn.getresponse()
        raw  = resp.read().decode("utf-8", errors="replace")
        if accept == "application/json":
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, {"_raw": raw}
        return resp.status, raw
    except Exception as e:
        return None, str(e)


def http_post(url, payload, cookie_header):
    try:
        parsed = urlparse(url)
        conn   = HTTPSConnection(parsed.netloc, timeout=TIMEOUT)
        body   = json.dumps(payload)
        conn.request("POST", parsed.path, body=body, headers={
            "Cookie":       cookie_header,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        })
        resp   = conn.getresponse()
        status = resp.status
        text   = resp.read().decode("utf-8", errors="replace")
        return status, json.loads(text) if text else {}
    except Exception as e:
        return None, str(e)


# ── shared helpers ─────────────────────────────────────────────────────────────
def session_expired(env: dict, status) -> dict:
    """Return a structured error when cookie auth fails. Includes refresh hint if configured."""
    hint = env.get("refresh_command") or "Refresh your Airflow session cookies and try again."
    return {
        "error":        "session_expired",
        "env_name":     env["name"],
        "http_status":  status,
        "message":      f"Cookie auth failed for '{env['name']}' (HTTP {status}). Session has expired.",
        "refresh_hint": hint,
    }


def find_env(cfg, env_name):
    env = next((e for e in cfg.get("environments", []) if e["name"] == env_name), None)
    if not env:
        known = [e["name"] for e in cfg.get("environments", [])]
        return None, {"error": "env_not_found", "message": f"Unknown environment '{env_name}'", "known_environments": known}
    return env, None


# ── tool implementations ───────────────────────────────────────────────────────

def tool_list_dags(args: dict) -> dict:
    """List all configured DAGs. Optionally filter by env_name or tag."""
    cfg = load_config()
    if not cfg:
        return {"error": "config_unavailable", "message": f"Cannot load config from {get_config_path()}"}

    env_filter = args.get("env_name", "").strip()
    tag_filter = args.get("tag", "").strip().lower()

    result = []
    for env in cfg.get("environments", []):
        if env_filter and env["name"] != env_filter:
            continue
        for dag in env.get("dags", []):
            tags = [t.lower() for t in dag.get("tags", [])]
            if tag_filter and tag_filter not in tags:
                continue
            result.append({
                "env_name": env["name"],
                "env_url":  env["url"],
                "dag_id":   dag["id"],
                "label":    dag.get("label", dag["id"]),
                "tags":     dag.get("tags", []),
            })

    return {"total": len(result), "dags": result}


def tool_get_dag_runs(args: dict) -> dict:
    """Fetch the most recent runs for a DAG."""
    env_name = args.get("env_name", "").strip()
    dag_id   = args.get("dag_id", "").strip()
    limit    = int(args.get("limit", 10))

    if not env_name or not dag_id:
        return {"error": "missing_args", "message": "env_name and dag_id are required"}

    cfg = load_config()
    if not cfg:
        return {"error": "config_unavailable", "message": f"Cannot load config from {get_config_path()}"}

    env, err = find_env(cfg, env_name)
    if err:
        return err

    cookie_header = load_cookies_header(cookies_path_for_env(env))
    url           = f"{env['url']}/airflow/api/v1/dags/~/dagRuns/list"
    status, data  = http_post(url, {
        "dag_ids":    [dag_id],
        "page_limit": limit,
        "order_by":   "-execution_date",
    }, cookie_header)

    if status in (401, 403, None):
        return session_expired(env, status)

    runs = []
    if isinstance(data, dict) and "dag_runs" in data:
        for run in data["dag_runs"][:limit]:
            runs.append({
                "dag_run_id":     run.get("dag_run_id"),
                "state":          run.get("state"),
                "execution_date": run.get("execution_date"),
                "start_date":     run.get("start_date"),
                "end_date":       run.get("end_date"),
                "run_type":       run.get("run_type"),
            })

    return {"env_name": env_name, "dag_id": dag_id, "runs": runs, "total": len(runs)}


def tool_get_task_instances(args: dict) -> dict:
    """Fetch all task instances for a specific DAG run."""
    env_name   = args.get("env_name", "").strip()
    dag_id     = args.get("dag_id", "").strip()
    dag_run_id = args.get("dag_run_id", "").strip()

    if not all([env_name, dag_id, dag_run_id]):
        return {"error": "missing_args", "message": "env_name, dag_id, and dag_run_id are required"}

    cfg = load_config()
    if not cfg:
        return {"error": "config_unavailable", "message": f"Cannot load config from {get_config_path()}"}

    env, err = find_env(cfg, env_name)
    if err:
        return err

    cookie_header = load_cookies_header(cookies_path_for_env(env))
    url           = f"{env['url']}/airflow/api/v1/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances"
    status, data  = http_get(url, cookie_header)

    if status in (401, 403, None):
        return session_expired(env, status)

    tasks = []
    if isinstance(data, dict) and "task_instances" in data:
        for ti in data["task_instances"]:
            tasks.append({
                "task_id":    ti.get("task_id"),
                "state":      ti.get("state"),
                "start_date": ti.get("start_date"),
                "end_date":   ti.get("end_date"),
                "try_number": ti.get("try_number"),
                "duration":   ti.get("duration"),
                "operator":   ti.get("operator"),
            })

    return {"env_name": env_name, "dag_id": dag_id, "dag_run_id": dag_run_id, "tasks": tasks, "total": len(tasks)}


def tool_get_dag_run_conf(args: dict) -> dict:
    """
    Fetch the conf payload for a specific DAG run.
    GET /airflow/api/v1/dags/{dag_id}/dagRuns/{dag_run_id}
    Returns conf dict so callers can reconstruct context when task logs are unavailable.
    """
    env_name   = args.get("env_name", "").strip()
    dag_id     = args.get("dag_id", "").strip()
    dag_run_id = args.get("dag_run_id", "").strip()

    if not all([env_name, dag_id, dag_run_id]):
        return {"error": "missing_args", "message": "env_name, dag_id, and dag_run_id are required"}

    cfg = load_config()
    if not cfg:
        return {"error": "config_unavailable", "message": f"Cannot load config from {get_config_path()}"}

    env, err = find_env(cfg, env_name)
    if err:
        return err

    cookie_header = load_cookies_header(cookies_path_for_env(env))
    url           = f"{env['url']}/airflow/api/v1/dags/{dag_id}/dagRuns/{dag_run_id}"
    status, data  = http_get(url, cookie_header)

    if status in (401, 403, None):
        return session_expired(env, status)

    if status != 200 or not isinstance(data, dict):
        return {"error": "fetch_failed", "http_status": status, "detail": str(data)[:200]}

    return {
        "env_name":   env_name,
        "dag_id":     dag_id,
        "dag_run_id": dag_run_id,
        "conf":       data.get("conf") or {},
        "state":      data.get("state"),
        "run_type":   data.get("run_type"),
    }


def tool_get_task_log(args: dict) -> dict:
    """Fetch the log for a specific task attempt (tail N lines)."""
    env_name   = args.get("env_name", "").strip()
    dag_id     = args.get("dag_id", "").strip()
    dag_run_id = args.get("dag_run_id", "").strip()
    task_id    = args.get("task_id", "").strip()
    try_number = int(args.get("try_number", 1))
    max_lines  = int(args.get("max_lines", 200))

    if not all([env_name, dag_id, dag_run_id, task_id]):
        return {"error": "missing_args", "message": "env_name, dag_id, dag_run_id, task_id are required"}

    cfg = load_config()
    if not cfg:
        return {"error": "config_unavailable", "message": f"Cannot load config from {get_config_path()}"}

    env, err = find_env(cfg, env_name)
    if err:
        return err

    cookie_header = load_cookies_header(cookies_path_for_env(env))
    url = (
        f"{env['url']}/airflow/api/v1/dags/{dag_id}"
        f"/dagRuns/{dag_run_id}/taskInstances/{task_id}/logs/{try_number}"
    )
    status, data = http_get(url, cookie_header, accept="text/plain")

    if status in (401, 403, None):
        return session_expired(env, status)

    log_text  = data if isinstance(data, str) else json.dumps(data)
    lines     = log_text.splitlines()
    truncated = len(lines) > max_lines
    snippet   = "\n".join(lines[-max_lines:]) if truncated else log_text

    return {
        "env_name":    env_name,
        "dag_id":      dag_id,
        "dag_run_id":  dag_run_id,
        "task_id":     task_id,
        "try_number":  try_number,
        "log":         snippet,
        "truncated":   truncated,
        "total_lines": len(lines),
    }


def tool_list_dag_runs_batch(args: dict) -> dict:
    """
    Fetch the latest run for every DAG in an environment in a single API call.

    Uses POST /dags/~/dagRuns/list — the Airflow batch endpoint that accepts
    multiple dag_ids. This is the efficient path for health monitoring: 1 call
    per environment instead of 1 call per DAG.

    Returns:
      {
        "total_dags": int,
        "auth_failures": [env_name, ...],
        "errors": [...],
        "dag_runs": {                          # keyed by dag_id (NOT a list)
          "<dag_id>": {
            "env_name": str,
            "dag_id": str,
            "latest_run": {                    # None if no runs exist
              "run_id": str,
              "state": str,                    # "success" | "failed" | "running" | "upstream_failed"
              "execution_date": str,           # ISO8601
              "start_date": str,
              "end_date": str,
              "run_type": str
            } | None,
            "recent_runs": [...]               # up to runs_per_dag entries
          }
        }
      }

    To find failures: iterate dag_runs.values(), check latest_run.state == "failed".
    Skips disabled environments silently.
    """
    env_filter   = args.get("env_name", "").strip()   # optional — single env
    runs_per_dag = int(args.get("runs_per_dag", 3))    # how many recent runs to fetch per DAG

    cfg = load_config()
    if not cfg:
        return {"error": "config_unavailable", "message": f"Cannot load config from {get_config_path()}"}

    envs_to_check = []
    for env in cfg.get("environments", []):
        if env.get("disabled"):
            continue
        if env_filter and env["name"] != env_filter:
            continue
        envs_to_check.append(env)

    if not envs_to_check:
        return {"error": "no_envs", "message": f"No active environments found{f' matching {env_filter!r}' if env_filter else ''}"}

    results      = {}   # dag_id → {run_id, state, execution_date, start_date, end_date, env_name}
    auth_failures = []
    errors       = []

    for env in envs_to_check:
        env_name      = env["name"]
        dag_ids       = [d["id"] for d in env.get("dags", [])]
        if not dag_ids:
            continue

        cookie_header = load_cookies_header(cookies_path_for_env(env))
        url           = f"{env['url']}/airflow/api/v1/dags/~/dagRuns/list"

        # page_limit: runs_per_dag × number of DAGs, min 50 — matches run.py logic
        page_limit = max(len(dag_ids) * runs_per_dag, 50)

        status, data = http_post(url, {
            "dag_ids":    dag_ids,
            "page_limit": page_limit,
            "order_by":   "-execution_date",
        }, cookie_header)

        if status in (401, 403, None):
            auth_failures.append(env_name)
            for dag_id in dag_ids:
                results[dag_id] = {
                    "env_name":  env_name,
                    "dag_id":    dag_id,
                    "error":     "session_expired",
                    "runs":      [],
                }
            continue

        if not isinstance(data, dict) or "dag_runs" not in data:
            errors.append({"env_name": env_name, "http_status": status, "detail": str(data)[:200]})
            continue

        # Index: dag_id → [run, ...] keeping runs_per_dag most recent
        dag_runs_map: dict = {}
        for run in data["dag_runs"]:
            did = run.get("dag_id")
            if did not in dag_runs_map:
                dag_runs_map[did] = []
            if len(dag_runs_map[did]) < runs_per_dag:
                dag_runs_map[did].append({
                    "run_id":         run.get("dag_run_id"),
                    "state":          run.get("state"),
                    "execution_date": run.get("execution_date"),
                    "start_date":     run.get("start_date"),
                    "end_date":       run.get("end_date"),
                    "run_type":       run.get("run_type"),
                })

        for dag_id in dag_ids:
            runs = dag_runs_map.get(dag_id, [])
            results[dag_id] = {
                "env_name":   env_name,
                "dag_id":     dag_id,
                "latest_run": runs[0] if runs else None,
                "recent_runs": runs,
            }

    return {
        "total_dags":    len(results),
        "auth_failures": auth_failures,
        "errors":        errors,
        "dag_runs":      results,
    }


def tool_get_dag_topology(args: dict) -> dict:
    """Fetch task definitions and dependency graph for a DAG."""
    env_name = args.get("env_name", "").strip()
    dag_id   = args.get("dag_id", "").strip()

    if not env_name or not dag_id:
        return {"error": "missing_args", "message": "env_name and dag_id are required"}

    cfg = load_config()
    if not cfg:
        return {"error": "config_unavailable", "message": f"Cannot load config from {get_config_path()}"}

    env, err = find_env(cfg, env_name)
    if err:
        return err

    cookie_header = load_cookies_header(cookies_path_for_env(env))
    url           = f"{env['url']}/airflow/api/v1/dags/{dag_id}/tasks"
    status, data  = http_get(url, cookie_header)

    if status in (401, 403, None):
        return session_expired(env, status)

    tasks = []
    if isinstance(data, dict) and "tasks" in data:
        for t in data["tasks"]:
            tasks.append({
                "task_id":               t.get("task_id"),
                "operator":              t.get("operator_name") or t.get("operator"),
                "downstream_task_ids":   t.get("downstream_task_ids", []),
                "depends_on_past":       t.get("depends_on_past", False),
                "retries":               t.get("retries", 0),
            })

    return {"env_name": env_name, "dag_id": dag_id, "tasks": tasks, "total": len(tasks)}


# ── tool registry ─────────────────────────────────────────────────────────────
TOOLS = {
    "list_dags": {
        "fn":          tool_list_dags,
        "description": (
            "List all DAGs defined in the config YAML. "
            "Optionally filter by environment name or tag. "
            "Use this first to discover valid env_name and dag_id values."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "env_name": {
                    "type":        "string",
                    "description": "Filter to a single environment by name. Leave empty for all environments.",
                },
                "tag": {
                    "type":        "string",
                    "description": "Filter DAGs by tag (case-insensitive). Matches any tag in the DAG's tags list.",
                },
            },
        },
    },
    "get_dag_runs": {
        "fn":          tool_get_dag_runs,
        "description": (
            "Get the most recent runs for a specific DAG. "
            "Returns run state, execution date, start/end times. "
            "Call list_dags first to find valid env_name and dag_id values."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "env_name": {
                    "type":        "string",
                    "description": "Environment name as defined in your config YAML.",
                },
                "dag_id": {
                    "type":        "string",
                    "description": "The DAG ID to query.",
                },
                "limit": {
                    "type":        "integer",
                    "default":     10,
                    "description": "Number of recent runs to return (default: 10).",
                },
            },
            "required": ["env_name", "dag_id"],
        },
    },
    "get_task_instances": {
        "fn":          tool_get_task_instances,
        "description": (
            "Get all task instances for a specific DAG run. "
            "Shows each task's state, duration, try number, and operator. "
            "Call get_dag_runs first to obtain a dag_run_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "env_name":   {"type": "string", "description": "Environment name from your config YAML."},
                "dag_id":     {"type": "string", "description": "The DAG ID."},
                "dag_run_id": {"type": "string", "description": "The DAG run ID from get_dag_runs."},
            },
            "required": ["env_name", "dag_id", "dag_run_id"],
        },
    },
    "get_task_log": {
        "fn":          tool_get_task_log,
        "description": (
            "Fetch the execution log for a specific task attempt. "
            "Returns the last N lines (default 200). "
            "Call get_task_instances first to find failed task IDs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "env_name":   {"type": "string", "description": "Environment name from your config YAML."},
                "dag_id":     {"type": "string", "description": "The DAG ID."},
                "dag_run_id": {"type": "string", "description": "The DAG run ID."},
                "task_id":    {"type": "string", "description": "The task ID from get_task_instances."},
                "try_number": {"type": "integer", "default": 1,   "description": "Attempt number (1-indexed). Default: 1."},
                "max_lines":  {"type": "integer", "default": 200, "description": "Max log lines to return (tail). Default: 200."},
            },
            "required": ["env_name", "dag_id", "dag_run_id", "task_id"],
        },
    },
    "list_dag_runs_batch": {
        "fn":          tool_list_dag_runs_batch,
        "description": (
            "Fetch the latest run for ALL DAGs in an environment in a single API call. "
            "Uses POST /dags/~/dagRuns/list (batch endpoint). "
            "Much more efficient than calling get_dag_runs per DAG — use this for health monitoring. "
            "Returns dag_id → {latest_run, recent_runs} map plus auth_failures list. "
            "Omit env_name to scan all active environments."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "env_name": {
                    "type":        "string",
                    "description": "Optional: limit to a single environment. Omit to scan all active environments.",
                },
                "runs_per_dag": {
                    "type":        "integer",
                    "default":     3,
                    "description": "How many recent runs to return per DAG (default: 3, enough to detect flapping).",
                },
            },
        },
    },
    "get_dag_run_conf": {
        "fn":          tool_get_dag_run_conf,
        "description": (
            "Fetch the conf payload for a specific DAG run. "
            "Useful when task logs are unavailable (ES lag) — conf may contain "
            "gcs_sensor_path, fail_message, or other scenario context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "env_name":   {"type": "string", "description": "Environment name from your config YAML."},
                "dag_id":     {"type": "string", "description": "The DAG ID."},
                "dag_run_id": {"type": "string", "description": "The DAG run ID from get_dag_runs."},
            },
            "required": ["env_name", "dag_id", "dag_run_id"],
        },
    },
    "get_dag_topology": {
        "fn":          tool_get_dag_topology,
        "description": (
            "Fetch the task dependency graph for a DAG. "
            "Shows all task IDs, operators, downstream dependencies, and retry config. "
            "Useful for understanding DAG structure during triage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "env_name": {"type": "string", "description": "Environment name from your config YAML."},
                "dag_id":   {"type": "string", "description": "The DAG ID."},
            },
            "required": ["env_name", "dag_id"],
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

    server = Server("airflow-stdio-mcp")
    log(f"Airflow MCP server starting — config: {get_config_path()}")

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
        log("Airflow MCP server ready (stdio)")
        await server.run(read_stream, write_stream, server.create_initialization_options())


# ── CLI test mode ──────────────────────────────────────────────────────────────
def run_cli_test(tool_name: str, args_json: str):
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


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Generic local Airflow MCP stdio server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Config resolution order: --config > AIRFLOW_MCP_CONFIG env var > ~/.config/airflow-mcp/config.yaml\n\n"
            "Test examples:\n"
            "  python3 server.py --test list_dags '{}'\n"
            "  python3 server.py --test get_dag_runs '{\"env_name\": \"production\", \"dag_id\": \"my_dag\"}'\n"
        ),
    )
    ap.add_argument("--config", metavar="PATH",
                    help="Path to config YAML (overrides AIRFLOW_MCP_CONFIG env var)")
    ap.add_argument("--test", nargs=2, metavar=("TOOL", "JSON_ARGS"),
                    help="CLI test mode: run a single tool and print JSON result to stdout")
    parsed = ap.parse_args()

    _cfg[0] = resolve_config_path(parsed.config)

    if parsed.test:
        run_cli_test(parsed.test[0], parsed.test[1])
    else:
        asyncio.run(run_mcp_server())
