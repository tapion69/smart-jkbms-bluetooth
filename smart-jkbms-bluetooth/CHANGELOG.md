# Changelog

## 0.3.7 — Safer Home Assistant parameter write feedback (development preview)

- Fixed misleading `Confirmé par le BMS ...` followed immediately by `write_rate_limit_15s` when Home Assistant or another MQTT publisher repeats the **same** parameter value.
- Identical commands sent during an ongoing write or within 15 seconds of a **BMS-confirmed** identical write are silently ignored. A failed/unverified write is never considered confirmed.
- Distinct write requests still respect the strict **15-second per-BMS safety rate limit**. Refusals now display the remaining wait time in seconds; no writes are queued or replayed automatically.
- Clear recent-success suppression state on BMS disconnect, protecting against stale readback after reconnection.
- Regression tests cover `balance_start_v = 2.601 V`, duplicate MQTT submissions, fresh different values and the central rate limit.
- Bluetooth frame decoding, readback verification, authorization guards, BIP and MQTT entity identities remain unchanged.

## 0.3.6 — Simplified BIP configuration and shorter README (development preview)

- Keep **one** BIP setting: `send_bip` (enabled by default; `false` disables the complete BIP process).
- Remove the redundant `bip_geolocation` setting and the unused `bip_endpoint` configuration field. The Google POST node keeps the established collector URL directly.
- With `send_bip: true`, geographic information for the installation map is still requested automatically from `ipwho.is`. If the service times out or fails, Google still receives the installation heartbeat, without the geographic fields. No new installation ID is generated.
- Upgrade the packaged v0.3.5 Node-RED functions on restart, preserving user-created flows, Debug wiring and custom function code.
- Rewrite the English README as a short setup guide with clear multi-BMS instructions and Ko-fi support.
- Bluetooth/MQTT telemetry, BMS protections, and the existing Voltronic/Finance Google Sheets handling are unchanged.

## 0.3.5 — Non-blocking IP geolocation timeout (development preview)

- **Fixed** the Google BIP failure caused by `ipwho.is` timeouts being forwarded as `statusCode: "ETIMEDOUT"` with `responseUrl: https://ipwho.is/`. Node-RED HTTP requests can produce ordinary output error messages without triggering a Catch node.
- Added **Check GEO reply / continue BIP**, between geolocation and Google: accept valid HTTP 200 / `success: true`, otherwise continue with empty geographic fields. Clears the stale `statusCode`, `responseUrl`, request/redirect headers and timeout metadata before the independent Google POST.
- A bounded timeout is requested for the optional lookup. If Node-RED reports the error both on its regular output and through a Catch event, de-duplicate by message ID to avoid two BIPs.
- The existing v0.3.4 Node-RED flow is automatically migrated if its source nodes are unchanged; extra Debug wiring and customized Functions remain untouched. Migration backs up the previous flow.
- Unchanged: the persistent installation ID, daily/startup BIP schedule, user opt-outs, Google Apps Script endpoint, multiple BMS support, Bluetooth/MQTT behavior and write safeguards.
- Google Sheets retains one row per installation even when the location provider is unavailable. Geographic columns are populated on a later successful location lookup.
- Tests include an actual `ETIMEDOUT`-shaped response, successful IP location, catch+output duplication, stale HTTP metadata cleanup, and installed v0.3.4 migration.

## 0.3.4 — Finance-style BIP location fields (development preview)

- Fixed blank `country`, `region`, `city`, `lat` and `lon` columns in Google Sheets by restoring a lookup using `https://ipwho.is/`, following the Smart Energy Finance BIP flow.
- Country, region, city and **approximate IP-derived** coordinates are submitted in the same Google payload (never raw BMS readings or MAC addresses). This is not GPS location and may not match the physical installation.
- Added `bip_geolocation` (default `true`) as an independent opt-out for the third-party IP lookup and geographic reporting. Set `send_bip: false` to disable all BIP and geolocation traffic.
- Geolocation HTTP timeouts and errors fall back to a standard BIP, without losing installation counting.
- Existing v0.3.3 flows are migrated automatically only when vendor Function code matches a known fingerprint. Added Debug nodes and customized code are preserved, and backups are created when flows change.
- Existing installation IDs remain unchanged. Next successful BIP updates the existing Google Sheets row and fills the location columns; it does not create another installation.
- Google Apps Script itself requires **no additional change** because it already accepts these five geographic fields. The existing Voltronic and Finance tabs remain untouched.
- Regression tests cover successful country/region/city/lat/lon, independent geolocation opt-out, API failure fallback, invalid coordinates and idempotent Node-RED migration.

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

