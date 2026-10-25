"""Test migration never deletes a user's Node-RED flow."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGED = ROOT / "smart-jkbms-bluetooth" / "flows.json"
SCRIPT = ROOT / "smart-jkbms-bluetooth" / "merge_flows.py"
spec = importlib.util.spec_from_file_location("merge_flows", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class MergeFlowsTests(unittest.TestCase):
    def test_non_destructive_merge_and_idempotence(self):
        all_nodes = json.loads(PACKAGED.read_text())
        new_ids = {"8b55b11b32e064ac", "77930ff9204bec01", "8f9c58b4058b143e", "65ad8ac512b5e001", "5524471869b2e0af", "8d30a20107f452b3", "b1e8a31ca20a9361"}
        old_nodes = [dict(n) for n in all_nodes if n["id"] not in new_ids]
        user_node = {"id": "user_custom_node", "type": "comment", "z": old_nodes[0]["id"], "name": "CUSTOM USER CONTENT"}
        old_nodes.append(user_node)
        health = next(n for n in old_nodes if n["id"] == "136f1472850339d1")
        health["wires"] = [["d4cb3acdbe43f291"]]
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "flows.json"
            dest.write_text(json.dumps(old_nodes))
            mod.merge(dest, PACKAGED)
            upgraded = json.loads(dest.read_text())
            self.assertEqual(len(upgraded), len(all_nodes) + 1)
            self.assertEqual(next(n for n in upgraded if n["id"] == "user_custom_node"), user_node)
            upgraded_health = next(n for n in upgraded if n["id"] == "136f1472850339d1")
            self.assertIn("d4cb3acdbe43f291", upgraded_health["wires"][0])
            self.assertIn("77930ff9204bec01", upgraded_health["wires"][0])
            self.assertEqual(len(list(Path(td).glob("*.bak"))), 1)
            self.assertEqual(mod.merge(dest, PACKAGED), 0)
            self.assertEqual(len(list(Path(td).glob("*.bak"))), 1)


if __name__ == "__main__":
    unittest.main()
