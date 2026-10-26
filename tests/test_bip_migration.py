"""Ensure optional BIP packaging cannot overwrite other Node-RED flows."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "smart-jkbms-bluetooth"
spec = importlib.util.spec_from_file_location("jk_merge", ROOT / "merge_flows.py")
merge_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge_mod)


class BipFlowMigrationTests(unittest.TestCase):
    def test_add_bip_to_existing_install_and_preserve_user_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / "flows.json"
            base = [ROOT / name for name in
                    ("flows.json", "decoder_flows.json", "mqtt_flows.json")]
            bip = ROOT / "bip_flows.json"
            merge_mod.merge(installed, *base)
            original = json.loads(installed.read_text(encoding="utf-8"))
            user = {"id": "user_custom_diagnostics", "type": "function",
                    "z": "my_tab", "name": "User-owned custom node",
                    "func": "return msg;", "wires": [[]]}
            original.append(user)
            installed.write_text(json.dumps(original), encoding="utf-8")
            added = merge_mod.merge(installed, *base, bip)
            merged = json.loads(installed.read_text(encoding="utf-8"))
            self.assertEqual(added, 13)
            self.assertIn(user, merged)
            self.assertEqual(len(merged), len(original) + 13)
            self.assertEqual(merge_mod.merge(installed, *base, bip), 0)
            self.assertEqual(len(json.loads(installed.read_text())), len(merged))
            self.assertTrue(list(Path(directory).glob("flows.json.*.bak")))

    def test_v032_stock_bip_repaired_without_losing_attached_debug(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / "flows.json"
            packages = [ROOT / name for name in
                        ("flows.json", "decoder_flows.json", "mqtt_flows.json",
                         "bip_flows.json")]
            old = json.loads((Path(__file__).resolve().parent / "fixtures"
                             / "bip_v032.json").read_text(encoding="utf-8"))
            reporter = next(n for n in old if n.get("id")=="jkbms_bip_report_0301")
            reporter["wires"][0].append("custom_debug_user")
            old.append({"id": "custom_debug_user", "type": "debug",
                        "z": "jkbms_bip_tab_0301", "name": "my debug",
                        "wires": []})
            installed.write_text(json.dumps(old), encoding="utf-8")
            added = merge_mod.merge(installed, *packages)
            current = json.loads(installed.read_text(encoding="utf-8"))
            by_id = {n["id"]: n for n in current}
            self.assertGreater(added, 0)
            self.assertEqual(by_id["jkbms_bip_http_0301"]["method"],"POST")
            self.assertTrue(by_id["jkbms_bip_http_0301"]["url"].startswith(
                "https://script.google.com/macros/s/"))
            self.assertEqual(by_id["jkbms_bip_http_0301"]["wires"][0],
                             ["jkbms_bip_redirect_0303"])
            self.assertEqual(by_id["jkbms_bip_prepare_0301"]["wires"][0],
                             ["jkbms_bip_environment_0303"])
            self.assertIn("custom_debug_user",
                          by_id["jkbms_bip_report_0301"]["wires"][0])
            self.assertIn("created", by_id["jkbms_bip_report_0301"]["func"])
            self.assertEqual(merge_mod.merge(installed, *packages),0)
            second = json.loads(installed.read_text(encoding="utf-8"))
            self.assertEqual(current,second)
            self.assertTrue(list(Path(directory).glob("flows.json.*.bak")))

    def test_user_edited_bip_function_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / "flows.json"
            old = json.loads((Path(__file__).resolve().parent / "fixtures"
                             / "bip_v032.json").read_text(encoding="utf-8"))
            gate = next(n for n in old if n["id"]=="jkbms_bip_prepare_0301")
            gate["func"]="return null; // user customization"
            installed.write_text(json.dumps(old),encoding="utf-8")
            packages = [ROOT / name for name in
                        ("flows.json", "decoder_flows.json", "mqtt_flows.json",
                         "bip_flows.json")]
            merge_mod.merge(installed,*packages)
            current = {n["id"]:n for n in json.loads(installed.read_text())}
            self.assertEqual(current["jkbms_bip_prepare_0301"]["func"],
                             "return null; // user customization")
            self.assertEqual(current["jkbms_bip_prepare_0301"]["wires"],
                             gate["wires"])

    def test_v033_geo_upgrade_keeps_original_install_and_custom_debug(self):
        with tempfile.TemporaryDirectory() as directory:
            installed=Path(directory) / "flows.json"
            previous=json.loads((Path(__file__).resolve().parent / "fixtures"
                                 / "bip_v033.json").read_text(encoding="utf-8"))
            by_id={n["id"]:n for n in previous}
            analysis=by_id["jkbms_bip_environment_0303"]
            analysis["wires"][0].append("my_debug")
            previous.append({"id":"my_debug", "type":"debug",
                             "z":"jkbms_bip_tab_0301", "name":"Custom debug",
                             "wires":[]})
            installed.write_text(json.dumps(previous),encoding="utf-8")
            packages=[ROOT / name for name in
                      ("flows.json","decoder_flows.json","mqtt_flows.json",
                       "bip_flows.json")]
            added=merge_mod.merge(installed,*packages)
            merged=json.loads(installed.read_text(encoding="utf-8"))
            result={n["id"]:n for n in merged}
            self.assertGreaterEqual(added,4)
            self.assertEqual(result["jkbms_bip_environment_0303"]["wires"][0],
                             ["jkbms_bip_geo_gate_0304","my_debug"])
            self.assertIn("geo.country",
                          result["jkbms_bip_payload_0303"]["func"])
            self.assertIn("my_debug",result)
            self.assertEqual(merge_mod.merge(installed,*packages),0)
            self.assertEqual(merged,json.loads(installed.read_text()))
            self.assertTrue(list(Path(directory).glob("flows.json.*.bak")))

    def test_v033_custom_geo_prepare_remains_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            installed=Path(directory) / "flows.json"
            previous=json.loads((Path(__file__).resolve().parent / "fixtures"
                                 / "bip_v033.json").read_text(encoding="utf-8"))
            fn=next(n for n in previous if n["id"]=="jkbms_bip_payload_0303")
            fn["func"]="return msg; // custom Google payload"
            installed.write_text(json.dumps(previous),encoding="utf-8")
            packages=[ROOT / name for name in
                      ("flows.json","decoder_flows.json","mqtt_flows.json",
                       "bip_flows.json")]
            merge_mod.merge(installed,*packages)
            result={n["id"]:n for n in json.loads(installed.read_text())}
            self.assertEqual(result["jkbms_bip_payload_0303"]["func"],fn["func"])

    def test_separate_bip_tab_and_no_ble_pipeline_wires(self):
        nodes = json.loads((ROOT / "bip_flows.json").read_text(encoding="utf-8"))
        self.assertEqual(len({n["id"] for n in nodes}), len(nodes))
        tabs = [n for n in nodes if n["type"] == "tab"]
        self.assertEqual(len(tabs), 1)
        all_ids = {n["id"] for n in nodes}
        self.assertTrue(all(target in all_ids
                            for node in nodes for wires in node.get("wires", [])
                            for target in wires))
        self.assertNotIn("b200000000000002", all_ids)


if __name__ == "__main__":
    unittest.main()
