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


# Published *unmodified* v0.1.11 vendor functions only. This is a conservative
# one-time upgrade for a bug in temperature validation. Never replace any
# user-modified Function, including nodes whose IDs happen to be unchanged.
STOCK_FUNCTIONS_0111 = {
    "b150100000000004": (2963, "a14e767badfd813c"),
    "f5500ba6100a0001": (1301, "4f0f9790d60cea4f"),
    "b111a90000000002": (3500, "dd5173ca8290ccef"),
}

# Published unmodified v0.1.12/v0.1.13 decoder. A safe additional migration:
# only the exact vendor source can be replaced, never a customized Function.
STOCK_DECODER_0112 = (4071, "a4454e533518ac4f")


def legacy_fingerprint(source: str) -> str:
    # 64-bit FNV-1a over unicode code units; current reference functions are
    # BMP-only. Paired with exact length + unchanged vendor ID/name/type.
    value = 0xCBF29CE484222325
    for character in source:
        value = ((value ^ ord(character)) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def update_stock_functions(
    current_by_id: dict, packaged_by_id: dict
) -> int:
    updated = 0
    for node_id, (length, fingerprint) in STOCK_FUNCTIONS_0111.items():
        installed = current_by_id.get(node_id)
        packaged = packaged_by_id.get(node_id)
        if not isinstance(installed, dict) or not isinstance(packaged, dict):
            continue
        if installed.get("type") != "function" or packaged.get("type") != "function":
            continue
        if installed.get("name") != packaged.get("name"):
            print(f"[WARN] Preserving renamed custom Node-RED function {node_id}")
            continue
        before = installed.get("func")
        if not isinstance(before, str):
            continue
        desired = packaged.get("func")
        if before == desired:
            continue
        fp = legacy_fingerprint(before)
        known_v0111 = len(before) == length and fp == fingerprint
        known_v0112_decoder = (node_id == "b150100000000004"
            and (len(before), fp) == STOCK_DECODER_0112)
        if known_v0111 or known_v0112_decoder:
            installed["func"] = desired
            updated += 1
        else:
            print(f"[WARN] Preserving modified Node-RED function {node_id}; update it manually")
    return updated



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
    packaged_by_id = {n.get("id"): n for n in base if isinstance(n, dict)}
    additions = [n for n in base if n["id"] not in by_id]
    updated_functions = update_stock_functions(by_id, packaged_by_id)
    # Make the effective running decoder version visible in the add-on startup
    # log, rather than relying on the add-on version number or old flow comments.
    decoder = by_id.get("b150100000000004", {})
    packaged_decoder = packaged_by_id.get("b150100000000004", {})
    installed_code = decoder.get("func") if isinstance(decoder, dict) else None
    packaged_code = packaged_decoder.get("func") if isinstance(packaged_decoder, dict) else None
    if isinstance(installed_code, str) and installed_code == packaged_code:
        print("[INFO] JK02 decoder active: current v0.1.14 exact -200C raw sentinel fallback")
    elif isinstance(installed_code, str):
        old_size, old_fingerprint = STOCK_FUNCTIONS_0111["b150100000000004"]
        old_fp = legacy_fingerprint(installed_code)
        if (len(installed_code), old_fp) == STOCK_DECODER_0112:
            print("[WARN] JK02 decoder active: legacy v0.1.12; raw -200C fallback not installed")
        elif len(installed_code) == old_size and old_fp == old_fingerprint:
            print("[WARN] JK02 decoder active: legacy v0.1.11; raw -200C fallback not installed")
        else:
            print("[WARN] JK02 decoder active: customized/unrecognized Function; upgrade preserved it")
    else:
        print("[WARN] JK02 decoder not installed yet")
    changed = bool(additions or updated_functions)

    # Append vendor links only; never replace custom source nodes or wires.
    links = (
        ("136f1472850339d1", "77930ff9204bec01"),
        ("65ad8ac512b5e001", "b150100000000002"),
        ("b150100000000004", "f5500ba6100a0001"),
        ("136f1472850339d1", "b190021900000001"),
        ("65ad8ac512b5e001", "b190021900000001"),
        ("b150100000000004", "b190021900000001"),
        ("136f1472850339d1", "b111a90000000002"),
        ("65ad8ac512b5e001", "b111a90000000002"),
        ("b150100000000004", "b111a90000000002"),
        ("65ad8ac512b5e001", "b120001300000001"),
        ("65ad8ac512b5e001", "b121500000000001"),
        ("65ad8ac512b5e001", "b161600000000010"),
        ("136f1472850339d1", "b200000000000002"),
        ("65ad8ac512b5e001", "b200000000000002"),
        ("b150100000000004", "b200000000000002"),
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
        "b190021900000003": "ÉTAT BMS 1 + BMS 2 (20 s)",
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
    print(f"[INFO] Node-RED vendor flows merged: {len(additions)} nodes, {disabled} noisy Debug nodes disabled, {updated_functions} stock functions upgraded, backup {backup.name}")
    return len(additions)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: merge_flows.py INSTALLED_JSON PACKAGED_JSON [MORE_PACKAGES...]", file=sys.stderr)
        sys.exit(2)
    merge(Path(sys.argv[1]), Path(sys.argv[2]), *(Path(p) for p in sys.argv[3:]))
