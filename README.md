# Smart JK-BMS Bluetooth — Home Assistant add-on

**Development milestone 0.1.10. Not yet a complete JK-BMS monitoring integration.**

Standalone Bluetooth add-on following the clean repository structure of Smart Voltronic. It uses a local Bluetooth adapter (built into a mini-PC or a Home Assistant OS-compatible USB Bluetooth dongle) via BlueZ D-Bus and Bleak. A full **Node-RED editor is available on port 1895** for diagnostics and future JK-BMS decoding.

## Included in v0.1.10 development milestone

- Home Assistant add-on configuration, Dockerfile and startup script.
- Node-RED 5.0.9 editor, login `pi`, and the same pre-hashed bcrypt password as Smart Voltronic (stored in `settings.js`).
- BLE discovery on the host adapter, optionally including all nearby devices.
- Read-only Bluetooth connection probes use BLEDevice objects retained from discovery; absent configured BMS addresses are skipped until the next scan.
- Detect separate FFE1 write and notify handles; send only documented JK02 read requests `0x97` and `0x96` (optional), then stream raw BLE notifications to Node-RED.
- Python-to-Node-RED local HTTP bridge protected by a random per-installation token.
- Node-RED tabs: **Bluetooth | Diagnostics**, **JK-BMS | Trames**, and **JK-BMS | Mesures** (diagnostic-only JK02 parser).
- Persistent Node-RED flows loaded from `/data/node-red/flows.json` (not `/addon/flows.json`); user modifications are retained on restart.
- Home Assistant options translated into French and English.

**Not yet validated:** decoded cell measurements/SOC/temperature/current against a physical battery; MQTT Discovery and dashboards are not implemented. The only commands sent by this build are JK02 **read requests** `0x97` and `0x96`; no BMS configuration writes.

## Installation

1. In Home Assistant, open **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
2. Add this URL: https://github.com/tapion69/smart-jkbms-bluetooth
3. Install **Smart JK-BMS Bluetooth (Development)**.
4. Node-RED credentials are not configured in the add-on options. Log in as **pi** using the same password as your Smart Voltronic installation.
5. Start the add-on. Access Node-RED at **http://YOUR_HOME_ASSISTANT_IP:1895** from your LAN or trusted VPN.
6. Open **Bluetooth | Diagnostics** and enable the right-side Debug panel. Look for **BLE raw and diagnostics**.
7. If a BMS is discovered, place its Bluetooth MAC address in **bms_addresses** to test an actual connection, then restart the add-on. Multiple MAC addresses can be separated by commas.

If your BLE scanner returns no named JK-BMS devices, temporarily enable **scan_all_devices** to see other advertised peripherals and their RSSI.

BatMON or the official JK app may already be connected to a BMS. Disconnect their active BLE session before connection testing with this add-on. In particular, stop BatMON while testing the same BMS.

## Configuration

- **bluetooth_adapter**: auto, hci0, hci1, hci2, hci3. auto uses the BlueZ-selected adapter.
- **scan_interval_seconds**: pause between full BLE scan/connection-probe cycles.
- **scan_duration_seconds**: duration of discovery.
- **scan_all_devices**: show all advertisements instead of only JK/BMS names.
- **bms_addresses**: comma-separated BLE MAC addresses; blank means scanning only.
- **connection_probe_seconds**: listen duration (seconds) in legacy short-session mode only.
- **persistent_connections**: enabled by default in v0.1.8. Runs one independent long-lived BlueZ/Bleak connection per configured battery instead of repeatedly disconnecting after 15 seconds. Set false to restore the v0.1.7 short-session behavior.
- **read_only_requests**: enabled by default; sends JK02 read requests 0x97 and 0x96 to the writable FFE1 characteristic, not to the notification characteristic. Disable for passive scanning.
- **adapter_reset_on_start**: optional global BlueZ adapter power cycle at add-on startup; OFF by default. Requires explicitly selecting the correct hci0-hci3 adapter instead of auto. Interrupts all Home Assistant BLE devices using that adapter. Disallowed in auto mode. The add-on continues to scan if the reset fails.
- **Node-RED access**: account `pi`, bcrypt password hash set in `settings.js` (same hash as Smart Voltronic); no credential fields in the add-on configuration.

Known limitation: Some JK-BMS implementations only transmit telemetry after they receive protocol-specific read commands. In those cases a connection can succeed without any raw notifications. This is expected when read-only requests are disabled or the BMS does not use the supported JK02 protocol.

## Security

- The editor is reachable on port 1895 without TLS termination inside the add-on. Restrict usage to a trusted LAN or VPN, **do not port-forward it to the public internet**.
- The Node-RED editor is protected with a fixed bcrypt password hash, copied from Smart Voltronic as requested. The plaintext password is not stored here. Sharing the same credentials across add-ons increases the impact of a leaked password.
- The internal BLE events endpoint verifies a secret per-installation token.
- User flows and secrets are stored under /data.
- Bluetooth transport uses the Home Assistant host BlueZ through D-Bus, and does not take exclusive ownership of the adapter.

