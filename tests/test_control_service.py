import asyncio
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "smart-jkbms-bluetooth" / "ble"))
from control import ControlService, CONFIRM, temperature_control_frame

A = "C8:47:80:1A:1A:EF"
B = "C8:47:80:1A:27:12"


def addresses(raw):
    return [x.strip().upper() for x in raw.split(",") if x.strip()]


class TemperatureControlTests(unittest.TestCase):
    def test_packets_exactly_match_jk02_32s_register_write(self):
        for disabled in (True,False):
            p=temperature_control_frame(disabled)
            self.assertEqual(len(p),20)
            self.assertEqual(p[:4],bytes.fromhex("AA 55 90 EB"))
            self.assertEqual(p[4],0x28)
            self.assertEqual(p[5],4)
            self.assertEqual(p[6:10],bytes((1 if disabled else 0,0,0,0)))
            self.assertEqual(p[10:19],bytes(9))
            self.assertEqual(p[19],sum(p[:19])&255)
        for invalid in ("ON",1,0,None):
            with self.assertRaises(ValueError):
                temperature_control_frame(invalid)

    def test_manual_writes_default_off_and_require_authorization(self):
        async def run():
            cfg={"bms_addresses":A+","+B,"allow_parameter_changes":False}
            svc=ControlService(lambda:cfg,addresses)
            svc.register(A)
            status,body=await svc.dispatch({"address":A,"action":"set_temperature_disabled",
                "disable":True,"confirmation":CONFIRM})
            self.assertEqual(status,403)
            cfg["allow_parameter_changes"]=True
            for candidate in [
                {"address":A,"action":"set_temperature_disabled","disable":True},
                {"address":A,"action":"set_temperature_disabled","disable":1,"confirmation":CONFIRM},
                {"address":"AA:BB:CC:DD:EE:FF","action":"refresh"},
                {"address":A,"action":"write_any_register"},
            ]:
                status,body=await svc.dispatch(candidate)
                self.assertIn(status,(400,403))
            svc.unregister(A)
        asyncio.run(run())

    def test_connected_manual_write_reports_sent_not_confirmed(self):
        async def run():
            cfg={"bms_addresses":A+","+B,"allow_parameter_changes":True}
            svc=ControlService(lambda:cfg,addresses)
            svc.mqtt_sink=SimpleNamespace(permission={A:True})
            queue=svc.register(A)
            async def worker():
                cmd=await asyncio.wait_for(queue.get(),2)
                self.assertEqual(cmd.action,"set_temperature_disabled")
                self.assertTrue(cmd.disable)
                cmd.future.set_result({"register":"0x28"})
            task=asyncio.create_task(worker())
            status,body=await svc.dispatch({"address":A,"action":"set_temperature_disabled",
                "disable":True,"confirmation":CONFIRM})
            await task
            self.assertEqual(status,202)
            self.assertTrue(body["write_sent"])
            self.assertFalse(body["verified_by_bms"])
            self.assertEqual(body["register"],"0x28")
            status,body=await svc.dispatch({"address":A,"action":"set_temperature_disabled",
                "disable":False,"confirmation":CONFIRM})
            self.assertEqual(status,429)
            svc.unregister(A)
        asyncio.run(run())

    def test_disconnected_and_rate_limit_dont_queue_writes(self):
        async def run():
            cfg={"bms_addresses":A,"allow_parameter_changes":True}
            svc=ControlService(lambda:cfg,addresses)
            svc.mqtt_sink=SimpleNamespace(permission={A:True})
            status,body=await svc.dispatch({"address":A,"action":"set_temperature_disabled",
                "disable":True,"confirmation":CONFIRM})
            self.assertEqual(status,409)
            queue=svc.register(A)
            async def worker():
                cmd=await queue.get()
                self.assertEqual(cmd.action,"refresh")
                cmd.future.set_result({"requests_sent":["0x97","0x96"]})
            task=asyncio.create_task(worker())
            status,body=await svc.dispatch({"address":A,"action":"refresh"})
            self.assertEqual(status,202)
            self.assertFalse(body["write_sent"])
            await task
            svc.unregister(A)
        asyncio.run(run())

    def test_jk_parameter_write_is_allowlisted_and_nonoptimistic(self):
        async def run():
            cfg={"bms_addresses":A,"allow_parameter_changes":True}
            svc=ControlService(lambda:cfg,addresses)
            svc.mqtt_sink=SimpleNamespace(permission={A:True})
            queue=svc.register(A)
            invalid=[
                {"register":0x77,"value":42},
                {"register":0x02,"value":5.0},
                {"register":0x02,"value":"3.0"},
                {"register":0x1D,"value":1},
            ]
            for args in invalid:
                status,_=await svc.dispatch({
                    "address":A,"action":"write_parameter",
                    "confirmation":CONFIRM,**args})
                self.assertIn(status,(400,403))
            async def worker():
                cmd=await asyncio.wait_for(queue.get(),2)
                self.assertEqual(cmd.action,"write_parameter")
                self.assertEqual(cmd.register,0x02)
                self.assertEqual(cmd.value,2.65)
                cmd.future.set_result({"register":"0x02"})
            task=asyncio.create_task(worker())
            status,result=await svc.dispatch({
                "address":A,"action":"write_parameter",
                "register":0x02,"value":2.65,"confirmation":CONFIRM})
            await task
            self.assertEqual(status,202)
            self.assertTrue(result["write_sent"])
            self.assertFalse(result["verified_by_bms"])
            svc.unregister(A)
        asyncio.run(run())

    def test_read_only_refresh_is_always_available_and_does_not_write(self):
        async def run():
            # The former read_only_requests option was removed from public
            # config. Reading settings remains available without write consent.
            cfg={"bms_addresses":A,"allow_parameter_changes":False}
            svc=ControlService(lambda:cfg,addresses)
            queue=svc.register(A)
            async def respond():
                cmd=await asyncio.wait_for(queue.get(),1)
                self.assertEqual(cmd.action,"refresh")
                cmd.future.set_result({"requests_sent":["0x96"]})
            worker=asyncio.create_task(respond())
            status,body=await svc.dispatch({"address":A,"action":"refresh"})
            await worker
            self.assertEqual(status,202)
            self.assertEqual(body["requests_sent"],["0x96"])
            self.assertFalse(body["write_sent"])
            svc.unregister(A)
        asyncio.run(run())

    def test_local_api_rejects_bad_token(self):
        async def run():
            svc=ControlService(lambda:{"bms_addresses":A},addresses)
            server=await asyncio.start_server(svc.handle,"127.0.0.1",0)
            port=server.sockets[0].getsockname()[1]
            try:
                reader,writer=await asyncio.open_connection("127.0.0.1",port)
                data=b'{"address":"'+A.encode()+b'","action":"refresh"}'
                req=(b"POST /control HTTP/1.1\r\nHost: localhost\r\n"
                    b"X-BLE-Bridge-Token: WRONG\r\nContent-Type: application/json\r\n"
                    + b"Content-Length: "+str(len(data)).encode()+b"\r\n\r\n"+data)
                writer.write(req)
                await writer.drain()
                response=await reader.read()
                self.assertIn(b"401 Unauthorized",response)
                writer.close()
                await writer.wait_closed()
            finally:
                server.close()
                await server.wait_closed()
        with patch.dict(os.environ,{"BLE_BRIDGE_TOKEN":"SECRET"}):
            asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
