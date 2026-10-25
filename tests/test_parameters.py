import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"smart-jkbms-bluetooth"/"ble"))
from parameters import PARAMS, BY_KEY, read_settings, build_write
from mqtt_ha import parse_settings

def frame():
    b=bytearray(300);b[:5]=bytes.fromhex("55 AA EB 90 01")
    b[10:14]=(2650).to_bytes(4,"little")
    b[14:18]=(3050).to_bytes(4,"little")
    b[18:22]=(3630).to_bytes(4,"little")
    b[22:26]=(3473).to_bytes(4,"little")
    b[26:30]=(5).to_bytes(4,"little")
    b[38:42]=(3475).to_bytes(4,"little")
    b[42:46]=(3375).to_bytes(4,"little")
    b[50:54]=(150000).to_bytes(4,"little")
    b[62:66]=(150000).to_bytes(4,"little")
    b[98:102]=(-20).to_bytes(4,"little",signed=True)
    b[114]=16;b[118]=1;b[122]=1;b[126]=0
    b[130:134]=(280000).to_bytes(4,"little")
    b[138:142]=(3410).to_bytes(4,"little")
    b[282:284]=(0x200).to_bytes(2,"little")
    b[286]=23;b[296]=2;b[297]=5
    b[299]=sum(b[:299])&255
    return bytes(b)

class ParameterTests(unittest.TestCase):
    def test_jk02_decode_grouped_read_only(self):
        p=parse_settings(frame())
        self.assertGreaterEqual(len(PARAMS),40)
        self.assertEqual(p["cell_uvp_v"],2.65)
        self.assertEqual(p["cell_ovp_v"],3.63)
        self.assertEqual(p["request_charge_v"],3.475)
        self.assertEqual(p["request_float_v"],3.375)
        self.assertEqual(p["balance_trigger_v"],0.005)
        self.assertEqual(p["configured_cell_count"],16)
        self.assertEqual(p["capacity_config_ah"],280)
        self.assertEqual(p["max_charge_current_a"],150)
        self.assertTrue(p["charging_enabled"])
        self.assertFalse(p["balancer_enabled"])
        self.assertFalse(p["disable_temperature_sensors"])
        self.assertTrue(p["charging_float_mode"])
        self.assertEqual(p["charge_utp_c"],-2.0)
        self.assertEqual(p["discharge_utpr_c"],5)

    def test_command_packet_exact_reg_type_scaling_crc(self):
        for key,value,raw in [
            ("cell_uvp_v",2.650,2650),
            ("request_float_v",3.375,3375),
            ("max_charge_current_a",150,150000),
            ("charge_utp_c",-2.0,-20),
            ("balancer_enabled",True,1),
            ("disable_temperature_sensors",False,0),
            ("smart_sleep_delay_h",23,23),
        ]:
            with self.subTest(key=key):
                param=BY_KEY[key]
                cmd=build_write(param.reg,value)
                self.assertEqual(len(cmd),20)
                self.assertEqual(cmd[:4],bytes.fromhex("AA 55 90 EB"))
                self.assertEqual(cmd[4],param.reg)
                self.assertEqual(cmd[5],param.length)
                self.assertEqual(int.from_bytes(cmd[6:6+param.length],"little",signed=raw<0),raw)
                self.assertEqual(cmd[19],sum(cmd[:19])&0xff)

    def test_reject_unsafe_or_undocumented_register_writes(self):
        for reg,v in [(0x77,1),(0x64,4000),(0x02,0),(0x04,4.9),(0x1D,1),
                      (0x1D,"ON"),(0x0C,float("nan")),(0x0C,-1),(0x02,2.6519)]:
            with self.subTest(reg=reg,value=v), self.assertRaises(ValueError):
                build_write(reg,v)

    def test_settings_checksum_and_version_required(self):
        b=bytearray(frame())
        b[299]^=0xff
        self.assertFalse(read_settings(bytes(b)))
        self.assertFalse(parse_settings(bytes(b)))
        b=bytearray(frame())
        b[4]=2;b[299]=sum(b[:299])&255
        self.assertFalse(read_settings(bytes(b)))

if __name__=="__main__":
    unittest.main()
