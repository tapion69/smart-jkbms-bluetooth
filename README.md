# Smart JK-BMS Bluetooth — Home Assistant add-on

**Version 0.2.4 — experimental JK02 BLE integration with Home Assistant MQTT Discovery.**

Connect JK-BMS batteries by Bluetooth (BLE) to Home Assistant, with one stable MQTT device per configured BMS. The two devices keep their MAC-based unique IDs. Supports independently connected JK02_24S and JK02_32S telemetry profiles; these names describe the frame layout, not the number of cells connected.

## Architecture (current)

```text
JK-BMS1, JK-BMS2
   │ Bluetooth 0xFFE1
   ▼
Python BLE bridge (BlueZ/Bleak)
   │ per-BMS BLE sessions, notifications and authenticated local HTTP
   ▼
Node-RED — internal transport and JK02 frame decoder (1895)
   │ assemble 300-byte frames, verify checksum, validate measurements
   ▼
Python MQTT publisher (local-only HTTP 127.0.0.1:1896)
   │ independent state, availability, HA discovery + approved commands
   ▼
Mosquitto → Home Assistant
```

**Node-RED is still part of the *data pipeline***. Do not stop the Node-RED process or delete its three remaining functional flow branches. **Node-RED is not the Home Assistant dashboard** and no standalone HTML page is needed: state, diagnostics, and configuration are managed directly through the discovered MQTT devices.

### Minimal Node-RED flows

There are only three packaged files, with **no packaged Debug, Inject timer or obsolete HTML nodes**:

- `flows.json` — authenticated internal BLE HTTP events and CRC-checked 300-byte frame assembler;
- `decoder_flows.json` — JK02_24S / JK02_32S electrical decoder and plausibility checks;
- `mqtt_flows.json` — forward only verified frames/measurements to Python's MQTT publisher.

`merge_flows.py` performs an idempotent update. It removes **unmodified vendor-owned legacy** debug/HTML/inject functions via `vendor_cleanup.json` and fixes their wires, but never deletes your own nodes or a renamed / modified old function. Existing custom Node-RED content is preserved, with a dated `/data/node-red/flows.json.*.bak` backup before changes. If you have manually connected a custom node to a retired vendor node, that dependency is preserved and logged.

The old `/jk-bms/temperature` HTML interface is removed. Home Assistant MQTT **Configuration** already exposes the parameter controls and the per-BMS `Autoriser modification paramètres` switch.

## Configuration

Add repository `https://github.com/tapion69/smart-jkbms-bluetooth` in Home Assistant → Add-ons → Add-on Store → Repositories, then install the add-on and set:

```yaml
bms_addresses: "C8:47:80:1A:1A:EF,C8:47:80:1A:27:12"
persistent_connections: true
read_only_requests: true
mqtt_enabled: true
mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_username: "<mosquitto-user>"
mqtt_password: "<mosquitto-password>"
mqtt_discovery_prefix: homeassistant
mqtt_topic_prefix: smart_jkbms_ble
allow_temperature_control: false
```

Replace MAC addresses and MQTT credentials with your own. Never publish private passwords. Open Home Assistant → Settings → Devices & services → MQTT → Devices to see your BMS. Node-RED developer editor (if needed) is on port 1895 and has its own authentication.

## Home Assistant organization

**Measurements** — voltage, signed current, power, charging/discharging power, SOC, remaining capacity, balancing, cell 1–16 voltage, min/max/average and delta, and available temperature probes. Cell voltages and delta are shown with **3 decimals**, battery voltage with **1 decimal**, delta in **V**.

**Configuration** — one `number` or `switch` per allowlisted JK02 setting, **not** a second read-only sensor showing the same setting. `Autoriser modification paramètres` is OFF by default and resets to OFF on reconnect. The add-on-wide option `allow_temperature_control: true` must also be explicitly enabled before manual writes. A setting change is not reported as accepted until the BMS sends verified type-0x01 configuration readback; writes require fresh telemetry and config state.

**Diagnostics** — useful values only: cell resistances, cell min/max index, cycle count/cycled capacity, SOH, remaining protection release timers, power-on count, supported firmware/hardware/identity fields, DRY1/DRY2 contacts, charging/heating state, readable alarms, emergency countdown and online status. No hex bitmask entities, raw numeric protocol/trigger IDs, redundant battery nominal capacity, redundant cell count, extra raw balancing/status codes or repeated runtime copies.

Obsolete MQTT Discovery announcements are **actively deleted from the broker on reconnection** for each configured BMS; their stable device identity and surviving sensors are preserved. This updates the integration, not old manually created Lovelace YAML cards that explicitly reference removed entity IDs.

### Accuracy and protections

The bridge only publishes validated electrical telemetry. A JK02 frame with exactly -200.0 °C in all three standard probes may still provide valid electrical data, but these missing temperatures remain unavailable in HA. Never use this experimental integration as a replacement for hardware battery or thermal protection.

Current source references: [syssi JK-BMS BLE protocol documentation](https://github.com/syssi/esphome-jk-bms/blob/main/docs/protocol-design-ble.md) and [JK-BMS BLE decoder](https://github.com/syssi/esphome-jk-bms/blob/main/components/jk_bms_ble/jk_bms_ble.cpp).

## Updates and test policy

Source and GitHub Actions cover JK02 framing, electrical validation, two-BMS MQTT discovery, parameter write safety, obsolete entity cleanup, and non-destructive Node-RED migration. Tests run without real batteries; verify newly supported measurements against the official JK application or BatMON before relying on them.

For problems, check the add-on log for `MQTT broker connected`, `MQTT Discovery published`, and `Node-RED cleanup` messages before enabling any debugging.
