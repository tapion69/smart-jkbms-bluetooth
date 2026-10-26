<p align="center">
  <img src="assets/logo.svg" alt="Smart JK-BMS Bluetooth logo" width="135">
</p>

# Smart JK-BMS Bluetooth for Home Assistant

**Development preview — v0.3.5. Testers wanted!**

An experimental, community-tested Home Assistant add-on for monitoring multiple JK-BMS batteries over Bluetooth Low Energy (BLE). The add-on combines a Python/Bleak connection manager, a lightweight Node-RED frame decoder and MQTT Discovery so supported JK-BMS readings appear as native Home Assistant entities. It is **free to use**.

> **Important:** This is a work in progress, not a stable release. JK-BMS hardware and firmware differ. Validate measurements against the official JK app and never rely on experimental software for battery safety, charge cutoffs or thermal protection.

## Features

- One Home Assistant MQTT device per configured JK-BMS, identified by its stable Bluetooth address
- Multiple independent BLE sessions, with independent reconnection for each BMS. There is **no coded limit of two BMS**: you can list three or more Bluetooth addresses, subject to host adapter/connection capacity and hardware testing.
- Pack SOC, voltage, current, charge/discharge power, cell average/min/max/delta, cell voltages and available wire resistances
- Cycle count, SOH, runtime, temperatures, alarm states and confirmed configuration values where the BMS actually provides them
- Available settings exposed through native HA controls, protected by explicit authorization, validated JK02 registers and verified BMS readback
- Fixed English entity names and stable entity identifiers across restarts and updates
- Node-RED inside the add-on; users do not need a separately installed Node-RED add-on

Currently tested with JK02 Bluetooth frame formats. `JK02_24S` and `JK02_32S` describe **frame layouts**, not necessarily the installed cell count. Some fields are model-dependent and should remain unavailable rather than show invented values.

## Installation guide

### 1. Requirements

- Home Assistant OS on an eligible `amd64` or `aarch64` machine
- A working Bluetooth adapter available to Home Assistant through BlueZ (built-in or USB)
- One or more compatible JK-BMS units with Bluetooth enabled
- The **Mosquitto broker** add-on and the Home Assistant MQTT integration, already configured with a working MQTT login
- Network access to GitHub for installation and updates

**Bluetooth ownership:** close other Bluetooth monitoring applications and any phone app actively connected to the same batteries while testing. A BLE device may only support one notification subscriber at a time. If you see `org.bluez.Error.NotPermitted: Notify acquired`, check for competing BLE readers first.

### 2. Find your JK-BMS Bluetooth address

