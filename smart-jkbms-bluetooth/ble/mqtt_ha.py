"""Home Assistant MQTT Discovery for verified JK02 BLE data.

All updates are fed by Node-RED's CRC-valid frame and validated decoder.
No BMS passwords or credentials are ever published.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt
from parameters import PARAMS, BY_KEY, read_settings, build_write
from presentation import (INFO_NAMES, INFO_BINARY_NAMES, MAIN_NAMES,
                          CONFIG_STATUS_NAMES, sensor_name, binary_name,
                          cell_voltage_name, cell_resistance_name)

LOG = logging.getLogger("smart_jkbms_ble.mqtt")
VALID_MAC = re.compile(r"^(?:[A-F0-9]{2}:){5}[A-F0-9]{2}$")
ALARM_NAMES = {
    0:"Wire resistance",1:"MOS overtemperature",2:"Cell count mismatch",
    4:"Battery fully charged",5:"Pack overvoltage",6:"Charge overcurrent",
    7:"Charge short circuit",8:"Charge overtemperature",9:"Charge undertemperature",
    10:"Coprocessor communication",11:"Cell undervoltage",12:"Pack undervoltage",
    13:"Discharge overcurrent",14:"Discharge short circuit",15:"Discharge overtemperature",
    16:"Charging MOS abnormal",17:"Discharging MOS abnormal",18:"GPS disconnected",
    19:"Password change",20:"Discharge on failed",21:"Battery overtemperature",
    22:"Temperature sensor anomaly",23:"PL module anomaly",24:"SCP release failed",
    25:"Discharge OCP II",26:"Discharge OCP III",27:"Discharge undertemperature",
    28:"GPS remote lock",
}
# Key, label, unit, device_class, state_class, entity_category.
MEASURES = [
 ("voltage_v","Total Voltage","V","voltage","measurement",None),
 ("current_a","Total Current","A","current","measurement",None),
 ("power_w","Total Power","W","power","measurement",None),
 ("charge_power_w","Charge Power","W","power","measurement",None),
 ("discharge_power_w","Discharge Power","W","power","measurement",None),
 ("soc_pct","SOC","%","battery","measurement",None),
 ("soh_pct","SOH","%",None,"measurement",None),
 ("cell_min_v","Min Cell Voltage","V","voltage","measurement",None),
 ("cell_max_v","Max Cell Voltage","V","voltage","measurement",None),
 ("cell_avg_v","Average Cell Voltage","V","voltage","measurement",None),
 ("cell_delta_mv","Cell Voltage Difference","mV",None,"measurement",None),
 ("balance_current_a","Balance Current","A","current","measurement",None),
 ("balance_state","Balancing State",None,None,None,None),
 ("capacity_remaining_ah","Remaining Capacity","Ah",None,"measurement",None),
 ("total_cycle_capacity_ah","Total Cycled Capacity","Ah",None,None,None),
 ("cycles","Cycle Count",None,None,"total_increasing",None),
 ("temp1_c","Temperature Sensor 1","°C","temperature","measurement",None),
 ("temp2_c","Temperature Sensor 2","°C","temperature","measurement",None),
 ("mos_temp_c","MOS Temperature","°C","temperature","measurement",None),
 ("temp3_c","Temperature Sensor 3","°C","temperature","measurement",None),
 ("temp4_c","Temperature Sensor 4","°C","temperature","measurement",None),
 ("temp5_c","Temperature Sensor 5","°C","temperature","measurement",None),
 ("alarm_text","BMS Alarm List",None,None,None,"diagnostic"),
 ("charge_status","Charge Status",None,None,None,None),
 ("hardware_version","Hardware Version",None,None,None,"diagnostic"),
 ("software_version","Software Version",None,None,None,"diagnostic"),
 ("device_model","BMS Model",None,None,None,"diagnostic"),
 ("device_name","BMS Name",None,None,None,"diagnostic"),
 ("manufacturing_date","Manufacturing Date",None,None,None,"diagnostic"),
 ("serial_number","Serial Number",None,None,None,"diagnostic"),
 ("power_on_count","Power-On Count",None,None,"total_increasing",None),
 ("rcv_time_h","RCV Time","h","duration","measurement",None),
 ("rfv_time_h","RFV Time","h","duration","measurement",None),
 ("battery_type","Battery Type",None,None,None,"diagnostic"),
 ("heating_current_a","Heating Current","A","current","measurement",None),
 ("smart_sleep_countdown_s","Smart Sleep Countdown","s","duration","measurement",None),
 ("emergency_time_countdown_s","Emergency Countdown","s","duration","measurement",None),
 ("charge_status_time_s","Charge Status Duration","s","duration","measurement",None),
 ("detail_log_count","Detail Log Count",None,None,None,None),
 ("total_runtime_formatted","Total Runtime",None,None,None,None),
 ("discharge_ocp_release_s","Discharge OCP Recovery","s","duration","measurement",None),
 ("discharge_short_release_s","Discharge Short Recovery","s","duration","measurement",None),
 ("charge_ocp_release_s","Charge OCP Recovery","s","duration","measurement",None),
 ("charge_short_release_s","Charge Short Recovery","s","duration","measurement",None),
 ("undervoltage_release_s","Undervoltage Recovery","s","duration","measurement",None),
 ("overvoltage_release_s","Overvoltage Recovery","s","duration","measurement",None),
]
BINARY_MEASURES=[
 ("charging_mos","Charge MOS Active"),
 ("discharging_mos","Discharge MOS Active"),
 ("precharge","Precharge Active"),
 ("heating","Heating Active"),
 ("alarm_active","BMS Alarm Active"),
 ("dry1_contact","DRY1 Contact"),
 ("dry2_contact","DRY2 Contact"),
 ("emergency_active","Emergency Active"),
 ("charger_connected","Charger Connected"),
 ("balancing_active","Balancing Active"),
 ("pcl_module_active","PCL Module Active"),
]

# Explicit tombstones for retained discovery published by previous versions.
RETIRED_SENSOR_KEYS = [
    "nominal_capacity_ah",
    "cell_count",
    "total_runtime_h",
    "error_count",
    "error_mask_hex",
    "temperature_quality",
    "format",
    "cell_wire_warning_mask",
    "temperature_sensor_absent_mask",
    "balance_action",
    "controls_hex",
    "cell_uvp_v",
    "cell_ovp_v",
    "balance_start_v",
    "max_charge_current_a",
    "max_discharge_current_a",
    "vendor_id",
    "device_uptime_h",
    "uart1_protocol",
    "uart2_protocol",
    "can_protocol",
    "uart3_protocol",
    "lcd_buzzer_trigger_id",
    "dry1_trigger_id",
    "dry2_trigger_id",
    "uart_protocol_library_version",
    "can_protocol_library_version",
    "data_stored_period",
    "battery_type_id",
    "charge_status_id",
    "dry_contact_mask",
    "cell_delta_mv"
]
RETIRED_BINARY_KEYS = ["balancing_active","pcl_module_active"]

# Discovery of optional diagnostic fields is deferred until their source
# actually reports a value. Missing 0x03 information is not an HA sensor
# stuck at Unknown forever.
ALWAYS_SENSOR_KEYS = {
 "voltage_v","current_a","power_w","charge_power_w","discharge_power_w",
 "soc_pct","capacity_remaining_ah","cell_min_v","cell_max_v","cell_avg_v",
 "balance_current_a","cycles","soh_pct","temp1_c","temp2_c","mos_temp_c",
}
ALWAYS_BINARY_KEYS = {"charging_mos","discharging_mos","alarm_active"}
SETTINGS_RESPONSE_TIMEOUT = 8.0  # seconds, configurable only in unit tests



def short_id(mac: str) -> str:
    return "jk_ble_"+mac.lower().replace(":","")


def numeric(value: Any, lower: float=-1e8, upper: float=1e8) -> float | None:
    if type(value) not in (int,float) or not math.isfinite(value) or not lower<=value<=upper:
        return None
    return value


def valid_frame(raw: Any, frame_type: int) -> bytes | None:
    if not isinstance(raw,str) or len(raw)!=600:
        return None
    try: data=bytes.fromhex(raw)
    except ValueError: return None
    if len(data)!=300 or data[:4]!=bytes.fromhex("55 AA EB 90") or data[4]!=frame_type:
        return None
    if sum(data[:299])&255!=data[299]:
        return None
    return data


def temperature(raw: bytes, pos: int) -> float | None:
    val=int.from_bytes(raw[pos:pos+2],"little",signed=True)/10
    return round(val,1) if -80<=val<=160 else None


def parse_settings(raw: bytes) -> dict[str, Any]:
    # Fail closed for layout mismatch; returns no assumed settings if no frame.
    cfg=read_settings(raw)
    uvp=cfg.get("cell_uvp_v");ovp=cfg.get("cell_ovp_v")
    if uvp is None or ovp is None or uvp>=ovp:
        return {}
    return cfg


def parse_info(raw: bytes) -> dict[str, Any]:
    # Type 0x03, 300 bytes, CRC checked upstream by valid_frame().
    # Never extract or publish passcode [62:78], user data [102:118],
    # setup passcode [118:134], nor any arbitrary string beyond allowlist.
    def ascii_field(pos: int, length: int) -> str | None:
        value=raw[pos:pos+length].split(b"\x00",1)[0]
        if not value or any(x<32 or x>126 for x in value):
            return None
        return value.decode("ascii").strip()[:32] or None

    result={
      "vendor_id":ascii_field(6,16),
      "device_model":ascii_field(6,16),
      "hardware_version":ascii_field(22,8),
      "software_version":ascii_field(30,8),
      "device_uptime_h":round(int.from_bytes(raw[38:42],"little")/3600,2),
      "power_on_count":int.from_bytes(raw[42:46],"little"),
      "device_name":ascii_field(46,16),
      "uart1_protocol":raw[184],
      "can_protocol":raw[185],
      "uart2_protocol":raw[218],
      "uart2_enabled":bool(raw[219]),
      "lcd_buzzer_trigger_id":raw[234],
      "dry1_trigger_id":raw[235],
      "dry2_trigger_id":raw[236],
      "uart_protocol_library_version":raw[237],
      "can_protocol_library_version":raw[268],
      "data_stored_period":int.from_bytes(raw[262:266],"little"),
      "rcv_time_h":round(raw[266]/10,1),
      "rfv_time_h":round(raw[267]/10,1),
      # UART3 is reported at byte 270 by the JK02 decoder in syssi;
      # expose the numeric ID, never send protocol writes automatically.
      "uart3_protocol":raw[270] if raw[270] != 255 else None,
    }
    date=ascii_field(78,8)
    if date and len(date)==6 and date.isascii() and date.isdigit():
        yy,mm,dd=int(date[:2]),int(date[2:4]),int(date[4:6])
        if 1<=mm<=12 and 1<=dd<=31:
            result["manufacturing_date"]=f"20{yy:02d}-{mm:02d}-{dd:02d}"
    # Read-only hardware serial; never include the adjacent access passcodes.
    result["serial_number"]=ascii_field(86,11)
    return result


def enrich(d: dict[str,Any], extras: dict[str,Any]) -> dict[str,Any] | None:
    # Checks have already passed the Node-RED JK02 decoder. Check again at
    # the MQTT boundary: fail closed for invalid/accidental messages.
    if d.get("validation")!="provisional_compare_with_BatMON" or d.get("source_crc_ok") is not True:
        return None
    fmt=d.get("format")
    if fmt not in ("JK02_24S","JK02_32S"):
        return None
    v=numeric(d.get("voltage_v"),5,170);soc=numeric(d.get("soc_pct"),0,100)
    current=numeric(d.get("current_a"),-3000,3000)
    cells=d.get("cells")
    if v is None or soc is None or current is None or not isinstance(cells,list) or not 4<=len(cells)<=32:
        return None
    readings=[]
    for idx, cell in enumerate(cells,1):
        if not isinstance(cell,dict) or cell.get("number")!=idx:
            return None
        value=numeric(cell.get("voltage_v"),1.5,4.5)
        if value is None:return None
        readings.append(value)
    if abs(sum(readings)-v)>max(1.5,v*0.04):
        return None
    out={
     "voltage_v":v,"current_a":current,"power_w":round(v*current,1),
     "charge_power_w":round(max(0,v*current),1),
     "discharge_power_w":round(max(0,-v*current),1),
     "soc_pct":int(soc),"cell_count":len(readings),
     "cell_min_v":min(readings),"cell_max_v":max(readings),
     "cell_min_number":readings.index(min(readings))+1,
     "cell_max_number":readings.index(max(readings))+1,
     "cell_avg_v":round(sum(readings)/len(readings),3),
     "cell_delta_mv":round((max(readings)-min(readings))*1000),
     "cell_delta_v":round(max(readings)-min(readings),3),
     "format":fmt,"temperature_quality":str(d.get("temperature_quality") or "unknown"),
    }
    for k in ("nominal_capacity_ah","cycles","error_mask","charging_mos",
              "discharging_mos","temperature_sensor_absent_mask"):
        if k in d:out[k]=d[k]
    for k in ("temp1_c","temp2_c","mos_temp_c"):
        value=d.get(k)
        out[k]=numeric(value,-80,160) if value is not None else None
    if d.get("electrical_data_only") is True:
        for k in ("temp1_c","temp2_c","mos_temp_c"):out[k]=None
    for i,voltage in enumerate(readings,1):
        out[f"cell_{i:02d}_v"]=voltage
    if fmt=="JK02_32S":
        for k in ("capacity_remaining_ah","soh_pct","balance_current_a",
                  "total_cycle_capacity_ah","total_runtime_h","balance_state",
                  "balance_action","cell_wire_warning_mask","charge_status"):
            val=extras.get(k)
            if val is not None:out[k]=val
        for k in ("precharge","heating","temp3_c","temp4_c","temp5_c"):
            val=extras.get(k)
            if val is not None:out[k]=val
        # All additional telemetry is sourced from the same sequence-matched
        # type-0x02 CRC-checked frame; never copy arbitrary caller fields.
        for k in ("dry1_contact","dry2_contact","emergency_active",
                  "balancing_active","charger_connected","pcl_module_active"):
            if type(extras.get(k)) is bool:
                out[k]=extras[k]
        for k,low,high in (
            ("heating_current_a",-300,300),
            ("emergency_time_countdown_s",0,65535),
            ("smart_sleep_countdown_s",0,4294967295),
            ("charge_status_time_s",0,65535),
            ("detail_log_count",0,4294967295),
            ("discharge_ocp_release_s",0,65535),
            ("discharge_short_release_s",0,65535),
            ("charge_ocp_release_s",0,65535),
            ("charge_short_release_s",0,65535),
            ("undervoltage_release_s",0,65535),
            ("overvoltage_release_s",0,65535),
        ):
            val=numeric(extras.get(k),low,high)
            if val is not None:out[k]=val
        for k in ("battery_type","total_runtime_formatted"):
            val=extras.get(k)
            if isinstance(val,str) and 0<len(val)<=40:
                out[k]=val
        for idx in range(1,len(readings)+1):
            resistance=extras.get(f"cell_{idx:02d}_resistance_ohm")
            if resistance is not None:out[f"cell_{idx:02d}_resistance_ohm"]=resistance
    mask=d.get("error_mask")
    if type(mask) is int and 0<=mask<=0xFFFFFFFF:
        # Bit 4 means "fully charged" in JK02 and is informational.
        alarms=[label for bit,label in ALARM_NAMES.items()
                if bit!=4 and mask&(1<<bit)]
        out["error_count"]=len(alarms)
        out["alarm_active"]=bool(alarms)
        out["alarm_text"]=", ".join(alarms) if alarms else "No alarms"
        out["error_mask_hex"]=f"0x{mask:08X}"
    return out


def runtime_from_validated_frame(raw:bytes,format_name:str)->dict[str,Any]:
    # syssi JK02 BLE and BatMON both decode uptime as uint32 seconds:
    # offset 162 on JK02_24S, 194 on JK02_32S (+32).
    offset={"JK02_24S":162,"JK02_32S":194}.get(format_name)
    if offset is None or len(raw)!=300 or raw[4]!=2:
        return {}
    seconds=int.from_bytes(raw[offset:offset+4],"little")
    days,remainder=divmod(seconds,86400)
    hours,remainder=divmod(remainder,3600)
    minutes=remainder//60
    return {
        "total_runtime_s":seconds,
        "total_runtime_formatted":f"{days}j {hours:02d}h {minutes:02d}m",
    }



class HomeAssistantMQTT:
    def __init__(self,cfg:dict[str,Any],addresses:list[str],control:Any=None,
                 client:Any=None) -> None:
        self.cfg=cfg
        self.addresses=addresses
        self.control=control
        self.prefix=str(cfg.get("mqtt_topic_prefix") or "smart_jkbms_ble").strip().strip("/")
        self.discovery=str(cfg.get("mqtt_discovery_prefix") or "homeassistant").strip().strip("/")
        # Distinct installations sharing one MQTT broker must not collide.
        instance_suffix=hashlib.sha256(",".join(addresses).encode("ascii")).hexdigest()[:12]
        self.client=client or mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                 client_id="smart-jkbms-"+instance_suffix)
        self.client.on_connect=self.on_connect
        self.client.on_disconnect=self.on_disconnect
        self.client.on_connect_fail=self.on_connect_fail
        self.client.on_message=self.on_message
        self.enabled=bool(cfg.get("mqtt_enabled",True))
        self.connected=False
        self._lock=threading.RLock()
        self.last_data:dict[str,float]={}
        self.state:dict[str,dict[str,Any]]={}
        self.settings:dict[str,dict[str,Any]]={}
        self.info:dict[str,dict[str,Any]]={}
        self.last_type1:dict[str,bytes]={}
        self.last_type3:dict[str,bytes]={}
        self.last_confirmed:dict[str,float]={}
        self.discovered_cells:dict[str,int]={}
        self.discovered_readable:dict[str,set[str]]={mac:set() for mac in addresses}
        self.last_telemetry_frame:dict[str,tuple[float,bytes]]={}
        self.last_telemetry_sequence:dict[str,int]={}
        self.permission:dict[str,bool]={mac:False for mac in addresses}
        self.command_pending:dict[str,float]={}
        self.pending_parameter_writes:set[str]=set()
        # Suppress duplicate MQTT commands while a write is running or soon
        # after a verified readback. No unverified writes count as success.
        self.pending_parameter_value:dict[str,tuple[str,bool|float]]={}
        self.recent_confirmed_parameter:dict[str,tuple[str,bool|float,float]]={}
        self.last_settings_frame:dict[str,float]={}
        self.settings_frame_rejected:dict[str,int]={}
        self.loop:asyncio.AbstractEventLoop|None=None
        self.last_mqtt_error=0.0
        self.online_cache:dict[str,bool]={}

    def base(self,mac:str)->str:
        return f"{self.prefix}/{short_id(mac)}"

    def send(self,topic:str,payload:Any,*,retain:bool=True)->None:
        if not self.connected:return
        value=json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False) \
            if isinstance(payload,(dict,list)) else str(payload)
        self.client.publish(topic,value,qos=1,retain=retain)

    def emit(self,mac:str,key:str,payload:Any,*,retain:bool=True)->None:
        self.send(f"{self.base(mac)}/{key}",payload,retain=retain)

    def on_connect(self,client,userdata,flags,reason_code,properties=None):
        # Paho MQTT 2.x returns a ReasonCode object, not an int; int(...) raises
        # TypeError and prevents HA discovery completely.
        with self._lock:
            self.connected = reason_code == 0
            if not self.connected:
                LOG.warning("MQTT broker refused connection: %s (check credentials/ACL)",
                            reason_code)
                return
            LOG.info("MQTT broker connected. Publishing HA Discovery for %d configured BMS: %s",
                     len(self.addresses), ", ".join(self.addresses) or "(none configured)")
            self.client.subscribe("homeassistant/status",qos=1)
            for mac in self.addresses:
                base=self.base(mac)
                self.client.subscribe(f"{base}/temperature_control/set",qos=1)
                self.client.subscribe(f"{base}/write_permission/set",qos=1)
                self.client.subscribe(f"{base}/parameters/+/set",qos=1)
            # The permission is intentionally non-persistent across reconnect.
            for mac in self.addresses:self.permission[mac]=False
            self.rediscover()
            LOG.info("MQTT Discovery published for %d BMS (%s/#)",
                     len(self.addresses),self.discovery)

    def on_connect_fail(self,client,userdata):
        # Called by loop_start() when a network connection cannot be established.
        now=time.monotonic()
        if now-self.last_mqtt_error>=30 or self.last_mqtt_error==0:
            self.last_mqtt_error=now
            LOG.warning("MQTT transport connection failed to %s:%s "
                        "(check Mosquitto is running, add-on network and DNS)",
                        self.cfg.get("mqtt_host","core-mosquitto"),
                        self.cfg.get("mqtt_port",1883))

    def on_disconnect(self,client,userdata,disconnect_flags,reason_code,properties=None):
        with self._lock:
            self.connected=False
            LOG.warning("MQTT disconnected: %s",reason_code)

    def on_message(self,client,userdata,msg):
        with self._lock:
            if msg.topic=="homeassistant/status" and msg.payload==b"online":
                self.rediscover()
                return
            # Retained command topics must NEVER re-apply protection settings
            # or re-enable write permission after a broker reconnect.
            if getattr(msg,"retain",False):
                return
            for mac in self.addresses:
                base=self.base(mac)
                if msg.topic==f"{base}/write_permission/set":
                    allow=(msg.payload==b"ON") and bool(self.cfg.get("allow_parameter_changes",False))
                    self.permission[mac]=allow
                    self.emit(mac,"write_permission/state","ON" if allow else "OFF")
                    self.emit(mac,"command_status",
                        "Modification des paramètres autorisée" if allow else
                        "Modification des paramètres verrouillée")
                    return
                if msg.topic==f"{base}/temperature_control/set":
                    self._parameter_command(mac,"disable_temperature_sensors",msg.payload)
                    return
                marker=f"{base}/parameters/"
                if msg.topic.startswith(marker) and msg.topic.endswith("/set"):
                    key=msg.topic[len(marker):-4]
                    self._parameter_command(mac,key,msg.payload)
                    return

    def _parameter_command(self,mac:str,key:str,payload:bytes)->None:
        p=BY_KEY.get(key)
        if p is None:return
        if not self.cfg.get("allow_parameter_changes",False) or not self.permission.get(mac,False):
            self.emit(mac,"command_status","Refus : autoriser d'abord la modification des paramètres")
            return
        if self.last_data.get(mac,0)<=0 or time.monotonic()-self.last_data[mac]>70:
            self.emit(mac,"command_status","Refus : pas de mesures BMS récentes")
            return
        if self.loop is None or self.control is None:
            self.emit(mac,"command_status","Refus : liaison BLE indisponible")
            return
        try:
            if p.kind=="switch":
                if payload not in (b"ON",b"OFF"):return
                value=payload==b"ON"
            else:
                value=float(payload.decode("ascii"))
            build_write(p.reg,value)  # Strong, typed allowlist check, no writes yet
        except (ValueError,UnicodeDecodeError,OverflowError):
            self.emit(mac,"command_status","Refus : valeur invalide pour "+key)
            return
        # A repeated HA/MQTT command must not replace the last successful
        # status or cause a second BLE write. Distinct values are not merged.
        target=(key,value)
        if mac in self.pending_parameter_writes:
            if self.pending_parameter_value.get(mac)==target:
                LOG.info("Ignoring identical in-flight JK-BMS command for %s (%s)",mac,key)
                return
            self.emit(mac,"command_status","Commande déjà en cours pour ce BMS")
            return
        prior=self.recent_confirmed_parameter.get(mac)
        if prior is not None and prior[0:2]==target and time.monotonic()-prior[2]<15:
            current=self.settings.get(mac,{}).get(key)
            matches=(current==value if p.kind=="switch" else
                     type(current) in (int,float) and
                     abs(current-value)<=max(1e-5,p.step/2))
            if matches:
                LOG.info("Ignoring identical already-confirmed JK-BMS command for %s (%s)",mac,key)
                return
        self.pending_parameter_writes.add(mac)
        self.pending_parameter_value[mac]=target

        async def confirmed_readback_after(since:float, seconds:float)->bool:
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                with self._lock:
                    if self.last_confirmed.get(mac,0)>since:
                        return True
                    if not self.permission.get(mac,False):
                        return False
                await asyncio.sleep(0.25)
            return False

        async def perform()->None:
            from control import CONFIRM
            try:
                # Never write from cached/stale configuration. The BMS normally
                # sends type-0x01 only after a request; trigger a fresh read if
                # the last verified configuration is older than one minute.
                with self._lock:
                    age=time.monotonic()-self.last_confirmed.get(mac,0)
                if age>60 or mac not in self.settings:
                    with self._lock:
                        self.emit(mac,"command_status",
                                  "Lecture des paramètres BMS (0x96) avant modification…")
                    since=time.monotonic()
                    rejected_before=self.settings_frame_rejected.get(mac,0)
                    status,result=await self.control.dispatch(
                        {"address":mac,"action":"refresh"})
                    if status!=202:
                        with self._lock:
                            self.emit(mac,"command_status",
                                "Refus : lecture paramètres impossible ("+
                                str(result.get("error","échec"))+")")
                        return
                    if not await confirmed_readback_after(since,SETTINGS_RESPONSE_TIMEOUT):
                        with self._lock:
                            rejected=self.settings_frame_rejected.get(mac,0)>rejected_before
                            reason=("trame 0x01 reçue mais invalide" if rejected else
                                    "aucune trame 0x01 reçue")
                            self.emit(mac,"command_status",
                                "Refus : "+reason+" après demande 0x96. Aucune écriture.")
                        return
                with self._lock:
                    if (not self.cfg.get("allow_parameter_changes",False) or
                        not self.permission.get(mac,False) or
                        time.monotonic()-self.last_data.get(mac,0)>70 or
                        time.monotonic()-self.last_confirmed.get(mac,0)>60):
                        self.emit(mac,"command_status",
                                  "Refus : autorisation ou mesures BMS périmées")
                        return
                    expected_current=self.settings[mac].get(key)
                    if expected_current is None:
                        self.emit(mac,"command_status",
                                  "Refus : paramètre "+key+" absent de la trame 0x01")
                        return
                since_write=time.monotonic()
                status,result=await self.control.dispatch(
                    {"address":mac,"action":"write_parameter",
                     "register":p.reg,"value":value,"confirmation":CONFIRM})
                if status!=202:
                    with self._lock:
                        if result.get("error")=="write_rate_limit_15s":
                            remaining=result.get("retry_after_seconds")
                            suffix=(" (encore "+str(remaining)+" s)" if
                                    type(remaining) is int and remaining>0 else "")
                            message=("Refus "+key+" : délai de sécurité entre écritures"
                                     " de 15 s"+suffix+". Réessayez après ce délai.")
                        else:
                            message="Refus "+key+" : "+str(result.get("error","échec"))
                        self.emit(mac,"command_status",message)
                    return
                with self._lock:
                    self.emit(mac,"command_status",
                              "Commande "+key+" transmise ; vérification de l'état BMS…")
                if await confirmed_readback_after(since_write,SETTINGS_RESPONSE_TIMEOUT):
                    with self._lock:
                        actual=self.settings.get(mac,{}).get(key)
                        confirmed=(actual==value if p.kind=="switch" else
                            type(actual) in (int,float) and
                            abs(actual-value)<=max(1e-5,p.step/2))
                        if confirmed:
                            self.recent_confirmed_parameter[mac]=(key,value,time.monotonic())
                        self.emit(mac,"command_status",
                            ("Confirmé par le BMS : "+key+" = "+str(actual))
                            if confirmed else
                            ("Commande reçue mais état non modifié : "+key+
                             " (BMS = "+str(actual)+")"))
                else:
                    with self._lock:
                        self.emit(mac,"command_status",
                            "Commande "+key+" envoyée, sans confirmation 0x01 : état incertain")
            except Exception as exc:
                LOG.warning("Parameter command processing failed for %s: %s",mac,exc)
                with self._lock:
                    self.emit(mac,"command_status",
                              "Échec commande : communication BLE / relecture")
            finally:
                with self._lock:
                    self.pending_parameter_writes.discard(mac)
                    self.pending_parameter_value.pop(mac,None)

        future=asyncio.run_coroutine_threadsafe(perform(),self.loop)
        def done(f):
            try:f.result()
            except Exception as exc:
                LOG.error("Unexpected parameter task error: %s",exc)
                with self._lock:
                    self.pending_parameter_writes.discard(mac)
                    self.pending_parameter_value.pop(mac,None)
        future.add_done_callback(done)

    def _device(self,mac:str)->dict[str,Any]:
        i=sorted(self.addresses).index(mac)+1
        return {"identifiers":[short_id(mac)],"name":f"JK-BMS {i}",
                "manufacturer":"JK","model":"JK02 Bluetooth (experimental)",
                "connections":[["mac",mac]]}

    def _component(self,mac:str,key:str,kind:str,name:str,options:dict[str,Any])->None:
        identity=short_id(mac)
        slug=key.lower()
        config={"name":name,"unique_id":identity+"_"+slug,
                "object_id":identity+"_"+slug,
                "device":self._device(mac),**options}
        self.send(f"{self.discovery}/{kind}/{identity}_{slug}/config",config)

    def discover(self,mac:str,cells:int=16)->None:
        root=self.base(mac)
        readable={key for key,val in self.full_state(mac).items() if val is not None}
        known=self.discovered_readable.setdefault(mac,set())
        skip_params=set(BY_KEY)
        for key,label,unit,dc,sc,category in MEASURES:
            if key in skip_params or key=="cell_delta_mv":continue
            if key not in ALWAYS_SENSOR_KEYS and key not in readable:continue
            opts={"state_topic":root+"/state",
                  "value_template":"{{ value_json.get('"+key+"') }}",
                  "availability_topic":root+"/availability"}
            if unit:opts["unit_of_measurement"]=unit
            if dc:opts["device_class"]=dc
            if sc:opts["state_class"]=sc
            if key in INFO_NAMES:opts["entity_category"]="diagnostic"
            if key=="voltage_v":
                # Publish two fractional digits while preserving measurement
                # metadata. A user's HA precision override still takes priority.
                opts["value_template"] = ("{{ '%.2f' | format(value_json.get('voltage_v') | float) "
                                          "if value_json.get('voltage_v') is not none else 'None' }}")
                opts["suggested_display_precision"]=2
            elif key in ("cell_min_v","cell_max_v","cell_avg_v","cell_delta_v"):
                opts["suggested_display_precision"]=3
            elif key in ("current_a","balance_current_a"):opts["suggested_display_precision"]=3
            if key in {"temp1_c","temp2_c","mos_temp_c","temp3_c","temp4_c","temp5_c"}:
                opts.pop("availability_topic")
                opts["availability"]=[
                    {"topic":root+"/availability"},
                    {"topic":root+"/temperature/"+key+"/availability"}]
                opts["availability_mode"]="all"
            self._component(mac,key,"sensor",sensor_name(key,label),opts)
            known.add(key)
        for key,label in [("cell_delta_v","cell_voltage_delta"),("cell_max_number","cell_voltage_max_number"),
                           ("cell_min_number","cell_voltage_min_number")]:
            opts={"state_topic":root+"/state",
                  "value_template":"{{ value_json.get('"+key+"') }}",
                  "availability_topic":root+"/availability"}
            if key=="cell_delta_v":
                opts.update({"unit_of_measurement":"V",
                             "device_class":"voltage","state_class":"measurement",
                             "suggested_display_precision":3})
            self._component(mac,key,"sensor",MAIN_NAMES.get(key,label),opts)
            known.add(key)
        # An independent connectivity entity must remain readable while
        # BLE telemetry is offline, so use availability as its state topic.
        self._component(mac,"online_status","binary_sensor","Online",{
            "state_topic":root+"/availability",
            "payload_on":"online","payload_off":"offline",
            "device_class":"connectivity","entity_category":"diagnostic",
        })
        for key,label in BINARY_MEASURES:
            if key not in ALWAYS_BINARY_KEYS and key not in readable:continue
            self._component(mac,key,"binary_sensor",binary_name(key,label),{
                "state_topic":root+"/state",
                "value_template":"{% if value_json.get('"+key+"') is none %}None{% elif value_json.get('"+key+"') %}ON{% else %}OFF{% endif %}",
                "payload_on":"ON","payload_off":"OFF",
                "availability_topic":root+"/availability",
                **({"entity_category":"diagnostic","device_class":"problem"} if key=="alarm_active"
                   else {"entity_category":"diagnostic"})
            })
            known.add(key)
        # Read-only, BMS-confirmed status for every configurable switch.
        # These are separate from editable controls in Configuration.
        for p in PARAMS:
            if p.kind!="switch" or p.key not in readable:continue
            if p.key not in CONFIG_STATUS_NAMES:continue
            self._component(mac,"status_"+p.key,"binary_sensor",
                            CONFIG_STATUS_NAMES[p.key],{
                "state_topic":root+"/state",
                "value_template":
                    "{% if value_json.get('"+p.key+"') is none %}None{% elif value_json.get('"+p.key+"') %}ON{% else %}OFF{% endif %}",
                "payload_on":"ON","payload_off":"OFF",
                "availability_topic":root+"/availability",
                "entity_category":"diagnostic",
            })
        # Some firmware exposes UART2 as a status flag in device info.
        if "uart2_enabled" in readable:
            self._component(mac,"uart2_enabled","binary_sensor",
                            "UART2 Enabled",{
                "state_topic":root+"/state",
                "value_template":
                    "{% if value_json.get('uart2_enabled') is none %}None{% elif value_json.get('uart2_enabled') %}ON{% else %}OFF{% endif %}",
                "payload_on":"ON","payload_off":"OFF",
                "availability_topic":root+"/availability",
                "entity_category":"diagnostic",
            })
        for i in range(1,cells+1):
            # The native HA list groups identical cell numbers together;
            # both readings are in the Measurements category.
            self._component(mac,f"cell_{i:02d}_v","sensor",cell_voltage_name(i),{
                "state_topic":root+"/state",
                "value_template":"{{ value_json.get('cell_%02d_v') }}"%i,
                "unit_of_measurement":"V","device_class":"voltage",
                "state_class":"measurement","suggested_display_precision":3,
                "availability_topic":root+"/availability"})
            known.add(f"cell_{i:02d}_v")
            resistance=f"cell_{i:02d}_resistance_ohm"
            if resistance not in readable:continue
            self._component(mac,resistance,"sensor",
                cell_resistance_name(i),{
                "state_topic":root+"/state",
                "value_template":"{{ value_json.get('cell_%02d_resistance_ohm') }}"%i,
                "unit_of_measurement":"Ω","state_class":"measurement",
                "suggested_display_precision":3,
                "availability_topic":root+"/availability"})
            known.add(resistance)
        # Each documented setting has a single editable Number or Switch, not
        # both a sensor and an editable entity with competing unique IDs.
        for p in PARAMS:
            options={
                "state_topic":root+"/state",
                "value_template":"{{ value_json.get('"+p.key+"') }}",
                "command_topic":root+"/parameters/"+p.key+"/set",
                "availability_topic":root+"/availability",
                "entity_category":"config",
                "optimistic":False,
                "retain":False,
            }
            if p.kind=="switch":
                options.update({"value_template":
                    "{% if value_json.get('"+p.key+"') is none %}None{% elif value_json.get('"+p.key+"') %}ON{% else %}OFF{% endif %}",
                    "payload_on":"ON","payload_off":"OFF"})
            else:
                options.update({"min":p.minimum,"max":p.maximum,"step":p.step,
                                "mode":"box"})
                if p.unit:options["unit_of_measurement"]=p.unit
            self._component(mac,p.key,p.kind,p.label,options)
        self._component(mac,"write_permission","switch",
            "Allow Parameter Changes",{
                "state_topic":root+"/write_permission/state",
                "command_topic":root+"/write_permission/set",
                "payload_on":"ON","payload_off":"OFF",
                "optimistic":False,"retain":False,
                "availability_topic":root+"/availability",
                "entity_category":"config","icon":"mdi:lock-open-variant"
            })
        self._component(mac,"command_status","sensor","Last Parameter Command",{
            "state_topic":root+"/command_status","entity_category":"diagnostic",
            "availability_topic":root+"/availability"
        })
        self.discovered_cells[mac]=max(self.discovered_cells.get(mac,0),cells)

    def rediscover(self)->None:
        for mac in self.addresses:
            identity=short_id(mac)
            # Remove stale optional discoveries from previous versions. Publish
            # them again below only if the BMS has supplied real measurements.
            for key,*_ in MEASURES:
                if key not in ALWAYS_SENSOR_KEYS and key not in BY_KEY:
                    self.send(f"{self.discovery}/sensor/{identity}_{key}/config","")
            for idx in range(1,33):
                self.send(f"{self.discovery}/sensor/{identity}_cell_{idx:02d}_resistance_ohm/config","")
            for key,*_ in BINARY_MEASURES:
                if key not in ALWAYS_BINARY_KEYS:
                    self.send(f"{self.discovery}/binary_sensor/{identity}_{key}/config","")
            self.discovered_readable[mac]=set()
            for p in PARAMS:
                self.send(f"{self.discovery}/sensor/{identity}_{p.key}/config","")
            # UART2 status used to be a sensor; now it's an ON/OFF binary sensor.
            self.send(f"{self.discovery}/sensor/{identity}_uart2_enabled/config","")
            # Remove retained v0.2.3 discovery entries without deleting valid
            # measurements or the stable per-MAC Home Assistant device.
            for key in RETIRED_SENSOR_KEYS:
                self.send(f"{self.discovery}/sensor/{identity}_{key}/config","")
            for key in RETIRED_BINARY_KEYS:
                self.send(f"{self.discovery}/binary_sensor/{identity}_{key}/config","")
            self.send(f"{self.discovery}/button/{identity}_arm_temperature_control/config","")
            self.discover(mac,max(16,self.discovered_cells.get(mac,16)))
            self.emit(mac,"write_permission/state","OFF")
            self.emit(mac,"availability","offline")
            if mac in self.state:
                self.emit(mac,"state",self.full_state(mac))
                if time.monotonic()-self.last_data.get(mac,0)<70:
                    self.emit(mac,"availability","online")
                self._temps_available(mac,self.state[mac])

    def full_state(self,mac:str)->dict[str,Any]:
        result={**self.info.get(mac,{}),**self.settings.get(mac,{}),**self.state.get(mac,{})}
        keys={m[0] for m in MEASURES}
        keys.update(m[0] for m in BINARY_MEASURES)
        keys.update(p.key for p in PARAMS)
        keys.update(("cell_delta_v","cell_min_number","cell_max_number","uart2_enabled"))
        for index in range(1,33):
            keys.update((f"cell_{index:02d}_v",f"cell_{index:02d}_resistance_ohm"))
        return {key:value for key,value in result.items() if key in keys}

    def _temps_available(self,mac:str,data:dict[str,Any])->None:
        for k in ("temp1_c","temp2_c","mos_temp_c","temp3_c","temp4_c","temp5_c"):
            self.emit(mac,"temperature/"+k+"/availability",
                      "online" if data.get(k) is not None else "offline")

    def start(self,loop:asyncio.AbstractEventLoop)->None:
        self.loop=loop
        if not self.enabled:
            LOG.info("MQTT disabled by configuration")
            return
        user=str(self.cfg.get("mqtt_username","") or "")
        if user:
            self.client.username_pw_set(user,str(self.cfg.get("mqtt_password","") or ""))
        host=str(self.cfg.get("mqtt_host","core-mosquitto")).strip()
        port=int(self.cfg.get("mqtt_port",1883))
        LOG.info("MQTT configuration: host=%s port=%d discovery=%s enabled=%s "
                 "BMS=%d auth=%s (password hidden)",
                 host,port,self.discovery,self.enabled,len(self.addresses),
                 "configured" if user else "missing")
        if not self.addresses:
            LOG.warning("MQTT Discovery: bms_addresses is empty; no devices can be registered")
        if not user:
            LOG.warning("MQTT username empty; protected Mosquitto brokers will reject authentication")
        self.client.reconnect_delay_set(2,60)
        # paho's network loop retries if the MQTT broker is temporarily down.
        try:
            self.client.connect_async(host,port,keepalive=30)
            self.client.loop_start()
            LOG.info("MQTT discovery client started for %s:%d",host,port)
        except Exception as exc:
            LOG.warning("MQTT start failed: %s",exc)

    def stop(self)->None:
        if not self.enabled:return
        with self._lock:
            for mac in self.addresses:
                self.emit(mac,"availability","offline")
                self.emit(mac,"write_permission/state","OFF")
        self.client.disconnect()
        self.client.loop_stop()
        self.connected=False

    def watchdog(self)->None:
        if not self.enabled:return
        now=time.monotonic()
        with self._lock:
            for mac in self.addresses:
                alive=now-self.last_data.get(mac,0)<70
                if self.online_cache.get(mac) != alive:
                    self.emit(mac,"availability","online" if alive else "offline")
                    self.online_cache[mac]=alive

                if not alive and self.permission.get(mac):
                    self.permission[mac]=False
                    self.emit(mac,"write_permission/state","OFF")

    def ingest(self,data:Any)->bool:
        if not self.enabled:return False
        if not isinstance(data,dict):return False
        mac=str(data.get("address","")).upper()
        if mac not in self.addresses or not VALID_MAC.fullmatch(mac):return False
        kind=data.get("kind")
        with self._lock:
            if kind=="telemetry":
                extra=data.get("extras") if isinstance(data.get("extras"),dict) else {}
                decoded=enrich(data.get("data") or {},extra)
                if decoded is None:return False
                source=data.get("data") or {}
                sequence=source.get("sequence")
                if type(sequence) is int:
                    self.last_telemetry_sequence[mac]=sequence
                frame=self.last_telemetry_frame.get(mac)
                if frame is not None and time.monotonic()-frame[0]<15:
                    if type(sequence) is int and frame[1][5]==sequence:
                        decoded.update(runtime_from_validated_frame(frame[1],decoded["format"]))
                self.state[mac]=decoded
                self.last_data[mac]=time.monotonic()
                readable={key for key,value in self.full_state(mac).items() if value is not None}
                if (decoded["cell_count"] > self.discovered_cells.get(mac,0) or
                    not readable.issubset(self.discovered_readable.get(mac,set()).union(
                        {p.key for p in PARAMS}).union(
                        ALWAYS_SENSOR_KEYS).union(ALWAYS_BINARY_KEYS).union({
                        f"cell_{index:02d}_v" for index in range(1,33)}).union({
                        "cell_delta_v","cell_min_number","cell_max_number"}))):
                    self.discover(mac,decoded["cell_count"])
                self.emit(mac,"state",self.full_state(mac))
                self._temps_available(mac,decoded)
                self.emit(mac,"availability","online")
                self.online_cache[mac]=True

                return True
            if kind=="frame" and data.get("frame_type") in (1,2,3):
                frame_type=data["frame_type"]
                raw=valid_frame(data.get("raw_hex"),frame_type)
                if raw is None:return False
                if frame_type==2:
                    self.last_telemetry_frame[mac]=(time.monotonic(),raw)
                    if (mac in self.state and
                        self.last_telemetry_sequence.get(mac)==raw[5]):
                        new=runtime_from_validated_frame(raw,
                                                       self.state[mac].get("format"))
                        if new:
                            self.state[mac].update(new)
                            if "total_runtime_formatted" not in self.discovered_readable.get(mac,set()):
                                self.discover(mac,max(16,self.discovered_cells.get(mac,16)))
                            self.emit(mac,"state",self.full_state(mac))
                    return True
                if frame_type==1:
                    parsed=parse_settings(raw)
                    if not parsed:
                        self.settings_frame_rejected[mac]=self.settings_frame_rejected.get(mac,0)+1
                        LOG.warning("JK settings CRC OK but unsupported/implausible layout for %s; "
                                    "values not trusted, no writes enabled",mac)
                        return False
                    self.settings[mac]=parsed
                    self.last_confirmed[mac]=time.monotonic()
                    self.last_settings_frame[mac]=time.monotonic()
                    self.settings_frame_rejected[mac]=0
                    LOG.info("JK settings 0x01 confirmed for %s (%d parameters)",mac,len(parsed))
                else:
                    self.info[mac]=parse_info(raw)
                if mac in self.state:
                    if frame_type in (1,3):
                        self.discover(mac,max(16,self.discovered_cells.get(mac,16)))
                    self.emit(mac,"state",self.full_state(mac))
                return True
            if kind=="lifecycle" and data.get("event") in ("disconnected","stream_stale"):
                self.emit(mac,"availability","offline")
                self.last_data.pop(mac,None)
                self.last_confirmed.pop(mac,None)
                self.settings.pop(mac,None)
                self.recent_confirmed_parameter.pop(mac,None)
                self.last_telemetry_frame.pop(mac,None)
                self.last_telemetry_sequence.pop(mac,None)
                self.permission[mac]=False
                self.emit(mac,"write_permission/state","OFF")
                self.online_cache[mac]=False
                self.permission[mac]=False
                self.emit(mac,"write_permission/state","OFF")
                return True
        return False
