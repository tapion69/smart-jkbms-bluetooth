"""JK02_32S allowlisted configuration fields from syssi JK-BMS protocol map.
Strict values only; writes require explicit local permission and BLE readback.
"""
from __future__ import annotations
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class Param:
    key:str
    label:str
    reg:int
    offset:int
    scale:int=1000
    minimum:float=0
    maximum:float=1000
    unit:str|None=None
    step:float=0.001
    length:int=4
    signed:bool=False
    kind:str="number"
    bit:int|None=None

def volt(k,n,r,o,lo=1.2,hi=4.35):
    return Param(k,n,r,o,1000,lo,hi,"V",0.001)
def amp(k,n,r,o,hi=500):
    return Param(k,n,r,o,1000,0,hi,"A",0.001)
def deg(k,n,r,o,lo=-40,hi=120,signed=False):
    return Param(k,n,r,o,10,lo,hi,"°C",0.1,4,signed)
def number(k,n,r,o,hi=3600,unit="s"):
    return Param(k,n,r,o,1,0,hi,unit,1)
def switch(k,n,r,o,bit=None):
    return Param(k,n,r,o,1,0,1,None,1,4,False,"switch",bit)

PARAMS=[
 volt("smart_sleep_voltage","BMS smart sleep voltage",0x01,6,0.003,3.65),
 volt("cell_uvp_v","BMS cell voltage undervoltage protection",0x02,10),
 volt("cell_uvpr_v","BMS cell voltage undervoltage recovery",0x03,14),
 volt("cell_ovp_v","BMS cell voltage overvoltage protection",0x04,18),
 volt("cell_ovpr_v","BMS cell voltage overvoltage recovery",0x05,22),
 volt("balance_trigger_v","BMS balance trigger voltage",0x06,26,0,1),
 volt("cell_soc100_v","BMS cell soc100 voltage",0x07,30),
 volt("cell_soc0_v","BMS cell soc0 voltage",0x08,34),
 volt("request_charge_v","BMS cell request charge voltage",0x09,38),
 volt("request_float_v","BMS cell request float voltage",0x0A,42),
 volt("power_off_v","BMS power off voltage",0x0B,46),
 amp("max_charge_current_a","BMS max charge current",0x0C,50),
 number("charge_ocp_delay_s","BMS charge overcurrent protection delay",0x0D,54),
 number("charge_ocp_recovery_s","BMS charge overcurrent recovery",0x0E,58),
 amp("max_discharge_current_a","BMS max discharge current",0x0F,62),
 number("discharge_ocp_delay_s","BMS discharge overcurrent protection delay",0x10,66),
 number("discharge_ocp_recovery_s","BMS discharge overcurrent recovery",0x11,70),
 number("short_circuit_recovery_s","BMS short circuit recovery",0x12,74),
 amp("max_balance_current_a","BMS max balance current",0x13,78,20),
 deg("charge_otp_c","BMS charge overtemperature protection",0x14,82,0,120),
 deg("charge_otpr_c","BMS charge overtemperature recovery",0x15,86,0,120),
 deg("discharge_otp_c","BMS discharge overtemperature protection",0x16,90,0,120),
 deg("discharge_otpr_c","BMS discharge overtemperature recovery",0x17,94,0,120),
 deg("charge_utp_c","BMS charge undertemperature protection",0x18,98,signed=True),
 deg("charge_utpr_c","BMS charge undertemperature recovery",0x19,102,signed=True),
 deg("mos_otp_c","BMS power tube overtemperature protection",0x1A,106,0,160,True),
 deg("mos_otpr_c","BMS power tube overtemperature recovery",0x1B,110,0,160,True),
 Param("configured_cell_count","BMS cell count",0x1C,114,1,4,32,None,1),
 switch("charging_enabled","BMS charging switch",0x1D,118),
 switch("discharging_enabled","BMS discharging switch",0x1E,122),
 switch("balancer_enabled","BMS balance switch",0x1F,126),
 Param("capacity_config_ah","BMS total battery capacity",0x20,130,1000,1,10000,"Ah",0.001),
 number("short_circuit_delay_us","BMS short circuit protection delay",0x21,134,500000,"μs"),
 volt("balance_start_v","BMS balance starting voltage",0x22,138),
 number("precharge_time_s","BMS precharge time",0x25,274,255),
 switch("heating_enabled","BMS heating switch",0x27,282,0),
 switch("disable_temperature_sensors","BMS disable temperature sensors",0x28,282,1),
 switch("display_always_on","BMS display always on switch",0x2B,282,4),
 switch("smart_sleep_enabled","BMS smart sleep switch",0x2D,282,6),
 switch("disable_pcl_module","BMS disable PCL module switch",0x2E,282,7),
 switch("timed_stored_data","BMS timed stored data switch",0x2F,282,8),
 switch("charging_float_mode","BMS Charging Floating Mode",0x30,282,9),
 Param("heating_start_c","BMS heating start temperature",0x37,284,1,-30,90,"°C",1,1,True),
 Param("heating_stop_c","BMS heating stop temperature",0x38,285,1,-30,90,"°C",1,1,True),
 Param("smart_sleep_delay_h","BMS smart sleep delay",0x39,286,1,0,24,"h",1,1),
 Param("discharge_utp_c","BMS discharge undertemperature protection",0x3A,296,1,-40,50,"°C",1,1,True),
 Param("discharge_utpr_c","BMS discharge undertemperature recovery",0x3B,297,1,-40,50,"°C",1,1,True),
]
BY_KEY={p.key:p for p in PARAMS}
BY_REGISTER={p.reg:p for p in PARAMS}
assert len(BY_KEY)==len(PARAMS)==len(BY_REGISTER)

def read_settings(raw:bytes)->dict:
    if len(raw)!=300 or raw[:5]!=bytes.fromhex("55 AA EB 90 01") or (sum(raw[:299])&255)!=raw[299]:
        return {}
    out={}
    for p in PARAMS:
        if p.bit is not None:
            val=bool(int.from_bytes(raw[p.offset:p.offset+2],"little")&(1<<p.bit))
        elif p.kind=="switch":
            val=bool(raw[p.offset])
        else:
            val=round(int.from_bytes(raw[p.offset:p.offset+p.length],"little",signed=p.signed)/p.scale,3)
            if not p.minimum<=val<=p.maximum:continue
        out[p.key]=val
    out["controls_hex"]=f"0x{int.from_bytes(raw[282:284],'little'):04X}"
    out["temperature_monitoring_disabled"]=out.get("disable_temperature_sensors")
    out["device_address"]=raw[270]
    return out

def build_write(reg:int,value:object)->bytes:
    p=BY_REGISTER.get(reg)
    if p is None:raise ValueError("Register is not allowlisted")
    if p.kind=="switch":
        if type(value) is not bool:raise ValueError("Expected boolean")
        raw=int(value)
    else:
        if type(value) not in (float,int) or not math.isfinite(value) or not p.minimum<=value<=p.maximum:
            raise ValueError("Value outside validated parameter bounds")
        raw=round(value*p.scale)
        if abs(value-raw/p.scale)>max(0.00001,p.step/100):
            raise ValueError("Cannot represent this value at BMS precision")
    packet=bytearray(20);packet[:4]=bytes.fromhex("AA 55 90 EB")
    packet[4]=reg;packet[5]=p.length
    packet[6:6+p.length]=raw.to_bytes(p.length,"little",signed=raw<0)
    packet[19]=sum(packet[:19])&255
    return bytes(packet)
