"""Hybrid BLE regression: explicit local/ESPHome routes, shared MQTT and isolation.

Purely mocked: no BMS writes or real Bluetooth hardware used.
"""
import asyncio
import base64
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

ROOT=Path(__file__).resolve().parents[1]/"smart-jkbms-bluetooth"/"ble"
sys.path.insert(0,str(ROOT))
import bridge
import proxy

A="C8:47:80:1A:1A:EF"
B="C8:47:80:1A:27:12"
C="C8:47:80:1A:30:03"
D="C8:47:80:1A:40:04"

def cfg(**kwargs):
    return {"ble_connection_mode":"hybrid",
            "bms_addresses":",".join((A,B,C,D)),
            "local_bms_addresses":f"{A},{B}",
            "proxy_bms_addresses":f"{C},{D}",
            "proxy_host":"192.168.1.100",
            "proxy_noise_psk":"",
            "scan_interval_seconds":45,
            "persistent_connections":True,
            **kwargs}


class HybridTests(unittest.TestCase):
    def test_four_bms_have_exactly_one_route_case_insensitive(self):
        options=cfg()
        options["local_bms_addresses"]=A.lower()+"; "+B.lower()
        options["proxy_bms_addresses"]=C.lower()+"\n"+D.lower()
        routes=bridge.hybrid_routes(options)
        self.assertEqual(routes["local"],[A,B])
        self.assertEqual(routes["esphome_proxy"],[C,D])
        local=bridge.hybrid_transport_cfg(options,"local")
        remote=bridge.hybrid_transport_cfg(options,"esphome_proxy")
        self.assertEqual(local["ble_connection_mode"],"local")
        self.assertEqual(remote["ble_connection_mode"],"esphome_proxy")
        self.assertEqual(bridge.addresses(local["bms_addresses"]),[A,B])
        self.assertEqual(bridge.addresses(remote["bms_addresses"]),[C,D])
        self.assertEqual(options["bms_addresses"],",".join((A,B,C,D)))

    def test_invalid_or_ambiguous_routing_is_fail_closed(self):
        base=cfg()
        changes=[
            {"local_bms_addresses":A+","+C,"proxy_bms_addresses":C+","+D},
            {"local_bms_addresses":A,"proxy_bms_addresses":C+","+D},
            {"local_bms_addresses":A+","+B,"proxy_bms_addresses":C},
            {"local_bms_addresses":A+","+B+","+D,"proxy_bms_addresses":C+","+D},
            {"local_bms_addresses":A+","+B+","+B,"proxy_bms_addresses":C+","+D},
            {"local_bms_addresses":A+",00:00:00:00:00:0X","proxy_bms_addresses":C+","+D},
            {"local_bms_addresses":"","proxy_bms_addresses":",".join((A,B,C,D))},
            {"local_bms_addresses":",".join((A,B,C,D)),"proxy_bms_addresses":""},
            {"local_bms_addresses":A+","+B,"proxy_bms_addresses":C+","+D,
             "bms_addresses":A+","+B+","+C+","+D+",AA:BB:CC:DD:EE:FF"},
        ]
        for change in changes:
            candidate={**base,**change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                bridge.hybrid_routes(candidate)
        with self.assertRaises(ValueError):
            bridge.hybrid_routes({"ble_connection_mode":"local"})
        with self.assertRaises(ValueError):
            bridge.hybrid_transport_cfg(base,"unknown")

    def test_old_modes_do_not_consult_hybrid_assignments(self):
        self.assertFalse(proxy.proxy_enabled({"ble_connection_mode":"local"}))
        self.assertTrue(proxy.proxy_enabled({"ble_connection_mode":"esphome_proxy"}))
        self.assertTrue(proxy.proxy_enabled({"ble_connection_mode":"hybrid"}))
        self.assertEqual(proxy.ble_classes({"ble_connection_mode":"local"})[0].__name__,
                         "BleakScanner")
        for mode in ("local","esphome_proxy"):
            old={"ble_connection_mode":mode,"bms_addresses":A,
                 "local_bms_addresses":"invalid",
                 "proxy_bms_addresses":"invalid"}
            # Existing modes never run hybrid assignment checks.
            self.assertEqual(bridge.addresses(old["bms_addresses"]),[A])

    def test_hybrid_proxy_session_starts_esp32_api_in_background(self):
        async def run():
            manager=SimpleNamespace(async_setup=AsyncMock(),async_stop=AsyncMock())
            start=AsyncMock(side_effect=asyncio.Event().wait)
            stop=AsyncMock()
            remote=SimpleNamespace(start=start,stop=stop)
            hb=SimpleNamespace(BluetoothManager=lambda:manager,set_manager=MagicMock())
            eh=SimpleNamespace(APIConnectionManager=lambda settings:remote)
            report=AsyncMock(return_value=True)
            with patch.dict(sys.modules,{"habluetooth":hb,"bleak_esphome":eh}):
                async with proxy.proxy_session(cfg(),report):
                    await asyncio.sleep(.03)
                    manager.async_setup.assert_awaited_once()
                    start.assert_awaited_once()
                    self.assertEqual(report.call_args_list[0].args[0],"proxy_connecting")
                stop.assert_awaited_once()
                manager.async_stop.assert_awaited_once()
        asyncio.run(run())

    def test_two_independent_managers_route_each_bms_once(self):
        async def run():
            config=cfg()
            starts=[]
            finishes=[]
            scans=[]
            blz=[]
            async def scan(sub):
                mode=sub["ble_connection_mode"]
                scans.append((mode,tuple(bridge.addresses(sub["bms_addresses"]))))
                # A remote advertisement must NOT be connected via BlueZ and vice versa.
                return {mac:object() for mac in (A,B,C,D)}
            async def cached(sub,wanted):
                # In production BlueZ lookup short-circuits for proxy mode.
                if sub["ble_connection_mode"]=="local":
                    blz.append((sub["ble_connection_mode"],tuple(wanted)))
                return {}
            async def hold(mac,sub,device,*,persistent):
                self.assertTrue(persistent)
                starts.append((mac,sub["ble_connection_mode"]))
                try:
                    await asyncio.Event().wait()
                finally:
                    finishes.append(mac)
            with patch.object(bridge,"options",lambda:config),patch.object(
                bridge,"scan",scan),patch.object(
                bridge,"find_bluez_connected",cached),patch.object(
                bridge,"probe",hold),patch.object(
                bridge,"forward",AsyncMock(return_value=True)):
                tasks=[
                    bridge.persistent_sessions(
                        bridge.hybrid_transport_cfg(config,"local"),hybrid_transport="local"),
                    bridge.persistent_sessions(
                        bridge.hybrid_transport_cfg(config,"esphome_proxy"),
                        hybrid_transport="esphome_proxy")]
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.gather(*tasks),timeout=2.3)
            self.assertEqual(set(starts),
                             {(A,"local"),(B,"local"),(C,"esphome_proxy"),(D,"esphome_proxy")})
            self.assertEqual(len(starts),4)
            self.assertEqual(set(finishes),set((A,B,C,D)))
            self.assertEqual({t for t,_ in scans},{"local","esphome_proxy"})
            self.assertTrue(all(t=="local" for t,_ in blz))
        asyncio.run(run())

    def test_offline_proxy_does_not_prevent_local_bms_session(self):
        async def run():
            config=cfg()
            starts=[]
            async def scan(sub):
                if sub["ble_connection_mode"]=="esphome_proxy":
                    return {}
                return {mac:object() for mac in (A,B,C,D)}
            async def hold(mac,sub,device,*,persistent):
                starts.append(mac)
                await asyncio.Event().wait()
            with patch.object(bridge,"options",lambda:config),patch.object(
                bridge,"scan",scan),patch.object(
                bridge,"find_bluez_connected",AsyncMock(return_value={})),patch.object(
                bridge,"recover_missing_devices",AsyncMock(return_value={})),patch.object(
                bridge,"probe",hold),patch.object(
                bridge,"forward",AsyncMock(return_value=True)):
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.gather(
                        bridge.persistent_sessions(
                            bridge.hybrid_transport_cfg(config,"local"),hybrid_transport="local"),
                        bridge.persistent_sessions(
                            bridge.hybrid_transport_cfg(config,"esphome_proxy"),
                            hybrid_transport="esphome_proxy")),timeout=1.4)
            self.assertEqual(set(starts),{A,B})
        asyncio.run(run())

    def test_run_connections_shares_single_mqtt_publisher(self):
        import mqtt_ha
        async def run():
            config=cfg()
            started=[]
            fake_publisher=SimpleNamespace(
                start=MagicMock(),stop=MagicMock(),watchdog=MagicMock())
            class Publisher:
                def __init__(self,passed_cfg,addresses,control):
                    self.assertion_addresses=addresses
                    self.assertion_config=passed_cfg
                    started.append(("mqtt",tuple(addresses)))
                def start(self,loop):fake_publisher.start(loop)
                def stop(self):fake_publisher.stop()
                def watchdog(self):fake_publisher.watchdog()
            async def session(sub,*,hybrid_transport=None):
                started.append(("session",hybrid_transport,
                                tuple(bridge.addresses(sub["bms_addresses"]))))
                await asyncio.Event().wait()
            fake_control=SimpleNamespace(start=AsyncMock(),close=AsyncMock(),
                                         mqtt_sink=None)
            with patch.object(mqtt_ha,"HomeAssistantMQTT",Publisher),patch.object(
                bridge,"CONTROL",fake_control),patch.object(
                bridge,"persistent_sessions",session):
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(bridge.run_connections(config),timeout=.15)
            self.assertEqual(started.count(("mqtt",(A,B,C,D))),1)
            self.assertIn(("session","local",(A,B)),started)
            self.assertIn(("session","esphome_proxy",(C,D)),started)
            self.assertEqual(len([x for x in started if x[0]=="session"]),2)
            fake_control.start.assert_awaited_once()
            fake_control.close.assert_awaited_once()
            fake_publisher.stop.assert_called_once()
        asyncio.run(run())


if __name__=="__main__":
    unittest.main()
