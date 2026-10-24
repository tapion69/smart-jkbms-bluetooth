import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

PATH = Path(__file__).resolve().parents[1] / "smart-jkbms-bluetooth" / "ble" / "bridge.py"
spec = importlib.util.spec_from_file_location("smart_jkbms_bridge", PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class BleTests(unittest.TestCase):
    def test_addresses_normalized(self):
        self.assertEqual(
            bridge.addresses("c8:47:80:1a:27:12, C8:47:80:1A:27:12,foo"),
            ["C8:47:80:1A:27:12"],
        )

    def test_scan_returns_original_ble_device(self):
        mac = "C8:47:80:1A:27:12"
        device = SimpleNamespace(name="Batterie 2-02")
        adv = SimpleNamespace(local_name="Batterie 2-02", rssi=-38, service_uuids=["0000ffe0"])
        with patch.object(bridge.BleakScanner, "discover", AsyncMock(return_value={mac: (device, adv)})), patch.object(
            bridge, "forward", AsyncMock(return_value=True)
        ):
            devices = asyncio.run(bridge.scan({"scan_duration_seconds": 8, "bms_addresses": mac}))
        self.assertIs(devices[mac], device)

    def test_connect_uses_ble_device_object(self):
        device = object()
        class FakeClient:
            services = []
            async def __aenter__(self):
                return self
            async def __aexit__(self, typ, val, tb):
                return False
        factory = Mock(return_value=FakeClient())
        with patch.object(bridge, "BleakClient", factory), patch.object(
            bridge, "forward", AsyncMock(return_value=True)
        ), patch.object(bridge.asyncio, "sleep", AsyncMock()):
            asyncio.run(bridge.probe("C8:47:80:1A:27:12", {}, device))
        self.assertIs(factory.call_args.args[0], device)

if __name__ == "__main__":
    unittest.main()
