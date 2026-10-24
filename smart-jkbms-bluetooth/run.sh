#!/usr/bin/env bash
set -euo pipefail

OPTIONS="/data/options.json"
WORKDIR="/data/node-red"
mkdir -p "$WORKDIR"

if [[ ! -f "$OPTIONS" ]]; then
  echo "[ERROR] /data/options.json not found"
  exit 1
fi

NODE_RED_USER="$(jq -r '.node_red_user // "admin"' "$OPTIONS")"
NODE_RED_PASSWORD="$(jq -r '.node_red_password // ""' "$OPTIONS")"
if [[ -z "$NODE_RED_PASSWORD" ]]; then
  echo "[ERROR] Please set node_red_password in Smart JK-BMS Bluetooth add-on options."
  exit 1
fi
export NODE_RED_USER NODE_RED_PASSWORD

# One secret per installation. Never print secret values.
for secret_file in /data/.nodered_credential_secret /data/.ble_bridge_token; do
  if [[ ! -s "$secret_file" ]]; then
    /opt/venv/bin/python -c 'import secrets,sys;open(sys.argv[1],"w").write(secrets.token_hex(32))' "$secret_file"
    chmod 600 "$secret_file"
  fi
done
export BLE_BRIDGE_TOKEN="$(cat /data/.ble_bridge_token)"

if [[ ! -f "$WORKDIR/flows.json" ]]; then
  cp /addon/flows.json "$WORKDIR/flows.json"
  echo "[INFO] Initial Node-RED diagnostic flow installed"
fi

# User flows are never overwritten on startup or update.
export NODE_PATH="$(npm root -g)"
export BLE_BRIDGE_ENDPOINT="http://127.0.0.1:1895/internal/ble/events"
export BLE_OPTIONS_FILE="$OPTIONS"

NR_PID=""
BLE_PID=""
shutdown() {
  trap - INT TERM EXIT
  if [[ -n "$BLE_PID" ]]; then kill "$BLE_PID" 2>/dev/null || true; fi
  if [[ -n "$NR_PID" ]]; then kill "$NR_PID" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap shutdown INT TERM EXIT

echo "[INFO] Smart JK-BMS Bluetooth development v0.1.0"
echo "[INFO] Node-RED port: 1895"
echo "[INFO] Starting Node-RED and BLE diagnostics bridge"

node-red --userDir "$WORKDIR" --settings /addon/settings.js &
NR_PID=$!
/opt/venv/bin/python -u /addon/ble/bridge.py &
BLE_PID=$!

set +e
wait -n "$NR_PID" "$BLE_PID"
EXIT_CODE=$?
set -e
echo "[ERROR] One add-on service exited ($EXIT_CODE); stopping both services"
exit 1
