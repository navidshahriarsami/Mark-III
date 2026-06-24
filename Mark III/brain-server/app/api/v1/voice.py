"""
MARK III — Voice API (Phase 11)

Endpoints:
  POST /voice/start        — activate voice for a device (returns voice_session_id)
  POST /voice/stop         — stop voice session
  GET  /voice/status       — daemon + device + capability status
  POST /voice/transcribe   — upload audio → transcript + MARK III response (mobile PTT)
  POST /voice/speak        — text → WAV audio bytes (TTS only, no LLM call)
  POST /voice/interrupt    — signal stop/cancel/barge-in for active session
  POST /voice/handoff      — re-route I/O devices (glasses mic → earbuds out)
  POST /voice/device       — register a voice device (mobile, earbuds, glasses)

Mobile PTT flow:
  1. User holds voice button on mobile app
  2. Mobile records audio (native MediaRecorder / expo-av)
  3. POST /voice/transcribe {device_id, wav_bytes_b64, session_id?}
  4. Server: STT → conversation engine → TTS → return {transcript, response, audio_b64}
  5. Mobile plays audio_b64 through speaker

Desktop always-listening flow:
  1. POST /voice/start {device_id, mode: "always_listening"}
  2. Daemon runs wake word + utterance loop in background
  3. GET /voice/status to monitor
  4. POST /voice/stop when done

WebSocket (future):
  /voice/stream — real-time bidirectional audio for web and wearables
"""

import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.voice.voice_daemon import get_voice_daemon
from app.services.voice.presence_manager import get_presence_manager

