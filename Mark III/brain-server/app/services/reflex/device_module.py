"""
MARK III Reflex — Device Module

Handles: laptop battery, connected devices.
Future: Device Mesh, phone battery, Apple Watch.
"""
from __future__ import annotations

import re
from typing import Optional

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(laptop|computer|my) battery\b|\bpower (level|status)\b|\bhow (charged|much charge)\b", re.I), "battery"),
    (re.compile(r"\b(connected|paired) (devices|bluetooth)\b|\bwhat'?s connected\b",                        re.I), "devices"),
]


def can_handle(text: str) -> bool:
    return any(p.search(text) for p, _ in _PATTERNS)


def handle(text: str) -> Optional[str]:
    for pattern, action in _PATTERNS:
        if pattern.search(text):
            fn = globals().get(f"_get_{action}")
            if fn:
                return fn()
    return None


def _get_battery() -> str:
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return "No battery sensor found — likely a desktop."
        status = "charging" if b.power_plugged else "discharging"
        return f"Battery is at {b.percent:.0f} percent, {status}."
    except ImportError:
        return "Battery info unavailable."


def _get_devices() -> str:
    # Stub — Device Mesh integration planned
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-PnpDevice -Class Bluetooth -Status OK | Select-Object -ExpandProperty FriendlyName | Select-Object -First 5"],
            capture_output=True, text=True, timeout=3,
        )
        devices = [d.strip() for d in result.stdout.strip().splitlines() if d.strip()]
        if devices:
            return f"Bluetooth devices: {', '.join(devices)}."
        return "No Bluetooth devices connected."
    except Exception:
        return "Device list unavailable."
