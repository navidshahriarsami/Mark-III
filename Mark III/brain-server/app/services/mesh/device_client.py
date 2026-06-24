"""
MARK III Phase 16B — Device Client (Interactive Mesh)

Runs on MacBook (or any secondary device). Two-way mesh:

  Outbound (device → desktop):
    - Registration on startup
    - Heartbeat every 15s (battery, active state)

  Inbound (desktop → device):
    - HTTP listener on port 8766
    - POST /mark/response       → speak text + show notification
    - POST /mark/conversation   → receive conversation history transfer
    - POST /mark/ping           → connectivity check
    - GET  /mark/status         → device status

Usage (MacBook):
    python3 device_client.py --host 192.168.4.85 --name "MacBook Pro M1" --type macbook

Install deps (Mac):
    pip3 install requests psutil
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import socket
import subprocess
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

log = logging.getLogger("mark.device-client")

HEARTBEAT_INTERVAL_S = 15
LISTENER_PORT        = 8766    # MARK Core pushes to this port on the device


# ─── Platform helpers ──────────────────────────────────────────────────────────

def _get_battery() -> Optional[float]:
    try:
        import psutil
        b = psutil.sensors_battery()
        return round(b.percent, 1) if b else None
    except Exception:
        return None


def _is_active() -> bool:
    """True if user had input in the last 60 seconds."""
    try:
        if platform.system() == "Darwin":
            # macOS: check CPU activity as a proxy
            import psutil
            return psutil.cpu_percent(interval=0.2) > 1.5
        if platform.system() == "Windows":
            import ctypes
            class _LII(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            lii = _LII(); lii.cbSize = ctypes.sizeof(lii)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) < 60_000
    except Exception:
        pass
    return True


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ─── Delivery: TTS + notification ─────────────────────────────────────────────

def _speak(text: str) -> None:
    """Speak text using the device's native TTS."""
    try:
        if platform.system() == "Darwin":
            subprocess.run(["say", "-v", "Samantha", "-r", "185", text], timeout=30)
        elif platform.system() == "Windows":
            safe = text.replace("'", "''")
            subprocess.run(
                ["powershell", "-Command",
                 f"Add-Type -AssemblyName System.Speech; "
                 f"$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak('{safe}')"],
                timeout=30,
            )
    except Exception as e:
        log.warning("TTS failed: %s", e)


