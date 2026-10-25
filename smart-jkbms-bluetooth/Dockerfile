ARG BUILD_FROM=ghcr.io/hassio-addons/base:21.0.7
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apk add --no-cache \
    bash jq nodejs npm python3 py3-pip py3-virtualenv dbus-libs tzdata \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir bleak==3.0.2 paho-mqtt==2.1.0 \
    && npm install --global --no-audit --no-fund --unsafe-perm \
         node-red@5.0.9 bcryptjs@2.4.3 \
    && npm cache clean --force

COPY . /addon
WORKDIR /addon
RUN chmod +x /addon/run.sh \
    && python3 -m py_compile /addon/ble/bridge.py

EXPOSE 1895
ENTRYPOINT ["/addon/run.sh"]
