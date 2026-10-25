#!/usr/bin/env python3
"""Idempotent, non-destructive merge of new vendor Node-RED flow nodes.

Never overwrite or delete existing user nodes. Before any change, save a
timestamped backup. Only approved vendor link edges are added; existing nodes
and user wiring stay intact.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def merge(installed: Path, packaged: Path, *extra_packages: Path) -> int:
    base = []
    for source in (packaged, *extra_packages):
        nodes = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(nodes, list):
            raise ValueError(f"Vendor flow package {source} must be a JSON array")
        base.extend(nodes)
    if not isinstance(base, list):
        raise ValueError("Vendor flows must be a JSON array")
    if not installed.exists():
        installed.parent.mkdir(parents=True, exist_ok=True)
        # A fresh installation must include ALL packaged flow files,
        # not only the original base flows.json.
        installed.write_text(
            json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[INFO] Initial Node-RED flows installed: {len(base)} nodes")
        return len(base)

    current = json.loads(installed.read_text(encoding="utf-8"))
    if not isinstance(current, list):
        raise ValueError("User flows must be a JSON array")
    by_id = {n.get("id"): n for n in current if isinstance(n, dict)}
    additions = [n for n in base if n["id"] not in by_id]
    changed = bool(additions)

    # Append vendor links only; never replace custom source nodes or wires.
    links = (
        ("136f1472850339d1", "77930ff9204bec01"),
        ("65ad8ac512b5e001", "b150100000000002"),
        ("b150100000000004", "f5500ba6100a0001"),
    )
    packaged_ids = {n.get("id") for n in base if isinstance(n, dict)}
    for source_id, target_id in links:
        source = by_id.get(source_id)
        if source is None and source_id in packaged_ids:
            # First migration from a very old install: the source node will be
            # supplied by the packaged flow and should already have its wiring.
            continue
        if not isinstance(source, dict) or target_id not in packaged_ids:
            print(f"[WARN] Cannot automatically link {source_id} to {target_id}")
            continue
        wires = source.get("wires")
        if isinstance(wires, list) and wires and isinstance(wires[0], list):
            if target_id not in wires[0]:
                wires[0].append(target_id)
                changed = True
        else:
            print(f"[WARN] User wiring was customized for {source_id}; link manually")

    # Disable noisy *stock* Debug nodes only; preserve renamed/custom nodes.
    # This intentional v0.1.7 migration simplifies the Debug sidebar for users.
    noisy_defaults = {
        "d4cb3acdbe43f291": "BLE raw and diagnostics",
        "5524471869b2e0af": "Trames JK02 valides (HEX)",
        "8d30a20107f452b3": "Trames rejetées (CRC)",
        "b150100000000006": "Mesures batterie (à confirmer)",
        "b150100000000007": "Profil inconnu : raw_hex à envoyer",
    }
    disabled = 0
    for node_id, expected_name in noisy_defaults.items():
        item = by_id.get(node_id)
        if (
            isinstance(item, dict)
            and item.get("type") == "debug"
            and item.get("name") == expected_name
            and item.get("active") is True
        ):
            item["active"] = False
            disabled += 1
            changed = True

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
    print(f"[INFO] Node-RED vendor flows merged: {len(additions)} nodes, {disabled} noisy Debug nodes disabled, backup {backup.name}")
    return len(additions)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: merge_flows.py INSTALLED_JSON PACKAGED_JSON [MORE_PACKAGES...]", file=sys.stderr)
        sys.exit(2)
    merge(Path(sys.argv[1]), Path(sys.argv[2]), *(Path(p) for p in sys.argv[3:]))
