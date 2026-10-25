import asyncio
import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"smart-jkbms-bluetooth"/"ble"))
from mqtt_ha import HomeAssistantMQTT, enrich, valid_frame, parse_settings, parse_info, short_id
from paho.mqtt.reasoncodes import ReasonCode
from paho.mqtt.packettypes import PacketTypes

A="C8:47:80:1A:1A:EF"
B="C8:47:80:1A:27:12"


class FakeClient:
    def __init__(self):
        self.published=[]
        self.subscribed=[]
        self.on_connect=None
        self.on_disconnect=None
        self.on_message=None
    def publish(self,topic,payload,qos=0,retain=False):
        self.published.append((topic,payload,qos,retain))
    def subscribe(self,topic,qos=0):
        self.subscribed.append(topic)
    def username_pw_set(self,*args):pass
    def reconnect_delay_set(self,*args):pass
    def connect_async(self,*args):pass
    def loop_start(self):pass
    def disconnect(self):pass
    def loop_stop(self):pass


def sample_data(address=A,all_sensors_missing=False):
    voltage=round(sum(3.2+i*.0001 for i in range(16)),3)
    return {"kind":"telemetry","address":address,"data":{
      "address":address,"format":"JK02_32S","source_crc_ok":True,
      "validation":"provisional_compare_with_BatMON",
      "voltage_v":voltage,"current_a":0.0,"soc_pct":21,
      "temperature_quality":"all_unavailable_raw_minus200" if all_sensors_missing else "ok",
      "electrical_data_only":all_sensors_missing,
      "nominal_capacity_ah":314,"cycles":23,"charging_mos":True,
      "discharging_mos":True,"error_mask":0,
      "cells":[{"number":i+1,"voltage_v":3.2+i*.0001} for i in range(16)],
      "temp1_c":None if all_sensors_missing else 16.5,
      "temp2_c":None if all_sensors_missing else 16.5,
      "mos_temp_c":None if all_sensors_missing else 18.5,
    },"extras":{
      "capacity_remaining_ah":67.0,"soh_pct":96,
      "balance_current_a":0.01,"charge_status":"Bulk",
      "temp3_c":None,
      "cell_01_resistance_ohm":0.065,
    }}


def settings_frame():
    f=bytearray(300);f[:5]=bytes.fromhex("55 AA EB 90 01")
    f[10:14]=(2800).to_bytes(4,"little")
    f[18:22]=(3650).to_bytes(4,"little")
    f[138:142]=(3400).to_bytes(4,"little")
    f[50:54]=(100000).to_bytes(4,"little")
    f[62:66]=(150000).to_bytes(4,"little")
    f[282]=0x02
    f[299]=sum(f[:299])&255
    return f.hex()


