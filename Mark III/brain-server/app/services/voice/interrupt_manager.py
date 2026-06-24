"""
MARK III — Interrupt Manager (Phase 11)

Handles barge-in, stop-speaking, and request cancellation during voice sessions.

Why this matters:
  Without an interrupt layer, MARK III will finish speaking even if the user
  has already started talking again. That feels unnatural. The interrupt manager
  provides asyncio Events that each pipeline stage checks/awaits, enabling
  clean mid-response cancellation without killing the entire session.

Interrupt types:
  STOP_SPEAKING   — cancel the current TTS playback immediately
  CANCEL_REQUEST  — abort the in-flight LLM conversation call
  BARGE_IN        — new user speech detected during playback
                    (triggers STOP_SPEAKING + begins new LISTENING phase)
  FULL_RESET      — return to IDLE, clear all pending state

Pipeline integration:
  TTS playback loop:
    while playing_chunk:
      if interrupt.is_set(session_id, STOP_SPEAKING):
          stop()
          break

  LLM task:
    if interrupt.is_set(session_id, CANCEL_REQUEST):
        raise asyncio.CancelledError

  Wake word / recording:
    When barge-in is signalled, the daemon calls:
      interrupt.signal(session_id, BARGE_IN)
    The SPEAKING → LISTENING transition fires automatically.

Thread safety:
  asyncio Events are not thread-safe. All voice pipeline tasks run in
  the same asyncio event loop, so this is safe.
  If audio I/O runs in a thread pool (sounddevice callbacks), signal()
  should be called via loop.call_soon_threadsafe().
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger("markiii.voice.interrupt")


class InterruptType(str, Enum):
    STOP_SPEAKING   = "stop_speaking"
    CANCEL_REQUEST  = "cancel_request"
    BARGE_IN        = "barge_in"
    FULL_RESET      = "full_reset"


_ALL_TYPES = list(InterruptType)


class SessionInterrupts:
    """All interrupt signals for one voice session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._events: dict[InterruptType, asyncio.Event] = {
            t: asyncio.Event() for t in _ALL_TYPES
        }
        # Counts how many times each interrupt has fired (for diagnostics)
        self._counts: dict[InterruptType, int] = {t: 0 for t in _ALL_TYPES}

    def signal(self, interrupt_type: InterruptType) -> None:
        ev = self._events[interrupt_type]
        if not ev.is_set():
            ev.set()
            self._counts[interrupt_type] += 1
            logger.debug(
                "Interrupt  session=%s  type=%s  count=%d",
                self.session_id[:8], interrupt_type.value, self._counts[interrupt_type],
            )

    def clear(self, interrupt_type: InterruptType) -> None:
        self._events[interrupt_type].clear()

    def clear_all(self) -> None:
        for ev in self._events.values():
            ev.clear()

    def is_set(self, interrupt_type: InterruptType) -> bool:
        return self._events[interrupt_type].is_set()

    def get_event(self, interrupt_type: InterruptType) -> asyncio.Event:
        return self._events[interrupt_type]

    def any_set(self) -> bool:
        return any(ev.is_set() for ev in self._events.values())

    def status(self) -> dict:
        return {
            "session_id": self.session_id,
            "signals":    {t.value: self._events[t].is_set() for t in _ALL_TYPES},
            "counts":     {t.value: self._counts[t] for t in _ALL_TYPES},
        }


class InterruptManager:
    """
    Singleton interrupt registry.

    One SessionInterrupts is created per active VoiceSession and destroyed
    when the session ends.

    Usage pattern in pipeline stages:
      # Check without blocking:
      if mgr.is_set(sid, InterruptType.STOP_SPEAKING):
          ...

      # Await with timeout (pipeline step races against interrupt):
      done, pending = await asyncio.wait(
          [asyncio.create_task(do_work()), mgr.wait(sid, InterruptType.CANCEL_REQUEST)],
          return_when=asyncio.FIRST_COMPLETED,
      )
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInterrupts] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.get_event_loop()
        return self._loop

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, session_id: str) -> SessionInterrupts:
        si = SessionInterrupts(session_id)
        self._sessions[session_id] = si
        return si

    def destroy_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def get_session(self, session_id: str) -> Optional[SessionInterrupts]:
        return self._sessions.get(session_id)

    def _require(self, session_id: str) -> SessionInterrupts:
        si = self._sessions.get(session_id)
        if si is None:
            # Auto-create rather than crash — callers shouldn't have to guard
            si = self.create_session(session_id)
        return si

    # ------------------------------------------------------------------
    # Signal / check / clear (convenience wrappers)
    # ------------------------------------------------------------------

    def signal(self, session_id: str, interrupt_type: InterruptType) -> None:
        """Signal an interrupt for this session."""
        self._require(session_id).signal(interrupt_type)

    def signal_threadsafe(self, session_id: str, interrupt_type: InterruptType) -> None:
        """
        Signal from a non-asyncio thread (e.g. sounddevice audio callback).
        Must be called after the event loop is running.
        """
        loop = self._get_loop()
        si   = self._require(session_id)
        loop.call_soon_threadsafe(si.signal, interrupt_type)

    def clear(self, session_id: str, interrupt_type: InterruptType) -> None:
        self._require(session_id).clear(interrupt_type)

    def clear_all(self, session_id: str) -> None:
        self._require(session_id).clear_all()

    def is_set(self, session_id: str, interrupt_type: InterruptType) -> bool:
        return self._require(session_id).is_set(interrupt_type)

    def get_event(self, session_id: str, interrupt_type: InterruptType) -> asyncio.Event:
        """Return the raw asyncio.Event for use with asyncio.wait()."""
        return self._require(session_id).get_event(interrupt_type)

    async def wait(self, session_id: str, interrupt_type: InterruptType) -> None:
        """Await until the interrupt fires (or is already set)."""
        await self._require(session_id).get_event(interrupt_type).wait()

    # ------------------------------------------------------------------
    # Barge-in: composite signal
    # ------------------------------------------------------------------

    def barge_in(self, session_id: str) -> None:
        """
        User spoke while MARK III was speaking.
        Fires BARGE_IN + STOP_SPEAKING + CANCEL_REQUEST.
        The voice session transitions: SPEAKING → LISTENING.
        """
        si = self._require(session_id)
        si.signal(InterruptType.BARGE_IN)
        si.signal(InterruptType.STOP_SPEAKING)
        si.signal(InterruptType.CANCEL_REQUEST)
        logger.info("Barge-in  session=%s", session_id[:8])

    def reset(self, session_id: str) -> None:
        """
        Return session to IDLE: clear all signals.
        Call after the state machine re-enters IDLE.
        """
        si = self._sessions.get(session_id)
        if si:
            si.clear_all()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "active_sessions": len(self._sessions),
            "sessions": {sid: si.status() for sid, si in self._sessions.items()},
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_interrupt: InterruptManager | None = None


def get_interrupt_manager() -> InterruptManager:
    global _interrupt
    if _interrupt is None:
        _interrupt = InterruptManager()
    return _interrupt
