"""
MARK III Phase 16A — Device Registry

Persistent, thread-safe storage of all known mesh devices.
Backed by mesh_devices.json in brain-server/.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from typing import Optional

from app.services.mesh.mesh_protocol import Device, DeviceState

log = logging.getLogger("markiii.mesh.registry")

# brain-server/mesh_devices.json
_REGISTRY_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "mesh_devices.json")
)


class DeviceRegistry:
    """
    In-memory + on-disk registry of all MARK mesh devices.

    Thread-safe via RLock so the HTTP server, watchdog, and voice loop
    can all read/write without race conditions.
    """

    def __init__(self, path: str = _REGISTRY_PATH) -> None:
        self._path    = path
        self._lock    = threading.RLock()
        self._devices: dict[str, Device] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for d in data.get("devices", []):
                try:
                    dev = Device.from_dict(d)
                    # All devices start as offline on load; they must re-register
                    if dev.device_id != "desktop-mark-core":
                        dev.state  = DeviceState.OFFLINE.value
                        dev.active = False
                    self._devices[dev.device_id] = dev
                except Exception as e:
                    log.warning("Registry: skipping malformed device entry: %s", e)
            log.info("Registry loaded: %d devices from %s", len(self._devices), self._path)
        except Exception as e:
            log.warning("Registry load failed: %s", e)

    def _save(self) -> None:
        try:
            payload = {"devices": [d.to_dict() for d in self._devices.values()]}
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            log.warning("Registry save failed: %s", e)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def register(self, device: Device) -> None:
        with self._lock:
            is_new = device.device_id not in self._devices
            self._devices[device.device_id] = device
            self._save()
        verb = "registered" if is_new else "updated"
        log.info("Registry: %s %s [%s] @ %s", verb, device.name, device.state, device.ip)

    def update(self, device_id: str, **kwargs) -> Optional[Device]:
        """Update specific fields on an existing device. Returns updated device."""
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return None
            for key, value in kwargs.items():
                if hasattr(device, key):
                    setattr(device, key, value)
            self._save()
            return device

    def remove(self, device_id: str) -> bool:
        with self._lock:
            if device_id in self._devices:
                del self._devices[device_id]
                self._save()
                return True
            return False

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, device_id: str) -> Optional[Device]:
        with self._lock:
            return self._devices.get(device_id)

    def all(self) -> list[Device]:
        with self._lock:
            return list(self._devices.values())

    def online(self) -> list[Device]:
        with self._lock:
            return [
                d for d in self._devices.values()
                if d.state in (DeviceState.ONLINE.value, DeviceState.ACTIVE.value, DeviceState.IDLE.value)
            ]

    def by_type(self, device_type: str) -> list[Device]:
        with self._lock:
            return [d for d in self._devices.values() if d.type == device_type]

    def count(self) -> dict:
        with self._lock:
            total   = len(self._devices)
            online  = sum(1 for d in self._devices.values()
                          if d.state in (DeviceState.ONLINE.value, DeviceState.ACTIVE.value, DeviceState.IDLE.value))
            return {"total": total, "online": online, "offline": total - online}
