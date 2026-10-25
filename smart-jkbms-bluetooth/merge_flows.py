#!/usr/bin/env python3
"""Idempotent, non-destructive merge of new vendor Node-RED flow nodes.

Never overwrite or delete existing user nodes. Before any change, save a
timestamped backup. The only existing edge added is from the built-in
diagnostics node to the new link-out, leaving existing wires intact.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def merge(installed: Path, packaged: Path) -> int:
    base = json.loads(packaged.read_text(encoding="utf-8"))
    if not isinstance(base, list):
        raise ValueError("Vendor flows must be a JSON array")
    if not installed.exists():
        installed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(packaged, installed)
        print("[INFO] Initial Node-RED flows installed")
        return len(base)

    current = json.loads(installed.read_text(encoding="utf-8"))
    if not isinstance(current, list):
        raise ValueError("User flows must be a JSON array")
    by_id = {n.get("id"): n for n in current if isinstance(n, dict)}
    additions = [n for n in base if n["id"] not in by_id]
    changed = bool(additions)

    # Keep the original diagnostics function unmodified, add one outgoing wire.
    source = by_id.get("136f1472850339d1")
    target = "77930ff9204bec01"
    if isinstance(source, dict) and source.get("type") == "function":
        wires = source.get("wires")
        if isinstance(wires, list) and wires and isinstance(wires[0], list):
            if target not in wires[0]:
                wires[0].append(target)
                changed = True
        else:
            print("[WARN] Diagnostics wires are customized; cannot link frame analyzer")
    else:
        print("[WARN] Diagnostics function missing/customized; inspect new link manually")

    if not changed:
        return 0
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = installed.with_name(installed.name + "." + timestamp + ".bak")
    shutil.copy2(installed, backup)
    current.extend(additions)
    tmp = installed.with_name(installed.name + ".new")
    try:
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, installed)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"[INFO] Node-RED vendor flows merged: {len(additions)} nodes, backup {backup.name}")
    return len(additions)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: merge_flows.py INSTALLED_JSON PACKAGED_JSON", file=sys.stderr)
        sys.exit(2)
    merge(Path(sys.argv[1]), Path(sys.argv[2]))
