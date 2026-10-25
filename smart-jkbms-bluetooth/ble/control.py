"""Restricted local control endpoint for experimental JK02 temperature setting.

No external socket: listens on localhost only. Manual, explicit one-shot actions.
Confirmed BMS state must come separately from a verified settings frame.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable
from parameters import BY_REGISTER, build_write

LOG = logging.getLogger("smart_jkbms_ble.control")
CONFIRM = "I_UNDERSTAND_THERMAL_PROTECTION_RISK"
HEADER = bytes.fromhex("AA 55 90 EB")


def temperature_control_frame(disable: bool) -> bytes:
    if type(disable) is not bool:
        raise ValueError("Temperature disable value must be boolean")
    frame = bytearray(20)
    frame[:4] = HEADER
    frame[4] = 0x28
    frame[5] = 0x04
    frame[6] = 1 if disable else 0
    frame[19] = sum(frame[:19]) & 0xFF
    return bytes(frame)


@dataclass
class Command:
    action: str
    disable: bool | None
    future: asyncio.Future
    register: int | None = None
    value: Any = None


class ControlService:
    def __init__(self, options: Callable[[], dict[str, Any]],
                 addresses: Callable[[str], list[str]]) -> None:
        self.options = options
        self.addresses = addresses
        self.sessions: dict[str, asyncio.Queue[Command]] = {}
        self.server: asyncio.AbstractServer | None = None
        self.last_write: dict[str, float] = {}
        self.mqtt_sink = None  # Installed only when MQTT is configured.

    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self.handle, "127.0.0.1", 1896, limit=4096
        )
        LOG.info("JK-BMS private command endpoint listening on 127.0.0.1:1896")

    async def close(self) -> None:
        for mac in list(self.sessions):
            self.unregister(mac)
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    def register(self, mac: str) -> asyncio.Queue[Command]:
        if mac in self.sessions:
            raise RuntimeError("Duplicate BLE command session for "+mac)
        queue: asyncio.Queue[Command] = asyncio.Queue(maxsize=1)
        self.sessions[mac] = queue
        return queue

    def unregister(self, mac: str) -> None:
        queue = self.sessions.pop(mac, None)
        if queue is not None:
            while not queue.empty():
                command = queue.get_nowait()
                if not command.future.done():
                    command.future.set_exception(ConnectionError(
                        "BMS disconnected before sending command"
                    ))

    async def dispatch(self, payload: Any) -> tuple[int, dict[str, Any]]:
        if not isinstance(payload, dict):
            return 400, {"error": "invalid_body"}
        cfg = self.options()
        mac = payload.get("address")
        configured = self.addresses(str(cfg.get("bms_addresses", "")))
        if not isinstance(mac, str) or mac not in configured:
            return 403, {"error": "bms_not_configured"}
        action = payload.get("action")
        if action not in {"refresh", "set_temperature_disabled", "write_parameter"}:
            return 400, {"error": "action_not_allowed"}
        if action in ("write_parameter", "set_temperature_disabled"):
            if (self.mqtt_sink is None or
                    not self.mqtt_sink.permission.get(mac, False)):
                return 403, {"error": "allow_parameter_changes_disabled_for_bms"}
        if action == "write_parameter":
            if payload.get("confirmation") != CONFIRM:
                return 403, {"error": "explicit_confirmation_required"}
            register=payload.get("register")
            if type(register) is not int or register not in BY_REGISTER:
                return 403, {"error": "unsupported_register"}
            try:
                build_write(register,payload.get("value"))
            except (ValueError,OverflowError) as exc:
                return 400, {"error": "invalid_parameter_value", "details": str(exc)}
        if action == "set_temperature_disabled":
            if payload.get("confirmation") != CONFIRM:
                return 403, {"error": "explicit_confirmation_required"}
            if type(payload.get("disable")) is not bool:
                return 400, {"error": "boolean_disable_value_required"}
            last = self.last_write.get(mac, 0.0)
            if asyncio.get_running_loop().time()-last < 15:
                return 429, {"error": "write_rate_limit_15s"}
        if action == "write_parameter" and asyncio.get_running_loop().time()-self.last_write.get(mac,0.0)<15:
            return 429, {"error": "write_rate_limit_15s"}
        queue = self.sessions.get(mac)
        if queue is None:
            return 409, {"error": "bms_not_connected_or_no_persistent_session"}
        if queue.full():
            return 429, {"error": "bms_command_already_pending"}
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await queue.put(Command(action, payload.get("disable"), future,
                                payload.get("register"),payload.get("value")) )
        if action in ("set_temperature_disabled","write_parameter"):
            self.last_write[mac] = loop.time()
            if action == "set_temperature_disabled":
                LOG.warning("MANUAL JK02 TEMPERATURE PROTECTION WRITE REQUEST for %s: disabled=%s",
                            mac,payload["disable"])
            else:
                LOG.warning("MANUAL JK02 PARAMETER WRITE REQUEST for %s: register=0x%02X",
                            mac,payload["register"])
        try:
            result = await asyncio.wait_for(future, 12)
            return 202, {"address": mac, "write_sent": action in ("set_temperature_disabled","write_parameter"),
                         "verified_by_bms": False, "action": action, **result}
        except asyncio.TimeoutError:
            return 504, {"error": "command_timeout_unverified"}
        except (ConnectionError, RuntimeError, OSError) as exc:
            return 503, {"error": "command_not_completed", "details": str(exc)}

    async def handle(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter) -> None:
        status = 500
        body: dict[str, Any] = {"error":"internal_error"}
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 4)
            if len(request) > 4096:
                status, body = 413, {"error":"headers_too_long"}
            else:
                lines = request.decode("latin-1").split("\r\n")
                method, path, *_ = lines[0].split()
                headers = {}
                for line in lines[1:]:
                    if ":" in line:
                        name, value = line.split(":", 1)
                        headers[name.strip().lower()] = value.strip()
                token = os.environ.get("BLE_BRIDGE_TOKEN","")
                if not token or not hmac.compare_digest(
                    headers.get("x-ble-bridge-token",""), token
                ):
                    status, body = 401, {"error":"unauthorized"}
                elif method != "POST" or path not in ("/control", "/mqtt"):
                    status, body = 404, {"error":"not_found"}
                elif not headers.get("content-type","").startswith("application/json"):
                    status, body = 415, {"error":"expected_json"}
                else:
                    length = int(headers.get("content-length","0"))
                    if not 0 < length <= (16384 if path == "/mqtt" else 2048):
                        status, body = 413, {"error":"invalid_content_length"}
                    else:
                        data = await asyncio.wait_for(reader.readexactly(length), 4)
                        payload = json.loads(data)
                        if path == "/mqtt":
                            if self.mqtt_sink is None:
                                status, body = 503, {"error":"mqtt_not_configured"}
                            elif self.mqtt_sink.ingest(payload):
                                status, body = 202, {"ok":True}
                            else:
                                status, body = 422, {"error":"rejected_invalid_mqtt_event"}
                        else:
                            status, body = await self.dispatch(payload)
        except (ValueError, json.JSONDecodeError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError, asyncio.TimeoutError) as exc:
            status, body = 400, {"error":"bad_request"}
        except Exception:
            LOG.exception("Control endpoint internal error")
        finally:
            data = json.dumps(body, separators=(",",":")).encode("utf-8")
            reason = {202:"Accepted",400:"Bad Request",401:"Unauthorized",
                      403:"Forbidden",404:"Not Found",409:"Conflict",
                      413:"Payload Too Large",415:"Unsupported Media Type",
                      422:"Unprocessable Entity",
                      429:"Too Many Requests",500:"Internal Server Error",
                      503:"Service Unavailable",504:"Gateway Timeout"}.get(status,"Error")
            writer.write((
                f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(data)}\r\nConnection: close\r\n"
                "Cache-Control: no-store\r\n\r\n"
            ).encode("ascii")+data)
            try:
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
