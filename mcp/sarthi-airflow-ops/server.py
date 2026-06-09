#!/usr/bin/env python3
"""
sarthi-airflow-ops — Airflow mutation MCP server.

Six tools for controlled DAG/task operations. All mutating tools accept dry_run.
Every successful mutation is appended to ~/.wibey/sarthi/history/ops.jsonl.

Tools:
  clear_task             — Clear a single failed task instance
  clear_task_with_deps   — Clear a task + all downstream tasks
  set_dag_run_state      — PATCH dagRun state (queued / success / failed)
  trigger_dag_run        — POST a new dagRun with optional conf payload
  get_dag_run_state      — GET current dagRun state (read-only, no dry_run)
  poll_task              — Poll task state every N seconds until terminal/timeout

Safety:
  ops_allowed must be true in config.yaml for the target environment.
  If ops_allowed is false or the env is unknown, all mutation tools reject the call.
  get_dag_run_state and poll_task are read-only and bypass the ops_allowed check.

Config: same YAML as sarthi-airflow.
  Priority: --config arg > AIRFLOW_MCP_CONFIG env var > ~/.config/airflow-mcp/config.yaml

CLI test mode:
  python3 server.py --test clear_task '{"env_name":"ET360-CL-DEV","dag_id":"X","run_id":"Y","task_id":"Z","dry_run":true}'
  python3 server.py --test get_dag_run_state '{"env_name":"ET360-CL-DEV","dag_id":"X","run_id":"Y"}'

CRITICAL: stdout is JSON-RPC. ALL logs → sys.stderr. NEVER use print().
"""

import sys
import os
import json
import time
import asyncio
import argparse
import datetime
import http.cookiejar
import warnings
from http.client import HTTPSConnection
from urllib.parse import urlparse

warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    import yaml
except ImportError:
    print(json.dumps({"error": "PyYAML required: pip install pyyaml"}), file=sys.stderr)
    sys.exit(1)


# ── Config path resolution ─────────────────────────────────────────────────────
DEFAULT_CONFIG = os.path.expanduser("~/.config/airflow-mcp/config.yaml")
HISTORY_DIR = os.path.expanduser("~/.wibey/sarthi/history")
HISTORY_FILE = os.path.join(HISTORY_DIR, "ops.jsonl")
TIMEOUT = 15

_cfg = [None]

def resolve_config_path(cli_arg=None):
    if cli_arg:
        return os.path.expanduser(cli_arg)
    env = os.environ.get("AIRFLOW_MCP_CONFIG", "").strip()
    if env:
        return os.path.expanduser(env)
    return DEFAULT_CONFIG

def get_config_path() -> str:
    if _cfg[0] is None:
        _cfg[0] = resolve_config_path()
    return _cfg[0]


# ── Stderr logger ──────────────────────────────────────────────────────────────
def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)


# ── Config loading ─────────────────────────────────────────────────────────────
def load_config() -> dict:
    path = get_config_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log(f"[sarthi-airflow-ops] Config load error: {e}")
        return {}


def find_env(env_name: str) -> dict | None:
    cfg = load_config()
    for env in cfg.get("environments", []):
        if env.get("name") == env_name:
            return env
    return None


def check_ops_allowed(env_name: str) -> dict | None:
    """Returns None if allowed, or an error dict if denied."""
    env = find_env(env_name)
    if env is None:
        return {"error": "env_not_found", "env_name": env_name,
                "message": f"Environment '{env_name}' not found in config.yaml. "
                           f"Add it under the environments key with ops_allowed: true."}
    if env.get("disabled"):
        return {"error": "env_disabled", "env_name": env_name,
                "message": f"Environment '{env_name}' is disabled (incomplete config). "
                           f"Set a valid url and remove disabled: true before using ops tools."}
    if not env.get("ops_allowed", False):
        return {"error": "ops_not_allowed", "env_name": env_name,
                "message": f"ops_allowed is false for '{env_name}'. "
                           f"Set ops_allowed: true in config.yaml to enable mutation tools for this environment."}
    return None


