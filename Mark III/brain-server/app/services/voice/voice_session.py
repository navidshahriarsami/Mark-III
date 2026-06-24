"""
MARK III — Voice Session (Phase 11)

Orchestrates one complete voice interaction session.
Owns the state machine and coordinates the pipeline stages:

  STT (decoupled) → ConversationEngine (unchanged) → TTS (decoupled)

State machine:
  IDLE
    │  wake word fired / PTT pressed
    ▼
  WAKE           ← plays 880Hz beep to signal readiness
    │  immediately
    ▼
  LISTENING      ← audio_manager records until silence / PTT release
    │  recording done
    ▼
  TRANSCRIBING   ← stt.transcribe_bytes_async()
    │  transcript ready
    ▼
  THINKING       ← conversation_engine.generate_response()
    │  response text ready           [CANCEL_REQUEST can abort here]
    ▼
  SPEAKING       ← tts.synthesize_async() → audio_manager.play_wav_bytes_async()
    │  playback complete              [STOP_SPEAKING / BARGE_IN can abort here]
    ▼
  IDLE

Interrupt integration:
  - BARGE_IN:      SPEAKING → LISTENING (user spoke over MARK III)
  - STOP_SPEAKING: cut playback, return to IDLE
  - CANCEL_REQUEST: abort LLM call, return to IDLE or LISTENING
  - FULL_RESET:    any state → IDLE, clear queues

Device routing (via PresenceManager):
  input_device  — where to capture audio (desktop mic, glasses mic)
  output_device — where to play audio (desktop speaker, earbuds)
  These may differ (glasses in, earbuds out = natural wearables setup).

Multi-device support:
  The session does NOT assume local audio is available.
  If no local audio devices, the session operates in API mode:
    - Audio bytes are delivered via /voice/transcribe (mobile upload)
    - Audio output is delivered as bytes via /voice/speak response
  This makes the same session code work for desktop, mobile, and wearables.

Conversation engine decoupling:
  generate_response() is imported from conversation_engine.
  The voice session passes session_id and device_id — the conversation engine
  handles all context, memory, and LLM routing. Voice adds no logic there.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from enum import Enum
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("markiii.voice.session")


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class VoiceState(str, Enum):
    IDLE         = "idle"
    WAKE         = "wake"
    LISTENING    = "listening"
    TRANSCRIBING = "transcribing"
    THINKING     = "thinking"
    SPEAKING     = "speaking"
    INTERRUPTED  = "interrupted"
    ERROR        = "error"


# ---------------------------------------------------------------------------
# Session result types
# ---------------------------------------------------------------------------

class UtteranceResult:
    __slots__ = (
        "utterance_id", "trigger", "user_transcript", "stt_confidence",
        "stt_latency_ms", "response_text", "tts_latency_ms",
        "total_latency_ms", "audio_duration_s", "provider", "model",
        "cost_usd", "error",
    )

    def __init__(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    def to_dict(self) -> dict:
        return {s: getattr(self, s, None) for s in self.__slots__}


# ---------------------------------------------------------------------------
# VoiceSession
# ---------------------------------------------------------------------------

class VoiceSession:
    """
    One running voice session.

    A session persists until explicitly stopped or the device disconnects.
    It can handle many utterances sequentially.

    Args:
        session_id:       UUID for this voice session
        device_id:        MARK III device_id (for conversation context)
        conv_session_id:  ConversationSession.id to append voice turns to
        mode:             push_to_talk | always_listening
        input_device:     VoiceDevice providing audio input (or None = API mode)
        output_device:    VoiceDevice providing audio output (or None = API mode)
        interrupt_mgr:    InterruptManager instance
        db_session_factory: callable returning AsyncSession (for saving utterances)
    """

    def __init__(
        self,
        session_id:           str,
        device_id:            str,
        conv_session_id:      str,
        mode:                 str = "push_to_talk",
        input_device=None,
        output_device=None,
        interrupt_mgr=None,
        db_session_factory=None,
    ) -> None:
        self.session_id       = session_id
        self.device_id        = device_id
        self.conv_session_id  = conv_session_id
        self.mode             = mode
        self.input_device     = input_device
        self.output_device    = output_device
        self._interrupt_mgr   = interrupt_mgr
        self._db_factory      = db_session_factory

        self.state            = VoiceState.IDLE
        self.utterance_count  = 0
        self.started_at       = time.time()
        self.last_utterance   = 0.0
        self._active          = True

        # PTT: set this Event to stop recording (button released)
        self.ptt_release_event = threading.Event()

        # Stop event for always-listening loop
        self._stop_event      = asyncio.Event()

        # Last utterance result (for API polling)
        self.last_result: Optional[UtteranceResult] = None

        logger.info(
            "VoiceSession created  id=%s  device=%s  mode=%s",
            session_id[:8], device_id[:16], mode,
        )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _set_state(self, new_state: VoiceState) -> None:
        old = self.state
        self.state = new_state
        logger.debug("State  %s → %s  session=%s", old.value, new_state.value, self.session_id[:8])

    # ------------------------------------------------------------------
    # Single utterance: full pipeline
    # ------------------------------------------------------------------

    async def process_utterance(
        self,
        trigger:   str = "push_to_talk",   # wake_word | push_to_talk | api
        wav_bytes: Optional[bytes] = None,  # pre-recorded audio (API/mobile mode)
        db:        Optional[AsyncSession] = None,
    ) -> UtteranceResult:
        """
        Process one complete voice turn:
          [WAKE] → LISTENING → TRANSCRIBING → THINKING → SPEAKING → IDLE

        If wav_bytes is provided, skip recording (API/mobile mode).
        Returns UtteranceResult with full metadata.
        """
        from app.services.voice.audio_manager import (
            record_until_silence_async, play_wav_bytes_async, play_tone_async,
            audio_available,
        )
        from app.services.voice.stt import get_stt_engine, wav_bytes_duration
        from app.services.voice.tts import get_tts_engine
        from app.services.voice.interrupt_manager import InterruptType
        from app.services.ai.conversation_engine import generate_response
        from app.config import settings

        t_start = time.monotonic()
        result  = UtteranceResult(
            utterance_id      = 0,
            trigger           = trigger,
            user_transcript   = "",
            stt_confidence    = 0.0,
            stt_latency_ms    = 0.0,
            response_text     = "",
            tts_latency_ms    = 0.0,
            total_latency_ms  = 0.0,
            audio_duration_s  = 0.0,
            provider          = "",
            model             = "",
            cost_usd          = 0.0,
            error             = None,
        )

        # -- WAKE signal --
        if trigger == "wake_word":
            self._set_state(VoiceState.WAKE)
            mic_idx = self.input_device.mic_index if self.input_device else None
            spk_idx = self.output_device.speaker_index if self.output_device else None
            if audio_available():
                await play_tone_async(880.0, 0.15, 0.3, spk_idx)

        # -- LISTENING --
        self._set_state(VoiceState.LISTENING)

        if wav_bytes is None:
            # Record from local mic
            if not audio_available():
                result.error = "No audio hardware available"
                self._set_state(VoiceState.IDLE)
                return result

            mic_idx = self.input_device.mic_index if self.input_device else None

            if self.mode == "push_to_talk":
                # PTT: record until ptt_release_event is set
                from app.services.voice.audio_manager import record_push_to_talk
                recording = await asyncio.to_thread(
                    record_push_to_talk,
                    self.ptt_release_event,
                    mic_idx,
                    settings.voice_sample_rate,
                    settings.voice_max_duration,
                )
            else:
                # Always-listening: record until silence
                recording = await record_until_silence_async(
                    mic_index        = mic_idx,
                    sample_rate      = settings.voice_sample_rate,
                    silence_db       = settings.voice_silence_db,
                    silence_duration = settings.voice_silence_duration,
                    max_duration     = settings.voice_max_duration,
                )

            wav_bytes = recording.audio_bytes
            result.audio_duration_s = recording.duration_s

        else:
            # API mode: wav_bytes provided
            result.audio_duration_s = wav_bytes_duration(wav_bytes)

        if len(wav_bytes) < 1000:
            result.error = "Audio too short"
            self._set_state(VoiceState.IDLE)
            return result

        # -- TRANSCRIBING --
        self._set_state(VoiceState.TRANSCRIBING)

        stt = get_stt_engine(
            model_size   = settings.whisper_model,
            device       = settings.whisper_device,
            compute_type = settings.whisper_compute_type,
        )
        transcript = await stt.transcribe_bytes_async(wav_bytes)

        result.user_transcript = transcript.text
        result.stt_confidence  = transcript.confidence
        result.stt_latency_ms  = transcript.latency_ms

        if transcript.error:
            result.error = f"STT error: {transcript.error}"
            self._set_state(VoiceState.IDLE)
            return result

        if transcript.is_empty:
            result.error = "No speech detected"
            self._set_state(VoiceState.IDLE)
            return result

        logger.info(
            "Transcript  session=%s  text=%r  conf=%.2f",
            self.session_id[:8], transcript.text[:60], transcript.confidence,
        )

        # Check if transcript is a voice approval response ("yes" / "no")
        try:
            from app.services.actions.approval_manager import get_approval_manager
            mgr = get_approval_manager()
            if mgr.pending_for_device(self.device_id):
                if mgr.handle_voice_response(self.device_id, transcript.text):
                    logger.info(
                        "Voice approval response: %r  device=%s",
                        transcript.text[:30], self.device_id[:16],
                    )
        except Exception:
            pass

        # -- THINKING --
        self._set_state(VoiceState.THINKING)

        # Check for cancel interrupt before LLM call
        if self._interrupt_mgr and self._interrupt_mgr.is_set(
            self.session_id, InterruptType.CANCEL_REQUEST
        ):
            self._interrupt_mgr.clear(self.session_id, InterruptType.CANCEL_REQUEST)
            result.error = "Request cancelled"
            self._set_state(VoiceState.IDLE)
            return result

        # Call conversation engine (decoupled — no voice-specific logic there)
        conv_task = asyncio.create_task(
            self._call_conversation(transcript.text, db)
        )

        # Race: LLM call vs CANCEL_REQUEST interrupt
        if self._interrupt_mgr:
            cancel_ev = self._interrupt_mgr.get_event(
                self.session_id, InterruptType.CANCEL_REQUEST
            )
            cancel_task = asyncio.create_task(cancel_ev.wait())
            done, pending = await asyncio.wait(
                [conv_task, cancel_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            if cancel_task in done:
                conv_task.cancel()
                self._interrupt_mgr.clear(self.session_id, InterruptType.CANCEL_REQUEST)
                result.error = "Request cancelled by user"
                self._set_state(VoiceState.IDLE)
                return result

            conv_response = conv_task.result()
        else:
            conv_response = await conv_task

        result.response_text = conv_response.get("text", "")
        result.provider      = conv_response.get("provider", "")
        result.model         = conv_response.get("model", "")
        result.cost_usd      = conv_response.get("cost_usd", 0.0)
        result.utterance_id  = conv_response.get("message_id", 0)

        if not result.response_text:
            result.error = "Empty response from conversation engine"
            self._set_state(VoiceState.IDLE)
            return result

        # -- SPEAKING --
        self._set_state(VoiceState.SPEAKING)

        tts = get_tts_engine(
            engine           = settings.tts_engine,
            piper_binary     = settings.piper_binary,
            piper_model      = settings.piper_model,
            piper_config     = settings.piper_model_config,
            elevenlabs_key   = settings.elevenlabs_api_key,
            elevenlabs_voice = settings.elevenlabs_voice_id,
        )
        synthesis = await tts.synthesize_async(result.response_text)
        result.tts_latency_ms = synthesis.latency_ms

        if synthesis.error:
            logger.warning("TTS failed: %s", synthesis.error)
            # Continue — MARK III will be silent but result text is available
        elif synthesis.wav_bytes:
            spk_idx = self.output_device.speaker_index if self.output_device else None

            # Create a threading.Event linked to our asyncio stop_speaking signal
            stop_ev = threading.Event()

            async def _watch_stop():
                """Set thread stop_ev when asyncio stop_speaking fires."""
                if self._interrupt_mgr:
                    await self._interrupt_mgr.wait(
                        self.session_id, InterruptType.STOP_SPEAKING
                    )
                    stop_ev.set()

            watch_task = asyncio.create_task(_watch_stop())

            await play_wav_bytes_async(synthesis.wav_bytes, spk_idx, stop_ev)

            watch_task.cancel()

            if self._interrupt_mgr and self._interrupt_mgr.is_set(
                self.session_id, InterruptType.STOP_SPEAKING
            ):
                logger.info("Playback stopped by interrupt  session=%s", self.session_id[:8])
                self._interrupt_mgr.clear(self.session_id, InterruptType.STOP_SPEAKING)

                # BARGE_IN: new utterance follows immediately
                if self._interrupt_mgr.is_set(self.session_id, InterruptType.BARGE_IN):
                    self._interrupt_mgr.clear(self.session_id, InterruptType.BARGE_IN)
                    self._set_state(VoiceState.LISTENING)
                    result.total_latency_ms = (time.monotonic() - t_start) * 1000
                    self.utterance_count += 1
                    self.last_utterance   = time.time()
                    self.last_result      = result
                    await self._save_utterance(result, db)
                    return result

        result.total_latency_ms = (time.monotonic() - t_start) * 1000
        self.utterance_count   += 1
        self.last_utterance     = time.time()
        self._set_state(VoiceState.IDLE)
        self.last_result = result

        await self._save_utterance(result, db)

        logger.info(
            "Utterance complete  session=%s  total_latency=%.0fms  words=%d",
            self.session_id[:8], result.total_latency_ms,
            len(result.response_text.split()),
        )
        return result

    async def _call_conversation(
        self,
        text: str,
        db:   Optional[AsyncSession],
    ) -> dict:
        """Call the conversation engine. Pure bridge — no voice logic."""
        from app.services.ai.conversation_engine import generate_response

        if db is None and self._db_factory:
            async with self._db_factory() as _db:
                return await generate_response(
                    session_id   = self.conv_session_id,
                    user_message = text,
                    device_id    = self.device_id,
                    db           = _db,
                )
        elif db is not None:
            return await generate_response(
                session_id   = self.conv_session_id,
                user_message = text,
                device_id    = self.device_id,
                db           = db,
            )
        return {"text": "No database connection available.", "provider": "", "model": "", "cost_usd": 0.0}

    async def _save_utterance(
        self,
        result: UtteranceResult,
        db:     Optional[AsyncSession],
    ) -> None:
        """Persist VoiceUtterance row."""
        if db is None and self._db_factory:
            async with self._db_factory() as _db:
                await self._do_save(result, _db)
        elif db is not None:
            await self._do_save(result, db)

    async def _do_save(self, result: UtteranceResult, db: AsyncSession) -> None:
        from app.models.db import VoiceUtterance
        row = VoiceUtterance(
            voice_session_id     = self.session_id,
            conversation_msg_id  = result.utterance_id or None,
            device_id            = self.device_id,
            trigger              = result.trigger,
            user_transcript      = result.user_transcript,
            stt_confidence       = result.stt_confidence,
            stt_latency_ms       = result.stt_latency_ms,
            response_text        = result.response_text,
            tts_latency_ms       = result.tts_latency_ms,
            total_latency_ms     = result.total_latency_ms,
            audio_duration_s     = result.audio_duration_s,
            ts                   = time.time(),
        )
        db.add(row)
        await db.commit()

    # ------------------------------------------------------------------
    # Device handoff (live re-routing)
    # ------------------------------------------------------------------

    def handoff(self, new_input=None, new_output=None) -> None:
        """
        Re-route to new input/output devices without ending the session.
        Safe to call while IDLE or LISTENING.
        Calling during SPEAKING will take effect after current utterance.
        """
        if new_input is not None:
            old = self.input_device.name if self.input_device else "none"
            self.input_device = new_input
            logger.info(
                "Input handoff  session=%s  %s → %s",
                self.session_id[:8], old, new_input.name,
            )
        if new_output is not None:
            old = self.output_device.name if self.output_device else "none"
            self.output_device = new_output
            logger.info(
                "Output handoff  session=%s  %s → %s",
                self.session_id[:8], old, new_output.name,
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def stop(self) -> None:
        self._active = False
        self._stop_event.set()
        if self._interrupt_mgr:
            from app.services.voice.interrupt_manager import InterruptType
            self._interrupt_mgr.signal(self.session_id, InterruptType.FULL_RESET)
            self._interrupt_mgr.signal(self.session_id, InterruptType.STOP_SPEAKING)
        logger.info("VoiceSession stopped  id=%s", self.session_id[:8])

    @property
    def is_active(self) -> bool:
        return self._active

    def to_dict(self) -> dict:
        return {
            "session_id":      self.session_id,
            "device_id":       self.device_id,
            "conv_session_id": self.conv_session_id,
            "mode":            self.mode,
            "state":           self.state.value,
            "utterance_count": self.utterance_count,
            "last_utterance":  self.last_utterance,
            "is_active":       self._active,
            "input_device":    self.input_device.name if self.input_device else None,
            "output_device":   self.output_device.name if self.output_device else None,
        }