logger = logging.getLogger("markiii.api.voice")
router = APIRouter(prefix="/voice", tags=["voice"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class StartVoiceRequest(BaseModel):
    device_id:       str
    mode:            str = "push_to_talk"   # push_to_talk | always_listening
    conv_session_id: Optional[str] = None   # link to existing conversation
    device_type:     str = "desktop"        # desktop | mobile | earbud | glasses


class StartVoiceResponse(BaseModel):
    voice_session_id: str
    conv_session_id:  str
    mode:             str
    device_type:      str


class StopVoiceRequest(BaseModel):
    device_id: str


class TranscribeRequest(BaseModel):
    device_id:        str
    audio_b64:        str                   # base64-encoded WAV bytes
    voice_session_id: Optional[str] = None  # existing voice session
    conv_session_id:  Optional[str] = None  # existing conversation to continue


class TranscribeResponse(BaseModel):
    transcript:       str
    stt_confidence:   float
    stt_latency_ms:   float
    response_text:    str
    audio_b64:        str                   # base64-encoded WAV of TTS response
    tts_latency_ms:   float
    total_latency_ms: float
    provider:         str
    model:            str
    cost_usd:         float
    error:            Optional[str] = None


class SpeakRequest(BaseModel):
    text:          str
    device_id:     Optional[str] = None     # for I/O routing
    play_locally:  bool = False             # True = play on server speaker, False = return bytes


class SpeakResponse(BaseModel):
    audio_b64:   str                        # base64 WAV
    engine:      str
    duration_s:  float
    latency_ms:  float
    error:       Optional[str] = None


class InterruptRequest(BaseModel):
    device_id:      str
    interrupt_type: str = "stop_speaking"   # stop_speaking | cancel_request | barge_in | full_reset


class HandoffRequest(BaseModel):
    device_id:        str
    input_device_id:  Optional[str] = None  # new mic device
    output_device_id: Optional[str] = None  # new speaker device


class RegisterDeviceRequest(BaseModel):
    device_id:    str
    device_type:  str = "mobile"            # desktop | mobile | earbud | glasses
    name:         str = ""
    capabilities: list[str] = []           # overrides defaults for device_type
    bt_address:   str = ""                  # earbuds
    glasses_platform: str = ""             # meta_ray_ban | xreal
    mic_index:    Optional[int] = None
    speaker_index: Optional[int] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/start", response_model=StartVoiceResponse)
async def start_voice(
    body: StartVoiceRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Activate voice for a device.

    For desktop: starts the background daemon loop (always-listening) or
                 prepares a push-to-talk session.
    For mobile:  registers the device and returns session IDs for use with
                 /voice/transcribe.
    """
    daemon   = get_voice_daemon()
    presence = get_presence_manager()

    # Auto-register device if not already known
    dev = presence.get_device(body.device_id)
    if not dev:
        _auto_register(body.device_id, body.device_type, presence)

    # Create conversation session if not provided
    conv_session_id = body.conv_session_id
    if not conv_session_id:
        from app.services.ai.conversation_engine import create_session
        conv = await create_session(body.device_id, "Voice session", db)
        conv_session_id = conv.id

    try:
        voice_sid = await daemon.activate_device(
            device_id       = body.device_id,
            mode            = body.mode,
            conv_session_id = conv_session_id,
        )
    except Exception as e:
        logger.error("activate_device error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "voice_session_id": voice_sid,
        "conv_session_id":  conv_session_id,
        "mode":             body.mode,
        "device_type":      body.device_type,
    }


@router.post("/stop")
async def stop_voice(body: StopVoiceRequest):
    """Stop the active voice session for a device."""
    daemon = get_voice_daemon()
    await daemon.deactivate_device(body.device_id)
    return {"status": "stopped", "device_id": body.device_id}


@router.get("/status")
async def voice_status():
    """
    Full voice daemon status including:
    - Active sessions and their states
    - Presence registry (all known devices)
    - Hardware availability (mic, speaker, STT, TTS, wake word)
    - Interrupt state per session
    """
    from app.services.voice.interrupt_manager import get_interrupt_manager
    daemon    = get_voice_daemon()
    interrupt = get_interrupt_manager()

    status = daemon.status()
    status["interrupts"] = interrupt.status()
    return status


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    body: TranscribeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Mobile / API push-to-talk endpoint.

    Upload base64-encoded WAV audio.
    Returns: transcript + MARK III response text + TTS audio (base64 WAV).

    This is the complete voice round-trip for mobile devices:
      App records audio → encodes to base64 → POST here
      Server: STT → conversation engine → TTS → returns everything

    The TTS audio can be played directly by the mobile app.
    """
    daemon = get_voice_daemon()

    # Decode audio
    try:
        wav_bytes = base64.b64decode(body.audio_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 audio data")

    if len(wav_bytes) < 100:
        raise HTTPException(status_code=400, detail="Audio too short")

    # Ensure conversation session exists
    conv_session_id = body.conv_session_id
    if not conv_session_id:
        from app.services.ai.conversation_engine import create_session
        conv = await create_session(body.device_id, "Mobile voice session", db)
        conv_session_id = conv.id

    # Activate or reuse session
    voice_sid = body.voice_session_id
    session   = daemon.get_session(body.device_id)

    if not session:
        # Create a one-off PTT session for this request
        from app.services.voice.voice_session import VoiceSession
        from app.services.voice.interrupt_manager import get_interrupt_manager
        from app.services.voice.presence_manager import get_presence_manager
        from app.database import AsyncSessionLocal
        import uuid

        presence  = get_presence_manager()
        interrupt = get_interrupt_manager()

        dev = presence.get_device(body.device_id)
        if not dev:
            dev = presence.register_mobile(body.device_id)

        voice_sid = voice_sid or str(uuid.uuid4())
        interrupt.create_session(voice_sid)

        session = VoiceSession(
            session_id         = voice_sid,
            device_id          = body.device_id,
            conv_session_id    = conv_session_id,
            mode               = "push_to_talk",
            input_device       = None,   # API mode — no local mic
            output_device      = None,   # API mode — return bytes instead
            interrupt_mgr      = interrupt,
            db_session_factory = AsyncSessionLocal,
        )

    # Process utterance (API mode: wav_bytes provided, no recording)
    try:
        result = await session.process_utterance(
            trigger   = "push_to_talk",
            wav_bytes = wav_bytes,
            db        = db,
        )
    except Exception as e:
        logger.error("transcribe error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    # Synthesize response audio
    audio_b64     = ""
    tts_latency   = 0.0
    if result.response_text and not result.error:
        from app.services.voice.tts import get_tts_engine
        from app.config import settings
        tts = get_tts_engine(
            engine           = settings.tts_engine,
            piper_binary     = settings.piper_binary,
            piper_model      = settings.piper_model,
            elevenlabs_key   = settings.elevenlabs_api_key,
            elevenlabs_voice = settings.elevenlabs_voice_id,
        )
        synthesis = await tts.synthesize_async(result.response_text)
        tts_latency = synthesis.latency_ms
        if synthesis.wav_bytes:
            audio_b64 = base64.b64encode(synthesis.wav_bytes).decode("utf-8")

    return {
        "transcript":       result.user_transcript,
        "stt_confidence":   result.stt_confidence,
        "stt_latency_ms":   result.stt_latency_ms,
        "response_text":    result.response_text,
        "audio_b64":        audio_b64,
        "tts_latency_ms":   tts_latency,
        "total_latency_ms": result.total_latency_ms,
        "provider":         result.provider,
        "model":            result.model,
        "cost_usd":         result.cost_usd,
        "error":            result.error,
    }


@router.post("/speak", response_model=SpeakResponse)
async def speak(body: SpeakRequest):
    """
    Text → Audio synthesis only.
    No LLM call — converts text directly to WAV bytes.

    Use cases:
    - MARK III notifications via earbuds
    - Pre-caching a TTS response
    - Testing TTS engine configuration
    """
    from app.services.voice.tts import get_tts_engine
    from app.config import settings

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text cannot be empty")

    tts = get_tts_engine(
        engine           = settings.tts_engine,
        piper_binary     = settings.piper_binary,
        piper_model      = settings.piper_model,
        elevenlabs_key   = settings.elevenlabs_api_key,
        elevenlabs_voice = settings.elevenlabs_voice_id,
    )

    synthesis = await tts.synthesize_async(body.text.strip())

    audio_b64 = ""
    if synthesis.wav_bytes:
        audio_b64 = base64.b64encode(synthesis.wav_bytes).decode("utf-8")

        # Optional: play locally on server speaker
        if body.play_locally and synthesis.wav_bytes:
            from app.services.voice.audio_manager import play_wav_bytes_async, audio_available
            from app.services.voice.presence_manager import get_presence_manager
            if audio_available():
                presence   = get_presence_manager()
                dev        = presence.get_device(body.device_id) if body.device_id else None
                spk_index  = dev.speaker_index if dev and dev.speaker_index is not None else None
                await play_wav_bytes_async(synthesis.wav_bytes, spk_index)

    return {
        "audio_b64":  audio_b64,
        "engine":     synthesis.engine,
        "duration_s": synthesis.duration_s,
        "latency_ms": synthesis.latency_ms,
        "error":      synthesis.error,
    }


@router.post("/interrupt")
async def interrupt_voice(body: InterruptRequest):
    """
    Signal an interrupt to the active voice session.

    interrupt_type:
      stop_speaking   — cut TTS playback immediately
      cancel_request  — abort in-flight LLM call
      barge_in        — new speech detected (stop speaking + start listening)
      full_reset      — return to IDLE state

    Returns 404 if no active session found for the device.
    """
    daemon = get_voice_daemon()
    ok = daemon.interrupt(body.device_id, body.interrupt_type)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"No active voice session for device {body.device_id[:16]}",
        )
    return {"status": "interrupted", "type": body.interrupt_type}


@router.post("/handoff")
async def handoff_devices(body: HandoffRequest):
    """
    Re-route an active session to different I/O devices without ending it.

    Example: switch from desktop mic to glasses mic while keeping
    the conversation session and earbud audio output.

    Applies immediately; takes effect on the next utterance.
    """
    daemon = get_voice_daemon()
    result = await daemon.handoff(
        device_id        = body.device_id,
        input_device_id  = body.input_device_id,
        output_device_id = body.output_device_id,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/device")
async def register_device(body: RegisterDeviceRequest):
    """
    Register a voice-capable device with the PresenceManager.

    Call this when:
    - A mobile app connects
    - Earbuds pair
    - Smart glasses connect
    - Any device wants to participate in voice I/O

    After registration, the device can be used as input/output in
    /voice/start and /voice/handoff.
    """
    presence = get_presence_manager()

    if body.device_type == "desktop":
        dev = presence.register_desktop(
            body.device_id,
            name          = body.name or "Desktop",
            mic_index     = body.mic_index,
            speaker_index = body.speaker_index,
        )
    elif body.device_type == "mobile":
        dev = presence.register_mobile(body.device_id, name=body.name or "Mobile")
    elif body.device_type == "earbud":
        dev = presence.register_earbud(
            body.device_id,
            name       = body.name or "Earbuds",
            bt_address = body.bt_address,
        )
    elif body.device_type == "glasses":
        dev = presence.register_glasses(
            body.device_id,
            name     = body.name or "Smart Glasses",
            platform = body.glasses_platform or "meta_ray_ban",
        )
    else:
        dev = presence.register_desktop(body.device_id, name=body.name or "Unknown")

    # Apply capability overrides if provided
    if body.capabilities:
        dev.capabilities = set(body.capabilities)

    return dev.to_dict()


@router.get("/devices")
async def list_devices():
    """List all alive voice devices in the PresenceManager."""
    presence = get_presence_manager()
    return {
        "devices": [d.to_dict() for d in presence.list_alive()],
        **presence.status(),
    }


@router.get("/capabilities")
async def get_capabilities():
    """
    Report what voice capabilities are available on this server.
    Use this from the mobile app to decide which UI elements to show.
    """
    from app.services.voice.audio_manager import audio_status, list_microphones, list_speakers
    from app.services.voice.stt import stt_available
    from app.services.voice.tts import tts_available
    from app.services.voice.wake_word import detector_status

    return {
        "audio":          audio_status(),
        "microphones":    [m.to_dict() for m in list_microphones()],
        "speakers":       [s.to_dict() for s in list_speakers()],
        "stt_available":  stt_available(),
        "tts_available":  tts_available(),
        "wake_word":      detector_status(),
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _auto_register(device_id: str, device_type: str, presence) -> None:
    """Register a device with defaults if not already present."""
    if device_type == "mobile":
        presence.register_mobile(device_id)
    elif device_type == "earbud":
        presence.register_earbud(device_id)
    elif device_type == "glasses":
        presence.register_glasses(device_id)
    else:
        presence.register_desktop(device_id)
