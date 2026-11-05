"""JK02_32S Set SOC: guarded per-BMS MQTT command and live readback."""
import asyncio
import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smart-jkbms-bluetooth" / "ble"))
from control import ControlService, SOC_CONFIRM, soc_calibration_frame
from mqtt_ha import HomeAssistantMQTT, short_id

MACS = [
    "C8:47:80:1A:1A:EF",
    "C8:47:80:1A:27:12",
    "C8:47:80:1A:30:03",
    "C8:47:80:1A:40:04",
]


class FakeClient:
    def __init__(self):
        self.published=[]
        self.subscribed=[]
    def publish(self,topic,payload,qos=0,retain=False):
        self.published.append((topic,payload,qos,retain))
    def subscribe(self,topic,qos=0):
        self.subscribed.append(topic)


def instance():
    client=FakeClient()
    cfg={"mqtt_enabled":True,"allow_parameter_changes":True}
    manager=HomeAssistantMQTT(cfg,MACS,client=client)
    manager.connected=True
    for mac in MACS:
        manager.info[mac]={"software_version":"15.34","device_model":"JK_PB2A16S15P"}
        manager.info_confirmed.add(mac)
        manager.state[mac]={"format":"JK02_32S","soc_pct":15}
        manager.last_data[mac]=time.monotonic()
        manager.permission[mac]=True
    return manager,client


