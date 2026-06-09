#!/usr/bin/env python3
"""
sarthi-gcp MCP stdio server — GCS, Dataproc, and Hudi timeline tools for sArthI.

All GCP operations use gcloud/gsutil CLI (ADC already managed by gcloud auth — no
sarthi auth refresh needed). User must have gcloud configured with correct account
and project access.

Tools:
  gcs_ls              — List GCS objects at a URI prefix
  gcs_stat            — Stat a single GCS object (size, updated, metadata)
  gcs_cat             — Read a small GCS text file (capped at max_bytes)
  dataproc_list       — List Dataproc clusters in a project/region
  dataproc_describe   — Describe a specific Dataproc cluster
  dataproc_fetch_driver_log — Fetch Spark driver output chunks for a job
  hudi_timeline       — Parse Hudi .hoodie/ timeline for a GCS bucket URI

Access policy: access-based only. No ops_allowed gates.
No mutation tools — this is a read-only server.

CRITICAL: stdout is JSON-RPC. ALL diagnostic output → sys.stderr. NEVER use print() to stdout.
"""

import sys
import os
import json
import re
import argparse
import subprocess
import datetime
from pathlib import Path

# ── stderr logger ─────────────────────────────────────────────────────────────
def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)


# ── subprocess helpers ────────────────────────────────────────────────────────
def _run(cmd: list, timeout: int = 30) -> tuple[int, str]:
    """Run a subprocess, return (returncode, combined stdout+stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = r.stdout or ""
        err = r.stderr or ""
        combined = (out + err).strip()
        return r.returncode, combined
    except subprocess.TimeoutExpired:
        return -1, f"TIMEOUT after {timeout}s"
    except FileNotFoundError as e:
        return -1, f"Command not found: {cmd[0]} — {e}"
    except Exception as e:
        return -1, str(e)


def _gsutil(args: list, timeout: int = 30) -> tuple[int, str]:
    return _run(["gsutil"] + args, timeout=timeout)


def _gcloud(args: list, timeout: int = 30) -> tuple[int, str]:
    return _run(["gcloud"] + args, timeout=timeout)


# ── Tool implementations ──────────────────────────────────────────────────────

def tool_gcs_ls(args: dict) -> dict:
    """
    List GCS objects at a URI prefix.

    Args:
      uri        (str, required)  — gs://bucket/path/prefix
      recursive  (bool, default false)
      max_items  (int, default 200)
    """
    uri = args.get("uri", "").strip()
    if not uri or not uri.startswith("gs://"):
        return {"error": "uri is required and must start with gs://"}

    recursive = bool(args.get("recursive", False))
    max_items = int(args.get("max_items", 200))

    cmd = ["-m", "ls"]
    if recursive:
        cmd.append("-r")
    cmd.append(uri)

    rc, out = _gsutil(cmd, timeout=30)
    if rc != 0:
        return {"error": "gsutil_failed", "detail": out[:500], "uri": uri}

    lines = [l.strip() for l in out.splitlines() if l.strip() and not l.strip().endswith(":")]
    truncated = len(lines) > max_items
    return {
        "uri": uri,
        "items": lines[:max_items],
        "count": len(lines),
        "truncated": truncated,
    }


def tool_gcs_stat(args: dict) -> dict:
    """
    Stat a GCS object — returns size, content type, updated timestamp, metadata.

    Args:
      uri (str, required) — gs://bucket/path/to/object
    """
    uri = args.get("uri", "").strip()
    if not uri or not uri.startswith("gs://"):
        return {"error": "uri is required and must start with gs://"}

    rc, out = _gsutil(["stat", uri], timeout=15)
    if rc != 0:
        return {"error": "gsutil_failed", "detail": out[:500], "uri": uri}

    # Parse gsutil stat output (key-value lines)
    result: dict = {"uri": uri}
    for line in out.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip().lower().replace(" ", "_")] = v.strip()

    return result


def tool_gcs_cat(args: dict) -> dict:
    """
    Read a GCS text file. Capped at max_bytes to avoid blowing context.

    Args:
      uri       (str, required) — gs://bucket/path/to/file
      max_bytes (int, default 32768) — cap on content returned
    """
    uri = args.get("uri", "").strip()
    if not uri or not uri.startswith("gs://"):
        return {"error": "uri is required and must start with gs://"}

    max_bytes = int(args.get("max_bytes", 32768))

    rc, out = _gsutil(["cat", uri], timeout=60)
    if rc != 0:
        return {"error": "gsutil_failed", "detail": out[:500], "uri": uri}

    truncated = len(out) > max_bytes
    content = out[:max_bytes]

    # Try JSON parse (Hudi .commit files are JSON)
    parsed_json = None
    if content.strip().startswith("{") or content.strip().startswith("["):
        try:
            parsed_json = json.loads(content)
        except json.JSONDecodeError:
            pass

    result: dict = {
        "uri": uri,
        "content": content,
        "size_bytes": len(out),
        "truncated": truncated,
    }
    if parsed_json is not None:
        result["parsed_json"] = parsed_json

    return result


def tool_dataproc_list(args: dict) -> dict:
    """
    List Dataproc clusters in a GCP project.

    Args:
      project (str, required)  — GCP project ID e.g. wmt-bfdms-intldlcaprod
      region  (str, default "us-central1")
      state   (str, optional)  — filter by state: RUNNING, STOPPED, ERROR, etc.
    """
    project = args.get("project", "").strip()
    if not project:
        return {"error": "project is required"}

    region = args.get("region", "us-central1").strip()
    state_filter = args.get("state", "").strip().upper()

    cmd = [
        "dataproc", "clusters", "list",
        f"--project={project}",
        f"--region={region}",
        "--format=json",
    ]
    if state_filter:
        cmd.append(f"--filter=status.state={state_filter}")

    rc, out = _gcloud(cmd, timeout=30)
    if rc != 0:
        return {"error": "gcloud_failed", "detail": out[:500], "project": project}

    try:
        clusters = json.loads(out) if out.strip() else []
    except json.JSONDecodeError:
        return {"error": "parse_failed", "raw": out[:500]}

    # Summarize key fields
    summary = []
    for c in clusters:
        summary.append({
            "cluster_name": c.get("clusterName", ""),
            "state": c.get("status", {}).get("state", ""),
            "state_detail": c.get("status", {}).get("detail", ""),
            "zone": c.get("config", {}).get("gceClusterConfig", {}).get("zoneUri", "").split("/")[-1],
            "master_type": c.get("config", {}).get("masterConfig", {}).get("machineTypeUri", "").split("/")[-1],
            "worker_count": len(c.get("config", {}).get("workerConfig", {}).get("instanceNames", [])),
            "create_time": c.get("status", {}).get("history", [{}])[0].get("stateStartTime", ""),
        })

    return {"project": project, "region": region, "clusters": summary, "total": len(summary)}


def tool_dataproc_describe(args: dict) -> dict:
    """
    Describe a specific Dataproc cluster (full config).

    Args:
      project      (str, required)
      cluster_name (str, required)
      region       (str, default "us-central1")
    """
    project = args.get("project", "").strip()
    cluster_name = args.get("cluster_name", "").strip()
    if not project or not cluster_name:
        return {"error": "project and cluster_name are required"}

    region = args.get("region", "us-central1").strip()

    rc, out = _gcloud([
        "dataproc", "clusters", "describe", cluster_name,
        f"--project={project}",
        f"--region={region}",
        "--format=json",
    ], timeout=20)

    if rc != 0:
        return {"error": "gcloud_failed", "detail": out[:500]}

    try:
        cluster = json.loads(out)
    except json.JSONDecodeError:
        return {"error": "parse_failed", "raw": out[:500]}

    return {"cluster": cluster}


def tool_dataproc_fetch_driver_log(args: dict) -> dict:
    """
    Fetch Spark driver output for a Dataproc job.

    Discovers driver output URI via gcloud dataproc jobs describe, then
    fetches and concatenates all driveroutput.* chunks.

    Args:
      job_id   (str, required) — Dataproc job UUID or short ID
      project  (str, required) — GCP project ID
      region   (str, default "us-central1")
      max_bytes (int, default 65536) — cap on total log content
    """
    job_id = args.get("job_id", "").strip()
    project = args.get("project", "").strip()
    if not job_id or not project:
        return {"error": "job_id and project are required"}

    region = args.get("region", "us-central1").strip()
    max_bytes = int(args.get("max_bytes", 65536))

    # Step 1: get driver output URI
    rc, out = _gcloud([
        "dataproc", "jobs", "describe", job_id,
        f"--project={project}",
        f"--region={region}",
        "--format=value(driverOutputResourceUri)",
    ], timeout=15)

    if rc != 0 or not out.strip().startswith("gs://"):
        return {"error": "cannot_get_driver_uri", "detail": out[:300], "job_id": job_id}

    uri_prefix = out.strip()
    log(f"Driver output URI prefix: {uri_prefix}")

    # Step 2: list chunks
    rc, ls_out = _gsutil(["ls", f"{uri_prefix}*"], timeout=15)
    if rc != 0:
        return {"error": "no_chunks", "detail": ls_out[:300], "uri_prefix": uri_prefix}

    chunks = sorted(l.strip() for l in ls_out.splitlines() if l.strip().startswith("gs://"))
    if not chunks:
        return {"error": "no_chunks", "uri_prefix": uri_prefix}

    # Step 3: fetch and concat chunks
    parts = []
    total = 0
    for chunk in chunks:
        if total >= max_bytes:
            break
        rc, content = _gsutil(["cat", chunk], timeout=120)
        if rc == 0 and content:
            remaining = max_bytes - total
            parts.append(content[:remaining])
            total += len(content)

    combined = "\n".join(parts)
    truncated = total >= max_bytes

    return {
        "job_id": job_id,
        "project": project,
        "uri_prefix": uri_prefix,
        "chunk_count": len(chunks),
        "log_bytes": total,
        "truncated": truncated,
        "content": combined,
    }


def tool_hudi_timeline(args: dict) -> dict:
    """
    Parse the Hudi .hoodie/ timeline for a GCS bucket.

    Lists active timeline files (excludes archived/), classifies commits,
    inflights, and rollbacks, detects anomalies.

    Args:
      bucket_uri      (str, required)  — gs://bucket/path/to/hudi/table
      max_stale_hours (int, default 4) — stale_latest_commit threshold
    """
    bucket_uri = args.get("bucket_uri", "").strip()
    if not bucket_uri or not bucket_uri.startswith("gs://"):
        return {"error": "bucket_uri is required and must start with gs://"}

    max_stale_hours = int(args.get("max_stale_hours", 4))

    hoodie_uri = bucket_uri.rstrip("/") + "/.hoodie/"

    # List active timeline files
    rc, ls_out = _gsutil(["ls", hoodie_uri], timeout=30)
    if rc != 0:
        return {"error": "gsutil_failed", "detail": ls_out[:500], "hoodie_uri": hoodie_uri}

    all_files = [l.strip() for l in ls_out.splitlines() if l.strip()]
    # Exclude archived/ and directory entries
    timeline_files = [
        f for f in all_files
        if ".hoodie/archived" not in f and not f.endswith("/")
    ]

    # Parse timeline entries
    COMMIT_RE = re.compile(
        r"/(?P<ts>\d{14,17})\.(?P<ext>commit|inflight|rollback|clean|"
        r"commit\.requested|rollback\.inflight|clean\.inflight|"
        r"savepoint|savepoint\.inflight)$"
    )

    def ts_to_dt(ts: str) -> datetime.datetime:
        fmt = "%Y%m%d%H%M%S%f" if len(ts) > 14 else "%Y%m%d%H%M%S"
        return datetime.datetime.strptime(ts[:17] if len(ts) > 14 else ts[:14], fmt)

    parsed = []
    for f in timeline_files:
        m = COMMIT_RE.search(f)
        if m:
            parsed.append({"uri": f, "ts": m.group("ts"), "ext": m.group("ext")})

    commits   = {p["ts"]: p for p in parsed if p["ext"] == "commit"}
    inflights = {p["ts"]: p for p in parsed if p["ext"] == "inflight"}
    rollbacks = {p["ts"]: p for p in parsed if p["ext"] == "rollback"}

    now = datetime.datetime.utcnow()
    anomalies = []

    if not commits:
        return {
            "bucket_uri": bucket_uri,
            "healthy": False,
            "anomalies": [{"type": "no_commits", "severity": "critical",
                           "detail": "No completed commits in active .hoodie/ timeline"}],
            "commit_count": 0,
            "inflight_count": len(inflights),
            "rollback_count": len(rollbacks),
        }

    sorted_ts = sorted(commits.keys())
    latest_ts = sorted_ts[-1]
    latest_dt = ts_to_dt(latest_ts)
    hours_since = (now - latest_dt).total_seconds() / 3600

    # Stale check
    if hours_since > max_stale_hours:
        anomalies.append({
            "type": "stale_latest_commit",
            "severity": "critical",
            "detail": f"Latest commit {latest_ts} is {hours_since:.1f}h old (threshold: {max_stale_hours}h)",
            "age_hours": round(hours_since, 2),
        })

    # Orphan inflights (> 30 min with no matching commit)
    for ts, inf in inflights.items():
        if ts not in commits:
            age_min = (now - ts_to_dt(ts)).total_seconds() / 60
            if age_min > 30:
                anomalies.append({
                    "type": "orphan_inflight",
                    "severity": "warning",
                    "detail": f"Inflight {ts} has no matching .commit ({age_min:.0f} min old)",
                    "inflight_ts": ts,
                    "age_min": round(age_min),
                })

    # Recent rollbacks (last 48h)
    cutoff_48h = (now - datetime.timedelta(hours=48)).strftime("%Y%m%d%H%M%S")
    recent_rollbacks = [ts for ts in rollbacks if ts >= cutoff_48h]
    if recent_rollbacks:
        anomalies.append({
            "type": "rollback_recent",
            "severity": "info",
            "detail": f"{len(recent_rollbacks)} rollback(s) in last 48h: {sorted(recent_rollbacks)}",
            "rollback_timestamps": sorted(recent_rollbacks),
        })

    return {
        "bucket_uri": bucket_uri,
        "hoodie_uri": hoodie_uri,
        "healthy": len(anomalies) == 0,
        "latest_commit_ts": latest_ts,
        "latest_commit_age_hours": round(hours_since, 2),
        "commit_count": len(commits),
        "inflight_count": len(inflights),
        "rollback_count": len(rollbacks),
        "oldest_active_commit_ts": sorted_ts[0] if sorted_ts else None,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
    }


# ── MCP dispatcher ────────────────────────────────────────────────────────────
TOOLS = {
    "gcs_ls": {
        "fn": tool_gcs_ls,
        "description": "List GCS objects at a URI prefix",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": "GCS URI prefix e.g. gs://bucket/path/"},
                "recursive": {"type": "boolean", "description": "Recursive listing"},
                "max_items": {"type": "integer", "description": "Max items to return (default 200)"},
            },
            "required": ["uri"],
        },
    },
    "gcs_stat": {
        "fn": tool_gcs_stat,
        "description": "Stat a GCS object — size, content type, updated timestamp",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": "GCS object URI"},
            },
            "required": ["uri"],
        },
    },
    "gcs_cat": {
        "fn": tool_gcs_cat,
        "description": "Read a GCS text file (capped at max_bytes, default 32KB). JSON files are auto-parsed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": "GCS object URI"},
                "max_bytes": {"type": "integer", "description": "Max bytes to return (default 32768)"},
            },
            "required": ["uri"],
        },
    },
    "dataproc_list": {
        "fn": tool_dataproc_list,
        "description": "List Dataproc clusters in a GCP project",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GCP project ID e.g. wmt-bfdms-intldlcaprod"},
                "region": {"type": "string", "description": "GCP region (default us-central1)"},
                "state": {"type": "string", "description": "Filter by cluster state: RUNNING, STOPPED, ERROR"},
            },
            "required": ["project"],
        },
    },
    "dataproc_describe": {
        "fn": tool_dataproc_describe,
        "description": "Describe a specific Dataproc cluster (full config and status)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GCP project ID"},
                "cluster_name": {"type": "string", "description": "Dataproc cluster name"},
                "region": {"type": "string", "description": "GCP region (default us-central1)"},
            },
            "required": ["project", "cluster_name"],
        },
    },
    "dataproc_fetch_driver_log": {
        "fn": tool_dataproc_fetch_driver_log,
        "description": "Fetch Spark driver output for a Dataproc job (all driveroutput.* chunks)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Dataproc job UUID"},
                "project": {"type": "string", "description": "GCP project ID"},
                "region": {"type": "string", "description": "GCP region (default us-central1)"},
                "max_bytes": {"type": "integer", "description": "Max bytes of log to return (default 65536)"},
            },
            "required": ["job_id", "project"],
        },
    },
    "hudi_timeline": {
        "fn": tool_hudi_timeline,
        "description": "Parse Hudi .hoodie/ timeline for a GCS bucket — detects stale commits, orphan inflights, recent rollbacks",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bucket_uri": {"type": "string", "description": "GCS URI of the Hudi table root e.g. gs://bucket/path/to/table"},
                "max_stale_hours": {"type": "integer", "description": "Hours before latest commit is considered stale (default 4)"},
            },
            "required": ["bucket_uri"],
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
            "serverInfo": {"name": "sarthi-gcp", "version": "1.0.0"},
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
    log("sarthi-gcp MCP server starting (stdio)")
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
    parser = argparse.ArgumentParser(description="sarthi-gcp MCP server")
    parser.add_argument("--test", metavar="TOOL", help="Run a single tool and print result")
    parser.add_argument("args_json", nargs="?", default="{}", help="JSON args for --test mode")
    parsed = parser.parse_args()

    if parsed.test:
        run_test(parsed.test, parsed.args_json)
    else:
        run_stdio()
