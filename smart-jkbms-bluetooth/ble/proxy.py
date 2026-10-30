"""ESPHome Bluetooth Proxy transport for JK-BMS (optional, no local BlueZ required).

Proxy mode uses the official ESPHome API and habluetooth's remote GATT
scanner/client wrappers. It never tries the host's Bluetooth adapter.
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Awaitable

LOG = logging.getLogger("smart_jkbms_ble.proxy")
HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")


def proxy_enabled(cfg: dict[str, Any]) -> bool:
    return cfg.get("ble_connection_mode", "local") == "esphome_proxy"


def proxy_config(cfg: dict[str, Any]) -> dict[str, str | None]:
    host = str(cfg.get("proxy_host") or "").strip()
    if not host or not HOST.fullmatch(host) or ".." in host or host.endswith("."):
        raise ValueError("ESPHome proxy_host must be an IPv4 address or DNS host (without port)")
    # IPv4 literals are supported, hostnames use ESPHome LAN DNS; require
    # users to enter the address without a URL, port or credentials.
    if re.fullmatch(r"[\d.]+", host):
        ip = ipaddress.ip_address(host)
        if ip.version != 4:
            raise ValueError("proxy_host must be an IPv4 address or DNS hostname")
    key = str(cfg.get("proxy_noise_psk") or "").strip()
    if key:
        try:
            decoded = base64.b64decode(key, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("proxy_noise_psk must be the ESPHome API encryption key (base64)") from exc
        if len(decoded) != 32:
            raise ValueError("proxy_noise_psk must decode to a 32-byte ESPHome API key")
    return {"address": host, "noise_psk": key or None}


def ble_classes(cfg: dict[str, Any]):
    """Return the matching Bleak scanner/client pair without monkey-patching."""
    if proxy_enabled(cfg):
        from habluetooth import HaBleakClientWrapper, HaBleakScannerWrapper
        return HaBleakScannerWrapper, HaBleakClientWrapper
    from bleak import BleakClient, BleakScanner
    return BleakScanner, BleakClient


@asynccontextmanager
async def proxy_session(
    cfg: dict[str, Any],
    notify: Callable[..., Awaitable[bool]] | None = None,
) -> AsyncIterator[None]:
    """Run an auto-reconnecting ESPHome API connection for this bridge.

    A slow/offline ESP32 cannot block MQTT startup or Node-RED diagnostics.
    The background API manager registers a remote scanner when connected.
    """
    if not proxy_enabled(cfg):
        yield
        return

    connection = proxy_config(cfg)
    import habluetooth
    from bleak_esphome import APIConnectionManager

    manager = habluetooth.BluetoothManager()
    habluetooth.set_manager(manager)
    await manager.async_setup()
    remote = APIConnectionManager(connection)
    host = str(connection["address"])

    async def establish() -> None:
        try:
            await remote.start()
            LOG.info("ESPHome Bluetooth Proxy API connected: %s", host)
            if notify:
                await notify("proxy_connected", host=host, port=6053)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.error("ESPHome Bluetooth Proxy connection failed (%s): %s", host, exc)
            if notify:
                await notify("proxy_connection_error", host=host,
                             error=f"{type(exc).__name__}: {exc}")

    startup = asyncio.create_task(establish(), name="esphome-proxy-start")
    LOG.info("Connecting to ESPHome Bluetooth Proxy at %s:6053", host)
    try:
        if notify:
            await notify("proxy_connecting", host=host, port=6053)
        yield
    finally:
        # Stop reconnect logic first; it also cancels unfinished startup.
        try:
            await remote.stop()
        finally:
            startup.cancel()
            await asyncio.gather(startup, return_exceptions=True)
            await manager.async_stop()