def get_env_url(env_name: str) -> str | None:
    env = find_env(env_name)
    if env:
        return env.get("url", "").rstrip("/")
    return None


# ── Cookie loading ─────────────────────────────────────────────────────────────
def load_cookies_header(env_name: str | None = None) -> str:
    """Load cookies from the config-adjacent cookies.txt."""
    cfg_dir = os.path.dirname(get_config_path())
    # Check for env-specific cookies first
    if env_name:
        env_cookies = os.path.join(cfg_dir, f"cookies_{env_name}.txt")
        if os.path.exists(env_cookies):
            jar = http.cookiejar.MozillaCookieJar(env_cookies)
            try:
                jar.load(ignore_discard=True, ignore_expires=True)
                return "; ".join(f"{c.name}={c.value}" for c in jar)
            except Exception:
                pass
    # Fall back to shared cookies.txt
    cookies_path = os.path.join(cfg_dir, "cookies.txt")
    if not os.path.exists(cookies_path):
        return ""
    jar = http.cookiejar.MozillaCookieJar(cookies_path)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
        return "; ".join(f"{c.name}={c.value}" for c in jar)
    except Exception:
        return ""


# ── HTTP helpers ───────────────────────────────────────────────────────────────
def http_get(url: str, cookies: str) -> tuple:
    try:
        parsed = urlparse(url)
        conn = HTTPSConnection(parsed.netloc, timeout=TIMEOUT)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        conn.request("GET", path, headers={"Cookie": cookies, "Accept": "application/json"})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        try:
            return resp.status, json.loads(body)
        except Exception:
            return resp.status, body
    except Exception as e:
        return None, str(e)


def http_post(url: str, payload: dict, cookies: str) -> tuple:
    try:
        parsed = urlparse(url)
        conn = HTTPSConnection(parsed.netloc, timeout=TIMEOUT)
        body = json.dumps(payload)
        conn.request("POST", parsed.path, body=body,
                     headers={"Cookie": cookies, "Content-Type": "application/json",
                              "Accept": "application/json"})
        resp = conn.getresponse()
        text = resp.read().decode("utf-8", errors="replace")
        try:
            return resp.status, json.loads(text) if text else {}
        except Exception:
            return resp.status, text
    except Exception as e:
        return None, str(e)


def http_patch(url: str, payload: dict, cookies: str) -> tuple:
    try:
        parsed = urlparse(url)
        conn = HTTPSConnection(parsed.netloc, timeout=TIMEOUT)
        body = json.dumps(payload)
        conn.request("PATCH", parsed.path, body=body,
                     headers={"Cookie": cookies, "Content-Type": "application/json",
                              "Accept": "application/json"})
        resp = conn.getresponse()
        text = resp.read().decode("utf-8", errors="replace")
        try:
            return resp.status, json.loads(text) if text else {}
        except Exception:
            return resp.status, text
    except Exception as e:
        return None, str(e)


# ── Audit log ─────────────────────────────────────────────────────────────────
def audit_log(tool: str, args: dict, result: dict):
    """Append a structured audit entry to ops.jsonl. Never raises."""
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        entry = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "tool": tool,
            "env_name": args.get("env_name"),
            "dag_id": args.get("dag_id"),
            "run_id": args.get("run_id"),
            "task_id": args.get("task_id"),
            "dry_run": args.get("dry_run", False),
            "ok": result.get("ok", not result.get("error")),
        }
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        log(f"[sarthi-airflow-ops] audit_log error (non-fatal): {e}")


# ── Tool implementations ──────────────────────────────────────────────────────

