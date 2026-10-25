"""Test migration never deletes a user's Node-RED flow."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGED = ROOT / "smart-jkbms-bluetooth" / "flows.json"
DECODER = ROOT / "smart-jkbms-bluetooth" / "decoder_flows.json"
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

    def test_fresh_install_includes_decoder_flows(self):
        with tempfile.TemporaryDirectory() as td:
            dest=Path(td)/"flows.json"
            expected=len(json.loads(PACKAGED.read_text()))+len(json.loads(DECODER.read_text()))
            self.assertEqual(mod.merge(dest, PACKAGED, DECODER), expected)
            actual=json.loads(dest.read_text())
            self.assertEqual(len(actual),expected)
            self.assertIn("b150100000000004", {n["id"] for n in actual})
            self.assertEqual(mod.merge(dest, PACKAGED, DECODER),0)

    def test_add_decoder_to_existing_installation_without_overwriting_user_nodes(self):
        previous_nodes = json.loads(PACKAGED.read_text())
        decoder_nodes = json.loads(DECODER.read_text())
        custom = {"id":"my_node_custom", "type":"comment", "z":"8b55b11b32e064ac", "name":"Do not overwrite"}
        previous_nodes.append(custom)
        assembler = next(n for n in previous_nodes if n["id"]=="65ad8ac512b5e001")
        assembler["wires"] = [["5524471869b2e0af"],["8d30a20107f452b3"]]
        with tempfile.TemporaryDirectory() as td:
            dst=Path(td)/"flows.json"
            dst.write_text(json.dumps(previous_nodes))
            mod.merge(dst,PACKAGED,DECODER)
            actual=json.loads(dst.read_text())
            self.assertEqual(len(actual),len(previous_nodes)+len(decoder_nodes))
            self.assertEqual(next(n for n in actual if n["id"]=="my_node_custom"),custom)
            changed=next(n for n in actual if n["id"]=="65ad8ac512b5e001")
            self.assertEqual(changed["wires"][0], ["5524471869b2e0af","b150100000000002"])
            self.assertEqual(mod.merge(dst,PACKAGED,DECODER),0)
            self.assertEqual(len(list(Path(td).glob("*.bak"))),1)


if __name__ == "__main__":
    unittest.main()
