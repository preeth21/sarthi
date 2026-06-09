#!/usr/bin/env python3
"""
inject-mcp.py — sArthI MCP server registration helper.

Reads sarthi-mcp-additions.json (the single source of truth for all sArthI
MCP servers) and non-destructively injects any missing servers into:
  - ~/.wibey/mcp.json     (used by setup.sh / manual inspection)
  - ~/.wibey/.mcp.json    (loaded by Wibey CLI at startup)

Run by setup.sh Step 7. Also callable standalone:
  python3 ~/sarthi/scripts/inject-mcp.py [--dry-run] [--interactive]

Features:
  - Resolves ${HOME} and ${SARTHI_ROOT} variables in args/env values
  - Skips servers with "_skip_if_exists: true" that are already present
  - --interactive: prompts for any missing required fields (env vars etc.)
  - --dry-run: prints what would be injected, no writes
  - No hardcoded server names — iterates the JSON, works for any server

Usage from setup.sh:
  python3 "$SARTHI_ROOT/scripts/inject-mcp.py" \\
      "$WIBEY_DIR/mcp.json" \\
      "$SARTHI_ROOT/mcp/sarthi-mcp-additions.json" \\
      --sarthi-root "$SARTHI_ROOT"
"""

import sys
import os
import json
import argparse
import shutil
import subprocess
from pathlib import Path

HOME = str(Path.home())


def resolve_vars(value: str, sarthi_root: str) -> str:
    """Expand ${HOME} and ${SARTHI_ROOT} in a string value."""
    return value.replace("${HOME}", HOME).replace("${SARTHI_ROOT}", sarthi_root)


def resolve_entry(entry: dict, sarthi_root: str) -> dict:
    """Recursively resolve variable placeholders in an MCP server entry."""
    result = {}
    for k, v in entry.items():
        if k.startswith("_"):
            continue  # strip metadata keys
        if isinstance(v, str):
            result[k] = resolve_vars(v, sarthi_root)
        elif isinstance(v, list):
            result[k] = [
                resolve_vars(item, sarthi_root) if isinstance(item, str) else item
                for item in v
            ]
        elif isinstance(v, dict):
            result[k] = {
                dk: resolve_vars(dv, sarthi_root) if isinstance(dv, str) else dv
                for dk, dv in v.items()
                if not dk.startswith("_")
            }
        else:
            result[k] = v
    return result


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json(path: str, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def inject(mcp_file: str, additions_file: str, sarthi_root: str,
           dry_run: bool = False, interactive: bool = False) -> tuple[int, int, list[str]]:
    """
    Inject missing servers from additions_file into mcp_file.
    Returns (injected_count, skipped_count, injected_names).
    """
    additions = load_json(additions_file)
    servers_to_add = additions.get("mcpServers", {})

    if not os.path.exists(mcp_file):
        print(f"  Creating {mcp_file}")
        save_json(mcp_file, {"mcpServers": {}})

    cfg = load_json(mcp_file)
    existing = cfg.setdefault("mcpServers", {})

    injected = []
    skipped = []

    for name, spec in servers_to_add.items():
        if spec.get("_skip_if_exists") and name in existing:
            skipped.append(name)
            continue
        if name in existing:
            skipped.append(name)
            continue

        entry = resolve_entry(spec, sarthi_root)

        # Check if server binary exists (warn but don't block)
        if "args" in entry and entry.get("command") in ("python3", "python"):
            server_file = entry["args"][0] if entry["args"] else ""
            if server_file and not os.path.exists(server_file):
                print(f"  ⚠️  {name}: server file not found: {server_file}")
                if interactive:
                    resp = input(f"     Skip {name}? [y/N]: ").strip().lower()
                    if resp == "y":
                        skipped.append(name)
                        continue

        if dry_run:
            print(f"  [dry-run] Would inject: {name}")
            print(f"            {json.dumps(entry, indent=2)}")
        else:
            existing[name] = entry
            injected.append(name)

    if not dry_run and injected:
        save_json(mcp_file, cfg)

    # After injection, check _requires_binaries for all servers in additions
    _check_binary_deps(servers_to_add)

    return len(injected), len(skipped), injected


def _check_binary_deps(servers_to_add: dict):
    """Check _requires_binaries for each server and warn if any are missing."""
    for name, spec in servers_to_add.items():
        reqs = spec.get("_requires_binaries", [])
        if not reqs:
            continue
        missing = []
        for req in reqs:
            binary = req.get("binary", "")
            if binary and not shutil.which(binary):
                missing.append(req)
        if missing:
            print(f"\n  ⚠️  {name}: required binaries not installed:")
            for m in missing:
                print(f"       ❌ {m['binary']}: {m.get('install_hint', 'install manually')}")
            auth_steps = spec.get("_auth_steps", [])
            if auth_steps:
                print(f"       After installing, run:")
                for step in auth_steps:
                    print(f"         {step}")
            doctor = spec.get("_doctor_tool")
            if doctor:
                print(f"       Then use tool '{doctor}' to verify readiness.")


def sync_hidden(mcp_file: str, hidden_file: str):
    """Sync injected servers from mcp.json into .mcp.json (Wibey loads hidden file)."""
    if not os.path.exists(hidden_file):
        return
    cfg = load_json(mcp_file)
    hidden = load_json(hidden_file)
    hidden_servers = hidden.setdefault("mcpServers", {})
    for key, val in cfg.get("mcpServers", {}).items():
        hidden_servers.setdefault(key, val)
    save_json(hidden_file, hidden)


def main():
    parser = argparse.ArgumentParser(
        description="Inject sArthI MCP servers into Wibey mcp.json"
    )
    parser.add_argument("mcp_file", nargs="?",
                        default=str(Path.home() / ".wibey" / "mcp.json"),
                        help="Target mcp.json (default: ~/.wibey/mcp.json)")
    parser.add_argument("additions_file", nargs="?",
                        default=str(Path.home() / "sarthi" / "mcp" / "sarthi-mcp-additions.json"),
                        help="Source additions JSON (default: ~/sarthi/mcp/sarthi-mcp-additions.json)")
    parser.add_argument("--sarthi-root", default=str(Path.home() / "sarthi"),
                        help="Path to sarthi repo root (default: ~/sarthi)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be injected without writing")
    parser.add_argument("--interactive", action="store_true",
                        help="Prompt for confirmation on missing files")
    parser.add_argument("--list", action="store_true",
                        help="List all servers defined in additions_file")

    args = parser.parse_args()

    if args.list:
        additions = load_json(args.additions_file)
        servers = additions.get("mcpServers", {})
        print(f"Servers in {args.additions_file}:")
        for name, spec in servers.items():
            skip = " (skip_if_exists)" if spec.get("_skip_if_exists") else ""
            comment = spec.get("_comment", "")[:80] if spec.get("_comment") else ""
            print(f"  {name}{skip}")
            if comment:
                print(f"    {comment}")
        return 0

    hidden_file = str(Path(args.mcp_file).parent / ".mcp.json")

    n_injected, n_skipped, names = inject(
        args.mcp_file, args.additions_file, args.sarthi_root,
        dry_run=args.dry_run, interactive=args.interactive
    )

    if not args.dry_run:
        sync_hidden(args.mcp_file, hidden_file)

    if n_injected:
        print(f"✅ Injected {n_injected} server(s): {', '.join(names)}")
        print(f"   Restart Wibey to activate.")
    if n_skipped:
        print(f"ℹ️  Skipped {n_skipped} already-registered server(s)")
    if n_injected == 0 and n_skipped > 0:
        print("✅ All servers already registered")

    return 0


if __name__ == "__main__":
    sys.exit(main())
