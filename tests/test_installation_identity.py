"""Regression checks for anonymous installation identity persistence."""
import importlib.util
import tempfile
import unittest
import uuid
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1]
          / "smart-jkbms-bluetooth" / "ble" / "installation_id.py")
spec = importlib.util.spec_from_file_location("smart_jkbms_install_id", SOURCE)
installation_id = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installation_id)


class InstallationIdentityTests(unittest.TestCase):
    def test_persistent_id_remains_stable_across_restart_and_bms_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smart_jkbms_install_id"
            original = installation_id.get_install_id(path)
            self.assertEqual(uuid.UUID(original).version, 4)
            self.assertEqual(installation_id.get_install_id(path), original)
            self.assertEqual(path.read_text().strip(), original)

    def test_two_installations_have_distinct_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            a = installation_id.get_install_id(Path(directory) / "a" / "id")
            b = installation_id.get_install_id(Path(directory) / "b" / "id")
            self.assertNotEqual(a, b)

    def test_corrupt_stored_id_is_not_regenerated_silently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "id"
            path.write_text("not-a-uuid\n")
            with self.assertRaises(ValueError):
                installation_id.get_install_id(path)
            self.assertEqual(path.read_text(), "not-a-uuid\n")


if __name__ == "__main__":
    unittest.main()