def _notify(title: str, text: str) -> None:
    """Show a system notification."""
    try:
        if platform.system() == "Darwin":
            safe = text[:120].replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{safe}" with title "MARK III" subtitle "{title}"'],
                timeout=3,
            )
        elif platform.system() == "Windows":
            # Windows toast via PowerShell (works without extra packages)
            safe = text[:120].replace("'", "''")
            subprocess.run(
                ["powershell", "-Command",
                 f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null; "
                 f"$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(0); "
                 f"$t.SelectSingleNode('//text').InnerText = '{safe}'; "
                 f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('MARK III').Show("
                 f"[Windows.UI.Notifications.ToastNotification]::new($t))"],
                timeout=3,
            )
    except Exception as e:
        log.debug("Notification failed: %s", e)


def _deliver(text: str, source: str = "MARK", speak: bool = True) -> None:
    """Speak text and show notification — runs in a background thread."""
    log.info("← %s: %s", source, text[:100])
    _notify(f"From {source}", text)
    if speak:
        _speak(text)


# ─── MARKDeviceClient ─────────────────────────────────────────────────────────

class MARKDeviceClient:
    """
    Bidirectional MARK III mesh client.
    Connects this device to the desktop brain and listens for inbound messages.
    """

    def __init__(
        self,
        core_host:   str,
        core_port:   int  = 8765,
        device_id:   str  = "",
        name:        str  = "",
        device_type: str  = "unknown",
        listen_port: int  = LISTENER_PORT,
        tts:         bool = True,
    ) -> None:
        self._base        = f"http://{core_host}:{core_port}"
        self._id          = device_id or f"{device_type}-{platform.node().lower()[:12]}"
        self._name        = name or f"{device_type.title()} ({platform.node()})"
        self._type        = device_type
        self._listen_port = listen_port
        self._tts         = tts
        self._running     = False
        self._hb_thread:  Optional[threading.Thread] = None
        self._conversation_history: list = []

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        log.info("Connecting to MARK Core @ %s ...", self._base)
        if not self._register():
            log.warning("Registration failed — will retry via heartbeat loop")

        self._running = True

        # Inbound listener
        threading.Thread(
            target=self._run_listener, daemon=True, name="mesh-listener"
        ).start()

        # Outbound heartbeat
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="mesh-heartbeat"
        )
        self._hb_thread.start()

        log.info(
            "MARK client running — listening on port %d  ·  heartbeat every %ds",
            self._listen_port, HEARTBEAT_INTERVAL_S,
        )

    def stop(self) -> None:
        self._running = False

    def wait(self) -> None:
        if self._hb_thread:
            self._hb_thread.join()

    # ── Registration ───────────────────────────────────────────────────────────

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
            r = requests.post(f"{self._base}/mesh/register", json=payload, timeout=5)
            if r.status_code == 200:
                log.info("Registered as %r  id=%s", self._name, self._id)
                return True
            log.warning("Register HTTP %d", r.status_code)
        except Exception as e:
            log.warning("Register failed: %s", e)
        return False

    def _capabilities(self) -> list[str]:
        caps = ["microphone", "speaker", "display", "notifications"]
        if self._type == "macbook":
            caps += ["battery", "voice", "actions", "automation"]
        elif self._type == "iphone":
            caps += ["location", "battery", "voice", "actions"]
        elif self._type == "watch":
            caps = ["notifications", "battery", "presence"]
        return caps

    # ── Heartbeat loop ─────────────────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
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
                    f"{self._base}/mesh/heartbeat", json=payload, timeout=5
                )
                if r.status_code == 404 and not registered:
                    registered = self._register()
                elif r.status_code == 200:
                    registered = True
                    log.debug("♥ battery=%s  active=%s", payload["battery"], payload["active"])
            except Exception as e:
                log.debug("Heartbeat error: %s", e)
            time.sleep(HEARTBEAT_INTERVAL_S)

    # ── Inbound HTTP listener ──────────────────────────────────────────────────

    def _run_listener(self) -> None:
        client = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _json(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)

            def _body(self) -> dict:
                try:
                    n = int(self.headers.get("Content-Length", 0))
                    return json.loads(self.rfile.read(n)) if n else {}
                except Exception:
                    return {}

            def do_GET(self):
                if self.path == "/mark/status":
                    self._json(200, {
                        "device_id": client._id,
                        "name":      client._name,
                        "battery":   _get_battery(),
                        "active":    _is_active(),
                        "platform":  platform.system(),
                    })
                elif self.path == "/mark/ping":
                    self._json(200, {"status": "ok", "device": client._id})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                body = self._body()

                # ── Text response / message from MARK ──────────────────────
                if self.path == "/mark/response":
                    text   = body.get("text", "")
                    source = body.get("source", "MARK")
                    speak  = body.get("speak", True) and client._tts
                    self._json(200, {"status": "ok", "received": bool(text)})
                    if text:
                        threading.Thread(
                            target=_deliver, args=(text, source, speak), daemon=True
                        ).start()

                # ── Conversation handoff from desktop ─────────────────────
                elif self.path == "/mark/conversation":
                    history      = body.get("history", [])
                    last_text    = body.get("text", "")
                    source_device = body.get("source_device", "Desktop")
                    client._conversation_history = history
                    self._json(200, {"status": "ok", "history_len": len(history)})
                    log.info("Conversation transferred: %d messages", len(history))
                    msg = f"Conversation transferred from {source_device}."
                    threading.Thread(target=_deliver, args=(msg, "MARK", client._tts), daemon=True).start()

                # ── Ping ──────────────────────────────────────────────────
                elif self.path == "/mark/ping":
                    self._json(200, {"status": "ok"})

                else:
                    self._json(404, {"error": "not found"})

        try:
            server = HTTPServer(("0.0.0.0", self._listen_port), _Handler)
            log.info("MARK listener ready on 0.0.0.0:%d", self._listen_port)
            server.serve_forever()
        except OSError as e:
            log.error("Listener failed (port %d): %s", self._listen_port, e)


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MARK III Device Client — bidirectional mesh node",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 device_client.py --host 192.168.4.85 --name "MacBook Pro M1" --type macbook
  python3 device_client.py --host 100.94.x.x   --type iphone  --no-tts
        """,
    )
    parser.add_argument("--host",      required=True)
    parser.add_argument("--port",      type=int, default=8765)
    parser.add_argument("--name",      default="")
    parser.add_argument("--type",      default="unknown",
                        choices=["macbook", "iphone", "watch", "desktop", "esp32", "unknown"])
    parser.add_argument("--device-id", default="")
    parser.add_argument("--listen-port", type=int, default=LISTENER_PORT)
    parser.add_argument("--no-tts",    action="store_true", help="Disable TTS playback")
    parser.add_argument("--verbose",   action="store_true")
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
        listen_port = args.listen_port,
        tts         = not args.no_tts,
    )

    try:
        client.start()
        client.wait()
    except KeyboardInterrupt:
        client.stop()
        print("\nDisconnected.")


if __name__ == "__main__":
    main()
