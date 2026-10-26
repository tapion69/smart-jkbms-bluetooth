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

# Exact, unmodified GitHub vendor MQTT forwarding functions from v0.2.0–0.2.4.
# The 0.2.4 merge originally never upgraded this Function node. This made
# added runtime/diagnostic fields stay Unknown on otherwise upgraded installs.
STOCK_MQTT_FORWARDERS = {
    (2992, "753455542d4ab731"),  # v0.2.0
    (3081, "15794c8740330310"),  # v0.2.1 and early follow-ups
    (4502, "da76ac1e10a8011f"),  # v0.2.3/0.2.4
}


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
    publisher_id="b200000000000002"
    current=current_by_id.get(publisher_id)
    target=packaged_by_id.get(publisher_id)
    if isinstance(current,dict) and isinstance(target,dict):
        installed_code=current.get("func")
        desired=target.get("func")
        if (current.get("name")==target.get("name") and
            current.get("type")=="function" and isinstance(installed_code,str) and
            isinstance(desired,str) and installed_code!=desired):
            if (len(installed_code),legacy_fingerprint(installed_code)) in STOCK_MQTT_FORWARDERS:
                current["func"]=desired
                updated+=1
                print("[INFO] Stock MQTT forwarder upgraded to current JK02 runtime/diagnostics version")
            else:
                print("[WARN] Custom MQTT forwarder retained unchanged; "
                      "cannot guarantee current diagnostic data until manual review")
    return updated



# Official v0.3.1/0.3.2 BIP function fingerprints. We only migrate these
# verified stock functions, leaving custom Node-RED functions untouched.
STOCK_BIP_032 = {
    "jkbms_bip_prepare_0301": ("Check BIP consent", 865, "f1f4b543da72cac6"),
    "jkbms_bip_report_0301": ("BIP result", 142, "904ef0111c3716ed"),
}


def update_stock_bip(current_by_id: dict, packaged_by_id: dict) -> int:
    """Replace only the original publisher's broken BIP nodes.

    This also replaces the two stock edges but preserves any additional
    user wiring such as a downstream Debug node. Compatible with repeated
    upgrades; never rewire an edited/custom Function.
    """
    changed = 0
    gate_id = "jkbms_bip_prepare_0301"
    post_id = "jkbms_bip_http_0301"
    result_id = "jkbms_bip_report_0301"
    analysis_id = "jkbms_bip_environment_0303"
    resolve_id = "jkbms_bip_redirect_0303"

    for node_id in (gate_id, result_id):
        node = current_by_id.get(node_id)
        desired = packaged_by_id.get(node_id)
        if not isinstance(node, dict) or not isinstance(desired, dict):
            continue
        if node.get("type") != "function":
            continue
        old_name, length, fingerprint = STOCK_BIP_032[node_id]
        code = node.get("func")
        is_stock = (node.get("name") == old_name and
                    isinstance(code, str) and
                    (len(code), legacy_fingerprint(code)) == (length, fingerprint))
        if not is_stock:
            if code != desired.get("func"):
                print(f"[WARN] Custom JK-BMS BIP Function {node_id} preserved; "
                      "review/update it manually to enable confirmed replies")
            continue
        if node_id == gate_id:
            wires = node.get("wires")
            if not (isinstance(wires, list) and wires
                    and isinstance(wires[0], list)):
                print("[WARN] Original BIP consent wiring differs; preserving node")
                continue
            # Move the original HTTP link after the new Prepare function.
            before = list(wires[0])
            wires[0] = [analysis_id] + [
                target for target in before if target not in (analysis_id, post_id)
            ]
        node["name"] = desired["name"]
        node["func"] = desired["func"]
        changed += 1
        print(f"[INFO] Upgraded stock JK-BMS BIP Function {node_id}")

    http = current_by_id.get(post_id)
    new_http = packaged_by_id.get(post_id)
    if isinstance(http, dict) and isinstance(new_http, dict):
        if (http.get("type") == "http request" and
            http.get("name") == "Google Apps Script (BIP)" and
            http.get("method") == "use" and http.get("url") == ""):
            wires = http.get("wires")
            if isinstance(wires, list) and wires and isinstance(wires[0], list):
                before = list(wires[0])
                http["wires"][0] = [resolve_id] + [
                    target for target in before if target not in (result_id, resolve_id)
                ]
                http["name"] = new_http["name"]
                http["url"] = new_http["url"]
                http["method"] = new_http["method"]
                http["ret"] = new_http["ret"]
                changed += 1
                print("[INFO] Upgraded stock JK-BMS BIP: fixed Google POST URL "
                      "and explicit JSON redirect verification")
            else:
                print("[WARN] Modified original BIP POST wiring; preserving HTTP node")
        elif http.get("url") != new_http.get("url"):
            print("[WARN] Custom BIP HTTP URL preserved; verify collector settings")
    return changed


