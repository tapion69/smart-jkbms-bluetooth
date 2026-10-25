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
        self.assertTrue(m.settings[A]["disable_temperature_sensors"])
        self.assertEqual(m.full_state(A)["cell_ovp_v"],3.65)
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
        self.assertEqual(sw[0]["entity_category"],"config")

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

    def test_v023_additional_jk02_telemetry_and_binary_contacts(self):
        m,c=self.instance()
        d=sample_data()
        d["extras"].update({
          "dry_contact_mask":0x06,
          "dry1_contact":True,
          "dry2_contact":True,
          "heating_current_a":1.234,
          "emergency_time_countdown_s":90,
          "emergency_active":True,
          "smart_sleep_countdown_s":7200,
          "charge_status_time_s":45,
          "detail_log_count":29,
          "battery_type":"LiFePO4",
          "battery_type_id":0,
          "total_runtime_formatted":"0j 01h 16m",
          "discharge_ocp_release_s":7,
          "charge_ocp_release_s":9,
          "overvoltage_release_s":12,
          "balancing_active":True,
          "charger_connected":True,
          "pcl_module_active":False,
        })
        self.assertTrue(m.ingest(d))
        state=json.loads([p for t,p,_,_ in c.published
                          if t==m.base(A)+"/state"][-1])
        for key,value in (
            ("dry1_contact",True),("dry2_contact",True),
            ("heating_current_a",1.234),("emergency_time_countdown_s",90),
            ("smart_sleep_countdown_s",7200),("charge_status_time_s",45),
            ("battery_type","LiFePO4"),("detail_log_count",29),
            ("discharge_ocp_release_s",7),("overvoltage_release_s",12),
            ("total_runtime_formatted","0j 01h 16m"),
            ("charger_connected",True),
        ):
            self.assertEqual(state.get(key),value,key)
        conf={topic:json.loads(value) for topic,value,_,_
              in c.published if topic.endswith("/config") and value}
        base=m.discovery+"/"+ "binary_sensor/"+short_id(A)+"_"
        self.assertNotIn("pcl_module_active",state)
        self.assertNotIn("dry_contact_mask",state)
        self.assertEqual(conf[base+"dry1_contact/config"]["name"],"DRY1 contact")
        self.assertEqual(conf[base+"dry2_contact/config"]["name"],"DRY2 contact")
        self.assertEqual(conf[base+"online_status/config"]["state_topic"],
                         m.base(A)+"/availability")
        self.assertNotIn("availability_topic",conf[base+"online_status/config"])
        self.assertEqual(conf[m.discovery+"/sensor/"+short_id(A)+
                               "_heating_current_a/config"]["unit_of_measurement"],"A")

    def test_v023_device_information_readonly_and_no_passcode_leak(self):
        m,c=self.instance()
        f=bytearray(300);f[:5]=bytes.fromhex("55 AA EB 90 03")
        f[6:17]=b"JK_PB2A16S1"
        f[22:26]=b"14XA";f[30:35]=b"19.0b"
        f[38:42]=(3600).to_bytes(4,"little")
        f[42:46]=(93).to_bytes(4,"little")
        f[46:55]=b"Batterie1"
        f[62:72]=b"TOPSECRET!"
        f[78:84]=b"231118"
        f[86:97]=b"30925721340"
        f[102:113]=b"PRIVATEUSER"
        f[118:128]=b"ADMIN_PASS"
        f[184]=2;f[185]=4;f[218]=7;f[219]=1
        f[234]=3;f[235]=4;f[236]=5;f[237]=6
        f[262:266]=(30).to_bytes(4,"little")
        f[266]=12;f[267]=8;f[268]=2;f[270]=3
        f[299]=sum(f[:299])&255
        parsed=parse_info(bytes(f))
        self.assertEqual(parsed["device_model"],"JK_PB2A16S1")
        self.assertEqual(parsed["power_on_count"],93)
        self.assertEqual(parsed["manufacturing_date"],"2023-11-18")
        self.assertEqual(parsed["uart3_protocol"],3)
        self.assertEqual(parsed["dry1_trigger_id"],4)
        self.assertEqual(parsed["dry2_trigger_id"],5)
        self.assertEqual(parsed["rcv_time_h"],1.2)
        self.assertEqual(parsed["rfv_time_h"],0.8)
        self.assertEqual(parsed["serial_number"],"30925721340")
        self.assertTrue(m.ingest({"kind":"frame","frame_type":3,
                                  "address":A,"raw_hex":f.hex()}))
        self.assertTrue(m.ingest(sample_data(A)))
        state=json.loads([p for t,p,_,_ in c.published
                          if t==m.base(A)+"/state"][-1])
        self.assertEqual(state["device_name"],"Batterie1")
        self.assertEqual(state["power_on_count"],93)
        self.assertEqual(state["uart2_enabled"],True)
        self.assertEqual(m.info[A]["lcd_buzzer_trigger_id"],3)
        self.assertNotIn("lcd_buzzer_trigger_id",state)
        all_public=" ".join(str(x[1]) for x in c.published)
        for secret in ("TOPSECRET!","PRIVATEUSER","ADMIN_PASS"):
            self.assertNotIn(secret,all_public)
        discovery=[json.loads(value) for topic,value,_,_ in c.published
                   if topic.endswith("/config") and value]
        self.assertFalse(any(
            "command_topic" in row and
            any(k in row.get("unique_id","") for k in
                ("uart3_protocol","dry1_trigger_id","dry2_trigger_id"))
            for row in discovery
        ))

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
             if topic.endswith("/config") and payload]
        self.assertGreater(len(cfg),100)
        self.assertEqual(
            {body["device"]["identifiers"][0] for _,body in cfg},
            {short_id(A),short_id(B)}
        )
        self.assertIn("homeassistant/status",c.subscribed)
        self.assertTrue(all(retained for topic,_,_,retained in c.published
                            if topic.endswith("/config")))
        refused=ReasonCode(PacketTypes.CONNACK,"Bad user name or password")
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

    def test_mqtt_parameters_permission_switch_no_timeout_and_readback_only(self):
        async def run():
            m,c=self.instance()
            m.loop=asyncio.get_running_loop()
            m.control=SimpleNamespace(dispatch=AsyncMock(return_value=(202,{"verified_by_bms":False})))
            m.ingest(sample_data(A))
            m.ingest({"kind":"frame","address":A,
                      "frame_type":1,"raw_hex":settings_frame()})
            def send(topic,payload,retain=False):
                m.on_message(c,None,SimpleNamespace(topic=topic,payload=payload,retain=retain))
            gate=m.base(A)+"/write_permission/set"
            setting=m.base(A)+"/parameters/cell_uvp_v/set"
            send(setting,b"2.8")
            await asyncio.sleep(0.02)
            m.control.dispatch.assert_not_awaited()
            # Add-on opt-in must be enabled as well as the explicit per-BMS HA switch.
            send(gate,b"ON")
            self.assertFalse(m.permission[A])
            m.cfg["allow_temperature_control"]=True
            send(gate,b"ON",retain=True)
            self.assertFalse(m.permission[A])
            send(gate,b"ON")
            self.assertTrue(m.permission[A])
            self.assertFalse(m.permission[B])
            # No 30-second countdown: remaining ON until OFF/disconnect/restart.
            m.last_data[A]=time.monotonic()
            send(setting,b"2.8")
            await asyncio.sleep(0.05)
            m.control.dispatch.assert_awaited_once()
            cmd=m.control.dispatch.await_args.args[0]
            self.assertEqual(cmd["register"],0x02)
            self.assertEqual(cmd["value"],2.8)
            self.assertEqual(cmd["address"],A)
            self.assertEqual(m.full_state(A)["cell_uvp_v"],2.8)
            # Sending command does not make an unverified state change.
            self.assertFalse(any(
              json.loads(payload).get("cell_uvp_v")==2.9
              for topic,payload,_,_ in c.published
              if topic==m.base(A)+"/state"))
            m.control.dispatch.reset_mock()
            send(gate,b"OFF")
            send(setting,b"2.9")
            await asyncio.sleep(0.02)
            m.control.dispatch.assert_not_awaited()
            m.permission[A]=True
            m.ingest({"kind":"lifecycle","address":A,"event":"disconnected"})
            self.assertFalse(m.permission[A])
        asyncio.run(run())

    def test_v024_prune_duplicates_raw_masks_and_retained_entities(self):
        from mqtt_ha import RETIRED_SENSOR_KEYS, RETIRED_BINARY_KEYS
        from parameters import BY_KEY
        m,c=self.instance()
        m.on_connect(c,None,None,0,None)
        for mac in (A,B):
            root=m.discovery+"/sensor/"+short_id(mac)+"_"
            for key in ("nominal_capacity_ah","cell_count",
                        "cell_wire_warning_mask","temperature_sensor_absent_mask",
                        "error_mask_hex","controls_hex","battery_type_id",
                        "charge_status_id","dry_contact_mask","uart1_protocol",
                        "uart3_protocol","balance_action","vendor_id"):
                self.assertIn(key,RETIRED_SENSOR_KEYS)
                self.assertIn((root+key+"/config","",1,True),c.published,
                              "Obsolete HA retained discovery not deleted: "+key)
            self.assertIn("balancing_active",RETIRED_BINARY_KEYS)
            self.assertIn(
                (m.discovery+"/binary_sensor/"+short_id(mac)+
                 "_balancing_active/config","",1,True),c.published)
        m.ingest(sample_data(A))
        payload=json.loads([p for t,p,_,_ in c.published
                            if t==m.base(A)+"/state"][-1])
        for removed_key in ("nominal_capacity_ah","cell_count",
                            "error_mask_hex","cell_wire_warning_mask",
                            "temperature_sensor_absent_mask","controls_hex",
                            "battery_type_id","balance_action","format",
                            "uart1_protocol","vendor_id"):
            self.assertNotIn(removed_key,payload)
        for key in ("voltage_v","current_a","soc_pct","cell_01_v",
                    "cell_16_v","cell_delta_v","cell_min_number","cell_max_number"):
            self.assertIn(key,payload)
        # The number entity alone owns its setting, no read-only clone sensor.
        config={t:json.loads(p) for t,p,_,_ in c.published
                if t.endswith("/config") and p}
        self.assertIn(m.discovery+"/number/"+short_id(A)+
                      "_cell_uvp_v/config",config)
        self.assertNotIn(m.discovery+"/sensor/"+short_id(A)+
                         "_cell_uvp_v/config",config)
        self.assertEqual(len({x["unique_id"] for x in config.values()}),len(config))

    def test_precision_names_and_volts_delta_discovery(self):
        m,c=self.instance()
        m.discover(A,16)
        conf={topic:json.loads(value) for topic,value,_,_
              in c.published if topic.endswith("/config") and value}
        prefix=m.discovery
        ident=short_id(A)
        def item(component,key):
            return conf[f"{prefix}/{component}/{ident}_{key}/config"]
        self.assertEqual(item("sensor","cell_01_v")["name"],"Cell_1_volt")
        self.assertEqual(item("sensor","cell_01_v")["suggested_display_precision"],3)
        self.assertEqual(item("sensor","cell_16_v")["suggested_display_precision"],3)
        self.assertEqual(item("sensor","cell_01_resistance_ohm")["name"],"Cell_1_ohm")
        self.assertEqual(item("sensor","voltage_v")["name"],"Tension_Totale_volt")
        self.assertEqual(item("sensor","voltage_v")["suggested_display_precision"],1)
        self.assertEqual(item("sensor","cell_delta_v")["unit_of_measurement"],"V")
        self.assertEqual(item("sensor","cell_delta_v")["suggested_display_precision"],3)
        self.assertEqual(item("number","cell_uvp_v")["mode"],"box")
        self.assertEqual(item("number","cell_uvp_v")["entity_category"],"config")
        self.assertEqual(item("switch","balancer_enabled")["entity_category"],"config")
        self.assertNotIn(f"{prefix}/button/{ident}_arm_temperature_control/config",conf)
        self.assertNotIn(f"{prefix}/sensor/{ident}_cell_delta_mv/config",conf)
        self.assertFalse(item("switch","write_permission")["optimistic"])


if __name__=="__main__":
    unittest.main()
