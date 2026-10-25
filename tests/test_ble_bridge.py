import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
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

    def test_read_only_command_packet(self):
        for cmd in (0x97, 0x96):
            packet = bridge.build_read_command(cmd)
            self.assertEqual(len(packet), 20)
            self.assertEqual(packet[:4], bytes.fromhex("AA 55 90 EB"))
            self.assertEqual(packet[4], cmd)
            self.assertEqual(packet[5:19], bytes(14))
            self.assertEqual(packet[19], sum(packet[:19]) & 255)
        for forbidden in (0x1D, 0x1E, 0x00, 0xA1):
            with self.assertRaises(ValueError):
                bridge.build_read_command(forbidden)

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


    def test_missing_bms_recovery_scans_until_all_devices_found(self):
        a = "C8:47:80:1A:1A:EF"
        b = "C8:47:80:1A:27:12"
        first = object()
        second = object()
        scan = AsyncMock(side_effect=[{}, {a: first}])
        forward = AsyncMock(return_value=True)
        with patch.object(bridge, "scan", scan), patch.object(
            bridge, "forward", forward
        ), patch.object(bridge.asyncio, "sleep", AsyncMock()):
            found = asyncio.run(
                bridge.recover_missing_devices(
                    {"bms_addresses": a + "," + b, "scan_duration_seconds": 8},
                    {b: second},
                    startup=True,
                )
            )
        self.assertIs(found[a], first)
        self.assertIs(found[b], second)
        self.assertEqual(scan.await_count, 2)
        self.assertEqual(
            scan.call_args.kwargs.get("unused"), None
        )
        self.assertEqual(
            scan.call_args.args[0]["scan_duration_seconds"], 15
        )
        names = [x.args[0] for x in forward.call_args_list]
        self.assertIn("recovery_scan_start", names)
        self.assertIn("recovery_scan_result", names)

    def test_skip_reset_without_explicit_adapter(self):
        power_cycle = AsyncMock(return_value=True)
        forward = AsyncMock(return_value=True)
        with patch.object(bridge, "_power_cycle_adapter_dbus", power_cycle), patch.object(
            bridge, "forward", forward
        ):
            result = asyncio.run(
                bridge.maybe_reset_adapter_on_start(
                    {"adapter_reset_on_start": True, "bluetooth_adapter": "auto"}
                )
            )
        self.assertFalse(result)
        power_cycle.assert_not_awaited()
        self.assertEqual(forward.call_args.args[0], "adapter_reset_skipped")

    def test_adapter_reset_is_opt_in(self):
        power_cycle = AsyncMock(return_value=True)
        with tempfile.TemporaryDirectory() as td, patch.object(
            bridge, "RESET_MARKER", Path(td) / "last_reset"
        ), patch.object(bridge, "_power_cycle_adapter_dbus", power_cycle), patch.object(
            bridge, "forward", AsyncMock(return_value=True)
        ):
            self.assertFalse(asyncio.run(bridge.maybe_reset_adapter_on_start({})))
            self.assertTrue(asyncio.run(bridge.maybe_reset_adapter_on_start(
                {"adapter_reset_on_start": True, "bluetooth_adapter": "hci0"}
            )))
            # The opt-in power cycle MUST NOT repeat during an add-on restart.
            self.assertFalse(asyncio.run(bridge.maybe_reset_adapter_on_start(
                {"adapter_reset_on_start": True, "bluetooth_adapter": "hci0"}
            )))
        power_cycle.assert_awaited_once_with("hci0")

    def test_adapter_reset_error_does_not_stop_scanning(self):
        power_cycle = AsyncMock(side_effect=PermissionError("Access denied"))
        forward = AsyncMock(return_value=True)
        with tempfile.TemporaryDirectory() as td, patch.object(
            bridge, "RESET_MARKER", Path(td) / "last_reset"
        ), patch.object(bridge, "_power_cycle_adapter_dbus", power_cycle), patch.object(
            bridge, "forward", forward
        ):
            self.assertFalse(asyncio.run(bridge.maybe_reset_adapter_on_start(
                {"adapter_reset_on_start": True, "bluetooth_adapter": "hci0"}
            )))
        self.assertEqual(forward.call_args.args[0], "adapter_reset_failed")


    def test_healthy_bms_probed_before_missing_device_recovery(self):
        a, b = "C8:47:80:1A:1A:EF", "C8:47:80:1A:27:12"
        healthy = object()
        newly_found = object()
        order = []

        async def scan(cfg):
            order.append("scan")
            return {b: healthy}

        async def probe(address, cfg, device):
            order.append("probe:" + address)
            if address == b:
                self.assertIs(device, healthy)
            if address == a:
                self.assertIs(device, newly_found)

        async def recover(cfg, found, startup):
            order.append("recover")
            self.assertTrue(startup)
            return {**found, a: newly_found}

        with patch.object(bridge, "scan", scan), patch.object(
            bridge, "probe", probe
        ), patch.object(bridge, "recover_missing_devices", recover):
            asyncio.run(bridge.poll_cycle({"bms_addresses": a + "," + b}, startup=True))
        self.assertEqual(order, ["scan", "probe:" + b, "recover", "probe:" + a])


if __name__ == "__main__":
    unittest.main()
