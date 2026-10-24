"""Smart JK-BMS BLE diagnostics bridge, development milestone v0.1.0.

Read-only: scans host BlueZ adapters, probes connections to configured JK-BMS
devices, optionally observes FFE1 notifications, and reports raw events to
Node-RED. No BMS settings writes, polling or measurements decoding.
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

LOG = logging.getLogger("smart_jkbms_ble")
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
MAC_PATTERN = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")


def emit(event_type: str, **data: Any) -> None:
    event = {"type": event_type, "time": time.time(), **data}
    LOG.info("BLE event: %s", json.dumps(event, ensure_ascii=False))
    url = os.environ.get("BLE_BRIDGE_ENDPOINT", "http://127.0.0.1:1895/internal/ble/events")
    token = os.environ.get("BLE_BRIDGE_TOKEN", "")
    if not token:
        LOG.error("Missing internal bridge token")
        return
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
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        LOG.warning("Node-RED event forwarding failed: %s", exc)


async def forward(event_type: str, **data: Any) -> None:
    await asyncio.to_thread(emit, event_type, **data)


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


async def scan(cfg: dict[str, Any]) -> None:
    adapter = str(cfg.get("bluetooth_adapter", "auto"))
    duration = int(cfg.get("scan_duration_seconds", 8))
    show_all = bool(cfg.get("scan_all_devices", False))
    await forward("scan_start", adapter=adapter, duration_seconds=duration)
    try:
        detected = await BleakScanner.discover(
            timeout=duration, return_adv=True, **scan_kwargs(adapter)
        )
        jk_count = 0
        for address, (device, advertisement) in detected.items():
            name = (advertisement.local_name or device.name or "").strip()
            is_candidate = "JK" in name.upper() or "BMS" in name.upper()
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
    except Exception as exc:
        LOG.exception("BLE discovery failed")
        await forward("scan_error", adapter=adapter, error=f"{type(exc).__name__}: {exc}")


async def probe(address: str, cfg: dict[str, Any]) -> None:
    adapter = str(cfg.get("bluetooth_adapter", "auto"))
    listen = int(cfg.get("connection_probe_seconds", 15))
    await forward("connection_start", address=address)
    try:
        kwargs = scan_kwargs(adapter)
        # Talks to host BlueZ over D-Bus; does not take control of the HCI adapter.
        async with BleakClient(address, timeout=15, **kwargs) as client:
            services = list(client.services)
            characteristics = [c for s in services for c in s.characteristics]
            chosen = next(
                (c for c in characteristics if c.uuid.lower() == FFE1 and "notify" in c.properties),
                None,
            )
            await forward(
                "connected",
                address=address,
                services=[str(s.uuid) for s in services],
                notify_characteristic=FFE1 if chosen is not None else None,
            )
            if chosen is None:
                await forward("notify_unavailable", address=address)
                await asyncio.sleep(min(listen, 5))
                return

            def on_notification(_characteristic: Any, data: bytearray) -> None:
                # BLE notifications can be fragments, not valid complete JK frames.
                asyncio.create_task(
                    forward(
                        "raw_notification",
                        address=address,
                        characteristic=FFE1,
                        length=len(data),
                        hex=bytes(data).hex(" ").upper(),
                    )
                )

            await client.start_notify(chosen, on_notification)
            await asyncio.sleep(listen)
            await client.stop_notify(chosen)
    except Exception as exc:
        LOG.exception("BLE connection probe failed for %s", address)
        await forward("connection_error", address=address, error=f"{type(exc).__name__}: {exc}")
    finally:
        await forward("disconnected", address=address)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    await forward("bridge_start", version="0.1.0", note="read_only_discovery_and_connection_probe")
    while True:
        try:
            cfg = options()
            await scan(cfg)
            for address in addresses(str(cfg.get("bms_addresses", ""))):
                await probe(address, cfg)
            await asyncio.sleep(max(20, int(cfg.get("scan_interval_seconds", 45))))
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("Unexpected BLE bridge error; retrying")
            await asyncio.sleep(20)


if __name__ == "__main__":
    asyncio.run(main())
