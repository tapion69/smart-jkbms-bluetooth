"""Persistent, anonymous installation identity for optional BIP telemetry.

One UUID per Home Assistant add-on data directory. Never derived from MAC,
IP address, username, serial number or Home Assistant credentials.
No network activity is performed here.
"""
from __future__ import annotations
import os
import sys
import uuid
from pathlib import Path

DEFAULT_PATH = Path("/data/smart_jkbms_install_id")


def get_install_id(path: Path = DEFAULT_PATH) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w", encoding="ascii") as file:
            file.write(str(uuid.uuid4()) + "\n")
    # Invalid stored IDs are not silently replaced; that would double-count an installation.
    raw = path.read_text(encoding="ascii").strip()
    value = uuid.UUID(raw)
    if value.version != 4:
        raise ValueError("Stored installation ID is not a valid version-4 UUID")
    return str(value)


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    print(get_install_id(path))
