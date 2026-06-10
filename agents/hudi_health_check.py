#!/usr/bin/env python3
"""
hudi_health_check.py — sarthi Hudi metadata corruption scanner.

Scans all configured Hudi tables for known corruption patterns:
  MX variant: .log file where version token (between .log. and _) is not an integer
              e.g. .files-0000_<ts>.log._0-XXX-XXX  (empty version)
  CA variant: .hfile compaction artifact appearing in log file position
              e.g. files-0000_<ts>.log.5_1-XXX_<ts>.hfile

Runs all gsutil ls calls in parallel — ~8s for 18 tables.
Writes findings to hudi_health.json. Empty = all clean.

Usage:
  python3 hudi_health_check.py              # read tables from config.yaml
  python3 hudi_health_check.py --verbose    # show per-table results

NOT wired into check.sh — run manually or add as Stage 0 when ready.
"""

import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

AGENT_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH  = os.path.expanduser("~/.wibey/sarthi/config.yaml")
OUTPUT_FILE  = os.path.join(AGENT_DIR, "hudi_health.json")
TIMEOUT      = 20  # seconds per gsutil ls call

# Corruption detection patterns
LOG_VERSION_PATTERN = re.compile(r'\.log\.([^_]+)_')


def load_hudi_tables() -> list[dict]:
    """
    Load hudi_tables entries from config.yaml.
    Returns list of:
      { "table": str, "market": str, "dag_id": str, "metadata_path": str }
    """
    if not _HAS_YAML:
        print("ERROR: PyYAML not installed. pip install pyyaml", file=sys.stderr)
        return []

    if not os.path.exists(CONFIG_PATH):
        print(f"ERROR: config.yaml not found at {CONFIG_PATH}", file=sys.stderr)
        return []

    try:
        with open(CONFIG_PATH) as f:
            cfg = _yaml.safe_load(f)
    except Exception as e:
        print(f"ERROR: failed to load config.yaml: {e}", file=sys.stderr)
        return []

    tables = []
    for env in cfg.get("environments", []):
        env_name = env.get("name", "")
        for dag in env.get("dags", []):
            dag_id = dag.get("id", "")
            for ht in dag.get("hudi_tables", []):
                tables.append({
                    "table":         ht.get("table", ""),
                    "market":        ht.get("market", ""),
                    "dag_id":        dag_id,
                    "env_name":      env_name,
                    "metadata_path": ht.get("metadata_path", ""),
                    "critical":      ht.get("critical", False),
                })
    return tables


