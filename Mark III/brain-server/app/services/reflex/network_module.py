"""
MARK III Reflex — Network Module

Handles: internet status, IP address, WiFi, ping.
All checks are local or use lightweight socket calls.
"""
from __future__ import annotations

import re
import socket
import time
from typing import Optional

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(am i|are we|is (the|my)) (online|connected|on the internet)\b|\binternet (status|connection|check)\b|\bdo i have internet\b", re.I), "internet"),
    (re.compile(r"\b(my |what.?s (my )?)(ip|ip address|local ip)\b",                                  re.I), "local_ip"),
    (re.compile(r"\bwifi\b|\bwi-fi\b|\bwireless (network|connection|status)\b",                        re.I), "wifi"),
    (re.compile(r"\b(internet |network |connection )speed\b|\bhow fast is (my |the )?(internet|wifi|network)\b", re.I), "speed"),
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


def _get_internet() -> str:
    try:
        socket.setdefaulttimeout(2)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return "Yes, internet is connected."
    except OSError:
        return "No internet connection detected."


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"Local IP is {ip}."
    except Exception:
        return "Could not determine local IP."


def _get_wifi() -> str:
    try:
        import subprocess
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=3,
        )
        if "State" in result.stdout:
            for line in result.stdout.splitlines():
                if "SSID" in line and "BSSID" not in line:
                    ssid = line.split(":", 1)[-1].strip()
                    return f"Connected to WiFi network: {ssid}."
                if "State" in line and "disconnected" in line.lower():
                    return "WiFi is disconnected."
        return _get_internet()
    except Exception:
        return _get_internet()


def _get_speed() -> str:
    # Basic latency check — full speed test would require speedtest-cli
    try:
        t0 = time.monotonic()
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        ping_ms = (time.monotonic() - t0) * 1000
        return f"Ping to Google DNS is {ping_ms:.0f} ms. For full speed test, run speedtest."
    except Exception:
        return "Could not measure network speed."