# Exact published v0.3.3 BIP function sources; geolocation migration must
# not overwrite any code or wiring customized in the Node-RED editor.
STOCK_BIP_033_GEO = {
    "jkbms_bip_environment_0303": (
        "Analyse environnement", 283, "a90ef86315ac14d5"),
    "jkbms_bip_payload_0303": (
        "Prépare Google JK-BMS", 720, "54dae6cdba1e67a6"),
}


def update_stock_bip_geo(current_by_id: dict, packaged_by_id: dict) -> int:
    """Add IP geolocation for official v0.3.3 BIP installs, non-destructively.

    Update stock Function code only when exact source fingerprint matches;
    maintain extra user wires (e.g. Debug) and take a backup through merge().
    """
    changed = 0
    analysis_id = "jkbms_bip_environment_0303"
    old_next_id = "jkbms_bip_payload_0303"
    geo_gate_id = "jkbms_bip_geo_gate_0304"
    for node_id, (name, length, fp) in STOCK_BIP_033_GEO.items():
        node = current_by_id.get(node_id)
        desired = packaged_by_id.get(node_id)
        if not isinstance(node, dict) or not isinstance(desired, dict):
            continue
        original = node.get("func")
        if node.get("type") != "function" or node.get("name") != name:
            continue
        # Environment's official source is unchanged: the migration must
        # still reroute its old direct edge through the new geo branch.
        if original == desired.get("func") and node_id != analysis_id:
            continue
        if not isinstance(original, str) or (
                len(original), legacy_fingerprint(original)) != (length, fp):
            print(f"[WARN] Custom BIP Function {node_id} preserved; "
                  "configure geographic lookup manually if desired")
            continue
        if node_id == analysis_id:
            wires = node.get("wires")
            if not (isinstance(wires, list) and wires
                    and isinstance(wires[0], list)):
                print("[WARN] Custom BIP environment wiring preserved")
                continue
            if geo_gate_id in wires[0] and old_next_id not in wires[0]:
                continue
            if old_next_id not in wires[0]:
                print("[WARN] Custom BIP environment edges preserved")
                continue
            extra = [target for target in wires[0]
                     if target not in (old_next_id, geo_gate_id)]
            wires[0] = [geo_gate_id] + extra
        node["func"] = desired["func"]
        changed += 1
        print(f"[INFO] Upgraded stock v0.3.3 BIP Function {node_id} for "
              "Finance-style approximate IP location")
    return changed


STOCK_GEO_GATE_034 = (347, "e8b2ecb362e5338b")
STOCK_GEO_FALLBACK_034 = (204, "1991e5b23367eacf")


def upgrade_stock_geo_timeout(current: dict, packaged: dict) -> int:
    """Repair known v0.3.4 geo HTTP timeout handling.

    Migrate only exact stock Function nodes and original stock HTTP
    wiring; preserve user edits and extra user Debug links.
    """
    changed = 0
    gate_id="jkbms_bip_geo_gate_0304"
    http_id="jkbms_bip_geo_http_0304"
    fallback_id="jkbms_bip_geo_fallback_0304"
    prepared_id="jkbms_bip_payload_0303"
    verify_id="jkbms_bip_geo_verify_0305"

    gate=current.get(gate_id)
    desired=packaged.get(gate_id)
    if isinstance(gate,dict) and isinstance(desired,dict):
        code=gate.get("func")
        if (gate.get("type")=="function" and
            gate.get("name")=="Géolocalisation autorisée ?" and
            isinstance(code,str) and
            (len(code),legacy_fingerprint(code))==STOCK_GEO_GATE_034):
            gate["func"]=desired["func"]
            changed+=1
        elif code!=desired.get("func"):
            print("[WARN] Modified geo permission function preserved")

    for node_id,expected_name in (
        (http_id, "geoloc (ipwho.is)"),
        (fallback_id, "Geo unavailable (continue BIP)")
    ):
        current_node=current.get(node_id)
        desired=packaged.get(node_id)
        if not isinstance(current_node,dict) or not isinstance(desired,dict):
            continue
        if (current_node.get("name")!=expected_name or
            current_node.get("type")!=desired.get("type")):
            continue
        if node_id==http_id and (
            current_node.get("method")!="GET" or
            current_node.get("url")!="https://ipwho.is/"):
            continue
        if node_id==fallback_id:
            code=current_node.get("func")
            if (not isinstance(code,str) or
                (len(code),legacy_fingerprint(code))!=STOCK_GEO_FALLBACK_034):
                if code!=desired.get("func"):
                    print("[WARN] Modified geo fallback function preserved")
                continue
        wires=current_node.get("wires")
        if not (isinstance(wires,list) and wires and isinstance(wires[0],list)):
            continue
        if verify_id in wires[0] and prepared_id not in wires[0]:
            continue
        if prepared_id not in wires[0]:
            print(f"[WARN] Custom geo wiring {node_id} preserved")
            continue
        extra=[x for x in wires[0] if x not in (prepared_id,verify_id)]
        wires[0]=[verify_id]+extra
        changed+=1
    if changed:
        print(f"[INFO] Updated {changed} stock JK-BMS geo nodes: "
              "ETIMEDOUT now falls back to Google BIP without stale HTTP metadata")
    return changed