async def tool_clear_task(args: dict) -> dict:
    """
    Clear a single failed task instance (no downstream cascade).

    Use this for isolated retries — only the specified task is reset to None state.
    After clearing, call set_dag_run_state with state=queued to re-trigger it.
    """
    env_name = args.get("env_name", "").strip()
    dag_id   = args.get("dag_id", "").strip()
    run_id   = args.get("run_id", "").strip()
    task_id  = args.get("task_id", "").strip()
    dry_run  = bool(args.get("dry_run", False))

    if not all([env_name, dag_id, run_id, task_id]):
        return {"error": "missing_params", "required": ["env_name", "dag_id", "run_id", "task_id"]}

    denied = check_ops_allowed(env_name)
    if denied:
        return denied

    base_url = get_env_url(env_name)
    cookies  = load_cookies_header(env_name)
    if not cookies:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}

    url = f"{base_url}/airflow/api/v1/dags/{dag_id}/clearTaskInstances"
    payload = {
        "dry_run": dry_run,
        "task_ids": [task_id],
        "dag_run_id": run_id,
        "include_upstream": False,
        "include_downstream": False,
        "include_future": False,
        "include_past": False,
        "only_failed": True,
        "reset_dag_runs": False,
    }

    status, data = http_post(url, payload, cookies)
    if status == 200:
        affected = data.get("task_instances", []) if isinstance(data, dict) else []
        cleared  = [t.get("task_id") for t in affected]
        result = {"ok": True, "tool": "clear_task", "dry_run": dry_run,
                  "env_name": env_name, "dag_id": dag_id,
                  "task_id": task_id, "cleared_tasks": cleared, "count": len(cleared)}
        audit_log("clear_task", args, result)
        return result
    elif status == 401:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}
    return {"ok": False, "tool": "clear_task", "http_status": status, "error": str(data)}


async def tool_clear_task_with_deps(args: dict) -> dict:
    """
    Clear a task and all its downstream tasks (cascade recovery).

    Use this when a mid-DAG failure means all subsequent tasks need to re-run.
    Clears only failed tasks (only_failed=true). After clearing, call
    set_dag_run_state with state=queued to re-trigger.
    """
    env_name = args.get("env_name", "").strip()
    dag_id   = args.get("dag_id", "").strip()
    run_id   = args.get("run_id", "").strip()
    task_id  = args.get("task_id", "").strip()
    dry_run  = bool(args.get("dry_run", False))

    if not all([env_name, dag_id, run_id, task_id]):
        return {"error": "missing_params", "required": ["env_name", "dag_id", "run_id", "task_id"]}

    denied = check_ops_allowed(env_name)
    if denied:
        return denied

    base_url = get_env_url(env_name)
    cookies  = load_cookies_header(env_name)
    if not cookies:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}

    url = f"{base_url}/airflow/api/v1/dags/{dag_id}/clearTaskInstances"
    payload = {
        "dry_run": dry_run,
        "task_ids": [task_id],
        "dag_run_id": run_id,
        "include_upstream": False,
        "include_downstream": True,
        "include_future": False,
        "include_past": False,
        "only_failed": True,
        "reset_dag_runs": False,
    }

    status, data = http_post(url, payload, cookies)
    if status == 200:
        affected = data.get("task_instances", []) if isinstance(data, dict) else []
        cleared  = [t.get("task_id") for t in affected]
        result = {"ok": True, "tool": "clear_task_with_deps", "dry_run": dry_run,
                  "env_name": env_name, "dag_id": dag_id,
                  "task_id": task_id, "cleared_tasks": cleared, "count": len(cleared)}
        audit_log("clear_task_with_deps", args, result)
        return result
    elif status == 401:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}
    return {"ok": False, "tool": "clear_task_with_deps", "http_status": status, "error": str(data)}