One suitable Bluetooth LE scanner is **[nRF Connect for Mobile](https://www.nordicsemi.com/Products/Development-tools/nRF-Connect-for-mobile)** by Nordic Semiconductor, available for Android and iOS. You can also use a similar BLE scanner.

1. Stand near the battery and turn on Bluetooth on your phone.
2. Open nRF Connect and start a BLE scan.
3. Identify the nearby JK-BMS advertisement (often named `JK-BMS`, `Batterie…`, or another custom battery name).
4. On **Android**, open the device details and copy its advertised Bluetooth MAC address, such as `AA:BB:CC:DD:EE:FF`. Check the name and signal strength so you do not select a neighbour's device.
5. Repeat for each BMS, then disconnect the phone's BLE session before starting the add-on.

**iPhone/iPad note:** iOS often shows a device identifier rather than its physical Bluetooth MAC address. If you cannot see the actual MAC on iOS, use an Android BLE scanner, Linux/BlueZ or another method that exposes the device address. Do not substitute an iOS UUID for a MAC.

### 3. Install the add-on

1. In Home Assistant, open **Settings → Add-ons → Add-on Store**.
2. Open the store menu and choose **Repositories**.
3. Add `https://github.com/tapion69/smart-jkbms-bluetooth`.
4. Find **Smart JK-BMS Bluetooth (Development)** and install it.
5. Open **Configuration** and enter your actual BMS MAC address(es) and MQTT credentials.
6. Save the options, start the add-on, and enable **Start on boot** if you want continuous monitoring.
7. Check the add-on logs for successful Bluetooth connections and `MQTT broker connected`.
8. Open **Settings → Devices & services → MQTT → Devices**. Each configured BMS should be visible as its own device.

There is **no need** to install the bundled Node-RED flows by hand. The add-on installs and upgrades its own internal flows while preserving user-modified flows and making backups during migrations.

### 4. Example configuration

```yaml
bluetooth_adapter: auto
bms_addresses: "AA:BB:CC:DD:EE:FF,11:22:33:44:55:66,22:33:44:55:66:77"
persistent_connections: true
scan_duration_seconds: 8
scan_interval_seconds: 45
mqtt_enabled: true
mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_username: "your-mqtt-username"
mqtt_password: "your-mqtt-password"
allow_parameter_changes: false
send_bip: true
bip_geolocation: true
bip_endpoint: "https://script.google.com/macros/s/AKfycbyZsVdzOpUW32VetqOZ228eyftHxoCCAh6LvNH92wx8sb030-TuJqLPgANH3DZdL50y-g/exec"
```

Replace example MAC addresses and MQTT credentials with your own. Never share passwords, full configuration backups, internal IDs or private logs in public bug reports.

### 5. What the configuration options mean

| Option | Description |
|---|---|
| `bluetooth_adapter` | `auto` (recommended) or a specific `hci0`–`hci3` controller. |
| `bms_addresses` | Comma-separated JK-BMS Bluetooth MAC addresses; add as many as needed. There is no fixed two-BMS software cap, but BLE hardware capacity may limit simultaneous links. |
| `persistent_connections` | Recommended `true`: keep independent long-running BLE sessions. |
| `scan_interval_seconds` | Interval used by the connection manager to retry finding missing batteries. |
| `scan_duration_seconds` | How long a BLE advertisement scan runs. |
| `scan_all_devices` | Troubleshooting option to show non-JK nearby BLE advertisements. Usually `false`. |
| `connection_probe_seconds` | Duration of short connection probes when persistent sessions are disabled. |
| `adapter_reset_on_start` | **Leave `false`** unless diagnosing a specific adapter. Can disconnect all Bluetooth devices sharing it. |
| `mqtt_enabled` | Enable automatic Home Assistant MQTT Discovery and states. |
| `mqtt_host`, `mqtt_port` | Usually `core-mosquitto` and `1883`. |
| `mqtt_username`, `mqtt_password` | Credentials for your Mosquitto broker. |
| `mqtt_topic_prefix` | Advanced MQTT namespace; keep the default unless you understand migrations. |
| `mqtt_discovery_prefix` | Usually `homeassistant`. |
| `allow_parameter_changes` | Master safety switch for writing BMS settings. **Default: `false`**. |
| `debug_mode` | Optional development diagnostics. |
| `send_bip` | Sends an installation BIP on startup and daily; **enabled by default**. Opt out by setting `false`. A persistent UUID identifies one installation, not one BMS. | 
| `bip_geolocation` | Approximate geographic information based on the public IP through `ipwho.is`: country, region, city, latitude and longitude. Enabled by default when BIP is on; can be disabled separately. |
| `bip_endpoint` | HTTPS `/exec` URL for the shared multi-module Google Apps Script collector, preconfigured with the maintainer's existing endpoint. |

The former `allow_temperature_control` name was misleading: it controlled all JK02 parameter writes, not only temperature. The master write option has been renamed to `allow_parameter_changes`. JK02 read-only information and settings requests remain necessary for monitoring and readback and are performed automatically.

### 6. Viewing measurements and changing settings

The MQTT device page offers the native Home Assistant categories:

- **Sensors:** SOC, total voltage (two decimals), power/current, cell voltages, corresponding resistances, temperatures, cycles, SOH, capacities and other available readings.
- **Diagnostic:** BMS identity, connection status, alarms and confirmed read-only switch states.
- **Configuration:** editable supported parameters and the `Allow Parameter Changes` switch.

To change a BMS setting, intentionally enable `allow_parameter_changes: true` in the add-on options, then turn **Allow Parameter Changes** ON **for that individual BMS** in Home Assistant. No command is sent unless its register and range are allowlisted, recent valid telemetry and confirmed settings are available, and a readback can verify the value. Revoke the switch after editing. It resets to OFF following reconnect or restart. Do not disable protection settings for testing purposes.

Read-only JK02 `0x96` and `0x97` queries are necessary to retrieve and verify parameters; they are not user-adjustable settings.

## Diagnostics and known limitations

- **Connected but no readings:** verify that no other Bluetooth application or integration currently holds the BMS notification characteristic.
- **MQTT device missing:** verify Mosquitto credentials and the MQTT integration; check `MQTT broker connected` in the logs.
- **Unknown parameters:** the model may not have sent a valid JK02 settings frame yet. Values are intentionally not fabricated.
- **Temperature unavailable:** disconnected or faulty probes can report invalid readings (such as `-200 °C`). These are treated as unavailable.
- **Display precision:** Home Assistant per-entity display overrides can take precedence over the add-on's suggested precision.
- **Compatibility:** support varies by JK hardware/firmware and BLE frame layout. Report both positive tests and failures.

### Reporting test results

When reporting an issue, please include the add-on version, Home Assistant version, JK-BMS hardware and firmware versions (if known), symptoms and **sanitized** logs or screenshots. Remove MAC addresses, serial numbers, passwords, tokens and private network information before publishing.

## Optional installation BIP (privacy and setup)

The add-on includes a separate Node-RED **JK-BMS - BIP** flow based on the same Google Apps Script installation counter design as Smart Energy Finance. It does not affect the BLE, decoding or MQTT flows.

From v0.3.3, the Node-RED **POST Google JK-BMS** request node has the real collector URL entered directly in its URL field (matching Smart Energy Finance). The BIP flow uses `followRedirects = false` for POST and separately performs a safe **GET** on the Google ContentService redirect to read the response JSON. A plain HTTP 302 is not considered proof of registration. Look for **Google JK-BMS created** or **Google JK-BMS updated** on the `BIP result` node; if Google returns `module ou onglet inconnu : jkbms`, publish the updated Apps Script deployment first. A Debug node connected to `BIP result` receives the sanitized success/error information without the installation identifier.

Updates migrate the original packaged v0.3.2 BIP nodes automatically and retain any user-added Debug nodes. User-edited/custom BIP Function nodes are never overwritten; compare them with the new package if the fix is not applied automatically.

**Enabled by default.** Installation counting is optional and can be switched off at any time:
```yaml
send_bip: false
```
The maintainer's Google Apps Script collector URL is preconfigured. The collector owner must deploy the updated multi-module script so it recognizes `jkbms`. The flow will keep working as a no-op if you disable `send_bip`.
The add-on sends one BIP **15 seconds after Node-RED starts and daily at 15:00 (server/Node-RED local time)**. It transmits the following fields:
- `module: "jkbms"` — count the correct module in a dedicated `JK-BMS` spreadsheet tab
- `install_id` — randomly generated UUID v4, stored locally at `/data/smart_jkbms_install_id`
- `bip: "10"` — HA environment, free version (same convention as existing Finance reporting)
- `version` — installed add-on version
- `country`, `region`, `city`, `lat`, `lon` — approximate location provided by `ipwho.is` from the public IP **when `bip_geolocation: true`**. Empty if disabled or the lookup fails

No battery telemetry, BMS Bluetooth addresses, serial numbers, names or MQTT credentials are included. When BIP and geolocation are enabled, the add-on makes a request to the third-party `https://ipwho.is/` service, which necessarily receives the network's public IP, and sends the resulting approximate country/region/city and coordinates to the configured Google Apps Script collector. **These are network-based estimates, not GPS coordinates and not guaranteed to be accurate.** Like any HTTPS collector, Google also processes network connection metadata. You can disable transmission at any time with `send_bip: false`, and the install ID remains unchanged if you later opt back in. Existing Home Assistant installations that previously saved `send_bip: false` keep that setting after upgrading; switch it on manually if desired.

Each installation gets **one row**; startup/daily reports update `last_seen` and version. Adding a third, fourth or fifth BMS does **not** create another installation. Reinstalling after deleting the add-on's persistent data may generate a new identifier.

**Geolocation control:** set `bip_geolocation: false` to continue installation counting without contacting `ipwho.is` and without geographic fields. Set `send_bip: false` to disable the entire BIP, including all geolocation requests. Existing installation rows are updated on each successful BIP; they do not duplicate when location fields become available.

**Collector setup:** The project's existing multi-module Google Apps Script endpoint is the default destination. The maintainer must replace the old script with the updated code and redeploy the existing Web App version. The updated script automatically creates the `JK-BMS` tab and its headers on the first valid request when absent; no manual spreadsheet tab creation is needed. The existing Voltronic and Finance sheets remain unchanged. The counter is informational and has no bearing on Home Assistant functionality.

## Support this free project

Smart JK-BMS Bluetooth is free, but Bluetooth reverse-engineering, compatibility testing, maintenance and answering bug reports take considerable time.

If this project helps you, a small **[Ko-fi](https://ko-fi.com/tapion69)** would be greatly appreciated. Contributions are voluntary and help keep development moving. Thank you to everyone testing, reporting issues and helping improve compatibility!

**Project repository:** https://github.com/tapion69/smart-jkbms-bluetooth

## Technical overview

```text
JK-BMS (BLE) → Python/Bleak → authenticated local Node-RED frame assembler
             → JK02 CRC/validation → local Python MQTT publisher
             → Mosquitto → Home Assistant MQTT Discovery
```

Node-RED is an internal part of the add-on's data pipeline (development editor on port `1895`), not a separate required Home Assistant installation. Existing MAC-based entity IDs and MQTT discovery topics are retained during normal upgrades. A changed Bluetooth MAC or discovery prefix can create a new Home Assistant device.

The source is experimental. Always keep firmware safety protections active and independently supervise your battery system.