class SocCalibrationTests(unittest.TestCase):
    def test_packet_is_one_byte_with_correct_checksum(self):
        for soc in (0,14,100):
            p=soc_calibration_frame(soc)
            self.assertEqual(len(p),20)
            self.assertEqual(p[:6],bytes.fromhex("AA 55 90 EB 6E 01"))
            self.assertEqual(p[6],soc)
            self.assertEqual(p[7:19],bytes(12))
            self.assertEqual(p[19],sum(p[:19])&255)
        for invalid in (True,False,14.0,-1,101,None,"14"):
            with self.assertRaises(ValueError):
                soc_calibration_frame(invalid)

    def test_four_bms_discover_independent_numbers_without_changing_soc_sensor(self):
        m,c=instance()
        for mac in MACS:
            m.discover(mac,16)
            identity=short_id(mac)
            topic=f"homeassistant/number/{identity}_soc_calibration/config"
            rows=[json.loads(v) for t,v,_,_ in c.published if t==topic and v]
            self.assertEqual(len(rows),1)
            row=rows[0]
            self.assertEqual(row["name"],"Set SOC")
            self.assertEqual(row["min"],0)
            self.assertEqual(row["max"],100)
            self.assertEqual(row["step"],1)
            self.assertFalse(row["optimistic"])
            self.assertFalse(row["retain"])
            self.assertEqual(row["command_topic"],m.base(mac)+"/soc_calibration/set")
            self.assertEqual(row["value_template"],"{{ value_json.get('soc_pct') }}")
            self.assertTrue(any(t.endswith(f"/sensor/{identity}_soc_pct/config") for t,_,_,_ in c.published))
        m.on_connect(None,None,None,0)
        for mac in MACS:
            self.assertIn(m.base(mac)+"/soc_calibration/set",c.subscribed)

    def test_incompatible_or_unconfirmed_firmware_hides_entity_and_blocks_command(self):
        m,c=instance()
        a=MACS[0]
        cases=[
            ("JK02_24S","15.34",True),
            ("JK02_32S","10.20",True),
            ("JK02_32S","bogus",True),
            ("JK02_32S","15.34",False),
        ]
        for proto,sw,confirmed in cases:
            m.state[a]["format"]=proto
            m.info[a]["software_version"]=sw
            if confirmed:m.info_confirmed.add(a)
            else:m.info_confirmed.discard(a)
            self.assertFalse(m.soc_calibration_supported(a))
            m.discover(a,16)
            self.assertIn(
                (f"homeassistant/number/{short_id(a)}_soc_calibration/config","",1,True),
                c.published)
        m.state[a]["format"]="JK02_32S"
        m.info[a]["software_version"]="15.34"
        m.info_confirmed.add(a)
        m.last_data[a]=time.monotonic()-100
        self.assertFalse(m.soc_calibration_supported(a))

    def test_local_endpoint_requires_both_permissions_and_explicit_confirmation(self):
        async def run():
            m,_=instance()
            cfg={"bms_addresses":",".join(MACS),"allow_parameter_changes":False}
            service=ControlService(lambda:cfg,lambda s:[x.strip() for x in s.split(",")])
            service.mqtt_sink=m
            queue=service.register(MACS[0])
            req={"address":MACS[0],"action":"set_soc","value":14,
                 "confirmation":SOC_CONFIRM}
            self.assertEqual((await service.dispatch(req))[0],403)
            cfg["allow_parameter_changes"]=True
            m.permission[MACS[0]]=False
            self.assertEqual((await service.dispatch(req))[0],403)
            m.permission[MACS[0]]=True
            for bad in (
                {**req,"confirmation":"NO"},
                {**req,"value":14.5},
                {**req,"value":True},
                {**req,"value":101},
                {**req,"address":"AA:BB:CC:DD:EE:FF"},
            ):
                self.assertIn((await service.dispatch(bad))[0],(400,403))
            async def receive():
                cmd=await asyncio.wait_for(queue.get(),2)
                self.assertEqual(cmd.action,"set_soc")
                self.assertEqual(cmd.value,14)
                cmd.future.set_result({"register":"0x6E"})
            task=asyncio.create_task(receive())
            status,result=await service.dispatch(req)
            await task
            self.assertEqual(status,202)
            self.assertTrue(result["write_sent"])
            self.assertFalse(result["verified_by_bms"])
            self.assertEqual((await service.dispatch({**req,"value":13}))[0],429)
            service.unregister(MACS[0])
        asyncio.run(run())

    def test_mqtt_set_soc_15_to_14_confirmed_only_after_live_telemetry(self):
        async def run():
            m,c=instance()
            class Dispatcher:
                def __init__(self):self.calls=[]
                async def dispatch(self,payload):
                    self.calls.append(payload)
                    return 202,{"register":"0x6E"}
            m.control=Dispatcher()
            m.loop=asyncio.get_running_loop()
            a=MACS[0]
            m._soc_calibration_command(a,b"14")
            m._soc_calibration_command(a,b"14")  # must not duplicate a pending write
            await asyncio.sleep(.15)
            self.assertEqual(len(m.control.calls),1)
            self.assertEqual(m.state[a]["soc_pct"],15)
            self.assertIn(a,m.pending_parameter_writes)
            m.state[a]["soc_pct"]=14
            m.last_data[a]=time.monotonic()
            await asyncio.sleep(.5)
            self.assertNotIn(a,m.pending_parameter_writes)
            self.assertTrue(any(t==m.base(a)+"/command_status" and
                                "confirmé par télémétrie" in v for t,v,_,_ in c.published))
            self.assertEqual(m.state[MACS[1]]["soc_pct"],15)
        asyncio.run(run())

    def test_no_unauthorized_or_retained_mqtt_write(self):
        m,c=instance()
        a=MACS[0]
        m.permission[a]=False
        m._soc_calibration_command(a,b"14")
        self.assertEqual(m.state[a]["soc_pct"],15)
        self.assertFalse(m.pending_parameter_writes)
        m.permission[a]=True
        m._soc_calibration_command(a,b"14.5")
        self.assertFalse(m.pending_parameter_writes)
        m.on_message(None,None,SimpleNamespace(
            topic=m.base(a)+"/soc_calibration/set",payload=b"14",retain=True))
        self.assertFalse(m.pending_parameter_writes)


if __name__=="__main__":
    unittest.main()