# Exact v0.3.5 shipped Function sources; update only vendor-owned code.
# Do not rewrite a user-edited BIP function or its Debug wiring.
STOCK_SINGLE_BIP_035 = {
    "jkbms_bip_geo_gate_0304": (418, "7252dcab2e20d265"),
    "jkbms_bip_payload_0303": (1584, "689346e3b60d7401"),
}


def simplify_stock_bip_options(current: dict, packaged: dict) -> int:
    """Remove the redundant BIP GEO toggle from stock Node-RED functions.

    The one upstream send_bip gate remains the sole permission control.
    IP location still runs and falls back when unavailable.
    """
    changed=0
    for node_id,(length, fingerprint) in STOCK_SINGLE_BIP_035.items():
        node=current.get(node_id)
        wanted=packaged.get(node_id)
        if not isinstance(node,dict) or not isinstance(wanted,dict):
            continue
        if node.get("type")!="function":
            continue
        # Do not overwrite a user-renamed or customized Function.
        accepted_names={
            "jkbms_bip_geo_gate_0304":{"Géolocalisation autorisée ?","Localisation BIP"},
            "jkbms_bip_payload_0303":{"Prépare Google JK-BMS"}
        }[node_id]
        if node.get("name") not in accepted_names:
            continue
        current_code=node.get("func")
        if not isinstance(current_code,str):
            continue
        old_stock=(len(current_code),legacy_fingerprint(current_code))==(length,fingerprint)
        new_stock=current_code==wanted.get("func")
        if not old_stock and not new_stock:
            print(f"[WARN] Custom BIP Function {node_id} preserved")
            continue
        if node.get("name")!=wanted.get("name") or current_code!=wanted.get("func"):
            node["name"]=wanted["name"]
            node["func"]=wanted["func"]
            changed+=1
            print(f"[INFO] Simplified stock BIP Function {node_id} (send_bip only)")
    return changed


def _legacy_default(node: dict, manifest: dict) -> bool:
    """Remove only the exact published vendor node (never a user-edited one)."""
    if (node.get("id") != manifest["id"] or
        node.get("type") != manifest["type"] or
        node.get("name") != manifest.get("name")):
        return False
    if node.get("type") == "function":
        code = node.get("func")
        return isinstance(code, str) and (
            len(code) == manifest["func_length"] and
            legacy_fingerprint(code) == manifest["func_hash"]
        )
    return True


