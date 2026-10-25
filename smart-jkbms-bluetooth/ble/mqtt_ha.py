"""Home Assistant MQTT Discovery for verified JK02 BLE data.

All updates are fed by Node-RED's CRC-valid frame and validated decoder.
No BMS passwords or credentials are ever published.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

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
 ("voltage_v","Tension batterie","V","voltage","measurement",None),
 ("current_a","Courant batterie","A","current","measurement",None),
 ("power_w","Puissance batterie","W","power","measurement",None),
 ("charge_power_w","Puissance de charge","W","power","measurement",None),
 ("discharge_power_w","Puissance de décharge","W","power","measurement",None),
 ("soc_pct","État de charge","%","battery","measurement",None),
 ("soh_pct","État de santé","%",None,"measurement","diagnostic"),
 ("cell_count","Nombre de cellules",None,None,"measurement","diagnostic"),
 ("cell_min_v","Cellule minimum","V","voltage","measurement",None),
 ("cell_max_v","Cellule maximum","V","voltage","measurement",None),
 ("cell_avg_v","Cellule moyenne","V","voltage","measurement",None),
 ("cell_delta_mv","Écart cellules","mV",None,"measurement",None),
 ("balance_current_a","Courant équilibrage","A","current","measurement",None),
 ("balance_state","Équilibrage",None,None,None,None),
 ("capacity_remaining_ah","Capacité restante","Ah",None,"measurement",None),
 ("nominal_capacity_ah","Capacité nominale","Ah",None,"measurement","diagnostic"),
 ("total_cycle_capacity_ah","Capacité cumulée cyclée","Ah",None,None,"diagnostic"),
 ("cycles","Cycles",None,None,"total_increasing","diagnostic"),
 ("total_runtime_h","Temps fonctionnement","h","duration","total_increasing","diagnostic"),
 ("temp1_c","Température sonde 1","°C","temperature","measurement",None),
 ("temp2_c","Température sonde 2","°C","temperature","measurement",None),
 ("mos_temp_c","Température MOS","°C","temperature","measurement",None),
 ("temp3_c","Température sonde 3","°C","temperature","measurement","diagnostic"),
 ("temp4_c","Température sonde 4","°C","temperature","measurement","diagnostic"),
 ("temp5_c","Température sonde 5","°C","temperature","measurement","diagnostic"),
 ("error_count","Alarmes actives","",None,"measurement","diagnostic"),
 ("alarm_text","Détail alarmes",None,None,None,"diagnostic"),
 ("error_mask_hex","Masque alarmes",None,None,None,"diagnostic"),
 ("temperature_quality","Qualité températures",None,None,None,"diagnostic"),
 ("format","Protocole BLE",None,None,None,"diagnostic"),
 ("cell_wire_warning_mask","Alertes câblage cellules",None,None,None,"diagnostic"),
 ("temperature_sensor_absent_mask","Masque sondes",None,None,None,"diagnostic"),
 ("balance_action","Action équilibrage",None,None,None,"diagnostic"),
 ("charge_status","Phase de charge",None,None,None,"diagnostic"),
 ("controls_hex","Contrôles BMS",None,None,None,"diagnostic"),
 ("cell_uvp_v","Seuil cellule UVP","V","voltage","measurement","diagnostic"),
 ("cell_ovp_v","Seuil cellule OVP","V","voltage","measurement","diagnostic"),
 ("balance_start_v","Début équilibrage","V","voltage","measurement","diagnostic"),
 ("max_charge_current_a","Courant charge maximum","A","current","measurement","diagnostic"),
 ("max_discharge_current_a","Courant décharge maximum","A","current","measurement","diagnostic"),
 ("vendor_id","Fabricant déclaré",None,None,None,"diagnostic"),
 ("hardware_version","Version matérielle",None,None,None,"diagnostic"),
 ("software_version","Version logicielle",None,None,None,"diagnostic"),
 ("device_uptime_h","Uptime BMS","h","duration","total_increasing","diagnostic"),
 ("uart1_protocol","Protocole UART1",None,None,None,"diagnostic"),
 ("uart2_protocol","Protocole UART2",None,None,None,"diagnostic"),
 ("can_protocol","Protocole CAN",None,None,None,"diagnostic"),
]
BINARY_MEASURES=[
 ("charging_mos","MOS charge"),
 ("discharging_mos","MOS décharge"),
 ("precharge","Précharge"),
 ("heating","Chauffage"),
 ("alarm_active","Alarme BMS"),
]
SETTING_KEYS={"controls_hex","cell_uvp_v","cell_ovp_v","balance_start_v",
              "max_charge_current_a","max_discharge_current_a"}
INFO_KEYS={"vendor_id","hardware_version","software_version","device_uptime_h",
           "uart1_protocol","uart2_protocol","can_protocol"}


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
    # JK02_32S settings only. Explicitly reject implausible layout.
    def milli(pos: int, maximum: float=1000.0) -> float | None:
        val=int.from_bytes(raw[pos:pos+4],"little")/1000
        return round(val,3) if 0<val<=maximum else None
    cell_uvp=milli(10,5)
    cell_ovp=milli(18,5)
    if cell_uvp is None or cell_ovp is None or cell_uvp>=cell_ovp:
        return {}
    return {
      "cell_uvp_v":cell_uvp,"cell_ovp_v":cell_ovp,
      "balance_start_v":milli(138,5),
      "max_charge_current_a":milli(50,1500),
      "max_discharge_current_a":milli(62,1500),
      "controls_hex":f"0x{int.from_bytes(raw[282:284],'little'):04X}",
      "temperature_monitoring_disabled":bool(raw[282]&0x02),
    }


def parse_info(raw: bytes) -> dict[str, Any]:
    def ascii_field(pos: int, length: int) -> str | None:
        value=raw[pos:pos+length].split(b"\x00",1)[0]
        if not value or any(x<32 or x>126 for x in value):
            return None
        return value.decode("ascii").strip()[:32] or None
    result={
      "vendor_id":ascii_field(6,16),
      "hardware_version":ascii_field(22,8),
      "software_version":ascii_field(30,8),
      "device_uptime_h":round(int.from_bytes(raw[38:42],"little")/3600,2),
      "uart1_protocol":raw[184],
      "uart2_protocol":raw[218],
      "can_protocol":raw[185],
    }
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
     "cell_avg_v":round(sum(readings)/len(readings),3),
     "cell_delta_mv":round((max(readings)-min(readings))*1000),
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
        for idx in range(1,len(readings)+1):
            resistance=extras.get(f"cell_{idx:02d}_resistance_ohm")
            if resistance is not None:out[f"cell_{idx:02d}_resistance_ohm"]=resistance
    mask=d.get("error_mask")
    if type(mask) is int and 0<=mask<=0xFFFFFFFF:
        alarms=[label for bit,label in ALARM_NAMES.items() if mask&(1<<bit)]
        out["error_count"]=len(alarms)
        out["alarm_active"]=bool(alarms)
        out["alarm_text"]=", ".join(alarms) if alarms else "Aucune"
        out["error_mask_hex"]=f"0x{mask:08X}"
    return out


class HomeAssistantMQTT:
    def __init__(self,cfg:dict[str,Any],addresses:list[str],control:Any=None,
                 client:Any=None) -> None:
        self.cfg=cfg
        self.addresses=addresses
        self.control=control
        self.prefix=str(cfg.get("mqtt_topic_prefix") or "smart_jkbms_ble").strip().strip("/")
        self.discovery=str(cfg.get("mqtt_discovery_prefix") or "homeassistant").strip().strip("/")
        self.client=client or mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                 client_id="smart-jkbms-"+str(cfg.get("mqtt_client_suffix","bridge")))
        self.client.on_connect=self.on_connect
        self.client.on_disconnect=self.on_disconnect
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
        self.armed_until:dict[str,float]={}
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
        with self._lock:
            self.connected=int(reason_code)==0
            if not self.connected:
                LOG.warning("MQTT rejected connection: %s",reason_code)
                return
            LOG.info("MQTT connected; registering %d configured JK-BMS devices",len(self.addresses))
            self.client.subscribe("homeassistant/status",qos=1)
            for mac in self.addresses:
                base=self.base(mac)
                self.client.subscribe(f"{base}/temperature_control/set",qos=1)
                self.client.subscribe(f"{base}/temperature_control/arm",qos=1)
            self.rediscover()

    def on_disconnect(self,client,userdata,disconnect_flags,reason_code,properties=None):
        with self._lock:
            self.connected=False
            LOG.warning("MQTT disconnected: %s",reason_code)

    def on_message(self,client,userdata,msg):
        with self._lock:
            if msg.topic=="homeassistant/status" and msg.payload==b"online":
                self.rediscover()
                return
            for mac in self.addresses:
                base=self.base(mac)
                if msg.topic==f"{base}/temperature_control/arm":
                    if msg.payload==b"PRESS" and bool(self.cfg.get("allow_temperature_control",False)):
                        self.armed_until[mac]=time.monotonic()+30
                        self.emit(mac,"command_status","Commande thermique armée pour 30 s")
                    return
                if msg.topic==f"{base}/temperature_control/set":
                    self._temperature_set_command(mac,msg.payload)
                    return

    def _temperature_set_command(self,mac:str,payload:bytes)->None:
        if payload not in (b"ON",b"OFF"):
            return
        if not bool(self.cfg.get("allow_temperature_control",False)):
            self.emit(mac,"command_status","Refus : commandes thermiques désactivées")
            return
        expiration=self.armed_until.pop(mac,0)
        if expiration<time.monotonic():
            self.emit(mac,"command_status","Refus : armer d'abord la commande (30 s)")
            return
        if self.loop is None or self.control is None:
            self.emit(mac,"command_status","Refus : service BLE indisponible")
            return
        import concurrent.futures
        from control import CONFIRM
        action={"address":mac,"action":"set_temperature_disabled",
                "disable":payload==b"ON","confirmation":CONFIRM}
        async def dispatch():
            status,response=await self.control.dispatch(action)
            with self._lock:
                if status==202:
                    self.emit(mac,"command_status",
                         "Commande envoyée, en attente de confirmation BMS")
                else:
                    self.emit(mac,"command_status",
                         "Commande refusée : "+str(response.get("error","erreur")))
        future=asyncio.run_coroutine_threadsafe(dispatch(),self.loop)
        def done(f):
            try:f.result()
            except Exception as err:LOG.error("MQTT command handling failed: %s",err)
        future.add_done_callback(done)

    def _device(self,mac:str)->dict[str,Any]:
        i=self.addresses.index(mac)+1
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
        for key,label,unit,dc,sc,category in MEASURES:
            opts={"state_topic":root+"/state",
                  "value_template":"{{ value_json.get('"+key+"') }}",
                  "availability_topic":root+"/availability"}
            if unit:opts["unit_of_measurement"]=unit
            if dc:opts["device_class"]=dc
            if sc:opts["state_class"]=sc
            if category:opts["entity_category"]=category
            if key in {"temp1_c","temp2_c","mos_temp_c","temp3_c","temp4_c","temp5_c"}:
                opts.pop("availability_topic")
                opts["availability"]=[
                    {"topic":root+"/availability"},
                    {"topic":root+"/temperature/"+key+"/availability"}]
                opts["availability_mode"]="all"
            self._component(mac,key,"sensor",label,opts)
        for key,label in BINARY_MEASURES:
            self._component(mac,key,"binary_sensor",label,{
                "state_topic":root+"/state",
                "value_template":"{% if value_json.get('"+key+"') is none %}None{% elif value_json.get('"+key+"') %}ON{% else %}OFF{% endif %}",
                "payload_on":"ON","payload_off":"OFF",
                "availability_topic":root+"/availability",
                "entity_category":"diagnostic",
                **({"device_class":"problem"} if key=="alarm_active" else {})
            })
        for i in range(1,cells+1):
            self._component(mac,f"cell_{i:02d}_v","sensor",f"Cellule {i:02d} tension",{
                "state_topic":root+"/state",
                "value_template":"{{ value_json.get('cell_%02d_v') }}"%i,
                "unit_of_measurement":"V","device_class":"voltage",
                "state_class":"measurement","availability_topic":root+"/availability"})
            if i<=32:
                self._component(mac,f"cell_{i:02d}_resistance_ohm","sensor",
                    f"Cellule {i:02d} résistance",{
                    "state_topic":root+"/state",
                    "value_template":"{{ value_json.get('cell_%02d_resistance_ohm') }}"%i,
                    "unit_of_measurement":"Ω","state_class":"measurement",
                    "entity_category":"diagnostic",
                    "availability_topic":root+"/availability"})
        self._component(mac,"disable_temperature_sensors","switch",
            "Désactiver surveillance thermique",{
            "state_topic":root+"/temperature_control/state",
            "command_topic":root+"/temperature_control/set",
            "payload_on":"ON","payload_off":"OFF",
            "optimistic":False,"retain":False,
            "availability":[{"topic":root+"/availability"},
               {"topic":root+"/temperature_control/availability"}],
            "availability_mode":"all","entity_category":"config",
            "icon":"mdi:thermometer-off",
            "enabled_by_default":True,
        })
        self._component(mac,"arm_temperature_control","button",
            "Armer commande thermique (30 s)",{
            "command_topic":root+"/temperature_control/arm","payload_press":"PRESS",
            "availability_topic":root+"/temperature_control/availability",
            "entity_category":"config","icon":"mdi:shield-key",
            "enabled_by_default":True,
        })
        self._component(mac,"command_status","sensor","Dernière commande thermique",{
            "state_topic":root+"/command_status",
            "availability_topic":root+"/availability",
            "entity_category":"diagnostic",
        })
        self.discovered_cells[mac]=max(self.discovered_cells.get(mac,0),cells)

    def rediscover(self)->None:
        for mac in self.addresses:
            self.discover(mac,max(16,self.discovered_cells.get(mac,16)))
            self.emit(mac,"availability","offline")
            self.emit(mac,"temperature_control/availability",
                  "offline" if not self.cfg.get("allow_temperature_control",False) else
                  ("online" if self.last_data.get(mac) and
                   time.monotonic()-self.last_data[mac]<70 else "offline"))
            self.emit(mac,"temperature_control/state",
                ("ON" if self.settings[mac]["temperature_monitoring_disabled"] else "OFF")
                if mac in self.settings and mac in self.last_confirmed and
                time.monotonic()-self.last_confirmed[mac]<180 else "",retain=True)
            if mac in self.state:
                self.emit(mac,"state",self.full_state(mac))
                if time.monotonic()-self.last_data.get(mac,0)<70:
                    self.emit(mac,"availability","online")
                self._temps_available(mac,self.state[mac])

    def full_state(self,mac:str)->dict[str,Any]:
        result={**self.info.get(mac,{}),**self.settings.get(mac,{}),**self.state.get(mac,{})}
        return result

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
                self.emit(mac,"temperature_control/availability","offline")
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
                self.emit(mac,"temperature_control/availability",
                    "online" if alive and self.cfg.get("allow_temperature_control",False)
                    else "offline")
                if not alive:self.armed_until.pop(mac,None)

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
                self.state[mac]=decoded
                self.last_data[mac]=time.monotonic()
                current=self.discovered_cells.get(mac,0)
                if decoded["cell_count"] > current:
                    self.discover(mac,decoded["cell_count"])
                self.emit(mac,"state",self.full_state(mac))
                self._temps_available(mac,decoded)
                self.emit(mac,"availability","online")
                self.online_cache[mac]=True
                if self.cfg.get("allow_temperature_control",False):
                    self.emit(mac,"temperature_control/availability","online")
                return True
            if kind=="frame" and data.get("frame_type") in (1,3):
                frame_type=data["frame_type"]
                raw=valid_frame(data.get("raw_hex"),frame_type)
                if raw is None:return False
                if frame_type==1:
                    parsed=parse_settings(raw)
                    if not parsed:return False
                    self.settings[mac]=parsed
                    self.last_confirmed[mac]=time.monotonic()
                    self.emit(mac,"temperature_control/state",
                         "ON" if parsed["temperature_monitoring_disabled"] else "OFF")
                else:
                    self.info[mac]=parse_info(raw)
                if mac in self.state:
                    self.emit(mac,"state",self.full_state(mac))
                return True
            if kind=="lifecycle" and data.get("event") in ("disconnected","stream_stale"):
                self.emit(mac,"availability","offline")
                self.emit(mac,"temperature_control/availability","offline")
                self.last_data.pop(mac,None)
                self.online_cache[mac]=False
                self.armed_until.pop(mac,None)
                return True
        return False
