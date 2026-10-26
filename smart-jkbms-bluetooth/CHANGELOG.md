# Changelog

## 0.3.2 — Home Assistant icon and logo (development preview)

- Added a native **128 × 128 px PNG icon** (`icon.png`) to the Home Assistant app folder. The installed application tile no longer needs to fall back to the generic puzzle-piece icon.
- Added a **250 × 100 px PNG logo** (`logo.png`) for the application details screen.
- Kept the README's existing SVG logo and all MQTT Discovery devices, BLE sessions, Node-RED flows and BMS controls unchanged.
- Updated obsolete control-service tests to match the existing master `allow_parameter_changes` and per-BMS confirmation requirements; **no battery safety permissions are weakened**.
- This is still an experimental development release. If the old icon remains visible, refresh the add-on repository and hard-reload Home Assistant (Ctrl+F5). Existing installations may need to install the version update for Supervisor to refresh their app metadata.

## 0.3.1 — Optional installation telemetry and multi-BMS beta

- BIP with a persisted installation identifier and Google Apps Script collector support, user-disableable with `send_bip: false`.
- Multiple BLE battery sessions and stable MQTT device identifiers.
- Simplified settings write authorization and installation documentation.

