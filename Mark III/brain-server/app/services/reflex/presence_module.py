"""
MARK III Reflex — Presence & Mesh Module

Handles:
  1. Device Mesh queries (Phase 16A) — which devices online, active device, mesh status
  2. User idle time via Windows API (no hardware needed)

Radar / RF human presence detection (TI IWR6843ISK) is PARKED.
Hardware not yet available. Stub returns gracefully.
"""
from __future__ import annotations

import re
from typing import Optional

# ── Device mesh patterns ──────────────────────────────────────────────────────
_MESH_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(
        r"\b(which|what) devices? (are|is) (online|connected|active|nearby)\b"
        r"|\bhow many devices?\b"
        r"|\bwhat devices? (can you see|are in the mesh)\b",
        re.I,
    ), "mesh_devices"),
    (re.compile(
        r"\b(is|are) (my )?(mac(book)?|phone|iphone|watch|desktop|laptop)"
        r"( (online|connected|active|on|off|there|offline))?\b",
        re.I,
    ), "mesh_device_check"),
    (re.compile(
        r"\bwhere am i\b"
        r"|\bwhich device (is active|am i (on|using))\b"
        r"|\bwhat (device|screen) am i (on|using|at)\b",
        re.I,
    ), "mesh_active"),
    (re.compile(
        r"\b(device )?mesh (status|check|overview|health)\b"
        r"|\bwhat('?s| is) connected\b",
        re.I,
    ), "mesh_status"),
]

# ── Simple presence / idle patterns (no hardware needed) ──────────────────────
_IDLE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bhow (long|long have i been) (idle|inactive|away|gone)\b", re.I), "idle_time"),
    (re.compile(r"\bare you (there|online|listening|awake|active|up)\b", re.I), "online_check"),
]


def can_handle(text: str) -> bool:
    return (
        any(p.search(text) for p, _ in _MESH_PATTERNS) or
        any(p.search(text) for p, _ in _IDLE_PATTERNS)
    )


def handle(text: str) -> Optional[str]:
    for pattern, action in _MESH_PATTERNS:
        if pattern.search(text):
            fn = globals().get(f"_get_{action}")
            if fn:
                return fn(text)
    for pattern, action in _IDLE_PATTERNS:
        if pattern.search(text):
            fn = globals().get(f"_get_{action}")
            if fn:
                return fn()
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Idle time (Windows API — no hardware)
# ─────────────────────────────────────────────────────────────────────────────

def _get_online_check() -> str:
    return "Yes, I'm here."


def _get_idle_time() -> str:
    try:
        import ctypes

        class _LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = _LII()
        lii.cbSize = ctypes.sizeof(lii)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        idle_ms = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        idle_s  = idle_ms // 1000

        if idle_s < 30:
            return "You were just active — less than 30 seconds ago."
        elif idle_s < 120:
            return f"You've been inactive for about {idle_s} seconds."
        elif idle_s < 3600:
            mins = idle_s // 60
            return f"Inactive for {mins} minute{'s' if mins != 1 else ''}."
        else:
            hours = idle_s // 3600
            return f"Inactive for {hours} hour{'s' if hours != 1 else ''}."
    except Exception:
        return "Idle time unavailable."


# ─────────────────────────────────────────────────────────────────────────────
# Device Mesh handlers (Phase 16A)
# ─────────────────────────────────────────────────────────────────────────────

def _get_mesh_devices(text: str = "") -> str:
    try:
        from app.services.mesh.mesh_manager import get_mesh_manager
        online = get_mesh_manager().get_online_devices()
        if not online:
            return "Only the desktop is registered in the mesh right now."
        names = [d.name for d in online]
        if len(names) == 1:
            return f"{names[0]} is online."
        return "Online: " + ", ".join(names[:-1]) + " and " + names[-1] + "."
    except Exception:
        return "Device mesh not running."


def _get_mesh_device_check(text: str) -> str:
    try:
        from app.services.mesh.mesh_manager import get_mesh_manager
        mgr = get_mesh_manager()
        tl  = text.lower()
        target = None
        if "macbook" in tl or " mac" in tl:   target = "macbook"
        elif "iphone" in tl or "phone" in tl:  target = "iphone"
        elif "watch" in tl:                     target = "watch"
        elif "desktop" in tl or "laptop" in tl: target = "desktop"

        if not target:
            return _get_mesh_devices()

        for d in mgr.get_all_devices():
            if target in d.type.lower() or target in d.name.lower():
                battery = f", battery {d.battery:.0f}%" if d.battery is not None else ""
                return f"{d.name} is {d.state}{battery}."
        return f"No {target} registered in the mesh yet."
    except Exception:
        return "Device mesh not running."


def _get_mesh_active(text: str = "") -> str:
    try:
        from app.services.mesh.mesh_manager import get_mesh_manager
        active = get_mesh_manager().get_active_device()
        if not active:
            return "Desktop is the only active device."
        battery = f" — battery {active.battery:.0f}%" if active.battery is not None else ""
        return f"You appear to be on {active.name}{battery}."
    except Exception:
        return "Device mesh not running."


def _get_mesh_status(text: str = "") -> str:
    try:
        from app.services.mesh.mesh_manager import get_mesh_manager
        s = get_mesh_manager().status()
        return (
            f"Mesh: {s.online_count} device{'s' if s.online_count != 1 else ''} online, "
            f"{s.offline_count} offline."
        )
    except Exception:
        return "Device mesh not running."