## Troubleshooting

- **Add-on will not start:** inspect the add-on logs and ensure the BLE / Node-RED dependencies started successfully.
- **Node-RED does not open:** verify add-on is running and port 1895 is not already taken.
- **scan_error mentioning BlueZ or D-Bus:** verify the Bluetooth adapter is detected by Home Assistant. Some hosts may require additional Supervisor/AppArmor configuration; check the error before changing privileges.
- **device_not_seen:** a configured BMS was absent in the last scan, so connection is skipped until the next scan. Consider increasing scan duration and stopping other BLE applications.
- **connection_error:** a BMS can disappear after discovery, or another app may be connected. Review BLE diagnostics.
- **connected but no SOC/cell data:** expected: measurement decoding is provisional in v0.1.5. `41 54 0D 0A` is ASCII `AT` plus CR/LF, not a valid JK02 telemetry frame.

## Project layout

    smart-jkbms-bluetooth/
      repository.json
      README.md
      smart-jkbms-bluetooth/
        config.yaml
        Dockerfile
        run.sh
        settings.js
        flows.json
        decoder_flows.json
        merge_flows.py
        ble/bridge.py
        translations/en.yaml
        translations/fr.yaml
      .github/workflows/validate.yml

## Development plan

- 0.1.4: send JK02 0x97 and 0x96 read-only requests and report separate FFE1 characteristic properties, while retaining v0.1.3 scan improvements.
- 0.1.5: provisional JK02_24S/JK02_32S telemetry decoder in Node-RED, profile plausibility checks, 5-second debug summaries, non-destructive flow migration.
- Next: validate the telemetry against BatMON on actual batteries, confirm the exact JK02 profile, then implement MQTT Discovery and dashboards.

**License:** copyright © 2026 tapion69. No redistribution or commercial-use license has been granted for this prototype. The licensing terms will be defined before a public release. We do not copy the source of BatMON, syssi, or the existing JK-BMS RS485 add-on.

## Experimental JK02 decoder — v0.1.5

The Node-RED **JK-BMS | Mesures** tab tries both JK02_24S and JK02_32S response layouts. It checks cell bitmask, individual cell voltage, pack voltage versus cell sum, SOC and temperature. Only a *single plausible* profile produces a diagnostic snapshot; ambiguous or invalid frames are shown in **Profil inconnu : raw_hex à envoyer** (no fabricated measurements).

**Important:** 24S and 32S mean protocol layouts, not the battery's physical number of cells. Do not turn these provisional values into monitoring, automation, billing or charging-control sensors until the first raw frames are cross-checked against BatMON. No MQTT telemetry is published by this version. The summary Debug is rate-limited to one message per BMS every five seconds, but Node-RED retains all valid frames and the user can enable raw debugging when needed. The user flows remain untouched; on upgrades `merge_flows.py` adds vendor-only nodes and connections with a timestamped backup.

Protocol reference: https://github.com/syssi/esphome-jk-bms/blob/main/docs/protocol-design-ble.md

## Bluetooth recovery (0.1.6)

When a configured BMS is absent from the first BLE scan, the add-on first reads every BMS that **was detected** (so battery 2 is not delayed by recovery of battery 1), then runs up to **two additional scans of at least 15 seconds on startup**, and up to **one additional scan in later cycles**, without powering the adapter off. Diagnostic events `recovery_scan_start`, `recovery_scan_result` and `device_not_seen` remain visible in Node-RED. Normal BLE connections use a `BleakClient` context manager and are disconnected when the probe ends.

### Optional one-time adapter power cycle

To diagnose a stuck adapter, choose the correct `bluetooth_adapter` (for example `hci0`) and explicitly enable `adapter_reset_on_start`. Restart **this add-on once** to test it, then switch this option back off. The D-Bus reset briefly powers down the host adapter, disrupting every HA Bluetooth device sharing it. It requires host privileges that may not be available. The add-on never repeats a power-cycle during normal operation. If the JK-BMS is not advertising because BatMON or another app is connected, resetting the *PC adapter* cannot guarantee that the BMS will start advertising. This option does not provide Bluetooth pairing or encryption.

## Quiet Node-RED diagnostics (v0.1.7)

To avoid the Debug sidebar being overwhelmed by ~2 telemetry frames per second on each JK BMS, the following stock Debug nodes are **off by default** on new installations and are selectively switched off during an upgrade: `BLE raw and diagnostics`, `Trames JK02 valides (HEX)`, `Trames rejetées (CRC)`, `Mesures batterie (à confirmer)`, and `Profil inconnu : raw_hex à envoyer`. Their nodes and wires remain available and users can re-enable them whenever raw troubleshooting is needed. Renamed/customized nodes are left untouched.

