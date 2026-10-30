"""Regression checks for optional ESPHome Bluetooth Proxy routing.

No actual ESP32 or Home Assistant is required for these tests.
"""
import asyncio
import base64
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

ROOT=Path(__file__).resolve().parents[1] / "smart-jkbms-bluetooth" / "ble"
sys.path.insert(0,str(ROOT))
import proxy


class ProxyOptionsTests(unittest.TestCase):
    def test_local_default_requires_no_proxy_host(self):
        self.assertFalse(proxy.proxy_enabled({}))
        self.assertFalse(proxy.proxy_enabled({"ble_connection_mode":"local"}))
        self.assertEqual(proxy.ble_classes({})[0].__name__,"BleakScanner")

    def test_remote_proxy_settings_and_encryption(self):
        key=base64.b64encode(bytes(range(32))).decode("ascii")
        self.assertEqual(proxy.proxy_config({
            "ble_connection_mode":"esphome_proxy",
            "proxy_host":"192.168.1.100",
            "proxy_noise_psk":key,
        }),{"address":"192.168.1.100","noise_psk":key})
        self.assertEqual(proxy.proxy_config({"proxy_host":"jk-ble.local"})["address"],
                         "jk-ble.local")
        self.assertIsNone(proxy.proxy_config({"proxy_host":"192.168.1.15"})["noise_psk"])
        for host in ("","http://192.168.1.10","1.2.3.4:6053",
                     "127.0.0.999","test/../../secrets","hostname."):
            with self.subTest(host=host),self.assertRaises(ValueError):
                proxy.proxy_config({"proxy_host":host})
        with self.assertRaises(ValueError):
            proxy.proxy_config({"proxy_host":"192.168.1.10","proxy_noise_psk":"not-a-key"})

    def test_select_wrapper_in_proxy_mode_no_local_fallback(self):
        fake=SimpleNamespace(HaBleakScannerWrapper=object(),
                             HaBleakClientWrapper=object())
        with patch.dict(sys.modules,{"habluetooth":fake}):
            self.assertEqual(proxy.ble_classes(
                {"ble_connection_mode":"esphome_proxy"}),(fake.HaBleakScannerWrapper,
                                                          fake.HaBleakClientWrapper))

    def test_proxy_session_starts_and_stops_remote_even_when_wifi_offline(self):
        async def run():
            setup=AsyncMock()
            shutdown=AsyncMock()
            start=AsyncMock(side_effect=asyncio.Event().wait)
            stop=AsyncMock()
            manager=SimpleNamespace(async_setup=setup,async_stop=shutdown)
            remote=SimpleNamespace(start=start,stop=stop)
            hb=SimpleNamespace(BluetoothManager=lambda:manager,
                               set_manager=MagicMock())
            eh=SimpleNamespace(APIConnectionManager=lambda cfg:remote)
            reports=[]
            async def report(event, **kw):
                reports.append((event,kw))
                return True
            cfg={"ble_connection_mode":"esphome_proxy",
                 "proxy_host":"192.168.1.25","proxy_noise_psk":""}
            with patch.dict(sys.modules,{"habluetooth":hb,"bleak_esphome":eh}):
                async with proxy.proxy_session(cfg,report):
                    await asyncio.sleep(.02)
                    setup.assert_awaited_once()
                    start.assert_awaited_once()
                    self.assertEqual(reports[0][0],"proxy_connecting")
                stop.assert_awaited_once()
                shutdown.assert_awaited_once()
        asyncio.run(run())

    def test_remote_scan_uses_esp32_advertisements_without_local_adapter(self):
        async def run():
            import bridge
            mac="C8:47:80:1A:27:12"
            device=SimpleNamespace(name="JK-BMS")
            advert=SimpleNamespace(local_name="JK-BMS",rssi=-48,
                                   service_uuids=["0000ffe0"])
            remote_scan=SimpleNamespace(discover=AsyncMock(
                return_value={mac:(device,advert)}))
            cfg={"ble_connection_mode":"esphome_proxy",
                 "proxy_host":"192.168.1.100",
                 "bluetooth_adapter":"hci3","bms_addresses":mac}
            with patch.object(bridge,"ble_classes",return_value=(remote_scan,object())), \
                 patch.object(bridge,"forward",AsyncMock(return_value=True)), \
                 patch.object(bridge.asyncio,"sleep",AsyncMock()), \
                 patch.object(bridge.BleakScanner,"discover",AsyncMock(
                      side_effect=AssertionError("Local BLE scanner must not run"))):
                devices=await bridge.scan(cfg)
            self.assertIs(devices[mac],device)
            remote_scan.discover.assert_awaited_once_with(return_adv=True)
        asyncio.run(run())

    def test_remote_probe_uses_wrapper_instead_of_local_bluez(self):
        async def run():
            import bridge
            device=object()
            class RemoteClient:
                services=[]
                async def __aenter__(self):
                    return self
                async def __aexit__(self,*args):
                    return False
            factory=MagicMock(return_value=RemoteClient())
            cfg={"ble_connection_mode":"esphome_proxy",
                 "proxy_host":"192.168.1.100","bluetooth_adapter":"hci2"}
            with patch.object(bridge,"ble_classes",return_value=(object(),factory)), \
                 patch.object(bridge,"forward",AsyncMock(return_value=True)), \
                 patch.object(bridge.asyncio,"sleep",AsyncMock()), \
                 patch.object(bridge,"BleakClient",MagicMock(
                     side_effect=AssertionError("BlueZ client must not run"))):
                await bridge.probe("C8:47:80:1A:27:12",cfg,device)
            self.assertIs(factory.call_args.args[0],device)
            self.assertEqual(factory.call_args.kwargs["timeout"],15)
            self.assertNotIn("bluez",factory.call_args.kwargs)
        asyncio.run(run())

    def test_remote_scan_and_probe_choose_proxy_not_bluez(self):
        # Structural safety: the proxy scanner path must never pass hci0/BlueZ
        # arguments; the same probe() GATT code is reused for both transports.
        source=(ROOT/"bridge.py").read_text(encoding="utf-8")
        self.assertIn("ble_classes(cfg)",source)
        self.assertIn("scanner_class.discover(return_adv=True)",source)
        self.assertIn("async with client_class(device",source)
        self.assertIn("if not wanted or proxy_enabled(cfg):",source)
        self.assertIn("if not proxy_enabled(cfg):",source)
        self.assertIn("async with proxy_session(cfg, forward)",source)


if __name__=="__main__":
    unittest.main()
