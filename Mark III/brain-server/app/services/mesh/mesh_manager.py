"""
MARK III Phase 16A — Mesh Manager

The central orchestrator for the MARK III device mesh.

Responsibilities:
  - Self-register the desktop as MARK Core at startup
  - Run a lightweight HTTP server on port 8765 (MARK Mesh port)
  - Accept device registrations and heartbeats from clients
  - Mark devices OFFLINE when heartbeats timeout (45s / 3 missed)
  - Expose presence: which device is the user currently active on?
  - Write mesh events to MeshDiagnostics

REST API (port 8765):
  GET  /mesh/devices    → list all registered devices
  GET  /mesh/status     → counts + active device
  GET  /mesh/presence   → active device + online list
  POST /mesh/register   → register a new device
  POST /mesh/heartbeat  → update last_seen + battery + state

Client heartbeat payload:
  { "device_id": "macbook-m1", "battery": 82, "active": true }

Desktop is always ACTIVE and never goes OFFLINE (it is the brain).
"""
from __future__ import annotations

import json
import logging
import platform
import socket
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from app.services.mesh.device_registry   import DeviceRegistry
from app.services.mesh.mesh_diagnostics  import MeshEvent, diag
from app.services.mesh.mesh_protocol     import (
    Capability, Device, DeviceState, DeviceType, MeshStatus,
)

log = logging.getLogger("markiii.mesh")

MESH_PORT           = 8765
HEARTBEAT_TIMEOUT_S = 45    # device → OFFLINE after 3 missed 15s heartbeats
WATCHDOG_INTERVAL_S = 10    # how often we check for stale heartbeats
DESKTOP_DEVICE_ID   = "desktop-mark-core"

_DESKTOP_CAPABILITIES = [
    Capability.REASONING.value,
    Capability.QWEN.value,
    Capability.COUNCIL.value,
    Capability.REFLEX.value,
    Capability.MICROPHONE.value,
    Capability.SPEAKER.value,
    Capability.DISPLAY.value,
    Capability.AUTOMATION.value,
    Capability.VOICE.value,
]


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
# MeshManager
# ---------------------------------------------------------------------------