The only enabled Debug is **RÉSUMÉ JK-BMS (10 s) – SEUL DEBUG ACTIF** in the **JK-BMS | Mesures** tab. It shows one copy-friendly line per configured BMS every 10 seconds: voltage, current, power, SOC, cell count, cell delta, temperatures and inferred JK02 protocol. Values remain **provisional** pending comparison with known-good BatMON data. Migration appends only the vendor summary branch, writes a backup, and preserves all custom nodes; Bluetooth scanning and settings are unchanged.

## Independent persistent Bluetooth sessions (v0.1.8)

Each configured BMS is assigned **at most one** persistent BLE session, using its MAC address as the identity. On connection, the add-on subscribes to FFE1 notifications and sends read-only JK02 `0x97` (device info) and `0x96` (settings) requests. The BMS then streams type-0x02 telemetry spontaneously, as described by the syssi protocol documentation. No BMS parameter writes, switches, or MOS commands are sent. References: https://github.com/syssi/esphome-jk-bms/blob/main/docs/protocol-design-ble.md and the user's existing JK-BMS RS485/Node-RED architecture (health monitoring, timeouts and alarms, used for design inspiration without copying RS485 framing into BLE).

The manager **does not perform BLE discovery when all configured BMS are connected**. It scans again only for missing or disconnected BMS, with independent reconnect delays of 10 to 120 seconds on repeated early failures. A BMS that reports only the non-telemetry `AT\\r\\n` messages triggers a read-only handshake refresh after 45 seconds without any actual BLE data; if still silent at 90 seconds the manager reconnects that BMS only. All active session tasks are cancelled cleanly when the add-on stops. The optional host adapter reset remains **off by default** and is never performed as part of routine reconnection.

Operational state is available as Node-RED events: `session_persistent`, `stream_refresh`, `stream_stale`, `reconnect_scheduled`, `connected`, `disconnected`, and `device_not_seen`. Debug traces remain opt-in; the single summary Debug reports measurements every 10 seconds per BMS. Values remain provisional until checked against physical BMS readings. If parallel connections do not work reliably on a particular HA Bluetooth adapter, switch **persistent_connections: false** and restart the add-on.

## Per-BMS decoding diagnostics (v0.1.9)

If the BLE logs show that a BMS is connected but **only another battery appears in the 10-second measurements**, this release differentiates four independent stages for each MAC address: Bluetooth connected, JK02 type-0x02 frame assembled with valid CRC, JK02_24S/JK02_32S layout plausibility check, and finally a decoded record. The **ÉTAT BMS 1 + BMS 2 (20 s)** Debug in **JK-BMS | Mesures** displays one text line per BMS every 20 seconds. It reports specific failures (cell bitmask, cell voltage, sum-of-cells versus pack voltage, invalid SOC, unexpected temperature), without flooding the Debug sidebar or exposing full HEX automatically.

There is **no automatic relaxation** of validation for a failing BMS, no MQTT publication of rejected measurements, and **no change to Bluetooth or polling behavior** from 0.1.8. The three feed connections (Bluetooth lifecycle events, verified JK02 frames and successful decoder output) are appended non-destructively to existing user flows with a timestamped backup. Original Debug nodes remain off by default, but can be enabled manually. To diagnose a rejected battery, send the `ÉTAT BMS 1 + BMS 2 (20 s)` lines; if required, temporarily enable the full HEX Debug for one frame only.

## BlueZ cached-connection recovery (v0.1.10)

**Symptoms:** after restarting the add-on, zero configured JK-BMS advertisements are found although BlueZ sees other BLE devices. Linux BlueZ can retain a device as connected after a program closes or crashes, and a connected BMS may stop advertising. Bleak may then fail to rediscover it by scanning even while the existing BlueZ GATT object remains available. [Bleak Linux backend](https://bleak.readthedocs.io/en/latest/_modules/bleak/backends/bluezdbus/client.html) documents the already-connected workaround.

**Behavior:** the persistent session manager now queries BlueZ `org.freedesktop.DBus.ObjectManager.GetManagedObjects` for **only the MAC addresses explicitly configured**. It accepts only `org.bluez.Device1` objects whose `Connected` flag is true, and only on the selected Bluetooth adapter (`hci0`, etc.). If a configured BMS is still connected in BlueZ, the bridge creates a native `BLEDevice` from that existing BlueZ object path, then opens a normal read-only Bleak session using the cached GATT connection **without requiring a fresh BLE advertisement**. Other devices are never touched. If the BMS is not connected according to BlueZ, the manager continues normal BLE discovery and the startup recovery scans. Errors reading BlueZ's object manager simply fall back to ordinary BLE scans.

Events: `bluez_connected_recovered`, `bluez_connected_not_found`, or `bluez_cache_unavailable` explain which path was used. **No automatic controller power cycles, forced disconnections, unpairing, or host Bluetooth service restarts** are performed. The optional `adapter_reset_on_start` setting must remain **false** for normal use. These changes are specifically for the startup/restart edge case; they do not make a disconnected non-advertising BMS connectable, nor can they override an active smartphone/BatMON Bluetooth connection. BMS commands stay read-only and no unverified MQTT telemetry is published.
