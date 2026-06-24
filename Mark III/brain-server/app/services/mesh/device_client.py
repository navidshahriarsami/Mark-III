"""
MARK III — Device Client

Run this on any secondary device (MacBook, future iPhone companion app,
Raspberry Pi, etc.) to connect it to the MARK desktop brain.

What it does:
  1. Registers with MARK Core at startup
  2. Sends heartbeats every 15 seconds (battery, active state)
  3. Reports whether the user is actively using this device
  4. Receives push notifications / text responses from MARK (polling)

Usage (MacBook):
    python3 device_client.py --host 192.168.4.85 --name "MacBook Pro M1" --type macbook

Flags:
    --host      MARK Core IP (desktop's local IP, shown in MARK log on startup)
    --port      Mesh port (default 8765)
    --name      Human name for this device
    --type      Device type: macbook | iphone | watch | esp32
    --device-id Unique ID (auto-generated from hostname if omitted)

Dependencies (pip install):
    requests   — HTTP client
    psutil     — battery + idle detection (optional but recommended)

Platform notes:
    macOS:   psutil works, battery detection works, idle via IOKit (optional)
    Windows: psutil works (used on desktop by MARK Core itself)
    Linux:   psutil works
"""
from __future__ import annotations

import argparse
import logging
import platform
import socket
import sys
import time
import threading
from typing import Optional

log = logging.getLogger("mark.device-client")

HEARTBEAT_INTERVAL_S = 15


# ---------------------------------------------------------------------------
# Battery + active state detection (platform-specific)
# ---------------------------------------------------------------------------

def _get_battery() -> Optional[float]:
    """Return battery percentage 0–100, or None if desktop/unknown."""
    try:
        import psutil
        b = psutil.sensors_battery()
        return round(b.percent, 1) if b else None
    except Exception:
        return None


def _is_active() -> bool:
    """Return True if the user has had input in the last 60 seconds."""
    try:
        import psutil
        # Idle time via last input — works on Windows
        if platform.system() == "Windows":
            import ctypes
            class _LII(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            lii = _LII()
            lii.cbSize = ctypes.sizeof(lii)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            idle_ms = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return idle_ms < 60_000

        # macOS: check CPU usage as a proxy (proper IOKit idle needs pyobjc)
        if platform.system() == "Darwin":
            cpu = psutil.cpu_percent(interval=0.2)
            return cpu > 2.0   # any meaningful CPU activity = active

        return True  # default: assume active
    except Exception:
        return True


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# MARKDeviceClient
# ---------------------------------------------------------------------------

class MARKDeviceClient:
    """
    Lightweight agent that connects this machine to the MARK III device mesh.
    Designed to be minimal — runs on any Python 3.8+ machine without a GUI.
    """

    def __init__(
        self,
        core_host:  str,
        core_port:  int   = 8765,
        device_id:  str   = "",
        name:       str   = "",
        device_type: str  = "unknown",
    ) -> None:
        self._base    = f"http://{core_host}:{core_port}"
        self._id      = device_id or f"{device_type}-{platform.node().lower()[:12]}"
        self._name    = name or f"{device_type.title()} ({platform.node()})"
        self._type    = device_type
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Register and begin heartbeat loop."""
        log.info("Connecting to MARK Core @ %s ...", self._base)
        if not self._register():
            log.error("Registration failed — will retry in background")
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="mesh-heartbeat"
        )
        self._thread.start()
        log.info("Device client running. Ctrl-C to stop.")

    def stop(self) -> None:
        self._running = False
        log.info("Device client stopped.")

    def wait(self) -> None:
        if self._thread:
            self._thread.join()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _register(self) -> bool:
        try:
            import requests
            payload = {
                "device_id":    self._id,
                "name":         self._name,
                "type":         self._type,
                "platform":     platform.system().lower(),
                "ip":           _local_ip(),
                "battery":      _get_battery(),
                "active":       _is_active(),
                "capabilities": self._capabilities(),
            }
            r = requests.post(
                f"{self._base}/mesh/register",
                json=payload,
                timeout=5,
            )
            if r.status_code == 200:
                log.info("Registered as %r  id=%s", self._name, self._id)
                return True
            log.warning("Register HTTP %d: %s", r.status_code, r.text[:80])
            return False
        except Exception as e:
            log.warning("Register failed: %s", e)
            return False

    def _capabilities(self) -> list[str]:
        caps = ["microphone", "speaker", "display", "notifications"]
        if self._type in ("iphone",):
            caps += ["location", "battery", "voice", "actions"]
        elif self._type in ("macbook",):
            caps += ["battery", "voice", "actions", "automation"]
        elif self._type in ("watch",):
            caps = ["notifications", "battery", "presence"]
        return caps

    # ------------------------------------------------------------------
    # Heartbeat loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        registered = True
        while self._running:
            try:
                import requests
                payload = {
                    "device_id": self._id,
                    "battery":   _get_battery(),
                    "active":    _is_active(),
                }
                r = requests.post(
                    f"{self._base}/mesh/heartbeat",
                    json=payload,
                    timeout=5,
                )
                if r.status_code == 404 and not registered:
                    # Brain restarted and lost our registration — re-register
                    log.info("Re-registering with MARK Core ...")
                    registered = self._register()
                elif r.status_code == 200:
                    registered = True
                    log.debug(
                        "Heartbeat OK  battery=%s  active=%s",
                        payload["battery"], payload["active"],
                    )
                else:
                    log.warning("Heartbeat HTTP %d", r.status_code)

            except Exception as e:
                log.debug("Heartbeat error (will retry): %s", e)

            time.sleep(HEARTBEAT_INTERVAL_S)


# ---------------------------------------------------------------------------
# CLI entry point — run this on Mac/future devices
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MARK III Device Client — connect this machine to the MARK mesh",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 device_client.py --host 192.168.4.85 --name "MacBook Pro M1" --type macbook
  python3 device_client.py --host 192.168.1.50 --type iphone --name "iPhone 15"
        """,
    )
    parser.add_argument("--host",      required=True,          help="MARK Core IP address")
    parser.add_argument("--port",      type=int, default=8765, help="Mesh port (default 8765)")
    parser.add_argument("--name",      default="",             help="Human name for this device")
    parser.add_argument("--type",      default="unknown",
                        choices=["macbook", "iphone", "watch", "desktop", "esp32", "unknown"],
                        help="Device type")
    parser.add_argument("--device-id", default="",             help="Override auto-generated device ID")
    parser.add_argument("--verbose",   action="store_true",    help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level   = logging.DEBUG if args.verbose else logging.INFO,
        format  = "%(asctime)s [%(name)s] %(message)s",
    )

    client = MARKDeviceClient(
        core_host   = args.host,
        core_port   = args.port,
        device_id   = args.device_id,
        name        = args.name,
        device_type = args.type,
    )

    try:
        client.start()
        client.wait()
    except KeyboardInterrupt:
        client.stop()
        print("\nDisconnected from MARK Core.")


if __name__ == "__main__":
    main()
