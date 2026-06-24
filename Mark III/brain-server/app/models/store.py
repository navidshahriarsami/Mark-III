"""
MARK III Brain Server — In-Memory Store (Phase 4)

Thread-safe in-process registry for devices, snapshots, heartbeats,
and command approval state. Replaced by PostgreSQL in Phase 5.

All public methods are synchronous — FastAPI runs them inside async
route handlers which is fine for pure in-memory operations.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DeviceRecord:
    device_id:    str
    hostname:     str
    platform:     str
    version:      str
    registered_at: float = field(default_factory=time.time)
    last_seen:    float  = field(default_factory=time.time)
    heartbeat_count: int = 0


@dataclass
class SnapshotRecord:
    device_id:      str
    ts:             float
    process_name:   str
    window_title:   str
    classification: str
    is_browser:     bool
    active_domain:  Optional[str]
    ocr_text:       Optional[str]


@dataclass
class CommandRecord:
    request_id:  str
    device_id:   str
    raw:         str
    requester:   str
    queued_at:   float = field(default_factory=time.time)
    status:      str   = "pending"     # pending | approved | denied
    stdout:      str   = ""
    stderr:      str   = ""
    returncode:  Optional[int] = None


class MemoryStore:
    """
    Single shared instance (imported as `store` below).
    All mutations hold a lock so concurrent request handlers don't race.
    """

    def __init__(self, max_snapshots: int = 500, max_commands: int = 200) -> None:
        self._lock     = threading.Lock()
        self._devices:  dict[str, DeviceRecord]  = {}
        self._snapshots: deque[SnapshotRecord]   = deque(maxlen=max_snapshots)
        self._commands: dict[str, CommandRecord] = {}

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def upsert_device(self, **kwargs) -> DeviceRecord:
        with self._lock:
            did = kwargs["device_id"]
            if did in self._devices:
                rec = self._devices[did]
                rec.last_seen = time.time()
            else:
                rec = DeviceRecord(**kwargs)
                self._devices[did] = rec
            return rec

    def touch_device(self, device_id: str) -> Optional[DeviceRecord]:
        with self._lock:
            rec = self._devices.get(device_id)
            if rec:
                rec.last_seen = time.time()
                rec.heartbeat_count += 1
            return rec

    def all_devices(self) -> list[DeviceRecord]:
        with self._lock:
            return list(self._devices.values())

    def device_count(self) -> int:
        with self._lock:
            return len(self._devices)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def add_snapshot(self, **kwargs) -> SnapshotRecord:
        rec = SnapshotRecord(**kwargs)
        with self._lock:
            self._snapshots.append(rec)
        return rec

    def recent_snapshots(self, n: int = 20) -> list[SnapshotRecord]:
        with self._lock:
            items = list(self._snapshots)
        return items[-n:]

    def snapshot_count(self) -> int:
        with self._lock:
            return len(self._snapshots)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def add_command(self, **kwargs) -> CommandRecord:
        rec = CommandRecord(**kwargs)
        with self._lock:
            self._commands[rec.request_id] = rec
        return rec

    def get_command(self, request_id: str) -> Optional[CommandRecord]:
        with self._lock:
            return self._commands.get(request_id)

    def set_command_status(self, request_id: str, status: str) -> bool:
        with self._lock:
            rec = self._commands.get(request_id)
            if rec:
                rec.status = status
                return True
            return False

    def record_command_result(self, request_id: str, **kwargs) -> bool:
        with self._lock:
            rec = self._commands.get(request_id)
            if rec:
                for k, v in kwargs.items():
                    setattr(rec, k, v)
                return True
            return False

    def pending_commands(self, device_id: str) -> list[CommandRecord]:
        with self._lock:
            return [
                r for r in self._commands.values()
                if r.device_id == device_id and r.status == "pending"
            ]

    def command_count(self) -> int:
        with self._lock:
            return len(self._commands)


# Singleton — imported by route modules
store = MemoryStore()
