"""Smart JK-BMS BLE diagnostics bridge, development milestone v0.2.9.

Read-only: scans host BlueZ adapters, probes connections to configured JK-BMS
devices, optionally observes FFE1 notifications, and reports raw events to
Node-RED. Sends only approved 0x97/0x96 read requests. Measurement parsing is done in Node-RED.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakDBusError, BleakDeviceNotFoundError

from control import ControlService, temperature_control_frame
from parameters import build_write

LOG = logging.getLogger("smart_jkbms_ble")
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
MAC_PATTERN = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")
JK_READ_COMMANDS = (0x97, 0x96)
JK_WRITE_HEADER = bytes.fromhex("AA 55 90 EB")
RESET_MARKER = Path("/data/.ble_adapter_reset_last")
RESET_COOLDOWN_SECONDS = 3600
CONTROL = ControlService(options=lambda: options(), addresses=lambda raw: addresses(raw))


def build_read_command(command: int) -> bytes:
    """Build only documented 20-byte JK02 read requests, with sum8 CRC."""
    if command not in JK_READ_COMMANDS:
        raise ValueError("Command is not an approved read-only JK02 request")
    frame = bytearray(20)
    frame[0:4] = JK_WRITE_HEADER
    frame[4] = command
    frame[19] = sum(frame[:19]) & 0xFF
    return bytes(frame)



def emit(event_type: str, **data: Any) -> bool:
    event = {"type": event_type, "time": time.time(), **data}
    url = os.environ.get("BLE_BRIDGE_ENDPOINT", "http://127.0.0.1:1895/internal/ble/events")
    token = os.environ.get("BLE_BRIDGE_TOKEN", "")
    if not token:
        LOG.error("Missing internal bridge token")
        return False
    body = json.dumps(event, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "X-BLE-Bridge-Token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            if response.status not in (200, 202, 204):
                LOG.warning("Node-RED bridge response status: %d", response.status)
                return False
        if event_type not in {"raw_notification", "unrecognized_at"}:
            LOG.info("BLE event: %s", json.dumps(event, ensure_ascii=False))
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if event_type != "bridge_start":
            LOG.warning("Node-RED event forwarding failed: %s", exc)
        return False


async def forward(event_type: str, **data: Any) -> bool:
    return await asyncio.to_thread(emit, event_type, **data)


def options() -> dict[str, Any]:
    path = Path(os.environ.get("BLE_OPTIONS_FILE", "/data/options.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def scan_kwargs(adapter: str) -> dict[str, Any]:
    return {} if adapter == "auto" else {"bluez": {"adapter": adapter}}


def addresses(raw: str) -> list[str]:
    result: list[str] = []
    for item in re.split(r"[,;\s]+", raw.strip()):
        if not item:
            continue
        if not MAC_PATTERN.fullmatch(item):
            LOG.warning("Ignoring invalid BMS Bluetooth address: %r", item)
            continue
        normalized = item.upper()
        if normalized not in result:
            result.append(normalized)
    return result


async def scan(cfg: dict[str, Any]) -> dict[str, BLEDevice]:
    adapter = str(cfg.get("bluetooth_adapter", "auto"))
    duration = int(cfg.get("scan_duration_seconds", 8))
    show_all = bool(cfg.get("scan_all_devices", False))
    known_addresses = set(addresses(str(cfg.get("bms_addresses", ""))))
    await forward("scan_start", adapter=adapter, duration_seconds=duration)
    try:
        detected = await BleakScanner.discover(
            timeout=duration, return_adv=True, **scan_kwargs(adapter)
        )
        jk_count = 0
        found: dict[str, BLEDevice] = {}
        for address, (device, advertisement) in detected.items():
            found[address.upper()] = device
            name = (advertisement.local_name or device.name or "").strip()
            is_candidate = "JK" in name.upper() or "BMS" in name.upper() or address.upper() in known_addresses
            if not show_all and not is_candidate:
                continue
            if is_candidate:
                jk_count += 1
            await forward(
                "device_found",
                address=address,
                name=name or "Unknown",
                rssi=advertisement.rssi,
                service_uuids=advertisement.service_uuids,
                candidate=is_candidate,
                adapter=adapter,
            )
        await forward("scan_complete", scanned_count=len(detected), jk_candidates=jk_count)
        return found
    except Exception as exc:
        LOG.exception("BLE discovery failed")
        await forward("scan_error", adapter=adapter, error=f"{type(exc).__name__}: {exc}")
        return {}



async def _power_cycle_adapter_dbus(adapter: str) -> bool:
    """Explicit opt-in only: host-wide adapter power reset via BlueZ D-Bus."""
    from dbus_fast import BusType, Variant
    from dbus_fast.aio import MessageBus

    bus = await asyncio.wait_for(MessageBus(bus_type=BusType.SYSTEM).connect(), timeout=8)
    props = None
    off_attempted = False
    try:
        path = f"/org/bluez/{adapter}"
        introspect = await asyncio.wait_for(bus.introspect("org.bluez", path), timeout=8)
        obj = bus.get_proxy_object("org.bluez", path, introspect)
        props = obj.get_interface("org.freedesktop.DBus.Properties")
        powered = await asyncio.wait_for(props.call_get("org.bluez.Adapter1", "Powered"), timeout=8)
        if not powered.value:
            raise RuntimeError("Adapter was already off; refusing to change its power state")
        off_attempted = True
        await asyncio.wait_for(
            props.call_set("org.bluez.Adapter1", "Powered", Variant("b", False)),
            timeout=8,
        )
        await asyncio.sleep(2)
    finally:
        try:
            # Restore power even if the power-off call times out after changing
            # the controller state. Never leave the host adapter disabled.
            if off_attempted and props is not None:
                await asyncio.wait_for(
                    props.call_set("org.bluez.Adapter1", "Powered", Variant("b", True)),
                    timeout=10,
                )
                await asyncio.sleep(3)
        finally:
            bus.disconnect()
    return True


async def maybe_reset_adapter_on_start(cfg: dict[str, Any]) -> bool:
    if not bool(cfg.get("adapter_reset_on_start", False)):
        return False
    adapter = str(cfg.get("bluetooth_adapter", "auto")).lower()
    if not re.fullmatch(r"hci[0-3]", adapter):
        await forward(
            "adapter_reset_skipped", adapter=adapter,
            reason="Select a specific hci0/hci1/hci2/hci3; auto is unsafe",
        )
        return False
    # Persist a one-hour cooldown BEFORE the power cycle. Even if the add-on
    # crashes during a reset, it will not repeatedly disrupt Home Assistant.
    now = time.time()
    try:
        if RESET_MARKER.exists():
            last = float(RESET_MARKER.read_text(encoding="utf-8").strip())
            if 0 <= now - last < RESET_COOLDOWN_SECONDS:
                await forward("adapter_reset_skipped", adapter=adapter,
                              reason="Power-cycle already attempted within one hour")
                return False
        RESET_MARKER.parent.mkdir(parents=True, exist_ok=True)
        RESET_MARKER.write_text(str(now), encoding="utf-8")
    except (OSError, ValueError) as exc:
        await forward("adapter_reset_skipped", adapter=adapter,
                      reason=f"Cannot safely persist reset cooldown: {exc}")
        return False

    await forward(
        "adapter_reset_start", adapter=adapter,
        warning="All Home Assistant devices on this host adapter may disconnect",
    )
    try:
        restarted = await _power_cycle_adapter_dbus(adapter)
    except Exception as exc:
        LOG.warning("Optional adapter reset failed on %s: %s", adapter, exc)
        await forward("adapter_reset_failed", adapter=adapter,
                      error=f"{type(exc).__name__}: {exc}",
                      note="Continuing normal BLE scanning")
        return False
    if restarted:
        await forward("adapter_reset_complete", adapter=adapter)
    return restarted


async def recover_missing_devices(
    cfg: dict[str, Any], found: dict[str, BLEDevice], *, startup: bool
) -> dict[str, BLEDevice]:
    """Extra scanning for missing configured BMS; never reset the adapter."""
    wanted = addresses(str(cfg.get("bms_addresses", "")))
    missing = [a for a in wanted if a not in found]
    if not missing:
        return found
    attempts = 2 if startup else 1
    extended = dict(cfg)
    extended["scan_duration_seconds"] = max(
        15, int(cfg.get("scan_duration_seconds", 8))
    )
    for attempt in range(1, attempts + 1):
        await forward("recovery_scan_start", missing_addresses=missing,
                      attempt=attempt, max_attempts=attempts,
                      duration_seconds=extended["scan_duration_seconds"])
        await asyncio.sleep(1)
        more = await scan(extended)
        found.update(more)
        missing = [a for a in wanted if a not in found]
        await forward(
            "recovery_scan_result", missing_addresses=missing,
            available_addresses=[a for a in wanted if a in found], attempt=attempt,
        )
        if not missing:
            break
    return found


async def probe(address: str, cfg: dict[str, Any], device: BLEDevice, *, persistent: bool = False) -> None:
    adapter = str(cfg.get("bluetooth_adapter", "auto"))
    listen = int(cfg.get("connection_probe_seconds", 15))
    await forward("connection_start", address=address)
    try:
        kwargs = scan_kwargs(adapter)
        link_lost = asyncio.Event()
        if persistent:
            kwargs["disconnected_callback"] = lambda _client: link_lost.set()
        # Uses host BlueZ; this add-on never automatically power-cycles its adapter.
        async with BleakClient(device, timeout=15, **kwargs) as client:
            services = list(client.services)
            characteristics = [c for s in services for c in s.characteristics]
            notify_char = next(
                (c for c in characteristics if c.uuid.lower() == FFE1 and "notify" in c.properties), None
            )
            write_char = next(
                (
                    c for c in characteristics
                    if c.uuid.lower() == FFE1
                    and ("write-without-response" in c.properties or "write" in c.properties)
                ), None
            )
            await forward(
                "connected", address=address,
                services=[str(s.uuid) for s in services],
                ffe1_characteristics=[
                    {"handle": c.handle, "properties": sorted(c.properties)}
                    for c in characteristics if c.uuid.lower() == FFE1
                ],
                notify_characteristic=FFE1 if notify_char else None,
                write_characteristic=FFE1 if write_char else None
            )
            if notify_char is None:
                await forward("notify_unavailable", address=address)
                await asyncio.sleep(min(listen, 5))
                return

            at_notifications = {"last_report": 0.0, "count": 0}
            stream = {"last_data": time.monotonic(), "refresh_sent": False}

            def on_notification(_characteristic: Any, data: bytearray) -> None:
                # BLE notifications can be fragments, not complete JK frames.
                raw = bytes(data)
                if raw == b"AT\r\n":
                    at_notifications["count"] += 1
                    now = time.monotonic()
                    # Repeated ASCII AT/CRLF messages are not JK02 frames;
                    # summarize them instead of flooding logs and Node-RED.
                    if now - at_notifications["last_report"] < 10.0:
                        return
                    at_notifications["last_report"] = now
                    asyncio.create_task(
                        forward(
                            "unrecognized_at",
                            address=address,
                            sample_hex="41 54 0D 0A",
                            count_since_connection=at_notifications["count"],
                        )
                    )
                    return
                stream["last_data"] = time.monotonic()
                stream["refresh_sent"] = False
                asyncio.create_task(
                    forward(
                        "raw_notification",
                        address=address,
                        characteristic=FFE1,
                        length=len(raw),
                        hex=raw.hex(" ").upper(),
                    )
                )

            await client.start_notify(notify_char, on_notification)

            async def send_read_handshake(
                reason: str, commands: tuple[int, ...] = JK_READ_COMMANDS
            ) -> list[str]:
                # Per syssi/JK02: 0x97 requests device info, 0x96 settings;
                # frame 0x02 is then sent automatically. Never alter BMS settings.
                if not bool(cfg.get("read_only_requests", True)):
                    await forward("read_requests_disabled", address=address)
                    return []
                if write_char is None:
                    await forward("read_unavailable", address=address,
                                  message="FFE1 write characteristic not found")
                    return []
                response = "write-without-response" not in write_char.properties
                sent = []
                for command in commands:
                    packet = build_read_command(command)
                    await client.write_gatt_char(write_char, packet, response=response)
                    await forward(
                        "read_request_sent", address=address,
                        command=f"0x{command:02X}", handle=write_char.handle,
                        frame_hex=packet.hex(" ").upper(), reason=reason
                    )
                    sent.append(f"0x{command:02X}")
                    await asyncio.sleep(0.6)
                return sent

            await send_read_handshake("initial")
            if persistent:
                control_queue = CONTROL.register(address)
                # JK settings 0x01 is usually sent *only* on request. A single
                # handshake at startup becomes stale within minutes; refresh
                # the settings at a gentle, read-only interval per BMS.
                last_settings_read=time.monotonic()
                await forward("session_persistent", address=address)
                try:
                    while client.is_connected and not link_lost.is_set():
                        if not control_queue.empty():
                            command = control_queue.get_nowait()
                            try:
                                if command.action == "refresh":
                                    sent = await send_read_handshake(
                                        "manual_settings_refresh", (0x96,))
                                    last_settings_read=time.monotonic()
                                    if not sent:
                                        raise RuntimeError("JK settings request disabled/unavailable")
                                    result = {"requests_sent": sent}
                                elif command.action == "write_parameter":
                                    if write_char is None:
                                        raise RuntimeError("BLE write characteristic unavailable")
                                    packet = build_write(command.register,command.value)
                                    response = "write-without-response" not in write_char.properties
                                    await client.write_gatt_char(write_char,packet,response=response)
                                    await forward("parameter_write_sent",address=address,
                                      register=f"0x{command.register:02X}",
                                      confirmed_by_bms=False)
                                    await asyncio.sleep(0.5)
                                    await send_read_handshake("verify_modified_parameter")
                                    result={"register":f"0x{command.register:02X}"}
                                elif command.action == "set_temperature_disabled":
                                    if write_char is None:
                                        raise RuntimeError("BLE write characteristic unavailable")
                                    packet = temperature_control_frame(command.disable)
                                    response = "write-without-response" not in write_char.properties
                                    await client.write_gatt_char(write_char, packet, response=response)
                                    await forward("temperature_protection_write_sent",
                                                  address=address,
                                                  disabled=command.disable,
                                                  register="0x28",
                                                  confirmed_by_bms=False)
                                    await asyncio.sleep(0.5)
                                    await send_read_handshake("verify_temperature_setting")
                                    result = {"register": "0x28"}
                                else:
                                    raise RuntimeError("Unexpected command action")
                                if not command.future.done():
                                    command.future.set_result(result)
                            except Exception as exc:
                                if not command.future.done():
                                    command.future.set_exception(exc)
                        if (time.monotonic()-last_settings_read>=120 and
                            bool(cfg.get("read_only_requests",True))):
                            try:
                                sent=await send_read_handshake(
                                    "periodic_settings_refresh",(0x96,))
                                if sent:
                                    last_settings_read=time.monotonic()
                            except Exception as exc:
                                LOG.warning("Settings read 0x96 failed for %s: %s",
                                            address,exc)
                                last_settings_read=time.monotonic()
                        # AT/CRLF heartbeats alone are not proof of telemetry.
                        age = time.monotonic() - stream["last_data"]
                        if age > 90:
                            await forward("stream_stale", address=address,
                                          no_data_seconds=round(age),
                                          action="reconnect_this_BMS_only")
                            break
                        if (
                            age > 45 and not stream["refresh_sent"]
                            and bool(cfg.get("read_only_requests", True))
                        ):
                            stream["refresh_sent"] = True
                            await forward("stream_refresh", address=address,
                                          no_data_seconds=round(age))
                            await send_read_handshake("stream_refresh")
                        try:
                            await asyncio.wait_for(link_lost.wait(), timeout=1)
                        except asyncio.TimeoutError:
                            pass
                finally:
                    CONTROL.unregister(address)
            else:
                await asyncio.sleep(listen)
            if client.is_connected:
                await client.stop_notify(notify_char)
            return

    except BleakDBusError as exc:
        if (exc.dbus_error == "org.bluez.Error.NotPermitted"
                and "Notify acquired" in str(exc.dbus_error_details or "")):
            LOG.warning("FFE1 notification access reserved for %s by another BlueZ client; "
                        "stop the competing integration or release its BLE connection", address)
            await forward("notification_reserved", address=address,
                          characteristic=FFE1,
                          note="Notify acquired: another BlueZ client holds exclusive FFE1 notifications",
                          action="stop_other_BLE_reader_then_retry")
        else:
            LOG.exception("BLE connection probe failed for %s", address)
            await forward("connection_error", address=address,
                          error=f"{type(exc).__name__}: {exc}")
    except BleakDeviceNotFoundError as exc:
        LOG.warning("Discovered BLE device disappeared before connection: %s", address)
        await forward("connection_error", address=address, error=f"{type(exc).__name__}: {exc}", retry_on_next_scan=True)
    except Exception as exc:
        LOG.exception("BLE connection probe failed for %s", address)
        await forward("connection_error", address=address, error=f"{type(exc).__name__}: {exc}")
    finally:
        await forward("disconnected", address=address)


async def poll_cycle(cfg: dict[str, Any], *, startup: bool) -> None:
    """Probe discovered batteries FIRST, recover missing batteries SECOND.

    A missing battery never delays polling a healthy battery.
    """
    found = await scan(cfg)
    configured = addresses(str(cfg.get("bms_addresses", "")))
    missing = []
    for address in configured:
        device = found.get(address)
        if device is not None:
            await probe(address, cfg, device)
        else:
            missing.append(address)
    if not missing:
        return
    extended = await recover_missing_devices(cfg, found, startup=startup)
    for address in missing:
        device = extended.get(address)
        if device is None:
            await forward("device_not_seen", address=address,
                          message="Not advertised after recovery scans; retry next cycle")
        else:
            await probe(address, cfg, device)




def bluez_cached_connected(
    managed: dict[str, Any], adapter: str, wanted: list[str]
) -> dict[str, BLEDevice]:
    """Use only already-connected BMS objects known by BlueZ.

    After an add-on restart, a BMS connected in BlueZ may not advertise.
    This does not disconnect, pair, or remove any Bluetooth device.
    """
    matches: dict[str, BLEDevice] = {}
    selected = set(wanted)
    for path, interfaces in managed.items():
        if not isinstance(path, str) or not path.startswith("/org/bluez/hci"):
            continue
        parts = path.split("/")
        if len(parts) != 5 or not parts[4].startswith("dev_"):
            continue
        controller = parts[3]
        if adapter != "auto" and controller != adapter:
            continue
        props_map = interfaces.get("org.bluez.Device1", {})
        # dbus-fast ObjectManager properties contain D-Bus Variant values.
        props = {k: getattr(v, "value", v) for k, v in props_map.items()}
        address = str(props.get("Address", "")).upper()
        if address not in selected or not props.get("Connected", False):
            continue
        name = str(props.get("Name") or props.get("Alias") or "JK-BMS")
        matches[address] = BLEDevice(
            address, name, {"path": path, "props": props}
        )
    # A cached BlueZ connection may be owned by another process that has
    # exclusive access to FFE1 via AcquireNotify. Checking this property
    # prevents reconnecting/disconnecting that process's shared link.
    for char_path, interfaces in managed.items():
        props_map = interfaces.get("org.bluez.GattCharacteristic1", {})
        if not props_map:
            continue
        props = {k: getattr(v, "value", v) for k, v in props_map.items()}
        if str(props.get("UUID", "")).lower() != FFE1 or props.get("NotifyAcquired") is not True:
            continue
        for device in matches.values():
            if char_path.startswith(device.details["path"] + "/"):
                device.details["notify_acquired"] = True
    return matches


async def find_bluez_connected(
    cfg: dict[str, Any], wanted: list[str]
) -> dict[str, BLEDevice]:
    if not wanted:
        return {}
    adapter = str(cfg.get("bluetooth_adapter", "auto"))
    bus = None
    try:
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus
        bus = await asyncio.wait_for(
            MessageBus(bus_type=BusType.SYSTEM).connect(), timeout=5
        )
        introspection = await asyncio.wait_for(
            bus.introspect("org.bluez", "/"), timeout=5
        )
        proxy = bus.get_proxy_object("org.bluez", "/", introspection)
        manager = proxy.get_interface("org.freedesktop.DBus.ObjectManager")
        objects = await asyncio.wait_for(
            manager.call_get_managed_objects(), timeout=8
        )
        matched = bluez_cached_connected(objects, adapter, wanted)
        for address in wanted:
            if address in matched and matched[address].details.get("notify_acquired"):
                await forward(
                    "notification_reserved", address=address, adapter=adapter,
                    characteristic=FFE1,
                    note="FFE1 AcquireNotify already held by another BlueZ client; waiting without disconnecting the device",
                )
            elif address in matched:
                await forward(
                    "bluez_connected_recovered",
                    address=address,
                    adapter=adapter,
                    name=matched[address].name,
                    note="Reuse existing BlueZ GATT connection without advertisement",
                )
        if not matched:
            await forward(
                "bluez_connected_not_found",
                adapter=adapter, missing_addresses=wanted,
                note="No configured BMS marked Connected in BlueZ cache",
            )
        return matched
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await forward(
            "bluez_cache_unavailable", adapter=adapter,
            error=f"{type(exc).__name__}: {exc}",
        )
        return {}
    finally:
        if bus is not None:
            bus.disconnect()


async def persistent_sessions(initial_cfg: dict[str, Any]) -> None:
    """One long-running BLE session per configured BMS; independent reconnection.

    Discovery is shared and serialized. Only missing/disconnected BMS are
    scanned. There is at most one connection task per configured MAC address.
    """
    workers: dict[str, asyncio.Task[None]] = {}
    started: dict[str, float] = {}
    failures: dict[str, int] = {}
    retry_at: dict[str, float] = {}
    first_scan = True
    next_scan = 0.0
    await forward("persistent_manager_start", mode="one_session_per_BMS")
    try:
        while True:
            cfg = options()
            configured = addresses(str(cfg.get("bms_addresses", "")))
            now = time.monotonic()

            # Handle removals in add-on config and dead connections independently.
            for mac, task in list(workers.items()):
                if mac not in configured:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    del workers[mac]
                    retry_at.pop(mac, None)
                elif task.done():
                    await asyncio.gather(task, return_exceptions=True)
                    del workers[mac]
                    lived = now - started.get(mac, now)
                    failures[mac] = 0 if lived > 60 else min(5, failures.get(mac, 0) + 1)
                    delay = min(120, max(10, 10 * (2 ** max(0, failures[mac] - 1))))
                    retry_at[mac] = now + delay
                    await forward("reconnect_scheduled", address=mac,
                                  delay_seconds=delay, previous_session_seconds=round(lived))

            missing = [mac for mac in configured if mac not in workers]
            eligible = [mac for mac in missing if now >= retry_at.get(mac, 0.0)]
            if now >= next_scan and (eligible or not configured):
                # A BlueZ connection surviving an add-on restart may prevent
                # the BMS from advertising. Try its existing BlueZ GATT object
                # before trying further BLE advertising scans.
                cached = await find_bluez_connected(cfg, eligible)
                # The foreign AcquireNotify owner must release FFE1. Scanning,
                # reconnecting or resetting hci0 cannot safely steal the lock.
                reserved = {mac for mac, device in cached.items()
                            if getattr(device, "details", {}).get("notify_acquired")}
                for mac in reserved:
                    retry_at[mac] = time.monotonic() + 60
                    cached.pop(mac)
                eligible = [mac for mac in eligible if mac not in reserved]
                need_scan = [a for a in eligible if a not in cached]
                found = await scan(cfg) if (need_scan or not configured) else {}
                found.update(cached)
                # Start healthy discovered batteries immediately, without waiting
                # for extra scans aimed at a missing battery.
                for mac in eligible:
                    device = found.get(mac)
                    if device is None:
                        continue
                    workers[mac] = asyncio.create_task(
                        probe(mac, cfg, device, persistent=True),
                        name="jk-bms:" + mac
                    )
                    started[mac] = time.monotonic()
                    await asyncio.sleep(0.5)

                still_missing = [mac for mac in eligible if mac not in workers]
                if still_missing and first_scan:
                    # The initial reboot can leave some batteries briefly silent.
                    extra = await recover_missing_devices(cfg, found, startup=True)
                    for mac in still_missing:
                        device = extra.get(mac)
                        if device is None:
                            await forward("device_not_seen", address=mac,
                                          message="Absent after startup recovery scans")
                            continue
                        workers[mac] = asyncio.create_task(
                            probe(mac, cfg, device, persistent=True),
                            name="jk-bms:" + mac
                        )
                        started[mac] = time.monotonic()
                        await asyncio.sleep(0.5)
                elif still_missing:
                    for mac in still_missing:
                        await forward("device_not_seen", address=mac,
                                      message="Not advertising; retry next scan")

                first_scan = False
                next_scan = time.monotonic() + max(
                    20, int(cfg.get("scan_interval_seconds", 45))
                )
            await asyncio.sleep(3)
    finally:
        for task in workers.values():
            task.cancel()
        if workers:
            await asyncio.gather(*workers.values(), return_exceptions=True)
        await forward("persistent_manager_stop")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    attempt = 0
    while not await forward(
        "bridge_start", version="0.2.9", note="JK02_BlueZ_FFE1_notify_ownership_diagnostics"
    ):
        if attempt % 10 == 0:
            LOG.info("Waiting for Node-RED HTTP flow on port 1895...")
        attempt += 1
        await asyncio.sleep(1)
    LOG.info("Node-RED diagnostic endpoint ready")
    startup = True
    try:
        await maybe_reset_adapter_on_start(options())
    except Exception:
        LOG.exception("Optional BLE adapter reset encountered an error; proceeding")
    cfg = options()
    if bool(cfg.get("persistent_connections", True)):
        # Import lazily, preserving standalone BLE diagnostics/test mode.
        from mqtt_ha import HomeAssistantMQTT
        publisher = HomeAssistantMQTT(cfg,addresses(str(cfg.get("bms_addresses",""))),
                                      control=CONTROL)
        await CONTROL.start()
        CONTROL.mqtt_sink = publisher
        publisher.start(asyncio.get_running_loop())
        async def mqtt_watchdog() -> None:
            while True:
                await asyncio.sleep(10)
                publisher.watchdog()
        health_task = asyncio.create_task(mqtt_watchdog())
        try:
            await persistent_sessions(cfg)
        finally:
            health_task.cancel()
            try:
                await health_task
            except asyncio.CancelledError:
                pass
            publisher.stop()
            CONTROL.mqtt_sink = None
            await CONTROL.close()
    else:
        await forward("legacy_probe_mode", mode="short_connections")
        while True:
            try:
                cfg = options()
                await poll_cycle(cfg, startup=startup)
                startup = False
                await asyncio.sleep(max(20, int(cfg.get("scan_interval_seconds", 45))))
            except asyncio.CancelledError:
                raise
            except Exception:
                LOG.exception("Unexpected BLE bridge error; retrying")
                await asyncio.sleep(20)


if __name__ == "__main__":
    asyncio.run(main())
