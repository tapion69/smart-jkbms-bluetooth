# Smart JK-BMS Bluetooth — Home Assistant add-on

**Development milestone 0.1.0. Not yet a complete JK-BMS monitoring integration.**

Standalone Bluetooth add-on following the clean repository structure of Smart Voltronic. It uses a local Bluetooth adapter (built into a mini-PC or a Home Assistant OS-compatible USB Bluetooth dongle) via BlueZ D-Bus and Bleak. A full **Node-RED editor is available on port 1895** for diagnostics and future JK-BMS decoding.

## Included in v0.1.0 development milestone

- Home Assistant add-on configuration, Dockerfile and startup script.
- Node-RED 5.0.9 editor with a username and mandatory password.
- BLE discovery on the host adapter, optionally including all nearby devices.
- Short read-only Bluetooth connection probes on individually configured BMS MAC addresses.
- BLE service discovery and raw FFE1 notifications, if provided by the device.
- Python-to-Node-RED local HTTP bridge protected by a random per-installation token.
- A visual Node-RED tab: **Bluetooth | Diagnostics**.
- Data under persistent /data; the user's Node-RED flows are not overwritten at every restart.
- Home Assistant options translated into French and English.

**Not yet implemented:** JK02 read polling commands, verified BMS frame assembly, cell voltages, temperature, current, SOC, MQTT Discovery, dashboards, and BMS parameter changes. No BMS write commands are sent in this milestone.

## Installation

1. In Home Assistant, open **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
2. Add this URL: https://github.com/tapion69/smart-jkbms-bluetooth
3. Install **Smart JK-BMS Bluetooth (Development)**.
4. In the add-on configuration, enter a strong **node_red_password**. An empty password blocks startup for safety. The default user is **admin**.
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
- **connection_probe_seconds**: how long to listen for unsolicited FFE1 notifications.
- **node_red_user / node_red_password**: Node-RED editor login.

Known limitation: Some JK-BMS implementations only transmit telemetry after they receive protocol-specific read commands. In those cases a connection can succeed without any raw notifications. This is expected in v0.1.0.

## Security

- The editor is reachable on port 1895 without TLS termination inside the add-on. Restrict usage to a trusted LAN or VPN, **do not port-forward it to the public internet**.
- The Node-RED administrative interface requires a configured password.
- The internal BLE events endpoint verifies a secret per-installation token.
- User flows and secrets are stored under /data.
- Bluetooth transport uses the Home Assistant host BlueZ through D-Bus, and does not take exclusive ownership of the adapter.

## Troubleshooting

- **Add-on will not start:** ensure the Node-RED password is filled in. Check add-on logs.
- **Node-RED does not open:** verify add-on is running and port 1895 is not already taken.
- **scan_error mentioning BlueZ or D-Bus:** verify the Bluetooth adapter is detected by Home Assistant. Some hosts may require additional Supervisor/AppArmor configuration; check the error before changing privileges.
- **connection_error:** the app or BatMON may already be connected to the BMS, the MAC may be wrong, or the signal may be insufficient.
- **connected but no SOC/cell data:** expected: these are not implemented in v0.1.0.

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
        ble/bridge.py
        translations/en.yaml
        translations/fr.yaml
      .github/workflows/validate.yml

## Development plan

- 0.1.0: Node-RED editor port 1895; BLE discovery, raw events and diagnostics.
- Later: validated JK-BMS read commands, framed responses, verified measurements.
- Later: MQTT Discovery and battery diagnostics; optional dashboard integration.

**License:** copyright © 2026 tapion69. No redistribution or commercial-use license has been granted for this prototype. The licensing terms will be defined before a public release. We do not copy the source of BatMON, syssi, or the existing JK-BMS RS485 add-on.