class MQTTTests(unittest.TestCase):
    def instance(self):
        c=FakeClient()
        cfg={"mqtt_enabled":True,"allow_temperature_control":False}
        m=HomeAssistantMQTT(cfg,[A,B],client=c)
        m.connected=True
        return m,c

    def test_two_distinct_devices_and_temps_availability(self):
        m,c=self.instance()
        self.assertTrue(m.ingest(sample_data(A,True)))
        self.assertTrue(m.ingest(sample_data(B,False)))
        self.assertNotEqual(short_id(A),short_id(B))
        info=[json.loads(p) for t,p,_,_ in c.published if t.endswith("/config")]
        devices={d["device"]["identifiers"][0] for d in info}
        self.assertEqual(devices,{short_id(A),short_id(B)})
        bms1=[json.loads(p) for t,p,_,_ in c.published if t==m.base(A)+"/state"]
        self.assertIsNone(bms1[-1]["temp1_c"])
        self.assertAlmostEqual(bms1[-1]["cell_16_v"],3.2015,places=4)
        self.assertEqual(bms1[-1]["capacity_remaining_ah"],67.0)
        self.assertEqual(bms1[-1]["soc_pct"],21)
        self.assertIn((m.base(A)+"/temperature/temp1_c/availability","offline",1,True),c.published)
        self.assertIn((m.base(B)+"/temperature/temp1_c/availability","online",1,True),c.published)
        self.assertFalse(any("3276" in payload or "-200.0" in payload for _,payload,_,_ in c.published))
        for d in info:
            self.assertTrue(d["unique_id"].startswith(d["device"]["identifiers"][0]))
        self.assertEqual(len(info),len(set(d["unique_id"] for d in info)))

    def test_rejects_unverified_or_wrong_pack(self):
        m,c=self.instance()
        bad=sample_data()
        bad["data"]["validation"]="unverified"
        self.assertFalse(m.ingest(bad))
        bad=sample_data()
        bad["data"]["voltage_v"]=20
        self.assertFalse(m.ingest(bad))
        bad=sample_data()
        bad["address"]="AA:BB:CC:DD:EE:FF"
        self.assertFalse(m.ingest(bad))
        self.assertFalse(any(t.endswith("/state") for t,_,_,_ in c.published))

    def test_read_only_settings_frame_and_switch_truthful(self):
        m,c=self.instance()
        m.ingest(sample_data(A))
        frame=settings_frame()
        self.assertTrue(m.ingest({"kind":"frame","address":A,
           "frame_type":1,"raw_hex":frame}))
        self.assertIn((m.base(A)+"/temperature_control/state","ON",1,True),c.published)
        self.assertEqual(m.settings[A]["cell_ovp_v"],3.65)
        self.assertEqual(m.settings[A]["cell_uvp_v"],2.8)
        self.assertEqual(m.settings[A]["temperature_monitoring_disabled"],True)
        self.assertFalse(m.ingest({"kind":"frame","address":B,
           "frame_type":1,"raw_hex":"00"*300}))
        self.assertNotIn(B,m.settings)
        c.published.clear()
        m.discover(A,16)
        sw=[json.loads(p) for t,p,_,_ in c.published
          if t.endswith("disable_temperature_sensors/config")]
        self.assertEqual(len(sw),1)
        self.assertEqual(sw[0]["optimistic"],False)
        self.assertEqual(sw[0]["payload_on"],"ON")
        self.assertEqual(sw[0]["payload_off"],"OFF")
        self.assertIn("command_topic",sw[0])
        self.assertEqual(sw[0]["availability_mode"],"all")

    def test_device_info_never_publishes_passwords(self):
        m,c=self.instance()
        f=bytearray(300);f[:5]=bytes.fromhex("55 AA EB 90 03")
        f[6:6+3]=b"JK-";f[22:25]=b"2.0";f[30:35]=b"19.0a"
        f[62:71]=b"SECRETPIN"
        f[118:128]=b"SETUP_PASS"
        f[184]=2;f[218]=7;f[185]=4
        f[299]=sum(f[:299])&255
        self.assertTrue(m.ingest({"kind":"frame","frame_type":3,"address":A,
          "raw_hex":f.hex()}))
        m.ingest(sample_data(A))
        all_payload=" ".join(x[1] for x in c.published)
        self.assertNotIn("SECRETPIN",all_payload)
        self.assertNotIn("SETUP_PASS",all_payload)
        self.assertIn("19.0a",all_payload)

    def test_real_paho_v2_reason_code_connect_publishes_discovery(self):
        # Regression for v0.2.0: int(ReasonCode) raised TypeError and the
        # on_connect callback died before publishing any HA devices.
        accepted=ReasonCode(PacketTypes.CONNACK,"Success")
        with self.assertRaises(TypeError):
            int(accepted)
        m,c=self.instance()
        m.connected=False
        m.on_connect(c,None,None,accepted,None)
        self.assertTrue(m.connected)
        cfg=[(topic,json.loads(payload)) for topic,payload,_,_ in c.published
             if topic.endswith("/config")]
        self.assertGreater(len(cfg),100)
        self.assertEqual(
            {body["device"]["identifiers"][0] for _,body in cfg},
            {short_id(A),short_id(B)}
        )
        self.assertIn("homeassistant/status",c.subscribed)
        self.assertTrue(all(retained for topic,_,_,retained in c.published
                            if topic.endswith("/config")))
        refused=ReasonCode(PacketTypes.CONNACK,"Bad User Name or Password")
        c.published.clear()
        m.on_connect(c,None,None,refused,None)
        self.assertFalse(m.connected)
        self.assertFalse(c.published,"No discovery on rejected credentials")

    def test_broker_connection_failure_is_visible_not_a_crash(self):
        m,c=self.instance()
        self.assertTrue(callable(c.on_connect_fail))
        with self.assertLogs("smart_jkbms_ble.mqtt",level="WARNING") as logs:
            c.on_connect_fail(c,None)
        self.assertTrue(any("MQTT transport connection failed" in line
                            for line in logs.output))

    def test_reconnect_availability_and_retained_discovery(self):
        m,c=self.instance()
        m.on_connect(c,None,None,0,None)
        config=[item for item in c.published if item[0].endswith("/config")]
        self.assertGreater(len(config),100)
        self.assertTrue(all(item[3] for item in config))
        self.assertIn("homeassistant/status",c.subscribed)
        self.assertEqual(sum(1 for x in c.subscribed if x.endswith("/temperature_control/set")),2)
        c.published.clear()
        m.ingest(sample_data(A))
        self.assertIn((m.base(A)+"/availability","online",1,True),c.published)
        m.ingest({"kind":"lifecycle","address":A,"event":"disconnected"})
        self.assertIn((m.base(A)+"/availability","offline",1,True),c.published)

    def test_mqtt_protection_requires_optin_and_30s_arm(self):
        async def run():
            m,c=self.instance()
            m.loop=asyncio.get_running_loop()
            m.control=SimpleNamespace(dispatch=AsyncMock(return_value=(202,{"verified_by_bms":False})))
            def publish(topic,text):
                m.on_message(c,None,SimpleNamespace(topic=topic,payload=text))
            set_topic=m.base(A)+"/temperature_control/set"
            arm_topic=m.base(A)+"/temperature_control/arm"
            publish(set_topic,b"ON")
            await asyncio.sleep(0.02)
            m.control.dispatch.assert_not_awaited()
            m.cfg["allow_temperature_control"]=True
            publish(set_topic,b"ON")
            await asyncio.sleep(0.02)
            m.control.dispatch.assert_not_awaited()
            publish(arm_topic,b"PRESS")
            publish(set_topic,b"ON")
            await asyncio.sleep(0.05)
            m.control.dispatch.assert_awaited_once()
            args=m.control.dispatch.await_args.args[0]
            self.assertEqual(args["address"],A)
            self.assertTrue(args["disable"])
            m.control.dispatch.reset_mock()
            publish(set_topic,b"OFF")
            await asyncio.sleep(0.02)
            m.control.dispatch.assert_not_awaited()
            self.assertFalse(any(t.endswith("temperature_control/state") for t,_,_,_ in c.published))
        asyncio.run(run())


if __name__=="__main__":
    unittest.main()