async def tool_set_dag_run_state(args: dict) -> dict:
    """
    PATCH a dagRun's state.

    Common use: after clearing tasks, PATCH state to 'queued' to re-trigger execution.
    Also useful for manually marking a run as 'success' or 'failed'.

    Valid states: queued, running, success, failed
    """
    env_name = args.get("env_name", "").strip()
    dag_id   = args.get("dag_id", "").strip()
    run_id   = args.get("run_id", "").strip()
    state    = args.get("state", "").strip()
    dry_run  = bool(args.get("dry_run", False))

    if not all([env_name, dag_id, run_id, state]):
        return {"error": "missing_params", "required": ["env_name", "dag_id", "run_id", "state"]}

    valid_states = {"queued", "running", "success", "failed"}
    if state not in valid_states:
        return {"error": "invalid_state", "state": state,
                "valid_states": sorted(valid_states)}

    denied = check_ops_allowed(env_name)
    if denied:
        return denied

    base_url = get_env_url(env_name)
    cookies  = load_cookies_header(env_name)
    if not cookies:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}

    url = f"{base_url}/airflow/api/v1/dags/{dag_id}/dagRuns/{run_id}"

    if dry_run:
        return {"ok": True, "tool": "set_dag_run_state", "dry_run": True,
                "env_name": env_name, "dag_id": dag_id, "run_id": run_id,
                "would_patch": {"state": state}}

    status, data = http_patch(url, {"state": state}, cookies)
    if status == 200:
        new_state = data.get("state") if isinstance(data, dict) else "?"
        result = {"ok": True, "tool": "set_dag_run_state", "dry_run": False,
                  "env_name": env_name, "dag_id": dag_id,
                  "run_id": run_id, "new_state": new_state}
        audit_log("set_dag_run_state", args, result)
        return result
    elif status == 401:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}
    return {"ok": False, "tool": "set_dag_run_state",
            "http_status": status, "error": str(data)}


async def tool_trigger_dag_run(args: dict) -> dict:
    """
    Trigger a new dagRun via POST /dagRuns.

    Optionally pass a conf dict for runtime parameters.
    A logical_date can be provided (ISO format); if omitted Airflow uses now().
    """
    env_name     = args.get("env_name", "").strip()
    dag_id       = args.get("dag_id", "").strip()
    conf         = args.get("conf", {}) or {}
    logical_date = args.get("logical_date", "").strip() or None
    dry_run      = bool(args.get("dry_run", False))

    if not all([env_name, dag_id]):
        return {"error": "missing_params", "required": ["env_name", "dag_id"]}

    denied = check_ops_allowed(env_name)
    if denied:
        return denied

    base_url = get_env_url(env_name)
    cookies  = load_cookies_header(env_name)
    if not cookies:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}

    url = f"{base_url}/airflow/api/v1/dags/{dag_id}/dagRuns"
    payload: dict = {"conf": conf}
    if logical_date:
        payload["logical_date"] = logical_date

    if dry_run:
        return {"ok": True, "tool": "trigger_dag_run", "dry_run": True,
                "env_name": env_name, "dag_id": dag_id,
                "would_post": payload}

    status, data = http_post(url, payload, cookies)
    if status in (200, 201):
        run_id    = data.get("dag_run_id") if isinstance(data, dict) else None
        new_state = data.get("state") if isinstance(data, dict) else None
        result = {"ok": True, "tool": "trigger_dag_run", "dry_run": False,
                  "env_name": env_name, "dag_id": dag_id,
                  "run_id": run_id, "state": new_state}
        audit_log("trigger_dag_run", args, result)
        return result
    elif status == 401:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}
    return {"ok": False, "tool": "trigger_dag_run",
            "http_status": status, "error": str(data)}


async def tool_get_dag_run_state(args: dict) -> dict:
    """
    GET the current state of a dagRun. Read-only — no ops_allowed check.

    Returns state, execution_date, start_date, end_date.
    """
    env_name = args.get("env_name", "").strip()
    dag_id   = args.get("dag_id", "").strip()
    run_id   = args.get("run_id", "").strip()

    if not all([env_name, dag_id, run_id]):
        return {"error": "missing_params", "required": ["env_name", "dag_id", "run_id"]}

    # Read-only — skip ops_allowed check, but env must exist and not be disabled
    env = find_env(env_name)
    if env is None:
        return {"error": "env_not_found", "env_name": env_name}
    if env.get("disabled"):
        return {"error": "env_disabled", "env_name": env_name}

    base_url = get_env_url(env_name)
    cookies  = load_cookies_header(env_name)
    if not cookies:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}

    url = f"{base_url}/airflow/api/v1/dags/{dag_id}/dagRuns/{run_id}"
    status, data = http_get(url, cookies)
    if status == 200 and isinstance(data, dict):
        return {"ok": True, "tool": "get_dag_run_state",
                "env_name": env_name, "dag_id": dag_id, "run_id": run_id,
                "state": data.get("state"),
                "execution_date": data.get("execution_date"),
                "start_date": data.get("start_date"),
                "end_date": data.get("end_date")}
    elif status == 401:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}
    return {"ok": False, "tool": "get_dag_run_state",
            "http_status": status, "error": str(data)}


