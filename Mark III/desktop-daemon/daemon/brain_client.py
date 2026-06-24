"""
MARK III — Brain Client

Async HTTP bridge between the desktop daemon and the unified-brain-server.
Runs three independent loops inside the daemon's asyncio event loop:

  heartbeat_loop   — POST /api/v1/heartbeat          every 30 s
  snapshot_loop    — POST /api/v1/snapshot            on meaningful window change
  command_poll     — GET  /api/v1/commands/pending    every 5 s (sudo approvals)

Fault model:
  - Connection failures use exponential backoff (2 s → 64 s cap).
  - A circuit breaker opens after 5 consecutive failures and pauses all
    outbound calls for 60 s before probing again.
  - No failure in any loop propagates to the daemon's other subsystems.
  - Tray status callbacks (on_connect / on_disconnect) let the icon dot
    reflect real connectivity without coupling this module to pystray.
"""

import asyncio
import logging
import socket
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Callable, Optional

import httpx

from daemon.payload import build_snapshot_payload, SnapshotPayload
from daemon.screen_monitor import WindowSnapshot

# Stdlib 'platform' is shadowed by our local platform/ package folder.
# Use socket and sys directly for the two values we need.
_HOSTNAME    = socket.gethostname()
_OS_PLATFORM = sys.platform          # e.g. "win32"

logger = logging.getLogger("markiii.brain_client")

# ---------------------------------------------------------------------------
# Configuration defaults — overridden by daemon_config.yaml at runtime
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL              = "http://localhost:8000"
HEARTBEAT_INTERVAL_S          = 30
SNAPSHOT_POLL_INTERVAL_S      = 10
COMMAND_POLL_INTERVAL_S       = 5
REQUEST_TIMEOUT_S             = 8.0
BACKOFF_BASE_S                = 2.0
BACKOFF_CAP_S                 = 64.0
CIRCUIT_BREAKER_THRESHOLD     = 5      # consecutive failures before open
CIRCUIT_BREAKER_RESET_S       = 60.0  # seconds to wait before half-open probe


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class _CBState(Enum):
    CLOSED    = auto()   # normal operation
    OPEN      = auto()   # blocking calls, waiting to probe
    HALF_OPEN = auto()   # single probe allowed


@dataclass
class _CircuitBreaker:
    threshold: int   = CIRCUIT_BREAKER_THRESHOLD
    reset_s:   float = CIRCUIT_BREAKER_RESET_S

    _state:       _CBState = field(default=_CBState.CLOSED, init=False)
    _failures:    int       = field(default=0,               init=False)
    _opened_at:   float     = field(default=0.0,             init=False)

    @property
    def allows_request(self) -> bool:
        if self._state == _CBState.CLOSED:
            return True
        if self._state == _CBState.OPEN:
            if time.monotonic() - self._opened_at >= self.reset_s:
                self._state = _CBState.HALF_OPEN
                logger.info("Circuit breaker → HALF-OPEN (probing brain server).")
                return True
            return False
        return True   # HALF_OPEN

    def record_success(self) -> None:
        if self._state != _CBState.CLOSED:
            logger.info("Circuit breaker → CLOSED (brain server reachable).")
        self._state    = _CBState.CLOSED
        self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._state == _CBState.HALF_OPEN or self._failures >= self.threshold:
            if self._state != _CBState.OPEN:
                logger.warning(
                    "Circuit breaker → OPEN after %d failure(s). "
                    "Pausing brain calls for %d s.",
                    self._failures, int(self.reset_s),
                )
            self._state     = _CBState.OPEN
            self._opened_at = time.monotonic()


# ---------------------------------------------------------------------------
# Retry helper with exponential backoff
# ---------------------------------------------------------------------------

async def _with_backoff(label: str, attempt: int) -> None:
    """Sleep for 2^attempt seconds, capped at BACKOFF_CAP_S."""
    delay = min(BACKOFF_BASE_S ** attempt, BACKOFF_CAP_S)
    logger.debug("%s — retry in %.0f s (attempt %d).", label, delay, attempt)
    await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# Device identity — stable across restarts
# ---------------------------------------------------------------------------

