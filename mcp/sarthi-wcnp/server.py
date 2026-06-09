"""
sarthi-wcnp MCP stdio server — Kubernetes/WCNP tools for sArthI.

Wraps kubectl CLI which is authenticated via `sledge connect <cluster>`.
Sledge is Walmart's cluster auth tool — run it once interactively per cluster;
it writes kubeconfig entries that kubectl uses for subsequent calls.

Auth pattern: CLI-wrapper (same as sarthi-git).
  - sledge connect <cluster>  → writes kubeconfig (interactive, run once)
  - On missing/expired kubeconfig → returns {"error": "auth_expired", "detail": "..."}
  - Never auto-refreshes (sledge is interactive-only)

Per-call design: every tool takes cluster + namespace params explicitly.
  - Uses --context <kubectl_context> and -n <namespace> on every call
  - Does NOT use `kubectl config set-context --current` for reads
    (that's a global state mutation — unsafe with multiple clusters)

Config: WCNP_CONFIG env var → path to wcnp-clusters.yaml
  (default: ~/.wibey/sarthi/wcnp-clusters.yaml)

wcnp-clusters.yaml format:
  default_namespace: amt-intl
  clusters:
    - name: uscentral1-dev-gke01        # matches sledge cluster name
      kubectl_context: ""               # auto-detected from kubeconfig after sledge connect
      ops_allowed: true
    - name: uswest1-prod-gke03
      kubectl_context: ""
      ops_allowed: false                # prod: read-only by default

Tools (read):
  wcnp_get_pods         — kubectl get pods
  wcnp_describe_pod     — kubectl describe pod
  wcnp_get_logs         — kubectl logs
  wcnp_get_deployments  — kubectl get deployments
  wcnp_get_events       — kubectl get events
  wcnp_describe_service — kubectl describe svc
  wcnp_get_nodes        — kubectl get nodes (cluster-level, no namespace)
  wcnp_list_namespaces  — kubectl get namespaces
  wcnp_list_clusters    — list configured clusters from wcnp-clusters.yaml

Tools (ops — requires ops_allowed: true for the cluster):
  wcnp_rollout_restart  — kubectl rollout restart deployment/<name>
  wcnp_scale            — kubectl scale deployment/<name> --replicas=N

CRITICAL: stdout is JSON-RPC. ALL diagnostic output → sys.stderr. NEVER use print() to stdout.
"""

import sys
import os
import json
import argparse
import subprocess
import shutil
from pathlib import Path

HOME = Path.home()
WCNP_CONFIG = os.environ.get("WCNP_CONFIG", str(HOME / ".wibey" / "sarthi" / "wcnp-clusters.yaml"))
TIMEOUT = 30  # seconds per kubectl call


def log(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr, flush=True)


# ── Config loader ─────────────────────────────────────────────────────────────

def _load_config() -> dict:
    """Load wcnp-clusters.yaml. Returns {"clusters": [], "default_namespace": "default"}."""
    if not os.path.exists(WCNP_CONFIG):
        return {"clusters": [], "default_namespace": "default"}
    try:
        import yaml
        with open(WCNP_CONFIG) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Fallback: basic YAML parser for simple key:value format
        cfg = {"clusters": [], "default_namespace": "default"}
        try:
            import re
            with open(WCNP_CONFIG) as f:
                content = f.read()
            dn = re.search(r"default_namespace:\s*(\S+)", content)
            if dn:
                cfg["default_namespace"] = dn.group(1)
        except Exception:
            pass
        return cfg
    except Exception as e:
        log(f"WARN: could not load {WCNP_CONFIG}: {e}")
        return {"clusters": [], "default_namespace": "default"}


def _get_cluster(cluster_name: str, cfg: dict) -> dict | None:
    """Find cluster entry by name."""
    for c in cfg.get("clusters", []):
        if c.get("name") == cluster_name:
            return c
    return None


# ── kubectl context resolution ────────────────────────────────────────────────

