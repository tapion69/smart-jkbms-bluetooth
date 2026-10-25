#!/usr/bin/env bash
set -euo pipefail

OPTIONS="/data/options.json"
WORKDIR="/data/node-red"
mkdir -p "$WORKDIR"

if [[ ! -f "$OPTIONS" ]]; then
  echo "[ERROR] /data/options.json not found"
  exit 1
fi

# One secret per installation. Never print secret values.
for secret_file in /data/.nodered_credential_secret /data/.ble_bridge_token; do
  if [[ ! -s "$secret_file" ]]; then
    /opt/venv/bin/python -c 'import secrets,sys;open(sys.argv[1],"w").write(secrets.token_hex(32))' "$secret_file"
    chmod 600 "$secret_file"
  fi
done
export BLE_BRIDGE_TOKEN="$(cat /data/.ble_bridge_token)"

# Merge new vendor nodes without overwriting existing user flows.
# A backup is made whenever an update adds nodes or a link.
 /opt/venv/bin/python /addon/merge_flows.py "$WORKDIR/flows.json" /addon/flows.json /addon/decoder_flows.json /addon/mqtt_flows.json

# User flows are never overwritten on startup or update.
export NODE_PATH="$(npm root -g)"
export BLE_BRIDGE_ENDPOINT="http://127.0.0.1:1895/internal/ble/events"
export BLE_OPTIONS_FILE="$OPTIONS"
export BLE_BMS_ADDRESSES="$(jq -r '.bms_addresses // ""' "$OPTIONS")"
export BLE_TEMP_CONTROL_ENABLED="$(jq -r '.allow_temperature_control // false' "$OPTIONS")"
export BLE_MQTT_ENABLED="$(jq -r '.mqtt_enabled // true' "$OPTIONS")"

NR_PID=""
BLE_PID=""
SHUTTING_DOWN=false
shutdown() {
  SHUTTING_DOWN=true
  trap - INT TERM EXIT
  if [[ -n "$BLE_PID" ]]; then kill "$BLE_PID" 2>/dev/null || true; fi
  if [[ -n "$NR_PID" ]]; then kill "$NR_PID" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap shutdown INT TERM EXIT

echo "[INFO] Smart JK-BMS Bluetooth development v0.2.4"
echo "[INFO] Node-RED port: 1895"
echo "[INFO] Starting lightweight JK02 decoder and BLE-to-MQTT bridge"

node-red --userDir "$WORKDIR" --settings /addon/settings.js "$WORKDIR/flows.json" &
NR_PID=$!
/opt/venv/bin/python -u /addon/ble/bridge.py &
BLE_PID=$!

set +e
wait -n "$NR_PID" "$BLE_PID"
EXIT_CODE=$?
set -e
if [[ "$SHUTTING_DOWN" == "true" ]]; then
  echo "[INFO] Add-on stopped normally by Home Assistant"
  exit 0
fi
echo "[ERROR] One add-on service exited unexpectedly ($EXIT_CODE); stopping both services"
exit 1
