"""
MARK III — Voice Daemon (Phase 11)

Background process that runs on the desktop, maintaining always-listening
or push-to-talk voice sessions for registered desktop devices.

The daemon:
  1. Watches PresenceManager for registered desktop devices
  2. For always-listening mode: runs wake word detection per device
  3. On wake / PTT signal: starts a VoiceSession utterance
  4. Loops until shutdown

Mobile devices:
  Mobile uses the API (/voice/transcribe + /voice/speak) — no daemon needed.
  The daemon only handles devices with local audio hardware (desktop).

Earbud / glasses (future):
  Register via PresenceManager with capability flags.
  The daemon will route audio I/O through the appropriate device.

Concurrency:
  One asyncio task per active desktop device.
  Tasks are cancelled cleanly on shutdown.

Singleton:
  get_voice_daemon() returns the one VoiceDaemon instance.
  start() / stop() are idempotent.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Optional

logger = logging.getLogger("markiii.voice.daemon")


class VoiceDaemon:
    """
    Background always-listening daemon for desktop devices.

    Manages device-level voice tasks. Each device gets its own
    asyncio task that runs the wake word → utterance loop.
    """

    def __init__(self) -> None:
        self._tasks:   dict[str, asyncio.Task] = {}   # device_id → task
        self._sessions: dict[str, object]      = {}   # device_id → VoiceSession
        self._running  = False
        self._db_factory = None

    def set_db_factory(self, factory) -> None:
        """Inject the database session factory (called from lifespan)."""
        self._db_factory = factory

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info("Voice daemon started")

    async def stop(self) -> None:
        self._running = False
        for device_id, task in list(self._tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        for sess in self._sessions.values():
            if hasattr(sess, "stop"):
                sess.stop()
        self._sessions.clear()
        logger.info("Voice daemon stopped")

    # ------------------------------------------------------------------
    # Device-level tasks
    # ------------------------------------------------------------------

    async def activate_device(
        self,
        device_id:       str,
        mode:            str = "push_to_talk",
        conv_session_id: Optional[str] = None,
    ) -> str:
        """
        Start a voice task for a desktop device.
        Returns the voice_session_id.
        """
        from app.services.voice.presence_manager import get_presence_manager
        from app.services.voice.interrupt_manager import get_interrupt_manager
        from app.services.voice.voice_session import VoiceSession
        from app.services.ai.conversation_engine import create_session as create_conv_session
        from app.database import AsyncSessionLocal

        presence  = get_presence_manager()
        interrupt = get_interrupt_manager()

        # Ensure device is registered
        device = presence.get_device(device_id)
        if not device:
            device = presence.register_desktop(device_id)

        # Create or reuse conversation session
        if not conv_session_id:
            async with AsyncSessionLocal() as db:
                conv = await create_conv_session(device_id, "Voice session", db)
                conv_session_id = conv.id

        # Resolve I/O devices via PresenceManager
        input_dev  = presence.preferred_input(device_id)
        output_dev = presence.preferred_output(device_id)

        voice_sid = str(uuid.uuid4())
        interrupt.create_session(voice_sid)

        session = VoiceSession(
            session_id           = voice_sid,
            device_id            = device_id,
            conv_session_id      = conv_session_id,
            mode                 = mode,
            input_device         = input_dev,
            output_device        = output_dev,
            interrupt_mgr        = interrupt,
            db_session_factory   = AsyncSessionLocal if self._db_factory is None else self._db_factory,
        )

        self._sessions[device_id] = session

        # Persist VoiceSession to DB
        await self._persist_session(session)

        if mode == "always_listening":
            task = asyncio.create_task(
                self._always_listening_loop(device_id, session),
                name=f"voice-{device_id[:8]}",
            )
            self._tasks[device_id] = task
        else:
            # push_to_talk: no background task — utterances triggered via API
            logger.info(
                "Push-to-talk mode active  device=%s  voice_session=%s",
                device_id[:16], voice_sid[:8],
            )

        return voice_sid

    async def deactivate_device(self, device_id: str) -> None:
        """Stop the voice task for a device."""
        task = self._tasks.pop(device_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        session = self._sessions.pop(device_id, None)
        if session:
            session.stop()
            await self._close_session(session)

    # ------------------------------------------------------------------
    # Always-listening loop
    # ------------------------------------------------------------------

    async def _always_listening_loop(
        self,
        device_id: str,
        session:   object,
    ) -> None:
        """
        Continuously listen for wake word, then process utterances.
        Runs until the task is cancelled or session.stop() is called.
        """
        from app.services.voice.wake_word import create_detector
        from app.services.voice.interrupt_manager import get_interrupt_manager, InterruptType
        from app.config import settings

        interrupt = get_interrupt_manager()
        detector  = create_detector(
            engine        = settings.wake_word_engine,
            porcupine_key = settings.porcupine_access_key,
            keyword_path  = settings.porcupine_keyword_path or None,
        )

        if not detector.is_available():
            logger.warning(
                "Always-listening mode requested but no wake word engine available. "
                "Switching to push-to-talk."
            )
            session.mode = "push_to_talk"
            return

        mic_idx   = session.input_device.mic_index if session.input_device else None
        stop_ev   = asyncio.Event()

        logger.info(
            "Always-listening started  device=%s  session=%s  engine=%s",
            device_id[:16], session.session_id[:8], detector.name,
        )

        try:
            async for wake_event in detector.stream(
                mic_index             = mic_idx,
                stop_event            = stop_ev,
                confidence_threshold  = 0.5,
            ):
                if not session.is_active:
                    break

                logger.info(
                    "Wake word  keyword=%s  conf=%.2f  device=%s",
                    wake_event.keyword, wake_event.confidence, device_id[:16],
                )

                # Process utterance (recording + STT + LLM + TTS)
                try:
                    result = await session.process_utterance(trigger="wake_word")
                    if result.error:
                        logger.warning("Utterance error: %s", result.error)
                except Exception as e:
                    logger.error("Utterance exception: %s", e)

                # After utterance, clear any stale interrupts
                interrupt.reset(session.session_id)

                # Brief pause before listening for next wake word
                await asyncio.sleep(0.3)

        except asyncio.CancelledError:
            stop_ev.set()
            raise
        except Exception as e:
            logger.error("Always-listening loop crashed: %s", e)

    # ------------------------------------------------------------------
    # API-triggered push-to-talk utterance
    # ------------------------------------------------------------------

    async def trigger_ptt(
        self,
        device_id: str,
        wav_bytes: Optional[bytes] = None,
    ) -> Optional[object]:
        """
        Trigger a PTT utterance for a device.
        Used by the /voice/transcribe API endpoint.

        If wav_bytes is provided: skip recording, go straight to STT.
        If not: signal PTT start and record until ptt_stop() is called.
        """
        session = self._sessions.get(device_id)
        if not session:
            logger.warning("PTT trigger: no active session for device %s", device_id[:16])
            return None

        result = await session.process_utterance(
            trigger   = "push_to_talk",
            wav_bytes = wav_bytes,
        )
        return result

    def ptt_stop(self, device_id: str) -> None:
        """Signal end of PTT recording (button released)."""
        session = self._sessions.get(device_id)
        if session:
            session.ptt_release_event.set()

    # ------------------------------------------------------------------
    # Interrupt passthrough
    # ------------------------------------------------------------------

    def interrupt(self, device_id: str, interrupt_type: str) -> bool:
        """
        Signal an interrupt for the active voice session on this device.
        Returns True if a session was found and interrupted.
        """
        from app.services.voice.interrupt_manager import get_interrupt_manager, InterruptType
        session = self._sessions.get(device_id)
        if not session:
            return False
        try:
            itype = InterruptType(interrupt_type)
        except ValueError:
            return False

        mgr = get_interrupt_manager()
        if interrupt_type == "barge_in":
            mgr.barge_in(session.session_id)
        else:
            mgr.signal(session.session_id, itype)
        return True

    # ------------------------------------------------------------------
    # Device handoff
    # ------------------------------------------------------------------

    async def handoff(
        self,
        device_id:        str,
        input_device_id:  Optional[str] = None,
        output_device_id: Optional[str] = None,
    ) -> dict:
        """
        Re-route an active session to different I/O devices.
        Used for: glasses mic → earbuds speaker handoff.
        """
        from app.services.voice.presence_manager import get_presence_manager

        presence = get_presence_manager()
        session  = self._sessions.get(device_id)

        if not session:
            return {"error": "No active voice session for this device"}

        new_input  = presence.get_device(input_device_id)  if input_device_id  else None
        new_output = presence.get_device(output_device_id) if output_device_id else None

        session.handoff(new_input, new_output)

        if input_device_id and output_device_id:
            presence.set_routing(device_id, input_device_id, output_device_id)

        return {
            "device_id":    device_id,
            "input_device": new_input.name if new_input else session.input_device.name if session.input_device else None,
            "output_device": new_output.name if new_output else session.output_device.name if session.output_device else None,
        }

    # ------------------------------------------------------------------
    # DB persistence
    # ------------------------------------------------------------------

    async def _persist_session(self, session: object) -> None:
        from app.models.db import VoiceSession as VoiceSessionDB
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            row = VoiceSessionDB(
                id              = session.session_id,
                device_id       = session.device_id,
                conversation_id = session.conv_session_id,
                mode            = session.mode,
                stt_engine      = "faster_whisper",
                tts_engine      = "piper",
                mic_name        = session.input_device.name if session.input_device else "",
                speaker_name    = session.output_device.name if session.output_device else "",
                is_active       = True,
                started_at      = session.started_at,
            )
            db.add(row)
            await db.commit()

    async def _close_session(self, session: object) -> None:
        from app.models.db import VoiceSession as VoiceSessionDB
        from app.database import AsyncSessionLocal
        from sqlalchemy import select
        import time

        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(VoiceSessionDB).where(VoiceSessionDB.id == session.session_id)
            )).scalar_one_or_none()
            if row:
                row.is_active        = False
                row.ended_at         = time.time()
                row.utterance_count  = session.utterance_count
                await db.commit()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def status(self) -> dict:
        from app.services.voice.presence_manager import get_presence_manager
        from app.services.voice.audio_manager import audio_status
        from app.services.voice.stt import stt_available
        from app.services.voice.tts import tts_available
        from app.services.voice.wake_word import detector_status

        return {
            "running":         self._running,
            "active_sessions": len(self._sessions),
            "sessions":        [s.to_dict() for s in self._sessions.values()],
            "presence":        get_presence_manager().status(),
            "audio":           audio_status(),
            "stt_available":   stt_available(),
            "tts_available":   tts_available(),
            "wake_word":       detector_status(),
        }

    def get_session(self, device_id: str) -> Optional[object]:
        return self._sessions.get(device_id)

    def is_active_for(self, device_id: str) -> bool:
        """Return True if a voice session is active for this device."""
        return device_id in self._sessions

    async def speak(self, device_id: str, text: str) -> None:
        """
        Synthesise text and play it on the device's output (non-blocking TTS).
        Used by ActionQueue to speak approval prompts.
        Falls back silently if no voice session is available.
        """
        session = self._sessions.get(device_id)
        if not session:
            return
        try:
            from app.services.voice.tts import get_tts_engine
            from app.config import settings
            tts = get_tts_engine(
                settings.tts_engine,
                settings.piper_binary,
                settings.piper_model,
                settings.piper_model_config,
                settings.elevenlabs_api_key,
                settings.elevenlabs_voice_id,
            )
            synth = await tts.synthesize_async(text)
            if synth.wav_bytes and session.output_device:
                from app.services.voice.audio_manager import AudioManager
                am = AudioManager()
                import threading
                stop_ev = threading.Event()
                await am.play_wav_bytes_async(synth.wav_bytes, stop_ev)
        except Exception as exc:
            import logging
            logging.getLogger("markiii.voice.daemon").debug(
                "speak() failed (non-fatal): %s", exc
            )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_daemon: VoiceDaemon | None = None


def get_voice_daemon() -> VoiceDaemon:
    global _daemon
    if _daemon is None:
        _daemon = VoiceDaemon()
    return _daemon