class MeshManager:
    """
    One Brain. Multiple Bodies.

    The desktop is always MARK Core.  Mac, iPhone, Watch and future devices
    register themselves and send heartbeats.  The manager routes voice queries,
    tracks presence, and knows which device is active at all times.
    """

    def __init__(self) -> None:
        self._registry   = DeviceRegistry()
        self._server:    Optional[ThreadingHTTPServer] = None
        self._running    = False
        self._start_time = time.monotonic()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        self._register_self()

        threading.Thread(
            target = self._heartbeat_watchdog,
            daemon = True,
            name   = "mesh-watchdog",
        ).start()

        threading.Thread(
            target = self._run_http_server,
            daemon = True,
            name   = "mesh-http",
        ).start()

        log.info(
            "Mesh Manager started — core=%s  port=%d",
            DESKTOP_DEVICE_ID, MESH_PORT,
        )

    def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.shutdown()

    # ------------------------------------------------------------------
    # Desktop self-registration
    # ------------------------------------------------------------------

    def _register_self(self) -> None:
        ip = _local_ip()
        desktop = Device(
            device_id    = DESKTOP_DEVICE_ID,
            name         = f"Desktop ({platform.node()})",
            type         = DeviceType.DESKTOP.value,
            platform     = "windows",
            ip           = ip,
            last_seen    = datetime.now(),
            battery      = None,
            active       = True,
            state        = DeviceState.ACTIVE.value,
            capabilities = _DESKTOP_CAPABILITIES,
        )
        self._registry.register(desktop)
        diag.record(MeshEvent(
            event_type  = "online",
            device_id   = DESKTOP_DEVICE_ID,
            device_name = desktop.name,
            detail      = f"MARK Core started @ {ip}",
        ))
        log.info("MARK Core online: %s @ %s", desktop.name, ip)

    # ------------------------------------------------------------------
    # Public API (called by voice loop, reflex modules, REST handlers)
    # ------------------------------------------------------------------

    def register_device(self, payload: dict, client_ip: str = "") -> Device:
        """Register or re-register a device. Idempotent."""
        device_id = payload["device_id"]
        existing  = self._registry.get(device_id)

        device = Device(
            device_id    = device_id,
            name         = payload.get("name", device_id),
            type         = payload.get("type", DeviceType.UNKNOWN.value),
            platform     = payload.get("platform", "unknown"),
            ip           = payload.get("ip") or client_ip,
            last_seen    = datetime.now(),
            battery      = payload.get("battery"),
            active       = payload.get("active", False),
            state        = DeviceState.ONLINE.value,
            capabilities = payload.get("capabilities", []),
        )
        self._registry.register(device)
        diag.record(MeshEvent(
            event_type  = "register",
            device_id   = device_id,
            device_name = device.name,
            detail      = "new" if not existing else "re-register",
        ))
        return device

    def heartbeat(self, device_id: str, payload: dict) -> Optional[Device]:
        """Update a device's last_seen, battery, and active state."""
        device = self._registry.get(device_id)
        if not device:
            log.warning("Heartbeat from unregistered device: %s", device_id)
            return None

        was_offline = device.state == DeviceState.OFFLINE.value
        new_state   = DeviceState.ACTIVE.value if payload.get("active") else DeviceState.IDLE.value

        device = self._registry.update(
            device_id,
            last_seen = datetime.now(),
            battery   = payload.get("battery", device.battery),
            active    = payload.get("active", device.active),
            state     = new_state,
        )

        if was_offline:
            log.info("Device back online: %s", device.name)
            diag.record(MeshEvent(
                event_type  = "online",
                device_id   = device_id,
                device_name = device.name,
                detail      = "returned after offline",
            ))
        else:
            diag.record(MeshEvent(
                event_type  = "heartbeat",
                device_id   = device_id,
                device_name = device.name,
                detail      = f"battery={payload.get('battery')}  state={new_state}",
            ))

        log.debug("Heartbeat: %s  state=%s  battery=%s", device.name, new_state, payload.get("battery"))
        return device

    def get_device(self, device_id: str) -> Optional[Device]:
        return self._registry.get(device_id)

    def get_all_devices(self) -> list[Device]:
        return self._registry.all()

    def get_online_devices(self) -> list[Device]:
        return self._registry.online()

    def get_active_device(self) -> Optional[Device]:
        """
        Return the device most likely to have the user's attention.
        Uses PresenceFusion for a scored, multi-signal decision.
        Falls back to the desktop if fusion returns nothing.
        """
        try:
            from app.services.mesh.presence_fusion import fuse
            result = fuse(self._registry.all())
            if result:
                return self._registry.get(result.device_id)
        except Exception:
            pass

        # Simple fallback: prefer ACTIVE non-desktop, then most-recent online
        online = self._registry.online()
        if not online:
            return self._registry.get(DESKTOP_DEVICE_ID)
        external_active = [
            d for d in online
            if d.state == DeviceState.ACTIVE.value and d.device_id != DESKTOP_DEVICE_ID
        ]
        if external_active:
            return max(external_active, key=lambda d: d.last_seen)
        active = [d for d in online if d.state == DeviceState.ACTIVE.value]
        if active:
            return max(active, key=lambda d: d.last_seen)
        return max(online, key=lambda d: d.last_seen)

    def get_presence(self):
        """Return full PresenceResult for the reflex presence module."""
        try:
            from app.services.mesh.presence_fusion import fuse
            return fuse(self._registry.all())
        except Exception:
            return None

    def push_to_device(self, device_id: str, text: str, speak: bool = True) -> bool:
        """
        Send a text response to a specific device.
        The device speaks it via native TTS and shows a notification.
        Returns True if delivered.
        """
        device = self._registry.get(device_id)
        if not device or device.state == DeviceState.OFFLINE.value:
            log.warning("push_to_device: %s is offline or unknown", device_id)
            return False
        try:
            import requests
            r = requests.post(
                f"http://{device.ip}:8766/mark/response",
                json={"text": text, "source": DESKTOP_DEVICE_ID, "speak": speak},
                timeout=4,
            )
            ok = r.status_code == 200
            log.info("→ %s: %s (HTTP %d)", device.name, text[:60], r.status_code)
            return ok
        except Exception as e:
            log.warning("push_to_device %s failed: %s", device.name, e)
            return False

    def handoff_conversation(self, device_id: str, last_text: str = "") -> bool:
        """
        Phase 16B: transfer conversation history to another device.
        The receiving device speaks the confirmation and loads the history
        so the next voice query continues the same context.
        """
        device = self._registry.get(device_id)
        if not device or device.state == DeviceState.OFFLINE.value:
            log.warning("handoff: %s is offline", device_id)
            return False
        try:
            import requests
            from app.services.ai.local_qwen_provider import _history
            payload = {
                "text":          f"Continuing from desktop. {last_text}".strip(),
                "history":       list(_history),
                "source_device": "Desktop",
                "source":        DESKTOP_DEVICE_ID,
            }
            r = requests.post(
                f"http://{device.ip}:8766/mark/conversation",
                json=payload,
                timeout=4,
            )
            ok = r.status_code == 200
            log.info("Handoff → %s: %d messages transferred (HTTP %d)", device.name, len(list(_history)), r.status_code)
            return ok
        except Exception as e:
            log.warning("handoff %s failed: %s", device_id, e)
            return False

    def ping_device(self, device_id: str) -> bool:
        """Check if a device's listener is reachable."""
        device = self._registry.get(device_id)
        if not device:
            return False
        try:
            import requests
            r = requests.get(f"http://{device.ip}:8766/mark/ping", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def status(self) -> MeshStatus:
        all_devs = self._registry.all()
        counts   = self._registry.count()
        active   = self.get_active_device()
        return MeshStatus(
            online_count  = counts["online"],
            offline_count = counts["offline"],
            active_device = active.device_id if active else None,
            devices       = [d.to_dict() for d in all_devs],
            mesh_uptime_s = time.monotonic() - self._start_time,
        )

    # ------------------------------------------------------------------
    # Heartbeat watchdog — background thread
    # ------------------------------------------------------------------

    def _heartbeat_watchdog(self) -> None:
        while self._running:
            time.sleep(WATCHDOG_INTERVAL_S)
            cutoff = datetime.now() - timedelta(seconds=HEARTBEAT_TIMEOUT_S)
            for device in self._registry.all():
                if device.device_id == DESKTOP_DEVICE_ID:
                    # Keep desktop heartbeat fresh (we ARE the desktop)
                    self._registry.update(DESKTOP_DEVICE_ID, last_seen=datetime.now())
                    continue
                if device.state != DeviceState.OFFLINE.value:
                    if device.last_seen < cutoff:
                        self._registry.update(
                            device.device_id,
                            state  = DeviceState.OFFLINE.value,
                            active = False,
                        )
                        log.info("Device offline (timeout): %s", device.name)
                        diag.record(MeshEvent(
                            event_type  = "offline",
                            device_id   = device.device_id,
                            device_name = device.name,
                            detail      = f"no heartbeat for {HEARTBEAT_TIMEOUT_S}s",
                        ))

    # ------------------------------------------------------------------
    # HTTP server
    # ------------------------------------------------------------------

    def _run_http_server(self) -> None:
        manager = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                log.debug("Mesh HTTP: " + fmt, *args)

            def _send(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)

            def _body(self) -> Optional[dict]:
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    return json.loads(self.rfile.read(length)) if length else {}
                except Exception:
                    return None

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self):
                if self.path == "/mesh/devices":
                    self._send(200, {
                        "devices": [d.to_dict() for d in manager.get_all_devices()],
                    })

                elif self.path == "/mesh/status":
                    s = manager.status()
                    self._send(200, {
                        "online":        s.online_count,
                        "offline":       s.offline_count,
                        "active_device": s.active_device,
                        "uptime_s":      round(s.mesh_uptime_s, 1),
                        "devices":       s.devices,
                    })

                elif self.path == "/mesh/presence":
                    active = manager.get_active_device()
                    online = manager.get_online_devices()
                    self._send(200, {
                        "active_device":  active.to_dict() if active else None,
                        "online_devices": [d.to_dict() for d in online],
                        "online_count":   len(online),
                    })

                elif self.path == "/mesh/ping":
                    self._send(200, {
                        "status": "ok",
                        "core":   DESKTOP_DEVICE_ID,
                        "time":   datetime.now().isoformat(),
                    })

                else:
                    self._send(404, {"error": "endpoint not found"})

            def do_POST(self):
                # ── /mesh/voice — audio relay from device mic ──────────────
                # Receives raw WAV bytes, runs full pipeline, returns text.
                # ThreadingHTTPServer gives each request its own thread so
                # blocking on Whisper + Council is safe here.
                if self.path == "/mesh/voice":
                    device_id = self.headers.get("X-Device-ID", "unknown")
                    length    = int(self.headers.get("Content-Length", 0))
                    if not length:
                        self._send(400, {"error": "no audio data"})
                        return

                    wav_bytes = self.rfile.read(length)
                    log.info("Voice relay from %s (%d bytes)", device_id, len(wav_bytes))

                    try:
                        from app.services.voice.always_listening_loop import (
                            transcribe, query_council, set_mesh_relay_active,
                        )
                        from app.services.voice.reflex_router import match as _social
                        from app.services.reflex.reflex_router import route as _sys
                        from app.services.voice.conversation_buffer import SentenceValidator

                        validator = SentenceValidator()

                        # Lock desktop voice loop — prevent double response
                        set_mesh_relay_active(True)

                        # STT
                        text = transcribe(wav_bytes)
                        log.info("  Device STT (%s): %r", device_id, text[:80])

                        if not text or validator.is_noise(text):
                            self._send(200, {"text": "", "utterance": text or ""})
                            return

                        # Reflex → Qwen/Council
                        answer = _social(text)
                        if not answer:
                            sys_r = _sys(text)
                            answer = sys_r.text if sys_r.handled else None
                        if not answer:
                            answer = query_council(text)

                        log.info("  Device answer: %r", answer[:80])
                        self._send(200, {"text": answer, "utterance": text})
                        set_mesh_relay_active(False)

                        # Also push to device listener so it speaks immediately
                        # (in parallel — don't block the response)
                        if answer and device_id != "unknown":
                            threading.Thread(
                                target=manager.push_to_device,
                                args=(device_id, answer),
                                kwargs={"speak": False},  # device already has the text
                                daemon=True,
                            ).start()

                    except Exception as e:
                        log.error("Voice relay processing error: %s", e)
                        try:
                            set_mesh_relay_active(False)
                        except Exception:
                            pass
                        self._send(500, {"error": str(e), "utterance": ""})
                    return

                # ── JSON body endpoints ────────────────────────────────────
                payload = self._body()

                if self.path == "/mesh/register":
                    if not payload or "device_id" not in payload:
                        self._send(400, {"error": "device_id required"})
                        return
                    payload.setdefault("ip", self.client_address[0])
                    device = manager.register_device(payload, self.client_address[0])
                    self._send(200, {"status": "registered", "device": device.to_dict()})

                elif self.path == "/mesh/heartbeat":
                    if not payload or "device_id" not in payload:
                        self._send(400, {"error": "device_id required"})
                        return
                    device = manager.heartbeat(payload["device_id"], payload)
                    if device:
                        self._send(200, {"status": "ok", "device": device.to_dict()})
                    else:
                        self._send(404, {"error": "device not registered — call /mesh/register first"})

                else:
                    self._send(404, {"error": "endpoint not found"})

        try:
            self._server = ThreadingHTTPServer(("0.0.0.0", MESH_PORT), _Handler)
            log.info("Mesh HTTP listening on 0.0.0.0:%d", MESH_PORT)
            self._server.serve_forever()   # proper select() loop — no missed responses
        except OSError as e:
            if self._running:
                log.error("Mesh HTTP failed (port %d in use?): %s", MESH_PORT, e)
        except Exception as e:
            if self._running:
                log.error("Mesh HTTP error: %s", e)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager: Optional[MeshManager] = None
_manager_lock = threading.Lock()


def get_mesh_manager() -> MeshManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = MeshManager()
    return _manager