async def tool_poll_task(args: dict) -> dict:
    """
    Poll a task's state every poll_interval seconds until it reaches a terminal
    state (success, failed, upstream_failed, skipped) or max_wait is exceeded.

    Read-only — no ops_allowed check.
    Returns final_state, elapsed_s, and the full state timeline.
    """
    env_name      = args.get("env_name", "").strip()
    dag_id        = args.get("dag_id", "").strip()
    run_id        = args.get("run_id", "").strip()
    task_id       = args.get("task_id", "").strip()
    poll_interval = int(args.get("poll_interval", 30))
    max_wait      = int(args.get("max_wait", 360))

    if not all([env_name, dag_id, run_id, task_id]):
        return {"error": "missing_params",
                "required": ["env_name", "dag_id", "run_id", "task_id"]}

    env = find_env(env_name)
    if env is None:
        return {"error": "env_not_found", "env_name": env_name}
    if env.get("disabled"):
        return {"error": "env_disabled", "env_name": env_name}

    base_url = get_env_url(env_name)
    cookies  = load_cookies_header(env_name)
    if not cookies:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}

    terminal = {"success", "failed", "upstream_failed", "skipped"}
    elapsed  = 0
    states_seen = []

    log(f"[sarthi-airflow-ops] Polling {task_id} every {poll_interval}s (max {max_wait}s)")

    while elapsed <= max_wait:
        url = f"{base_url}/airflow/api/v1/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}"
        status, data = http_get(url, cookies)

        if status == 401:
            return {"error": "session_expired", "env_name": env_name,
                    "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}

        state = None
        if status == 200 and isinstance(data, dict):
            state = data.get("state")

        ts = datetime.datetime.utcnow().strftime("%H:%M:%S")
        states_seen.append({"at_s": elapsed, "state": state, "ts": ts})
        log(f"[sarthi-airflow-ops]   [{ts}] {task_id} → {state}")

        if state in terminal:
            return {"ok": True, "tool": "poll_task",
                    "env_name": env_name, "dag_id": dag_id,
                    "task_id": task_id, "final_state": state,
                    "elapsed_s": elapsed, "states": states_seen,
                    "resolved": state == "success"}

        if elapsed < max_wait:
            await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    return {"ok": False, "tool": "poll_task",
            "env_name": env_name, "dag_id": dag_id,
            "task_id": task_id, "final_state": None,
            "elapsed_s": elapsed, "timeout": True, "states": states_seen}


async def tool_set_task_instance_state(args: dict) -> dict:
    """
    PATCH a single task instance's state (e.g. mark end_cluster as 'success'
    when the cluster was already gone). Uses the Airflow v1 PATCH taskInstances endpoint.

    Common use: mark a cleanup/teardown task success when the resource is already
    gone and re-running would fail again.
    Valid states: success, failed, skipped, up_for_retry, up_for_reschedule
    """
    env_name   = args.get("env_name", "").strip()
    dag_id     = args.get("dag_id", "").strip()
    run_id     = args.get("run_id", "").strip()
    task_id    = args.get("task_id", "").strip()
    state      = args.get("state", "success").strip()
    dry_run    = bool(args.get("dry_run", False))

    if not all([env_name, dag_id, run_id, task_id]):
        return {"error": "missing_params", "required": ["env_name", "dag_id", "run_id", "task_id"]}

    valid_states = {"success", "failed", "skipped", "up_for_retry", "up_for_reschedule"}
    if state not in valid_states:
        return {"error": "invalid_state", "state": state, "valid_states": sorted(valid_states)}

    denied = check_ops_allowed(env_name)
    if denied:
        return denied

    base_url = get_env_url(env_name)
    cookies  = load_cookies_header(env_name)
    if not cookies:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}

    if dry_run:
        return {"ok": True, "dry_run": True, "tool": "set_task_instance_state",
                "env_name": env_name, "dag_id": dag_id, "run_id": run_id,
                "task_id": task_id, "state": state}

    url = f"{base_url}/airflow/api/v1/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}"
    payload = {"new_state": state}

    status, data = http_patch(url, payload, cookies)
    if status in (200, 204):
        result = {"ok": True, "tool": "set_task_instance_state",
                  "env_name": env_name, "dag_id": dag_id,
                  "run_id": run_id, "task_id": task_id, "state": state}
        audit_log("set_task_instance_state", args, result)
        return result
    elif status == 401:
        return {"error": "session_expired", "env_name": env_name,
                "refresh_hint": "call mcp__sarthi-airflow-auth__refresh_session"}
    return {"ok": False, "tool": "set_task_instance_state",
            "http_status": status, "error": str(data)}