def _device_id() -> str:
    """
    Derive a stable device ID from the machine's hostname + MAC address.
    Not a security token — just a consistent identifier for the brain server
    to correlate sessions from the same machine.
    """
    mac  = uuid.getnode()
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{_HOSTNAME}-{mac}"))


# ---------------------------------------------------------------------------
# Brain client
# ---------------------------------------------------------------------------

class BrainClient:
    """
    Async client for the unified-brain-server.  Create once inside
    MarkIIIDaemon and pass to the subsystems that need it.

    Usage:
        async with BrainClient(base_url="http://localhost:8000") as client:
            await asyncio.gather(
                client.heartbeat_loop(),
                client.snapshot_loop(snapshot_source),
                client.command_poll(on_command_cb),
            )
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        on_connect:    Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
    ) -> None:
        self._base      = base_url.rstrip("/")
        self._device_id = _device_id()
        self._cb        = _CircuitBreaker()
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False

        # Optional tray callbacks — called from this async context (daemon thread)
        self._on_connect    = on_connect    or (lambda: None)
        self._on_disconnect = on_disconnect or (lambda: None)

        logger.info("Brain client initialised. device_id=%s  base=%s",
                    self._device_id, self._base)

    # ------------------------------------------------------------------
    # Context manager — manages the shared httpx session
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BrainClient":
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=REQUEST_TIMEOUT_S,
            headers={
                "X-Device-ID":  self._device_id,
                "X-Agent":      f"MarkIII-Desktop/{_HOSTNAME}",
                "Content-Type": "application/json",
            },
        )
        await self._register_device()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    async def _post(self, path: str, payload: dict) -> Optional[dict]:
        """
        POST with circuit-breaker guard. Returns parsed JSON or None on error.
        """
        if not self._cb.allows_request:
            return None
        try:
            r = await self._client.post(path, json=payload)
            r.raise_for_status()
            self._cb.record_success()
            self._set_connected(True)
            return r.json() if r.content else {}
        except httpx.HTTPStatusError as exc:
            logger.warning("Brain server HTTP %d on %s.", exc.response.status_code, path)
            self._cb.record_failure()
            return None
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            logger.warning("Brain server unreachable (%s): %s.", type(exc).__name__, exc)
            self._cb.record_failure()
            self._set_connected(False)
            return None

    async def _get(self, path: str, params: dict | None = None) -> Optional[dict]:
        if not self._cb.allows_request:
            return None
        try:
            r = await self._client.get(path, params=params or {})
            r.raise_for_status()
            self._cb.record_success()
            self._set_connected(True)
            return r.json()
        except (httpx.ConnectError, httpx.TimeoutException,
                httpx.HTTPStatusError, httpx.RemoteProtocolError) as exc:
            logger.debug("GET %s failed: %s.", path, exc)
            self._cb.record_failure()
            self._set_connected(False)
            return None

    def _set_connected(self, state: bool) -> None:
        if state == self._connected:
            return
        self._connected = state
        if state:
            logger.info("Brain server connection established.")
            self._on_connect()
        else:
            logger.warning("Brain server connection lost.")
            self._on_disconnect()

    # ------------------------------------------------------------------
    # Device registration
    # ------------------------------------------------------------------

    async def _register_device(self) -> None:
        """
        Called once on startup. The brain server uses this to create or
        update the device record so it can push notifications back.
        Failures are non-fatal — the daemon runs offline if the server is down.
        """
        payload = {
            "device_id": self._device_id,
            "hostname":  _HOSTNAME,
            "platform":  _OS_PLATFORM,
            "version":   sys.version,
        }
        result = await self._post("/api/v1/devices/register", payload)
        if result is not None:
            logger.info("Device registered with brain server. device_id=%s", self._device_id)
        else:
            logger.warning(
                "Device registration failed — brain server may be offline. "
                "Daemon will retry via heartbeat loop."
            )

    # ------------------------------------------------------------------
    # Loop 1: Heartbeat
    # ------------------------------------------------------------------

    async def heartbeat_loop(self) -> None:
        """
        Fires a lightweight POST every HEARTBEAT_INTERVAL_S seconds.
        Carries daemon health metrics the brain server can surface in the
        mobile app status view.
        """
        logger.info("Heartbeat loop starting (interval=%d s).", HEARTBEAT_INTERVAL_S)
        attempt = 0

        while True:
            payload = {
                "device_id":  self._device_id,
                "ts":         time.time(),
                "uptime_s":   time.monotonic(),
                "connected":  self._connected,
            }
            result = await self._post("/api/v1/heartbeat", payload)

            if result is None:
                attempt += 1
                await _with_backoff("heartbeat", attempt)
            else:
                attempt = 0
                await asyncio.sleep(HEARTBEAT_INTERVAL_S)

    # ------------------------------------------------------------------
    # Loop 2: Window snapshot relay
    # ------------------------------------------------------------------

    async def snapshot_loop(
        self,
        snapshot_source: Callable[[], "asyncio.Coroutine[None, None, Optional[WindowSnapshot]]"],
    ) -> None:
        """
        Polls the screen monitor every SNAPSHOT_POLL_INTERVAL_S seconds.
        Only sends a payload to the brain server when the active window
        has meaningfully changed (different process or title).
        """
        logger.info("Snapshot relay loop starting (interval=%d s).", SNAPSHOT_POLL_INTERVAL_S)
        last_key: Optional[str] = None
        attempt = 0

        while True:
            await asyncio.sleep(SNAPSHOT_POLL_INTERVAL_S)

            snapshot: Optional[WindowSnapshot] = await snapshot_source()
            if snapshot is None:
                continue

            # Deduplicate — only post if the window actually changed
            current_key = f"{snapshot.process_name}::{snapshot.window_title[:80]}"
            if current_key == last_key:
                continue
            last_key = current_key

            payload = build_snapshot_payload(snapshot, self._device_id)
            result  = await self._post("/api/v1/snapshot", asdict(payload))

            if result is None:
                attempt += 1
                # Don't backoff aggressively here — just skip this snapshot
                # and wait for the next poll cycle
            else:
                attempt = 0
                logger.debug(
                    "Snapshot posted: process=%s  classified=%s",
                    payload.process_name, payload.classification,
                )

    # ------------------------------------------------------------------
    # Loop 3: Pending command poll (sudo approval flow)
    # ------------------------------------------------------------------

    async def command_poll(
        self,
        on_command: Callable[[dict], "asyncio.Coroutine"],
    ) -> None:
        """
        Polls for commands queued by the brain server (e.g. sudo approvals
        initiated from the mobile app). Passes each command dict to
        on_command() which feeds it into executor.py's HITL gate.
        """
        logger.info("Command poll loop starting (interval=%d s).", COMMAND_POLL_INTERVAL_S)

        while True:
            await asyncio.sleep(COMMAND_POLL_INTERVAL_S)

            data = await self._get(
                "/api/v1/commands/pending",
                params={"device_id": self._device_id},
            )
            if not data:
                continue

            commands: list[dict] = data.get("commands", [])
            for cmd in commands:
                logger.info(
                    "Incoming command from brain: id=%s  raw=%r",
                    cmd.get("id"), cmd.get("raw", "")[:60],
                )
                asyncio.create_task(on_command(cmd), name=f"cmd-{cmd.get('id','?')}")

    # ------------------------------------------------------------------
    # Ad-hoc calls (used by executor.py HITL gate)
    # ------------------------------------------------------------------

    async def post_pending_command(self, req) -> None:
        """Notify the brain server that a privileged command is awaiting approval."""
        payload = {
            "device_id":  self._device_id,
            "request_id": req.id,
            "raw":        req.raw,
            "requester":  req.requester,
        }
        await self._post("/api/v1/commands/pending", payload)

    async def poll_command_status(self, request_id: str) -> str:
        """
        Return 'approved', 'denied', or 'pending'.
        Called by executor.py in a polling loop while waiting for mobile approval.
        """
        data = await self._get(f"/api/v1/commands/{request_id}/status")
        if data is None:
            return "pending"
        return data.get("status", "pending")

    async def post_command_result(self, result) -> None:
        """Post the execution result back to the brain server for audit logging."""
        payload = {
            "device_id":   self._device_id,
            "request_id":  result.request_id,
            "status":      result.status.name,
            "stdout":      result.stdout[:4096],
            "stderr":      result.stderr[:2048],
            "returncode":  result.returncode,
        }
        await self._post(f"/api/v1/commands/{result.request_id}/result", payload)
