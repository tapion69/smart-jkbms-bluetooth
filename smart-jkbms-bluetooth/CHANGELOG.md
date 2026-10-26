# Changelog

## 0.3.3 — Reliable Finance-style JK-BMS installation BIP (development preview)

- Rebuilt the **JK-BMS - BIP** Node-RED flow following the proven Smart Energy Finance pattern: startup/daily trigger, send permission, environment analysis, Google payload preparation and **HTTP POST configured with the real Google Apps Script /exec URL in the node itself**.
- Added an explicit GET of Google's ContentService redirection target (limited to `script.googleusercontent.com`) to read the JSON confirmation without replaying the POST. A 302 alone is **not** treated as successful installation registration.
- The final `BIP result` node reports `created` / `updated` from the JSON response or the actual error (e.g. `module ou onglet inconnu : jkbms`) and emits a sanitized debug payload.
- Migrates only the published unmodified v0.3.2 BIP nodes and preserves user-added Debug connections and custom functions. Node-RED flow backups remain automatic.
- BIP remains enabled by default and user-disableable via `send_bip: false`. The UUID persists across updates; no battery data or location lookups are sent.
- **Google-side prerequisite:** update/redeploy the Apps Script Web App to the version that recognizes `module: "jkbms"`; the updated script creates the `JK-BMS` tab automatically on the first successful POST.
- Tests cover the initial v0.3.2 migration, repeat upgrades, custom nodes, redirect-as-GET, confirmed registration and negative responses.

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

