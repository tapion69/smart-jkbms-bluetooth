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
            self.assertEqual(added, 5)
            self.assertIn(user, merged)
            self.assertEqual(len(merged), len(original) + 5)
            self.assertEqual(merge_mod.merge(installed, *base, bip), 0)
            self.assertEqual(len(json.loads(installed.read_text())), len(merged))
            self.assertTrue(list(Path(directory).glob("flows.json.*.bak")))

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
