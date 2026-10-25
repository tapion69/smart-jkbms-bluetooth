# Smart JK-BMS Bluetooth — Home Assistant add-on

**Version 0.2.6 — experimental JK02 BLE integration with Home Assistant MQTT Discovery.**

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

## v0.2.5 — Native HA presentation and runtime fix

**Root cause found:** earlier add-on updates kept the *old* stock Node-RED MQTT forwarding function `b200000000000002`, because `merge_flows.py` upgraded only decoder functions. Consequently, the running MQTT publisher never saw newly introduced fields such as uptime. The v0.2.5 migration recognizes **exact published vendor fingerprints** from 0.2.0/0.2.1/0.2.3/0.2.4 and updates only these unmodified functions, backing up the existing flow. Owner-edited / renamed Functions are **never overwritten**. Test fixtures contain the exact prior published versions. For custom code, a warning is logged and review remains necessary.

**Uptime is now independently derived in Python** from a CRC-valid type-0x02 JK02 frame, matched to a verified per-BMS electrical result using the frame counter; for JK02_32S the u32 little-endian seconds count is at byte offset **194**, and for JK02_24S at **162** (as independently decoded by syssi and BatMON). This avoids depending on JavaScript cached supplemental fields. The single human-readable `Total_runtime` entity uses the established `total_runtime_formatted` unique ID. Example: 53293405 seconds -> `616j 19h 43m`. No duplicate raw uptime sensor is registered.

**Better native HA organization:** charging cycles (`Nombre_Cycle`), accumulated cycle capacity and SOH are ordinary measured sensors, not hidden in the Diagnostic category. For each cell, voltage and wire resistance now use the **same primary measured-sensor category** and adjacent sortable names: `Cellule 01 - 1 Tension`, `Cellule 01 - 2 Résistance`; then cell 02, etc. Their original MAC-based unique IDs are preserved so histories are not lost. Note that Home Assistant's built-in device page ultimately controls sorting; a custom Lovelace card can provide stricter two-row-per-cell layout if needed.

**No phantom diagnostics:** optional information from the 0x03 device-info frame and optional extended diagnostics is now advertised only after a genuine non-null value has actually arrived. Old retained MQTT discovery is tombstoned before republishing each BMS's active supported entities, and **all legacy sensor announcements for parameters that already have Configuration number/switch entities** are deleted. Unknown is still correct for parameters that have never been received as CRC-valid settings (type 0x01); it cannot be fixed safely by copying another unrelated measurement.

These are deliberately presentation and data-reliability changes. No change is made to BLE sessions, thermal protections or register write safety.

**Protocol comparisons:** [syssi BLE JK02_32S frame offsets](https://github.com/syssi/esphome-jk-bms/blob/main/docs/protocol-design-ble.md), [BatMON JK BLE decoder](https://github.com/fl4p/batmon-ha/blob/master/bmslib/models/jikong.py). Verified against simulated 24S/32S type-0x02 packets with 300-byte checksum, MQTT data flow, discovery, and previous released forwarding functions.

**After upgrading:** restart the add-on, allow the current MQTT discovery to refresh, and review both devices. No manual deletion of MQTT devices is necessary. The old entity labels may persist if Home Assistant was customized by the owner; the entity's display name can be reset in its settings.

## v0.2.6 — Fix parameter switches reverting to their previous state

A real Home Assistant failure was captured on 25 October 2026 while trying to switch **BMS balance** off: `Refus : paramètres BMS non confirmés (trame 0x01 absente)`. The BMS and 0x02 measurements stayed online, but changes were correctly rejected because the add-on had not received **current, checksum-validated settings**. Previously the BLE bridge sent 0x96 mostly at initial connection, yet the command gate considered settings stale after three minutes. This could prevent every parameter write for long-running sessions.

**Fixed without bypassing the safety guard:**

- Python BLE bridge now gently requests a **read-only 0x96 settings update every 120 seconds**, separately on each persistent BMS BLE session, with no reconnect and no change to the electrical frame decoder.
- If a user adjusts a parameter while no fresh verified type-0x01 settings frame exists, the MQTT command handler **requests a fresh 0x96 reading automatically, then waits up to 8 seconds** for a 300-byte frame with a valid header, type, CRC and plausible JK02_32S settings values.
- **A write is sent only after that confirmation**, provided that explicit Home Assistant `Autoriser modification paramètres` remains ON, the add-on write option remains enabled, the telemetry is fresh, the setting appears in a verified configuration frame, and the requested value is on the strict register allowlist.
- An additional **readback after writing** determines whether the BMS actually applied the requested value. HA continues showing the verified BMS state: **no optimistic ON/OFF animation** or invented settings.
- If the BMS still does not transmit an accepted 0x01 frame, **no command is sent**. A diagnostic entity displays a specific reason: no frame received, invalid/unsupported frame, read-only requests disabled, BLE unavailable or post-write readback absent. It never disables BMS protection or writes around the fault.
- A per-BMS pending-command lock prevents repeated clicks from queuing multiple writes. The 15-second BLE write cooldown remains intact. Disconnection clears old settings confirmation.
- Existing MQTT device IDs, user Node-RED flows, cell formatting, settings ranges and thermal safeguards remain unchanged.

**To test:** Update to v0.2.6, ensure `read_only_requests: true` and `persistent_connections: true`, and restart. After the BMS is online, enable `allow_temperature_control: true` only if you intentionally want to modify BMS settings, then turn on the per-BMS HA switch `Autoriser modification paramètres`. When you manually change `BMS balance switch`, check the diagnostic entity `Dernière commande paramètres` for `Lecture des paramètres BMS (0x96)`, `Confirmé par le BMS` or a precise refusal. Do not repeatedly click or disable important BMS protections to make a test pass.

**Still to verify on the actual hardware:** whether the target BMS returns a valid type-0x01 settings packet in response to 0x96 (protocol and firmware vary). A successful CI test only verifies the software safety logic and synthetic 0x01 responses.
