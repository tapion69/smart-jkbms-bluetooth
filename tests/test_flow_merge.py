"""Minimal JK-BMS BLE Node-RED packaging and non-destructive upgrades."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PKG=ROOT/"smart-jkbms-bluetooth"
PACKAGED=(PKG/"flows.json",PKG/"decoder_flows.json",PKG/"mqtt_flows.json")
spec=importlib.util.spec_from_file_location("merge_flows",PKG/"merge_flows.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def stock():
    return [dict(node) for p in PACKAGED for node in json.loads(p.read_text())]


class FlowMigrationTests(unittest.TestCase):
    def test_installed_legacy_mqtt_forwarders_receive_safe_upgrade(self):
        fixtures=json.loads((ROOT/"tests"/"fixtures"/"legacy_mqtt_forwarders.json").read_text())
        canonical=next(n for n in stock() if n["id"]=="b200000000000002")
        for fixture in fixtures:
            with self.subTest(ref=fixture["ref"]):
                arr=stock()
                current=next(n for n in arr if n["id"]=="b200000000000002")
                current["func"]=fixture["node"]["func"]
                with tempfile.TemporaryDirectory() as td:
                    file=Path(td)/"flows.json"
                    file.write_text(json.dumps(arr))
                    mod.merge(file,*PACKAGED)
                    nodes={n["id"]:n for n in json.loads(file.read_text())}
                    self.assertEqual(nodes[current["id"]]["func"],canonical["func"])
                    self.assertEqual(len(list(Path(td).glob("*.bak"))),1)
                    self.assertEqual(mod.merge(file,*PACKAGED),0)

    def test_custom_mqtt_forwarder_never_overwritten(self):
        arr=stock()
        current=next(n for n in arr if n["id"]=="b200000000000002")
        current["func"]+="\n// owner modification"
        expected=current["func"]
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"flows.json"
            file.write_text(json.dumps(arr))
            self.assertEqual(mod.merge(file,*PACKAGED),0)
            found=next(n for n in json.loads(file.read_text()) if n["id"]==current["id"])
            self.assertEqual(found["func"],expected)

    def test_fresh_install_has_only_essential_nodes(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"flows.json"
            count=mod.merge(file,*PACKAGED)
            arr=json.loads(file.read_text())
            ids={node["id"] for node in arr}
            self.assertEqual(count,len(arr))
            self.assertFalse(any(n["type"] in ("debug","inject","template","file in")
                                 for n in arr))
            self.assertEqual(len(ids),len(arr))
            self.assertEqual(mod.merge(file,*PACKAGED),0)
            self.assertIn("b150100000000002",
                          next(n for n in arr if n["id"]=="65ad8ac512b5e001")["wires"][0])
            self.assertTrue({"136f1472850339d1","65ad8ac512b5e001",
                             "b150100000000004","b200000000000002"}.issubset(ids))

    def test_retired_debug_and_html_are_removed_on_upgrade(self):
        arr=stock()
        manifest=json.loads((PKG/"vendor_cleanup.json").read_text())
        ids=["f5500ba6100a0002","b111a90000000004",
             "b161600000000002","b161600000000011"]
        for key in ids:
            legacy=next(n for n in manifest if n["id"]==key)
            arr.append({"id":key,"type":legacy["type"],"name":legacy["name"],
                        "z":"b150100000000001","active":True,"wires":[]})
        assembler=next(n for n in arr if n["id"]=="65ad8ac512b5e001")
        assembler["wires"][0]+=["b111a90000000004","b161600000000002"]
        user={"id":"my_own_flow","name":"User flow","type":"function",
              "func":"return msg;","wires":[[]],"z":"b150100000000001"}
        arr.append(user)
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"flows.json"
            file.write_text(json.dumps(arr))
            mod.merge(file,*PACKAGED)
            actual={n["id"]:n for n in json.loads(file.read_text())}
            self.assertEqual(actual[user["id"]],user)
            self.assertTrue(all(id not in actual for id in ids))
            self.assertTrue(all(id not in actual["65ad8ac512b5e001"]["wires"][0]
                                for id in ids))
            self.assertEqual(len(list(Path(td).glob("*.bak"))),1)
            self.assertEqual(mod.merge(file,*PACKAGED),0)

    def test_user_renamed_or_customized_vendor_nodes_are_preserved(self):
        arr=stock()
        # An owner-renamed debug is now user-owned and will not be deleted.
        arr.append({"id":"f5500ba6100a0002","type":"debug",
                    "name":"My own diagnostic","active":True,"wires":[]})
        # A stock function with a user edit is not silently removed.
        arr.append({"id":"f5500ba6100a0001","type":"function",
                    "name":"Résumé lisible (10s / BMS)",
                    "func":"return msg; // MY MODIFIED FUNCTION","wires":[[]]})
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"flows.json"
            file.write_text(json.dumps(arr))
            mod.merge(file,*PACKAGED)
            actual={n["id"]:n for n in json.loads(file.read_text())}
            self.assertEqual(actual["f5500ba6100a0002"]["name"],"My own diagnostic")
            self.assertEqual(actual["f5500ba6100a0001"]["func"],
                             "return msg; // MY MODIFIED FUNCTION")
            self.assertEqual(mod.merge(file,*PACKAGED),0)

    def test_user_wiring_to_old_vendor_node_protects_that_node(self):
        arr=stock()
        legacy=next(n for n in json.loads((PKG/"vendor_cleanup.json").read_text())
                    if n["id"]=="b111a90000000004")
        arr.append({"id":legacy["id"],"type":legacy["type"],"name":legacy["name"]})
        arr.append({"id":"my_link","type":"function","name":"My custom flow",
                    "func":"return msg;","wires":[[legacy["id"]]]})
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/"flows.json"
            f.write_text(json.dumps(arr))
            mod.merge(f,*PACKAGED)
            self.assertIn(legacy["id"],{n["id"] for n in json.loads(f.read_text())})

    def test_runtime_no_longer_loads_legacy_debug_html_packages(self):
        script=(PKG/"run.sh").read_text()
        for obsolete in ("summary_flows.json","health_flows.json",
                "short_diagnostics_flows.json","raw_temperature_flows.json",
                "temperature_switch_flows.json","temperature_control_flows.json"):
            self.assertNotIn(obsolete,script)
        self.assertNotIn("httpNodeMiddleware",(PKG/"settings.js").read_text())
        self.assertNotIn("jk-bms/temperature",
                         json.dumps(stock()))
        self.assertIn("mqtt_flows.json",script)


if __name__=="__main__":
    unittest.main()
