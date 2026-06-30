"""
MARK III Phase 16A — Mesh Protocol

Canonical data types shared by all mesh components.
Devices send/receive these over the mesh HTTP API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────

class DeviceType(str, Enum):
    DESKTOP = "desktop"
    MACBOOK = "macbook"
    IPHONE  = "iphone"
    WATCH   = "watch"
    ESP32   = "esp32"
    RADAR   = "radar"
    GLASSES = "glasses"
    UNKNOWN = "unknown"


class DeviceState(str, Enum):
    ONLINE  = "online"    # reachable, not focused
    OFFLINE = "offline"   # no heartbeat within timeout
    ACTIVE  = "active"    # user is currently on this device
    IDLE    = "idle"      # reachable, user stepped away


class Capability(str, Enum):
    # Input/output
    MICROPHONE    = "microphone"
    SPEAKER       = "speaker"
    DISPLAY       = "display"
    NOTIFICATIONS = "notifications"
    # Sensing
    LOCATION      = "location"
    BATTERY       = "battery"
    PRESENCE      = "presence"
    # Intelligence (desktop only)
    REASONING     = "reasoning"
    QWEN          = "qwen"
    COUNCIL       = "council"
    REFLEX        = "reflex"
    # Action
    AUTOMATION    = "automation"
    ACTIONS       = "actions"
    VOICE         = "voice"
    # Governance
    APPROVAL_AUTHORITY = "approval_authority"   # may resolve CRITICAL-tier action approvals


# ─────────────────────────────────────────────────────────────────
# Device
# ─────────────────────────────────────────────────────────────────

@dataclass
class Device:
    """
    A device registered in the MARK III mesh.
    The desktop is the permanent MARK Core; all others are portals.
    """
    device_id:    str
    name:         str
    type:         str                  # DeviceType value
    platform:     str                  # "windows" | "macos" | "ios" | "watchos" | "linux"
    ip:           str
    last_seen:    datetime
    battery:      Optional[float]      # 0–100 or None (desktops have no battery)
    active:       bool
    state:        str                  # DeviceState value
    capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "device_id":    self.device_id,
            "name":         self.name,
            "type":         self.type,
            "platform":     self.platform,
            "ip":           self.ip,
            "last_seen":    self.last_seen.isoformat(),
            "battery":      self.battery,
            "active":       self.active,
            "state":        self.state,
            "capabilities": self.capabilities,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Device":
        return cls(
            device_id    = d["device_id"],
            name         = d.get("name", d["device_id"]),
            type         = d.get("type",     DeviceType.UNKNOWN.value),
            platform     = d.get("platform", "unknown"),
            ip           = d.get("ip",       ""),
            last_seen    = datetime.fromisoformat(d["last_seen"]),
            battery      = d.get("battery"),
            active       = d.get("active", False),
            state        = d.get("state",   DeviceState.OFFLINE.value),
            capabilities = d.get("capabilities", []),
        )


# ─────────────────────────────────────────────────────────────────
# API messages
# ─────────────────────────────────────────────────────────────────

@dataclass
class HeartbeatPayload:
    device_id: str
    battery:   Optional[float] = None
    active:    bool            = True
    timestamp: Optional[str]   = None   # ISO-8601


@dataclass
class MeshStatus:
    online_count:  int
    offline_count: int
    active_device: Optional[str]   # device_id
    devices:       list[dict]
    mesh_uptime_s: float