def merge(installed: Path, packaged: Path, *extra_packages: Path) -> int:
    base: list[dict] = []
    for source in (packaged, *extra_packages):
        chunk = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(chunk, list):
            raise ValueError(f"Vendor flow package {source} must be a JSON array")
        base.extend(chunk)
    packaged_by_id = {n["id"]: n for n in base}
    if len(packaged_by_id) != len(base):
        raise ValueError("Duplicated vendor Node-RED IDs")
    if not installed.exists():
        installed.parent.mkdir(parents=True, exist_ok=True)
        installed.write_text(json.dumps(base, ensure_ascii=False, indent=2)+"\n",
                             encoding="utf-8")
        print(f"[INFO] Minimal Node-RED pipeline initialized: {len(base)} nodes")
        return len(base)

    current = json.loads(installed.read_text(encoding="utf-8"))
    if not isinstance(current, list):
        raise ValueError("User flows must be a JSON array")
    before_count=len(current)
    by_id = {n.get("id"): n for n in current if isinstance(n, dict)}
    updated_functions = update_stock_functions(by_id, packaged_by_id)
    updated_bip = update_stock_bip(by_id, packaged_by_id)
    updated_bip_geo = update_stock_bip_geo(by_id, packaged_by_id)
    updated_geo_timeout = upgrade_stock_geo_timeout(by_id, packaged_by_id)
    updated_single_bip = simplify_stock_bip_options(by_id, packaged_by_id)

    # A retired vendor file must not be reimported indefinitely: migrate away
    # its stock nodes, including its Debug, Inject and HTML page. A renamed
    # node or a modified Function is considered user-owned and is preserved.
    manifest_file = Path(__file__).with_name("vendor_cleanup.json")
    cleanup = json.loads(manifest_file.read_text(encoding="utf-8"))
    matching = {n["id"] for n in cleanup if isinstance(by_id.get(n["id"]),dict)
                and _legacy_default(by_id[n["id"]],n)}
    # If a user's custom node links to a retired vendor node, preserve it
    # rather than silently destroying that custom integration.
    user_nodes = [n for n in current if isinstance(n,dict)
                  and n.get("id") not in matching
                  and n.get("id") not in packaged_by_id]
    protected = set()
    for node in user_nodes:
        for targets in node.get("wires",[]):
            if isinstance(targets,list):
                protected.update(k for k in targets if k in matching)
        for target in node.get("links",[]):
            if target in matching:
                protected.add(target)
    matching.difference_update(protected)
    for node_id in sorted(protected):
        print(f"[WARN] Preserving retired vendor node {node_id}: custom/user wiring depends on it")

    new_current = [n for n in current if not isinstance(n,dict)
                   or n.get("id") not in matching]
    changed = bool(updated_functions or updated_bip or updated_bip_geo or updated_geo_timeout or updated_single_bip or matching)

    if matching:
        for node in new_current:
            if not isinstance(node,dict):
                continue
            if isinstance(node.get("wires"),list):
                for output in node["wires"]:
                    if isinstance(output,list):
                        size=len(output)
                        output[:] = [target for target in output if target not in matching]
                        if size!=len(output):
                            changed=True
            if isinstance(node.get("links"),list):
                previous=len(node["links"])
                node["links"][:]=[target for target in node["links"] if target not in matching]
                if previous!=len(node["links"]):
                    changed=True

    by_id={n.get("id"):n for n in new_current if isinstance(n,dict)}
    additions=[n for n in base if n["id"] not in by_id]
    if additions:
        new_current.extend(additions)
        changed=True
    by_id.update({n["id"]: n for n in additions})
    # Only three functional branches remain: BLE events, CRC-validated
    # JK02 0x02 decoder and authenticated internal MQTT publisher.
    edges=(
        ("136f1472850339d1","77930ff9204bec01"),
        ("65ad8ac512b5e001","b150100000000002"),
        ("136f1472850339d1","b200000000000002"),
        ("65ad8ac512b5e001","b200000000000002"),
        ("b150100000000004","b200000000000002"),
    )
    for source,target in edges:
        node=by_id.get(source)
        if not isinstance(node,dict) or target not in packaged_by_id:
            print(f"[WARN] Pipeline source/target missing: {source} -> {target}")
            continue
        wires=node.get("wires")
        if not isinstance(wires,list) or not wires or not isinstance(wires[0],list):
            print(f"[WARN] Modified source wiring {source}, could not link {target}")
            continue
        if target not in wires[0]:
            wires[0].append(target)
            changed=True

    decoder=by_id.get("b150100000000004")
    packaged_decoder=packaged_by_id.get("b150100000000004")
    if isinstance(decoder,dict) and decoder.get("func")==packaged_decoder.get("func"):
        print("[INFO] JK02 decoder intact (CRC, 24S/32S, -200C sentinel checks)")
    else:
        print("[WARN] Custom/legacy JK02 decoder retained. Validate the decoding.")

    if not changed:
        return 0
    timestamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=installed.with_name(installed.name+"."+timestamp+".bak")
    # Preserve distinct backups even when two migrations run in one second.
    suffix=1
    while backup.exists():
        backup=installed.with_name(installed.name+"."+timestamp+f".{suffix}.bak")
        suffix+=1
    shutil.copy2(installed,backup)
    tmp=installed.with_name(installed.name+".new")
    try:
        tmp.write_text(json.dumps(new_current,ensure_ascii=False,indent=2)+"\n",
                       encoding="utf-8")
        os.replace(tmp,installed)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"[INFO] Node-RED cleanup: removed {len(matching)} legacy nodes, "
          f"added {len(additions)}, migrated {updated_functions} stock functions, "
          f"upgraded {updated_bip} old BIP, {updated_bip_geo} geo, "
          f"{updated_geo_timeout} timeout nodes, {updated_single_bip} one-switch BIP nodes; "
          f"{before_count} -> {len(new_current)} nodes; backup {backup.name}")
    return len(additions)


if __name__=="__main__":
    if len(sys.argv)<3:
        print("Usage: merge_flows.py INSTALLED_JSON PACKAGED_JSON [MORE_PACKAGES...]",
              file=sys.stderr)
        sys.exit(2)
    merge(Path(sys.argv[1]), Path(sys.argv[2]),*(Path(p) for p in sys.argv[3:]))