def _resolve_context(cluster_name: str, cfg: dict) -> str | None:
    """
    Get kubectl context for a cluster.
    1. Check wcnp-clusters.yaml for explicit kubectl_context
    2. Auto-detect from `kubectl config get-contexts` by matching cluster name fragment
    Returns None if not found (auth_expired).
    """
    cluster = _get_cluster(cluster_name, cfg)
    if cluster and cluster.get("kubectl_context"):
        return cluster["kubectl_context"]

    # Auto-detect: list contexts and find one matching the cluster name
    try:
        r = subprocess.run(
            ["kubectl", "config", "get-contexts", "--no-headers", "-o", "name"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            contexts = r.stdout.strip().splitlines()
            # Prefer exact match, then substring
            for ctx in contexts:
                if cluster_name in ctx:
                    return ctx
    except Exception:
        pass
    return None


def _kubectl(args: list[str], context: str, namespace: str | None = None,
             timeout: int = TIMEOUT) -> tuple[int, str, str]:
    """Run kubectl with --context and optional -n. Returns (rc, stdout, stderr)."""
    cmd = ["kubectl", "--context", context]
    if namespace:
        cmd += ["-n", namespace]
    cmd += args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except FileNotFoundError:
        return -1, "", "kubectl not found — install kubectl or check PATH"
    except Exception as e:
        return -1, "", str(e)


def _check_dependencies() -> dict | None:
    """
    Check kubectl and sledge are installed.
    Returns a dependency_missing error dict if either is absent, None if both present.
    Call this BEFORE any kubectl invocation — gives a clear install message
    instead of misattributing a missing binary to an auth problem.
    """
    missing = []
    if not shutil.which("kubectl"):
        missing.append({
            "binary": "kubectl",
            "install_hint": (
                "Install from Walmart Artifactory (on Walmart network/VPN): "
                "KUBECTL_VERSION=$(curl -sf https://generic.ci.artifacts.walmart.com/artifactory/dl-k8s-io-generic-release-remote/release/stable.txt) && "
                "curl -LO https://generic.ci.artifacts.walmart.com/artifactory/dl-k8s-io-generic-release-remote/release/${KUBECTL_VERSION}/bin/darwin/amd64/kubectl && "
                "chmod +x kubectl && mv kubectl ~/.local/bin/ "
                "(replace darwin/amd64 with linux/amd64 or darwin/arm64 as needed). "
                "Or run: bash ~/sarthi/setup.sh — it auto-installs kubectl."
            ),
        })
    if not shutil.which("sledge"):
        missing.append({
            "binary": "sledge",
            "install_hint": (
                "Install from Walmart wmlink (on Walmart network/VPN): "
                "curl -sL http://wmlink.wal-mart.com/getSledgeCore | sh - "
                "After install run: sledge connect <cluster-name>. "
                "Or run: bash ~/sarthi/setup.sh — it auto-installs sledge."
            ),
        })
    if missing:
        return {
            "error": "dependency_missing",
            "missing": missing,
            "detail": f"Required binaries not found: {', '.join(m['binary'] for m in missing)}. "
                      f"Install them first, then run 'sledge connect <cluster>' and restart Wibey.",
        }
    return None


def _check_auth(cluster_name: str) -> tuple[str | None, str | None]:
    """Returns (context, error_message). error_message is None if auth OK."""
    # Check binaries first — distinct from auth errors
    dep_err = _check_dependencies()
    if dep_err:
        # Return the full dep error as the "error_message" string so callers see dependency_missing
        return None, json.dumps(dep_err)

    cfg = _load_config()
    ctx = _resolve_context(cluster_name, cfg)
    if not ctx:
        return None, (
            f"No kubectl context found for cluster '{cluster_name}'. "
            f"Run: sledge connect {cluster_name} — then restart Wibey or re-run setup."
        )
    # Quick auth check
    rc, _, stderr = _kubectl(["auth", "can-i", "get", "pods"], ctx, timeout=10)
    if rc != 0 and any(w in stderr.lower() for w in ["unauthorized", "forbidden", "expired", "not found"]):
        return None, (
            f"Kubeconfig for '{cluster_name}' is expired or invalid. "
            f"Run: sledge connect {cluster_name}"
        )
    return ctx, None


def _auth_error(err: str) -> dict:
    """Return dependency_missing or auth_expired depending on what _check_auth returned."""
    try:
        parsed = json.loads(err)
        if parsed.get("error") == "dependency_missing":
            return parsed
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return {"error": "auth_expired", "detail": err}


def _check_ops(cluster_name: str, cfg: dict | None = None) -> bool:
    """Return True if ops_allowed for this cluster."""
    cfg = cfg or _load_config()
    cluster = _get_cluster(cluster_name, cfg)
    if cluster is None:
        return False
    return bool(cluster.get("ops_allowed", False))


def _default_namespace() -> str:
    cfg = _load_config()
    return cfg.get("default_namespace", "default")


# ── Tools ─────────────────────────────────────────────────────────────────────

def tool_wcnp_doctor(args: dict) -> dict:
    """
    Check all sarthi-wcnp dependencies and auth state.
    Run this first to understand what's installed, what's missing, and what to do next.
    """
    report = {"checks": [], "ready": True, "next_steps": []}

    # 1. kubectl
    kubectl_path = shutil.which("kubectl")
    if kubectl_path:
        try:
            r = subprocess.run(["kubectl", "version", "--client"],
                               capture_output=True, text=True, timeout=5)
            # Extract just the first line (client version) — works across kubectl versions
            out = r.stdout.strip() or r.stderr.strip()
            version = out.splitlines()[0] if out else "found"
        except Exception:
            version = "found (version check failed)"
        report["checks"].append({"name": "kubectl", "status": "ok", "detail": version})
    else:
        report["checks"].append({
            "name": "kubectl",
            "status": "missing",
            "detail": "kubectl not found in PATH",
            "install": (
                "Run: bash ~/sarthi/setup.sh  — it auto-installs kubectl from Walmart Artifactory. "
                "Manual: KUBECTL_VERSION=$(curl -sf https://generic.ci.artifacts.walmart.com/artifactory/"
                "dl-k8s-io-generic-release-remote/release/stable.txt) && "
                "curl -LO https://generic.ci.artifacts.walmart.com/artifactory/"
                "dl-k8s-io-generic-release-remote/release/${KUBECTL_VERSION}/bin/darwin/amd64/kubectl && "
                "chmod +x kubectl && mv kubectl ~/.local/bin/"
            ),
        })
        report["ready"] = False
        report["next_steps"].append(
            "Run: bash ~/sarthi/setup.sh  (auto-installs kubectl from Walmart Artifactory)"
        )

    # 2. sledge
    sledge_path = shutil.which("sledge")
    if sledge_path:
        report["checks"].append({"name": "sledge", "status": "ok", "detail": sledge_path})
    else:
        report["checks"].append({
            "name": "sledge",
            "status": "missing",
            "detail": "sledge not found in PATH",
            "install": (
                "Run: bash ~/sarthi/setup.sh  — it auto-installs sledge from wmlink. "
                "Manual: curl -sL http://wmlink.wal-mart.com/getSledgeCore | sh -  "
                "(must be on Walmart network/VPN)"
            ),
        })
        report["ready"] = False
        report["next_steps"].append(
            "Run: bash ~/sarthi/setup.sh  (auto-installs sledge from wmlink)"
        )

    # 3. wcnp-clusters.yaml
    if os.path.exists(WCNP_CONFIG):
        cfg = _load_config()
        clusters = cfg.get("clusters", [])
        report["checks"].append({
            "name": "wcnp-clusters.yaml",
            "status": "ok",
            "detail": f"{len(clusters)} cluster(s) configured at {WCNP_CONFIG}",
            "clusters": [c.get("name") for c in clusters],
        })
    else:
        report["checks"].append({
            "name": "wcnp-clusters.yaml",
            "status": "missing",
            "detail": f"Config not found at {WCNP_CONFIG}",
            "fix": f"Create {WCNP_CONFIG} with your cluster names. Run /sar-local-mcp for guided setup.",
        })
        report["ready"] = False
        report["next_steps"].append(f"Create {WCNP_CONFIG} with your cluster names")

    # 4. Per-cluster kubeconfig context (only if kubectl present)
    if kubectl_path:
        cfg = _load_config()
        for cluster in cfg.get("clusters", []):
            name = cluster.get("name", "")
            ctx = _resolve_context(name, cfg)
            if ctx:
                report["checks"].append({
                    "name": f"kubeconfig:{name}",
                    "status": "ok",
                    "detail": f"context found: {ctx}",
                })
            else:
                report["checks"].append({
                    "name": f"kubeconfig:{name}",
                    "status": "not_connected",
                    "detail": f"No kubectl context for '{name}'",
                    "fix": f"Run: sledge connect {name}",
                })
                report["ready"] = False
                report["next_steps"].append(f"Run: sledge connect {name}")

    if report["ready"]:
        report["summary"] = "✅ All dependencies ready. sarthi-wcnp is fully operational."
    else:
        report["summary"] = (
            f"❌ {len(report['next_steps'])} item(s) need attention before tools will work. "
            f"See next_steps."
        )

    return report


def tool_wcnp_list_clusters(args: dict) -> dict:
    """List configured clusters from wcnp-clusters.yaml."""
    cfg = _load_config()
    clusters = cfg.get("clusters", [])
    if not clusters:
        return {
            "clusters": [],
            "config_file": WCNP_CONFIG,
            "hint": f"Add clusters to {WCNP_CONFIG} — run /sar-local-mcp or edit manually.",
        }
    return {
        "clusters": [
            {
                "name": c.get("name"),
                "kubectl_context": c.get("kubectl_context") or "(auto-detect)",
                "ops_allowed": c.get("ops_allowed", False),
            }
            for c in clusters
        ],
        "default_namespace": cfg.get("default_namespace", "default"),
        "config_file": WCNP_CONFIG,
    }


def tool_wcnp_list_namespaces(args: dict) -> dict:
    """List namespaces in a cluster."""
    cluster = args.get("cluster", "").strip()
    if not cluster:
        return {"error": "cluster is required"}

    ctx, err = _check_auth(cluster)
    if err:
        return _auth_error(err)

    rc, stdout, stderr = _kubectl(["get", "namespaces", "-o", "wide"], ctx)
    if rc != 0:
        return {"error": "kubectl_failed", "detail": stderr[:500]}
    return {"cluster": cluster, "output": stdout}


def tool_wcnp_get_pods(args: dict) -> dict:
    """
    Get pods in a namespace.

    Args:
      cluster    (str, required) — cluster name (matches sledge cluster name)
      namespace  (str, optional) — namespace (default: from wcnp-clusters.yaml default_namespace)
      selector   (str, optional) — label selector e.g. app=my-app
      all_namespaces (bool, optional) — get pods across all namespaces
    """
    cluster = args.get("cluster", "").strip()
    if not cluster:
        return {"error": "cluster is required"}

    namespace = args.get("namespace", _default_namespace()).strip()
    selector = args.get("selector", "").strip()
    all_ns = bool(args.get("all_namespaces", False))

    ctx, err = _check_auth(cluster)
    if err:
        return _auth_error(err)

    kubectl_args = ["get", "pods", "-o", "wide"]
    if all_ns:
        kubectl_args.append("--all-namespaces")
        ns = None
    else:
        ns = namespace

    if selector:
        kubectl_args += ["-l", selector]

    rc, stdout, stderr = _kubectl(kubectl_args, ctx, ns)
    if rc != 0:
        return {"error": "kubectl_failed", "detail": stderr[:500]}
    return {"cluster": cluster, "namespace": ns or "all", "output": stdout}


def tool_wcnp_describe_pod(args: dict) -> dict:
    """
    Describe a pod.

    Args:
      cluster   (str, required)
      pod_name  (str, required)
      namespace (str, optional)
    """
    cluster = args.get("cluster", "").strip()
    pod_name = args.get("pod_name", "").strip()
    if not cluster or not pod_name:
        return {"error": "cluster and pod_name are required"}

    namespace = args.get("namespace", _default_namespace()).strip()
    ctx, err = _check_auth(cluster)
    if err:
        return _auth_error(err)

    rc, stdout, stderr = _kubectl(["describe", "pod", pod_name], ctx, namespace)
    if rc != 0:
        return {"error": "kubectl_failed", "detail": stderr[:500]}
    return {"cluster": cluster, "namespace": namespace, "pod": pod_name, "output": stdout}


def tool_wcnp_get_logs(args: dict) -> dict:
    """
    Get logs from a pod or container.

    Args:
      cluster    (str, required)
      pod_name   (str, required)
      namespace  (str, optional)
      container  (str, optional) — container name (for multi-container pods)
      tail       (int, optional) — last N lines (default 100)
      previous   (bool, optional) — get logs from previous container instance
    """
    cluster = args.get("cluster", "").strip()
    pod_name = args.get("pod_name", "").strip()
    if not cluster or not pod_name:
        return {"error": "cluster and pod_name are required"}

    namespace = args.get("namespace", _default_namespace()).strip()
    container = args.get("container", "").strip()
    tail = int(args.get("tail", 100))
    previous = bool(args.get("previous", False))

    ctx, err = _check_auth(cluster)
    if err:
        return _auth_error(err)

    kubectl_args = ["logs", pod_name, f"--tail={tail}"]
    if container:
        kubectl_args += ["-c", container]
    if previous:
        kubectl_args.append("--previous")

    rc, stdout, stderr = _kubectl(kubectl_args, ctx, namespace, timeout=60)
    if rc != 0:
        return {"error": "kubectl_failed", "detail": stderr[:500]}
    return {"cluster": cluster, "namespace": namespace, "pod": pod_name, "output": stdout}


def tool_wcnp_get_deployments(args: dict) -> dict:
    """
    Get deployments in a namespace.

    Args:
      cluster   (str, required)
      namespace (str, optional)
    """
    cluster = args.get("cluster", "").strip()
    if not cluster:
        return {"error": "cluster is required"}

    namespace = args.get("namespace", _default_namespace()).strip()
    ctx, err = _check_auth(cluster)
    if err:
        return _auth_error(err)

    rc, stdout, stderr = _kubectl(["get", "deployments", "-o", "wide"], ctx, namespace)
    if rc != 0:
        return {"error": "kubectl_failed", "detail": stderr[:500]}
    return {"cluster": cluster, "namespace": namespace, "output": stdout}


def tool_wcnp_get_events(args: dict) -> dict:
    """
    Get events in a namespace, sorted by time.

    Args:
      cluster   (str, required)
      namespace (str, optional)
      warning_only (bool, optional) — filter to Warning events only
    """
    cluster = args.get("cluster", "").strip()
    if not cluster:
        return {"error": "cluster is required"}

    namespace = args.get("namespace", _default_namespace()).strip()
    warning_only = bool(args.get("warning_only", False))

    ctx, err = _check_auth(cluster)
    if err:
        return _auth_error(err)

    kubectl_args = ["get", "events", "--sort-by=.metadata.creationTimestamp"]
    if warning_only:
        kubectl_args += ["--field-selector", "type=Warning"]

    rc, stdout, stderr = _kubectl(kubectl_args, ctx, namespace)
    if rc != 0:
        return {"error": "kubectl_failed", "detail": stderr[:500]}
    return {"cluster": cluster, "namespace": namespace, "output": stdout}


def tool_wcnp_describe_service(args: dict) -> dict:
    """
    Describe a service.

    Args:
      cluster      (str, required)
      service_name (str, required)
      namespace    (str, optional)
    """
    cluster = args.get("cluster", "").strip()
    service_name = args.get("service_name", "").strip()
    if not cluster or not service_name:
        return {"error": "cluster and service_name are required"}

    namespace = args.get("namespace", _default_namespace()).strip()
    ctx, err = _check_auth(cluster)
    if err:
        return _auth_error(err)

    rc, stdout, stderr = _kubectl(["describe", "svc", service_name], ctx, namespace)
    if rc != 0:
        return {"error": "kubectl_failed", "detail": stderr[:500]}
    return {"cluster": cluster, "namespace": namespace, "service": service_name, "output": stdout}


def tool_wcnp_get_nodes(args: dict) -> dict:
    """
    Get cluster nodes (no namespace — cluster-scoped).

    Args:
      cluster (str, required)
    """
    cluster = args.get("cluster", "").strip()
    if not cluster:
        return {"error": "cluster is required"}

    ctx, err = _check_auth(cluster)
    if err:
        return _auth_error(err)

    rc, stdout, stderr = _kubectl(["get", "nodes", "-o", "wide"], ctx)
    if rc != 0:
        return {"error": "kubectl_failed", "detail": stderr[:500]}
    return {"cluster": cluster, "output": stdout}


def tool_wcnp_rollout_restart(args: dict) -> dict:
    """
    Restart a deployment (ops — requires ops_allowed: true for cluster).

    Args:
      cluster         (str, required)
      deployment_name (str, required)
      namespace       (str, optional)
    """
    cluster = args.get("cluster", "").strip()
    deployment_name = args.get("deployment_name", "").strip()
    if not cluster or not deployment_name:
        return {"error": "cluster and deployment_name are required"}

    cfg = _load_config()
    if not _check_ops(cluster, cfg):
        return {
            "error": "ops_not_allowed",
            "detail": f"ops_allowed is false for cluster '{cluster}' in {WCNP_CONFIG}. "
                      f"Set ops_allowed: true to enable mutation tools.",
        }

    ctx, err = _check_auth(cluster)
    if err:
        return _auth_error(err)

    namespace = args.get("namespace", cfg.get("default_namespace", "default")).strip()
    rc, stdout, stderr = _kubectl(
        ["rollout", "restart", f"deployment/{deployment_name}"], ctx, namespace
    )
    if rc != 0:
        return {"error": "kubectl_failed", "detail": stderr[:500]}
    return {"ok": True, "cluster": cluster, "namespace": namespace,
            "deployment": deployment_name, "output": stdout}


def tool_wcnp_scale(args: dict) -> dict:
    """
    Scale a deployment (ops — requires ops_allowed: true for cluster).

    Args:
      cluster         (str, required)
      deployment_name (str, required)
      replicas        (int, required)
      namespace       (str, optional)
    """
    cluster = args.get("cluster", "").strip()
    deployment_name = args.get("deployment_name", "").strip()
    replicas = args.get("replicas")
    if not cluster or not deployment_name or replicas is None:
        return {"error": "cluster, deployment_name, and replicas are required"}

    cfg = _load_config()
    if not _check_ops(cluster, cfg):
        return {
            "error": "ops_not_allowed",
            "detail": f"ops_allowed is false for cluster '{cluster}'. "
                      f"Set ops_allowed: true in {WCNP_CONFIG} to enable.",
        }

    ctx, err = _check_auth(cluster)
    if err:
        return _auth_error(err)

    namespace = args.get("namespace", cfg.get("default_namespace", "default")).strip()
    rc, stdout, stderr = _kubectl(
        ["scale", f"deployment/{deployment_name}", f"--replicas={int(replicas)}"],
        ctx, namespace
    )
    if rc != 0:
        return {"error": "kubectl_failed", "detail": stderr[:500]}
    return {"ok": True, "cluster": cluster, "namespace": namespace,
            "deployment": deployment_name, "replicas": replicas, "output": stdout}


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS = {
    "wcnp_list_clusters": {
        "fn": tool_wcnp_list_clusters,
        "description": "List WCNP clusters configured in wcnp-clusters.yaml with their ops_allowed status.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "wcnp_list_namespaces": {
        "fn": tool_wcnp_list_namespaces,
        "description": "List Kubernetes namespaces in a WCNP cluster.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "Cluster name e.g. uscentral1-dev-gke01"},
            },
            "required": ["cluster"],
        },
    },
    "wcnp_get_pods": {
        "fn": tool_wcnp_get_pods,
        "description": "Get pods in a namespace. Supports label selector filtering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cluster":        {"type": "string",  "description": "Cluster name"},
                "namespace":      {"type": "string",  "description": "Namespace (default: from config)"},
                "selector":       {"type": "string",  "description": "Label selector e.g. app=my-app"},
                "all_namespaces": {"type": "boolean", "description": "Get pods across all namespaces"},
            },
            "required": ["cluster"],
        },
    },
    "wcnp_describe_pod": {
        "fn": tool_wcnp_describe_pod,
        "description": "Describe a pod — shows events, resource limits, container status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cluster":   {"type": "string", "description": "Cluster name"},
                "pod_name":  {"type": "string", "description": "Pod name"},
                "namespace": {"type": "string", "description": "Namespace (default: from config)"},
            },
            "required": ["cluster", "pod_name"],
        },
    },
    "wcnp_get_logs": {
        "fn": tool_wcnp_get_logs,
        "description": "Get logs from a pod or container. Supports tail, previous container.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cluster":   {"type": "string",  "description": "Cluster name"},
                "pod_name":  {"type": "string",  "description": "Pod name"},
                "namespace": {"type": "string",  "description": "Namespace (default: from config)"},
                "container": {"type": "string",  "description": "Container name (multi-container pods)"},
                "tail":      {"type": "integer", "description": "Last N lines (default 100)"},
                "previous":  {"type": "boolean", "description": "Get logs from previous container instance"},
            },
            "required": ["cluster", "pod_name"],
        },
    },
    "wcnp_get_deployments": {
        "fn": tool_wcnp_get_deployments,
        "description": "Get deployments in a namespace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cluster":   {"type": "string", "description": "Cluster name"},
                "namespace": {"type": "string", "description": "Namespace (default: from config)"},
            },
            "required": ["cluster"],
        },
    },
    "wcnp_get_events": {
        "fn": tool_wcnp_get_events,
        "description": "Get Kubernetes events in a namespace, sorted by time. Filter to warnings only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cluster":      {"type": "string",  "description": "Cluster name"},
                "namespace":    {"type": "string",  "description": "Namespace (default: from config)"},
                "warning_only": {"type": "boolean", "description": "Filter to Warning type events only"},
            },
            "required": ["cluster"],
        },
    },
    "wcnp_describe_service": {
        "fn": tool_wcnp_describe_service,
        "description": "Describe a Kubernetes service.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cluster":      {"type": "string", "description": "Cluster name"},
                "service_name": {"type": "string", "description": "Service name"},
                "namespace":    {"type": "string", "description": "Namespace (default: from config)"},
            },
            "required": ["cluster", "service_name"],
        },
    },
    "wcnp_get_nodes": {
        "fn": tool_wcnp_get_nodes,
        "description": "Get cluster nodes with status and resource info.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "Cluster name"},
            },
            "required": ["cluster"],
        },
    },
    "wcnp_rollout_restart": {
        "fn": tool_wcnp_rollout_restart,
        "description": "Restart a deployment (ops — requires ops_allowed: true for cluster in wcnp-clusters.yaml).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cluster":         {"type": "string", "description": "Cluster name"},
                "deployment_name": {"type": "string", "description": "Deployment name"},
                "namespace":       {"type": "string", "description": "Namespace (default: from config)"},
            },
            "required": ["cluster", "deployment_name"],
        },
    },
    "wcnp_scale": {
        "fn": tool_wcnp_scale,
        "description": "Scale a deployment to N replicas (ops — requires ops_allowed: true for cluster).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cluster":         {"type": "string",  "description": "Cluster name"},
                "deployment_name": {"type": "string",  "description": "Deployment name"},
                "replicas":        {"type": "integer", "description": "Target replica count"},
                "namespace":       {"type": "string",  "description": "Namespace (default: from config)"},
            },
            "required": ["cluster", "deployment_name", "replicas"],
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
            "serverInfo": {"name": "sarthi-wcnp", "version": "1.0.0"},
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
    log("sarthi-wcnp MCP server starting (stdio)")
    log(f"WCNP_CONFIG: {WCNP_CONFIG}")
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
    parser = argparse.ArgumentParser(description="sarthi-wcnp MCP server — Kubernetes/WCNP tools")
    parser.add_argument("--test", metavar="TOOL", help="Run a single tool and print result")
    parser.add_argument("args_json", nargs="?", default="{}", help="JSON args for --test mode")
    parsed = parser.parse_args()

    if parsed.test:
        run_test(parsed.test, parsed.args_json)
    else:
        run_stdio()