# ── Tool registry ─────────────────────────────────────────────────────────────
TOOLS = {
    "clear_task": {
        "fn": tool_clear_task,
        "description": (
            "Clear a single failed task instance (no downstream cascade). "
            "Requires ops_allowed: true for the target environment. "
            "After clearing, call set_dag_run_state with state='queued' to re-trigger. "
            "Pass dry_run=true to preview which tasks would be cleared without mutating state."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["env_name", "dag_id", "run_id", "task_id"],
            "properties": {
                "env_name":  {"type": "string", "description": "Environment name from config.yaml (e.g. ET360-CL-DEV)"},
                "dag_id":    {"type": "string", "description": "DAG ID"},
                "run_id":    {"type": "string", "description": "DAG run ID"},
                "task_id":   {"type": "string", "description": "Task ID to clear"},
                "dry_run":   {"type": "boolean", "description": "If true, preview affected tasks without clearing", "default": False},
            },
        },
    },
    "clear_task_with_deps": {
        "fn": tool_clear_task_with_deps,
        "description": (
            "Clear a task and all downstream tasks (cascade recovery). "
            "Use when a mid-DAG failure means all subsequent tasks need to re-run. "
            "Requires ops_allowed: true. After clearing, set_dag_run_state to 'queued'."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["env_name", "dag_id", "run_id", "task_id"],
            "properties": {
                "env_name":  {"type": "string"},
                "dag_id":    {"type": "string"},
                "run_id":    {"type": "string"},
                "task_id":   {"type": "string", "description": "Starting task — this and all downstream tasks are cleared"},
                "dry_run":   {"type": "boolean", "default": False},
            },
        },
    },
    "set_dag_run_state": {
        "fn": tool_set_dag_run_state,
        "description": (
            "PATCH a dagRun's state. Most common use: after clearing tasks, "
            "set state='queued' to re-trigger execution. "
            "Valid states: queued, running, success, failed. "
            "Requires ops_allowed: true."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["env_name", "dag_id", "run_id", "state"],
            "properties": {
                "env_name": {"type": "string"},
                "dag_id":   {"type": "string"},
                "run_id":   {"type": "string"},
                "state":    {"type": "string", "enum": ["queued", "running", "success", "failed"]},
                "dry_run":  {"type": "boolean", "default": False},
            },
        },
    },
    "trigger_dag_run": {
        "fn": tool_trigger_dag_run,
        "description": (
            "Trigger a new dagRun via POST. Optionally pass conf for runtime parameters. "
            "Requires ops_allowed: true."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["env_name", "dag_id"],
            "properties": {
                "env_name":     {"type": "string"},
                "dag_id":       {"type": "string"},
                "conf":         {"type": "object", "description": "Optional runtime conf dict", "default": {}},
                "logical_date": {"type": "string", "description": "ISO datetime for the run (default: now)"},
                "dry_run":      {"type": "boolean", "default": False},
            },
        },
    },
    "get_dag_run_state": {
        "fn": tool_get_dag_run_state,
        "description": (
            "GET the current state of a dagRun. "
            "Read-only — no ops_allowed check required. "
            "Returns state, execution_date, start_date, end_date."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["env_name", "dag_id", "run_id"],
            "properties": {
                "env_name": {"type": "string"},
                "dag_id":   {"type": "string"},
                "run_id":   {"type": "string"},
            },
        },
    },
    "poll_task": {
        "fn": tool_poll_task,
        "description": (
            "Poll a task's state every poll_interval seconds until it reaches a terminal state "
            "(success, failed, upstream_failed, skipped) or max_wait is exceeded. "
            "Read-only — no ops_allowed check required. "
            "Returns final_state, elapsed_s, resolved (true if success), and full state timeline."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["env_name", "dag_id", "run_id", "task_id"],
            "properties": {
                "env_name":      {"type": "string"},
                "dag_id":        {"type": "string"},
                "run_id":        {"type": "string"},
                "task_id":       {"type": "string"},
                "poll_interval": {"type": "integer", "description": "Seconds between polls", "default": 30},
                "max_wait":      {"type": "integer", "description": "Max seconds to wait total", "default": 360},
            },
        },
    },
    "set_task_instance_state": {
        "fn": tool_set_task_instance_state,
        "description": (
            "PATCH a single task instance's state directly. "
            "Use to mark cleanup/teardown tasks (e.g. end_cluster) as 'success' when the resource "
            "is already gone and re-running would fail again. "
            "Valid states: success, failed, skipped, up_for_retry, up_for_reschedule. "
            "Requires ops_allowed: true."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["env_name", "dag_id", "run_id", "task_id"],
            "properties": {
                "env_name": {"type": "string"},
                "dag_id":   {"type": "string"},
                "run_id":   {"type": "string"},
                "task_id":  {"type": "string", "description": "Task to patch"},
                "state":    {"type": "string", "enum": ["success", "failed", "skipped",
                             "up_for_retry", "up_for_reschedule"], "default": "success"},
                "dry_run":  {"type": "boolean", "default": False},
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

    server = Server("sarthi-airflow-ops")
    log(f"sarthi-airflow-ops MCP server starting — config: {get_config_path()}")

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
        log("sarthi-airflow-ops MCP server ready (stdio)")
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


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="sArthI Airflow ops MCP server — controlled DAG/task mutations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Config resolution: --config > AIRFLOW_MCP_CONFIG env var > ~/.config/airflow-mcp/config.yaml\n\n"
            "Test examples:\n"
            "  python3 server.py --test get_dag_run_state '{\"env_name\":\"ET360-CL-DEV\",\"dag_id\":\"INTLDLDAT-ET360-API-TEST-DAG\",\"run_id\":\"manual__2026-06-01T00:00:00\"}'\n"
            "  python3 server.py --test clear_task '{\"env_name\":\"ET360-CL-DEV\",\"dag_id\":\"X\",\"run_id\":\"Y\",\"task_id\":\"Z\",\"dry_run\":true}'\n"
            "  python3 server.py --test trigger_dag_run '{\"env_name\":\"ET360-CL-DEV\",\"dag_id\":\"INTLDLDAT-ET360-API-TEST-DAG\",\"dry_run\":true}'\n"
        ),
    )
    ap.add_argument("--config", metavar="PATH",
                    help="Path to config YAML (overrides AIRFLOW_MCP_CONFIG env var)")
    ap.add_argument("--test", nargs=2, metavar=("TOOL", "JSON_ARGS"),
                    help="CLI test mode: run a single tool and print JSON result to stdout")
    parsed = ap.parse_args()

    _cfg[0] = resolve_config_path(parsed.config)

    if parsed.test:
        asyncio.run(run_cli_test_async(parsed.test[0], parsed.test[1]))
    else:
        asyncio.run(run_mcp_server())