def scan_metadata_path(entry: dict) -> dict:
    """
    Run gsutil ls on a metadata/files/ path and check for corrupt filenames.
    Returns:
      { "table": ..., "market": ..., "status": "clean"|"corrupt"|"error",
        "corrupt_files": [...], "error": ... }
    """
    path = entry["metadata_path"]
    table = entry["table"]
    market = entry["market"]

    try:
        result = subprocess.run(
            ["gsutil", "ls", path],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        if result.returncode != 0:
            return {
                **entry,
                "status": "error",
                "corrupt_files": [],
                "error": result.stderr.strip()[:200],
            }

        filenames = [
            line.strip().split("/")[-1]
            for line in result.stdout.splitlines()
            if line.strip() and not line.strip().endswith("/")
        ]

        corrupt = []
        for fname in filenames:
            issue = _check_filename(fname)
            if issue:
                corrupt.append({"filename": fname, "variant": issue, "full_path": path + fname})

        return {
            **entry,
            "status": "corrupt" if corrupt else "clean",
            "corrupt_files": corrupt,
            "error": None,
            "files_scanned": len(filenames),
        }

    except subprocess.TimeoutExpired:
        return {**entry, "status": "error", "corrupt_files": [], "error": f"timeout after {TIMEOUT}s"}
    except Exception as e:
        return {**entry, "status": "error", "corrupt_files": [], "error": str(e)}


def _check_filename(fname: str) -> str | None:
    """
    Return corruption variant name if file is corrupt, else None.

    CA variant: file contains .log. but ends with .hfile
      e.g. files-0000_20260610040523372001.log.5_1-214-81266_20260610062000852001.hfile
    MX variant: .log. version token is not a valid integer
      e.g. .files-0000_20260610XXXXXXXX.log._0-XXX-XXX (empty string before _)
    """
    if ".log." not in fname:
        return None  # not a log file at all — hfile or partition metadata, skip

    # CA variant: .log. in name but ends with .hfile
    if fname.endswith(".hfile"):
        return "CA-variant: hfile appearing as log file (InvalidHoodiePathException)"

    # MX variant: version segment between .log. and first _ is not an integer
    m = LOG_VERSION_PATTERN.search(fname)
    if m:
        version_str = m.group(1)
        try:
            int(version_str)
        except ValueError:
            return f"MX-variant: empty/invalid version string '{version_str}' (NumberFormatException)"

    return None


def main():
    verbose = "--verbose" in sys.argv

    print(f"[hudi-health] Loading table config from {CONFIG_PATH}")
    tables = load_hudi_tables()

    if not tables:
        print("[hudi-health] No hudi_tables configured in config.yaml — nothing to scan.")
        with open(OUTPUT_FILE, "w") as f:
            json.dump([], f)
        return 0

    print(f"[hudi-health] Scanning {len(tables)} Hudi table(s) in parallel...")
    start = time.monotonic()

    results = []
    with ThreadPoolExecutor(max_workers=len(tables)) as pool:
        futures = {pool.submit(scan_metadata_path, t): t for t in tables}
        for future in as_completed(futures):
            results.append(future.result())

    elapsed = round(time.monotonic() - start, 1)

    # Sort: corrupt first, then error, then clean
    results.sort(key=lambda r: ({"corrupt": 0, "error": 1, "clean": 2}.get(r["status"], 3)))

    # Write output
    corrupt_items = [r for r in results if r["status"] == "corrupt"]
    with open(OUTPUT_FILE, "w") as f:
        json.dump(corrupt_items, f, indent=2)

    # Print summary
    clean   = [r for r in results if r["status"] == "clean"]
    errors  = [r for r in results if r["status"] == "error"]

    print(f"\n{'═'*60}")
    print(f"  Hudi Metadata Health Scan — {len(tables)} tables in {elapsed}s")
    print(f"{'═'*60}")
    print(f"  ✅ Clean:   {len(clean)}")
    print(f"  ⚠️  Corrupt: {len(corrupt_items)}")
    print(f"  ❌ Error:   {len(errors)}")

    if corrupt_items:
        print(f"\n{'─'*60}")
        print(f"  ⚠️  CORRUPT TABLES — action required:")
        print(f"{'─'*60}")
        for r in corrupt_items:
            print(f"  [{r['market']}] {r['table']} (DAG: {r['dag_id']})")
            for cf in r["corrupt_files"]:
                print(f"    → {cf['filename']}")
                print(f"       Variant: {cf['variant']}")
                print(f"       Fix:     gsutil rm \"{cf['full_path']}\"")
            print(f"    Then: clear_task_with_deps + re-queue parent DAG run")

    if errors:
        print(f"\n{'─'*60}")
        print(f"  ❌ SCAN ERRORS (could not access):")
        for r in errors:
            print(f"  [{r['market']}] {r['table']}: {r['error']}")

    if verbose:
        print(f"\n{'─'*60}")
        print(f"  All tables scanned:")
        for r in results:
            icon = {"clean": "✅", "corrupt": "⚠️ ", "error": "❌"}.get(r["status"], "?")
            files = r.get("files_scanned", "?")
            print(f"  {icon} [{r['market']}] {r['table']} ({files} files) — {r['metadata_path']}")

    print(f"{'═'*60}")
    print(f"  Output: {OUTPUT_FILE}")
    print()

    if corrupt_items:
        print(f"⚠️  {len(corrupt_items)} corrupt table(s) found. Fix before next job run.")
        return 1

    print("✅ All Hudi tables clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
