from __future__ import annotations

# Limit OpenBLAS threads before numpy/CTranslate2 loads.
import os as _os
_os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
_os.environ.setdefault("OMP_NUM_THREADS",      "1")
_os.environ.setdefault("MKL_NUM_THREADS",      "1")
_os.environ.setdefault("NUMEXPR_NUM_THREADS",  "1")

"""
MARK III — Always-Listening Loop  (Phase 14)

Full state machine:

  IDLE      → energy spike → WakeEngine detects "MARK" → WOKEN
  WOKEN     → TTS "Listening." → LISTENING
  LISTENING → utterance complete → THINKING
  THINKING  → STT + Council → SPEAKING
  SPEAKING  → TTS done → FOLLOWUP
  SPEAKING  → barge-in → LISTENING (no "MARK" required)
  FOLLOWUP  → 5 s window, user speaks → THINKING (no "MARK" required)
  FOLLOWUP  → timeout / stop command → IDLE

Special states:
  SLEEPING  — wake word paused (privacy mode)
  MUTED     — wake word active but TTS suppressed (text only)

Thread layout:
  mic_thread      — sounddevice InputStream → raw audio queue
  dispatch_thread — routes chunks by state
  worker_thread   — STT → Council → TTS
  council_thread  — asyncio event loop for council coroutines
"""

import asyncio
import io
import logging
import os
import queue
import tempfile
import threading
import time
import wave
from enum import Enum
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("markiii.loop")

# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

MIC_INDEX         = 1       # Microphone (K66)
SPEAKER_INDEX     = 4       # Speakers (Realtek)
SAMPLE_RATE       = 16000
CHUNK_SAMPLES     = 480     # 30 ms per chunk at 16 kHz
BARGE_IN_DB       = -20.0   # dBFS to trigger barge-in; was -32 (too sensitive — picked up speaker bleed at -24 to -30 dBFS)
BARGE_IN_PERSIST  = 5       # consecutive chunks above threshold (5 × 30 ms = 150 ms sustained audio)
BARGE_IN_DELAY_S  = 1.0     # seconds after TTS starts before barge-in is armed (was 0.3 — not long enough)
SAPI_VOICE_IDX    = 2       # 0=David 1=Hazel 2=Zira

# Phase 15B — Dynamic Listening (ConversationBuffer settings)
CONV_SPEECH_DB     = -35.0  # dBFS threshold (raised from -38; filters fan/keyboard noise)
CONV_ONSET_CHUNKS  =  10    # consecutive 30ms chunks above threshold to confirm speech (300ms)
CONV_SILENCE_S     =  2.0   # sustained silence before processing (halved from 4.0)
CONV_FOLLOWUP_S    =  5.0   # continuation window when utterance is incomplete
CONV_MAX_S         = 20.0   # hard ceiling on a single utterance (was 15)
FOLLOWUP_SILENCE_S =  2.0   # shorter silence timeout in follow-up mode
FOLLOWUP_ONSET_C   =  5     # 5×30ms = 150ms onset for short follow-up replies

# Phase 14 — Follow-up mode
FOLLOWUP_WINDOW_S =  5.0    # post-response listen window (no wake word required)

# Phase 16 — Conversation handoff patterns
import re as _re
_HANDOFF_RE = _re.compile(
    r"\b(continue|switch|send|move|forward|take)\s+(this|it|conversation|that|response)?\s*"
    r"(to|on|onto)?\s*(my\s+)?"
    r"(?P<target>mac(book)?|phone|iphone|watch|desktop|laptop)\b",
    _re.I,
)

# Phase 15B — WAIT_FOR_SPEECH safety timeout
# If no speech onset is confirmed within this window, silently return to IDLE.
# Prevents hanging when wake fires on fan noise / accidental sounds.
WAIT_FOR_SPEECH_TIMEOUT_S = 8.0

# STT confidence filtering (Phase 15B)
# -0.80 was too tight — valid quiet speech sits between -0.85 and -1.0.
_STT_MIN_LOGPROB   = -1.0   # reject only very-low-confidence segments (Whisper hallucinations)
_STT_MAX_NO_SPEECH =  0.80  # reject segments Whisper is 80%+ sure are silence

# Stop commands — abort active speech or follow-up without calling council
_STOP_CMDS: frozenset[str] = frozenset(
    {"stop", "cancel", "quiet", "silence", "enough", "bye"}
)


# ─────────────────────────────────────────────────────────────────
# State machine
# ─────────────────────────────────────────────────────────────────

class ServiceState(str, Enum):
    IDLE           = "idle"
    SLEEPING       = "sleeping"
    MUTED          = "muted"
    WOKEN          = "woken"
    WAIT_FOR_SPEECH = "wait_for_speech"  # Phase 15B: waiting for speech onset (300ms confirm)
    LISTENING      = "listening"
    THINKING       = "thinking"
    SPEAKING       = "speaking"
    FOLLOWUP       = "followup"          # Phase 14: post-response listen window
    STOPPING       = "stopping"


_STATE_COLORS = {
    ServiceState.IDLE:            "#2ECC71",   # green
    ServiceState.SLEEPING:        "#F39C12",   # yellow
    ServiceState.MUTED:           "#F39C12",   # yellow
    ServiceState.WOKEN:           "#3498DB",   # blue
    ServiceState.WAIT_FOR_SPEECH: "#3498DB",   # blue (same as listening)
    ServiceState.LISTENING:       "#3498DB",   # blue
    ServiceState.THINKING:        "#3498DB",   # blue
    ServiceState.SPEAKING:        "#E67E22",   # orange
    ServiceState.FOLLOWUP:        "#9B59B6",   # purple
    ServiceState.STOPPING:        "#E67E22",   # orange
}

_STATE_LABELS = {
    ServiceState.IDLE:            "Listening",
    ServiceState.SLEEPING:        "Sleeping",
    ServiceState.MUTED:           "Muted",
    ServiceState.WOKEN:           "Woken",
    ServiceState.WAIT_FOR_SPEECH: "Waiting for speech …",
    ServiceState.LISTENING:       "Listening to you …",
    ServiceState.THINKING:        "Thinking …",
    ServiceState.SPEAKING:        "Speaking",
    ServiceState.FOLLOWUP:        "Follow-up …",
    ServiceState.STOPPING:        "Stopping",
}


# ─────────────────────────────────────────────────────────────────
# Worker event sentinels
# ─────────────────────────────────────────────────────────────────

class _WakeCmd:
    def __init__(self, event):
        self.event = event   # WakeEvent from wake_engine

class _SpeakStatus: pass
class _Shutdown:    pass


# ─────────────────────────────────────────────────────────────────
# Beep — short tonal feedback (sd.play; not affected by WASAPI bug)
# ─────────────────────────────────────────────────────────────────

def _beep(freq: float = 880.0, dur: float = 0.1, vol: float = 0.2) -> None:
    import sounddevice as sd
    sr  = 22050
    t   = np.linspace(0, dur, int(sr * dur), endpoint=False)
    env = np.minimum(1.0, np.minimum(t / 0.01, (dur - t) / 0.01))
    sig = (np.sin(2 * np.pi * freq * t) * vol * env).astype(np.float32)
    sd.play(sig, samplerate=sr, device=SPEAKER_INDEX, blocking=False)


# ─────────────────────────────────────────────────────────────────
# Utterance recorder
# ─────────────────────────────────────────────────────────────────

def record_utterance(
    chunk_q:           queue.Queue,
    stop_ev:           threading.Event,
    max_s:             float    = CONV_MAX_S,
    timeout_s:         float    = 0.0,
    wait_timeout_s:    float    = 0.0,
    followup:          bool     = False,
    on_speech_start:   callable = None,
) -> bytes:
    """
    Consume mic chunks from chunk_q via ConversationBuffer VAD.

    Parameters
    ----------
    max_s           : hard ceiling on recording after onset
    timeout_s       : wall-clock deadline for the ENTIRE call (used by follow-up
                      mode — give up after N seconds whether or not speech started)
    wait_timeout_s  : deadline for the PRE-SPEECH WAITING phase only.
                      If onset is not confirmed within this window, return b"".
                      Once speech starts, recording runs until silence or max_s.
                      Use this for primary utterance to prevent infinite hangs on
                      accidental wake detections.
    on_speech_start : callback fired the moment onset is confirmed (300ms sustained)
    """
    from app.services.voice.conversation_buffer import ConversationBuffer, ConvState

    buf = ConversationBuffer(
        sample_rate       = SAMPLE_RATE,
        speech_db         = CONV_SPEECH_DB,
        onset_chunks      = FOLLOWUP_ONSET_C if followup else CONV_ONSET_CHUNKS,
        silence_timeout_s = FOLLOWUP_SILENCE_S if followup else CONV_SILENCE_S,
        max_duration_s    = max_s,
        on_speech_start   = on_speech_start,
    )

    now              = time.monotonic()
    wait_deadline    = now + wait_timeout_s if wait_timeout_s > 0 else float("inf")
    end_deadline     = now + timeout_s      if timeout_s      > 0 else float("inf")

    while not stop_ev.is_set():
        t = time.monotonic()
        # Pre-speech wait timeout (only active while WAITING for onset)
        if buf.state == ConvState.WAITING and t >= wait_deadline:
            break
        # Total call timeout (used by follow-up window)
        if t >= end_deadline:
            break
        try:
            pcm16: np.ndarray = chunk_q.get(timeout=0.1)
        except queue.Empty:
            continue
        if buf.feed(pcm16):
            break

    if buf.state == ConvState.WAITING:
        return b""

    return buf.get_wav()


# ─────────────────────────────────────────────────────────────────
# STT — Whisper base (CPU, int8); loaded once in background thread
# ─────────────────────────────────────────────────────────────────

_stt_model  = None
_stt_lock   = threading.Lock()
_stt_loaded = threading.Event()


def _load_stt() -> None:
    global _stt_model
    from faster_whisper import WhisperModel
    log.info("Loading Whisper base for utterance transcription ...")
    t0 = time.monotonic()
    with _stt_lock:
        _stt_model = WhisperModel("base", device="cpu", compute_type="int8")
    log.info("Whisper base loaded in %.1fs", time.monotonic() - t0)
    _stt_loaded.set()


def transcribe(wav_bytes: bytes) -> str:
    """
    Transcribe utterance WAV bytes using Whisper.
    Phase 15B: filters segments by confidence (avg_logprob + no_speech_prob).
    """
    if not wav_bytes:
        return ""
    _stt_loaded.wait(timeout=120)
    if not _stt_model:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        tmp = f.name
    try:
        with _stt_lock:
            # Phase 18: detect language automatically (no language="en" lock)
            segments, info = _stt_model.transcribe(
                tmp, vad_filter=True, beam_size=3,
            )
            parts = []
            for s in segments:
                if s.no_speech_prob > _STT_MAX_NO_SPEECH:
                    log.debug("STT: reject no_speech=%.2f %r", s.no_speech_prob, s.text[:40])
                    continue
                if s.avg_logprob < _STT_MIN_LOGPROB:
                    log.debug("STT: reject logprob=%.2f %r", s.avg_logprob, s.text[:40])
                    continue
                parts.append(s.text.strip())
            text = " ".join(parts).strip()

            # Update language service with detected language
            try:
                from app.services.integrations.language_service import from_whisper
                lang = from_whisper(info.language, getattr(info, "language_probability", 1.0))
                if lang.code != "en":
                    log.info("STT: detected language=%s (%.0f%%)", lang.name, lang.confidence * 100)
            except Exception:
                pass

            return text
    except Exception as e:
        log.error("STT: %s", e)
        return ""
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────
# Voice mode — which device is the active voice interface.
#
#   "desktop"  — K66 listens, Piper speaks  (default)
#   device_id  — that device listens+speaks, desktop is silent processor
#
# The desktop NEVER speaks in remote mode. It only processes /mesh/voice
# requests and returns text. The remote device handles all TTS.
# ─────────────────────────────────────────────────────────────────

_active_voice_device: str = "desktop"   # "desktop" or a mesh device_id
_voice_mode_lock = threading.Lock()


def get_active_voice_device() -> str:
    return _active_voice_device


def set_active_voice_device(device_id: str) -> None:
    global _active_voice_device
    with _voice_mode_lock:
        _active_voice_device = device_id
    log.info("Voice mode → %s", device_id)


def is_desktop_active() -> bool:
    return _active_voice_device == "desktop"


# Legacy relay lock — kept for compatibility, now delegates to voice mode
_mesh_relay_active = threading.Event()


def set_mesh_relay_active(active: bool) -> None:
    if active:
        _mesh_relay_active.set()
    else:
        _mesh_relay_active.clear()


# ─── Shift command parser ─────────────────────────────────────────────────────

import re as _shift_re

_SHIFT_RE = _shift_re.compile(
    r"\b(shift|move|switch|transfer|continue|use|using|go)\b.{0,15}"
    r"\b(?P<target>mac(book)?|desktop|windows|pc|laptop|iphone|phone|watch)\b"
    r"|\bim?\s+(using|on)\s+(my\s+)?(?P<target2>mac(book)?|desktop|pc|iphone|phone)\b"
    r"|\bmark\s+im?\s+(using|on)\s+(my\s+)?(?P<target3>mac(book)?|desktop|pc)\b"
    r"|\b(?P<target4>mac(book)?|desktop|pc)\s+(mark|please)\b",
    _shift_re.I,
)

_TARGET_MAP = {
    "mac": "macbook", "macbook": "macbook", "laptop": "macbook",
    "desktop": "desktop", "windows": "desktop", "pc": "desktop",
    "iphone": "iphone", "phone": "iphone",
    "watch": "watch",
}


def parse_shift_target(text: str) -> Optional[str]:
    """
    Return the device type to shift to ("macbook", "desktop", "iphone", …),
    or None if the text is not a shift command.
    """
    m = _SHIFT_RE.search(text)
    if not m:
        return None
    raw = (
        m.group("target") or m.group("target2") or
        m.group("target3") or m.group("target4") or ""
    ).lower()
    return _TARGET_MAP.get(raw)


# ─────────────────────────────────────────────────────────────────
# Council
# ─────────────────────────────────────────────────────────────────

_council_loop:     Optional[asyncio.AbstractEventLoop] = None
_startup_complete: threading.Event = threading.Event()   # set when all modules are ready


def _start_council_loop() -> None:
    global _council_loop
    _council_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_council_loop)

    # Startup: warm Qwen + weather, then signal ready for greeting
    async def _startup_checks():
        try:
            from app.services.ai.local_qwen_provider import health_check as _qwen_health
            ok = await _qwen_health()
            log.info(
                "Qwen local: %s",
                "available — local conversation active" if ok
                else "unavailable — OpenRouter fallback active",
            )
        except Exception as e:
            log.debug("Qwen startup check skipped: %s", e)
        try:
            from app.services.reflex.reflex_router import warm_weather_cache
            warm_weather_cache()
            log.info("Reflex: weather cache warming in background")
            await asyncio.sleep(2.0)
        except Exception as e:
            log.debug("Weather cache warm skipped: %s", e)

        # Initialize Obsidian knowledge base (non-blocking)
        try:
            import threading as _t
            def _init_kb():
                from app.services.knowledge.knowledge_manager import initialize_knowledge_base
                initialize_knowledge_base()
            _t.Thread(target=_init_kb, daemon=True, name="kb-init").start()
            log.info("Knowledge base initialization started in background")
        except Exception as e:
            log.debug("Knowledge base init skipped: %s", e)

        # Initialize identity system
        try:
            from app.services.identity.identity_manager    import get_identity_manager
            from app.services.identity.learning_engine     import start_learning_scheduler
            from app.services.identity.identity_diagnostics import log_identity_status
            get_identity_manager()   # loads/creates profile
            start_learning_scheduler(interval_hours=4.0)
            log_identity_status()
        except Exception as e:
            log.debug("Identity init skipped: %s", e)

        _startup_complete.set()
        log.info("Startup complete — greeting queued")

    _council_loop.call_soon(lambda: _council_loop.create_task(_startup_checks()))
    _council_loop.run_forever()


def _try_approval_response(text: str, device_id: str) -> bool:
    """
    If a pending action approval exists for this device, attempt to resolve
    it from this utterance's yes/no content.

    Must run BEFORE social reflex — reflex_router already matches bare
    "yes"/"no" as a conversational acknowledgment, which would otherwise
    swallow the utterance before an approval ever sees it.

    Returns True if this utterance was consumed as an approval response
    (caller should stop processing this turn as a normal query).
    """
    try:
        from app.services.actions.approval_manager import get_approval_manager
        mgr = get_approval_manager()
        if not mgr.pending_for_device(device_id):
            return False
        return mgr.handle_voice_response(device_id, text)
    except Exception as e:
        log.debug("Approval response check error: %s", e)
        return False


def _execute_action_and_speak(request) -> Optional[str]:
    """
    Submit an ActionRequest to the Universal Action System and build a spoken
    response from the resulting state.

    Returns None on any failure so the caller falls back to the normal
    reflex/Integration Manager/Qwen pipeline (safe degrade — never silently
    swallow a query just because the action system hiccuped).
    """
    try:
        from app.services.actions import action_loop as _action_loop
        from app.services.actions.base_action import ActionState
        from app.services.actions.approval_manager import get_approval_manager

        action = _action_loop.submit_action_sync(request, timeout=10.0)

        if action.state == ActionState.AWAITING_APPROVAL.value:
            approval = get_approval_manager().get(action.approval_id) if action.approval_id else None
            return approval.prompt if approval else "This action needs your approval. Allow?"

        if action.state == ActionState.COMPLETED.value:
            out = (action.result.output if action.result else None) or "Done."
            return str(out)[:160]

        if action.state == ActionState.FAILED.value:
            return f"Couldn't do that — {action.error_message or 'unknown error'}"[:160]

        if action.state == ActionState.DEFERRED.value:
            return "Queued for your next work session."

        return "Still working on it."
    except Exception as e:
        log.debug("Action execution error: %s", e)
        return None


def query_council(text: str) -> str:
    """
    Phase 18+ — Retrieval-first cognitive pipeline.

    Priority:
      1. Social Reflex         (<1ms)
      2. Integration Manager   (<10ms)
      3. Intent Classification (<2ms)
      4. Context Builder       (memory + context assembly)
      5. Direct Recall         (high-confidence memory bypasses LLM)
      6. Qwen 7B               (conversation/reasoning)
      7. Council               (complex/multi-step)
    """
    # ── 0. Structured Memory — authoritative facts bypass LLM ──────────
    try:
        from app.services.memory.recall_engine      import recall as _recall, is_fact_query as _is_fq
        from app.services.memory.recall_diagnostics import diag as _rdiag, RecallEvent as _RE
        import time as _t
        if _is_fq(text):
            _t0 = _t.monotonic()
            _rf = _recall(text)
            _ms = (_t.monotonic() - _t0) * 1000
            _rdiag.record(_RE(query=text[:80], source=_rf.source,
                              found=_rf.found, latency_ms=_ms, confidence=_rf.confidence))
            if _rf.found:
                log.info("Fact recall (%s) %.0fms — LLM bypassed", _rf.source, _ms)
                return _rf.answer
    except Exception as _re:
        log.debug("Recall engine error: %s", _re)

    # ── 0b. Universal Action System — "open X", "delete Y", "run Z" ─────
    try:
        from app.services.actions.action_router import classify_intent as _classify_action
        from app.services.actions import action_loop as _action_loop
        if _action_loop.is_running():
            _device_id = get_active_voice_device()
            _req = _classify_action(text, device_id=_device_id, source="voice")
            if _req is not None:
                _spoken = _execute_action_and_speak(_req)
                if _spoken is not None:
                    return _spoken
    except Exception as _ae:
        log.debug("Action router error: %s", _ae)

    # ── 1. Integration Manager — live factual data ──────────────────────
    try:
        from app.services.integrations.integration_manager import route as _integ_route
        from app.services.integrations.language_service    import get_current as _get_lang
        lang   = _get_lang()
        result = _integ_route(text, lang.code)
        if result.handled:
            log.info("Integration(%s) %.0fms", result.source, result.latency_ms)
            return result.text
    except Exception as e:
        log.debug("Integration manager error: %s", e)

    # ── 2. Intent Classification ────────────────────────────────────────
    intent_result = None
    try:
        from app.services.cognition.intent_classifier import classify
        intent_result = classify(text)
        log.info("Intent: %s (%.0f%%)", intent_result.intent.value, intent_result.confidence * 100)
    except Exception as e:
        log.debug("Intent classifier error: %s", e)

    # ── 3. Context Builder — assemble memory + context package ──────────
    ctx_string   = ""
    direct_reply = None
    try:
        from app.services.cognition.context_builder import build_context
        from app.services.cognition.intent_classifier import IntentResult, Intent
        if intent_result is None:
            from app.services.cognition.intent_classifier import classify
            intent_result = classify(text)
        pkg = build_context(text, intent_result)
        ctx_string = pkg.to_prompt_string()
        # Direct answer from memory (high-confidence recall bypasses LLM)
        if pkg.direct_answer and pkg.direct_score >= 0.75:
            log.info("Direct recall (%.2f): %s", pkg.direct_score, pkg.direct_answer[:60])
            return pkg.direct_answer
    except Exception as e:
        log.debug("Context builder error: %s", e)

    if not _council_loop:
        return "Council offline."
    try:
        from app.services.council.council_manager  import get_council
        from app.services.voice.personality_engine import build_context_hint

        # Activity tracking + habit detection
        try:
            from app.services.identity.activity_tracker  import get_activity_tracker
            from app.services.identity.preference_manager import update_language_preference
            from app.services.identity.habit_detector    import get_habit_detector
            from app.services.integrations.language_service import get_current as _gl
            _lang = _gl()
            if _lang.code != "en":
                update_language_preference(_lang.code)
            if intent_result:
                _intent_str = intent_result.intent.value
                get_activity_tracker().record_query(text, _intent_str, get_active_voice_device())
                # Observe habits from query patterns
                get_habit_detector().observe_query_type(_intent_str)
                get_habit_detector().observe_late_work()
        except Exception:
            pass

        # Vector memory recall — synchronous, runs before async council loop
        _memory_context = ""
        try:
            from app.services.memory.vector_store import get_memory_store
            _mems = get_memory_store().recall(text, top_k=3, min_score=0.45)
            if _mems:
                _memory_context = "MARK MEMORY:\n" + "\n".join(f"- {m.content}" for m in _mems)
                log.debug("Memory recall: %d relevant memories injected", len(_mems))
        except Exception as _me:
            log.debug("Memory recall skipped: %s", _me)

        context = build_context_hint(text)
        # Append assembled context package (memory + datetime + device)
        if ctx_string:
            context = (ctx_string + "\n\n" + context).strip()
        elif _memory_context:
            context = (_memory_context + "\n\n" + context).strip()

        async def _consult() -> str:
            session = await get_council().consult(
                query        = text,
                context_hint = context,
                device_id    = "mark-service",
            )
            return session.final_answer

        future = asyncio.run_coroutine_threadsafe(_consult(), _council_loop)
        return future.result(timeout=180)
    except Exception as e:
        log.error("Council: %s", e)
        return "Reasoning system unreachable."


# ─────────────────────────────────────────────────────────────────
# Main always-listening loop
# ─────────────────────────────────────────────────────────────────

class AlwaysListeningLoop:
    """
    Orchestrates all voice pipeline threads.
    Call start() to launch, stop() to clean up.
    """

    def __init__(
        self,
        on_state_change:  Callable[[ServiceState], None] = None,
        wake_sensitivity: float = 0.7,
    ) -> None:
        self._on_state_change  = on_state_change or (lambda s: None)
        self._wake_sensitivity = wake_sensitivity

        self._state      = ServiceState.IDLE
        self._state_lock = threading.Lock()
        self._running    = False

        self._raw_q:  queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._work_q: queue.Queue             = queue.Queue(maxsize=2)
        self._utt_q:  queue.Queue[np.ndarray] = queue.Queue(maxsize=500)

        self._interrupt: threading.Event = threading.Event()
        self._stop_ev:   threading.Event = threading.Event()

        self._barge_in_enabled = False
        self._barge_in_count   = 0

        self._wake_engine: Optional[object] = None
        self._tts:         Optional[object] = None   # XTTSProvider

        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def state(self) -> ServiceState:
        return self._state

    def _set_state(self, new: ServiceState) -> None:
        with self._state_lock:
            if self._state == new:
                return
            old = self._state
            self._state = new
        log.info("State: %s → %s", old.value, new.value)
        self._on_state_change(new)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_ev.clear()
        self._interrupt.clear()

        from app.services.voice.wake_engine   import WakeEngine
        from app.services.voice.xtts_provider import XTTSProvider

        self._wake_engine = WakeEngine(sensitivity=self._wake_sensitivity)
        self._tts         = XTTSProvider()

        threading.Thread(target=_load_stt, daemon=True, name="stt-model-load").start()

        # Phase 15E.5: start presence engine
        try:
            from app.services.presence.rf.rf_presence_engine import start_presence_engine
            start_presence_engine()
            log.info("PresenceEngine started")
        except Exception as e:
            log.warning("PresenceEngine start failed: %s", e)

        ct = threading.Thread(target=_start_council_loop, daemon=True, name="council-loop")
        ct.start()
        self._threads.append(ct)

        wt = threading.Thread(target=self._worker_loop, daemon=True, name="worker")
        wt.start()
        self._threads.append(wt)

        dt = threading.Thread(target=self._dispatch_loop, daemon=True, name="dispatch")
        dt.start()
        self._threads.append(dt)

        mt = threading.Thread(target=self._mic_loop, daemon=True, name="mic")
        mt.start()
        self._threads.append(mt)

        log.info("AlwaysListeningLoop started")
        self._set_state(ServiceState.IDLE)

    def stop(self) -> None:
        self._running = False
        self._stop_ev.set()
        self._interrupt.set()
        if self._tts:
            self._tts.stop()
        for q in (self._raw_q, self._work_q, self._utt_q):
            while not q.empty():
                try: q.get_nowait()
                except: pass
        if _council_loop:
            _council_loop.call_soon_threadsafe(_council_loop.stop)
        log.info("AlwaysListeningLoop stopped")

    def restart(self) -> None:
        self.stop()
        time.sleep(1.0)
        self._stop_ev.clear()
        self._interrupt.clear()
        self._threads.clear()
        self.start()

    # ------------------------------------------------------------------
    # Privacy controls
    # ------------------------------------------------------------------

    def sleep(self) -> None:
        self._set_state(ServiceState.SLEEPING)

    def wake_up(self) -> None:
        self._set_state(ServiceState.WAIT_FOR_SPEECH)

    def toggle_mute(self) -> bool:
        if self._state == ServiceState.MUTED:
            self._set_state(ServiceState.IDLE)
            return False
        self._set_state(ServiceState.MUTED)
        return True

    def is_sleeping(self) -> bool:
        return self._state == ServiceState.SLEEPING

    def is_muted(self) -> bool:
        return self._state == ServiceState.MUTED

    # ------------------------------------------------------------------
    # Mic loop
    # ------------------------------------------------------------------

    def _mic_loop(self) -> None:
        import sounddevice as sd

        def callback(indata, frames, time_info, status):
            if status:
                log.debug("Mic status: %s", status)
            mono  = indata[:, 0]
            pcm16 = (mono * 32767).astype(np.int16)
            try:
                self._raw_q.put_nowait(pcm16)
            except queue.Full:
                pass

        try:
            with sd.InputStream(
                samplerate = SAMPLE_RATE,
                channels   = 1,
                dtype      = "float32",
                blocksize  = CHUNK_SAMPLES,
                device     = MIC_INDEX,
                callback   = callback,
            ):
                log.info("Mic stream open (K66 idx=%d)", MIC_INDEX)
                self._stop_ev.wait()
        except Exception as e:
            log.error("Mic loop crashed: %s", e)
            self._set_state(ServiceState.IDLE)

    # ------------------------------------------------------------------
    # Dispatch loop — routes chunks by current state
    # ------------------------------------------------------------------

    def _dispatch_loop(self) -> None:
        while self._running:
            try:
                pcm16: np.ndarray = self._raw_q.get(timeout=0.5)
            except queue.Empty:
                continue

            state = self._state

            # SLEEPING — only wake engine runs (listens for "Mark" to resume)
            if state == ServiceState.SLEEPING:
                if self._wake_engine and self._wake_engine.is_loaded:
                    self._wake_engine.feed(pcm16, callback=self._handle_wake)
                continue

            # SPEAKING — no barge-in; MARK always finishes its sentence
            if state in (ServiceState.SPEAKING, ServiceState.STOPPING):
                continue

            # All other states: feed utterance recorder + wake engine for tray commands
            try:
                self._utt_q.put_nowait(pcm16)
            except queue.Full:
                pass
            if state in (ServiceState.IDLE, ServiceState.MUTED):
                if self._wake_engine and self._wake_engine.is_loaded:
                    self._wake_engine.feed(pcm16, callback=self._handle_wake)

    def _check_barge_in(self, pcm16: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(pcm16.astype(np.float64) ** 2)))
        db  = 20.0 * np.log10(rms / 32768.0 + 1e-9)
        if db > BARGE_IN_DB:
            self._barge_in_count += 1
            if self._barge_in_count >= BARGE_IN_PERSIST:
                log.info("Barge-in detected (db=%.1f)", db)
                self._interrupt.set()
                self._barge_in_count = 0
        else:
            self._barge_in_count = 0

    def _handle_wake(self, event) -> None:
        cmd = event.command
        if cmd == "stop":
            self._interrupt.set()
            return
        if cmd == "sleep":
            self.sleep()
            self._say_quick("Going quiet.")
            return
        if cmd == "wake":
            self.wake_up()
            self._say_quick("Back online.")
            return
        if cmd == "mute":
            muted = self.toggle_mute()
            self._say_quick("Audio off." if muted else "Audio on.")
            return
        if cmd == "status":
            try:
                self._work_q.put_nowait(_SpeakStatus())
            except queue.Full:
                pass
            return
        if cmd == "restart":
            self._say_quick("Cycling.")
            threading.Thread(target=self.restart, daemon=True).start()
            return

        # "Mark" during SLEEPING → beep and resume always-on listening
        if self._state == ServiceState.SLEEPING:
            _beep(880, 0.12)
            self.wake_up()
            return

        # In always-on mode we don't need WakeCmd — worker loop self-drives.
        # Keep the post for backward-compat with IDLE/MUTED tray states.
        if self._state not in (ServiceState.IDLE, ServiceState.MUTED):
            return
        try:
            self._work_q.put_nowait(_WakeCmd(event))
        except queue.Full:
            pass

    def _say_quick(self, text: str) -> None:
        """Speak a short prompt without blocking dispatch or entering SPEAKING state."""
        if self.is_muted():
            log.info("(muted) say_quick: %r", text)
            return
        def _do():
            try:
                self._tts.speak(text, threading.Event())
            except Exception as e:
                log.error("say_quick: %s", e)
        threading.Thread(target=_do, daemon=True).start()

    # ------------------------------------------------------------------
    # Startup greeting
    # ------------------------------------------------------------------

    def _handle_voice_shift(self, target_type: str) -> None:
        """
        Switch voice mode to a different device or back to desktop.

        Desktop mode  → K66 listens, Piper speaks.
        Remote mode   → Desktop silent processor; remote device listens + speaks.
        """
        from app.services.mesh.mesh_manager import get_mesh_manager
        from app.services.ai.local_qwen_provider import add_to_history

        mgr = get_mesh_manager()

        # ── Shift to desktop ──────────────────────────────────────────────
        if target_type == "desktop":
            if is_desktop_active():
                self._tts.speak("Already on desktop.", threading.Event())
                return
            set_active_voice_device("desktop")
            self._say_quick("Switching back to desktop. I'm listening here now.")
            self._set_state(ServiceState.WAIT_FOR_SPEECH)
            return

        # ── Shift to a remote device ──────────────────────────────────────
        # Find the device in the mesh
        candidates = [
            d for d in mgr.get_online_devices()
            if target_type in d.type.lower() or target_type in d.name.lower()
        ]

        # Future: if multiple candidates, ask which one
        if not candidates:
            self._tts.speak(
                f"No {target_type} is online in the mesh right now.", threading.Event()
            )
            return

        # For now: pick the first (only one per type expected in Phase 16)
        # Future Phase: prompt "Which one?" when multiple
        target_dev = candidates[0]

        # Transfer conversation history to target device
        from app.services.mesh.mesh_manager import get_mesh_manager as _mgr
        ok = _mgr().handoff_conversation(target_dev.device_id)

        set_active_voice_device(target_dev.device_id)

        # Signal the target device to exit standby and resume mic
        try:
            import requests as _req
            _req.post(
                f"http://{target_dev.ip}:8766/mark/relay",
                json={"action": "start"}, timeout=3,
            )
            log.info("Sent relay:start to %s @ %s", target_dev.name, target_dev.ip)
        except Exception as e:
            log.debug("relay:start signal failed: %s", e)

        ack = f"Switching to {target_dev.name}. Desktop going quiet."
        log.info("Voice mode shift → %s (id=%s)", target_dev.name, target_dev.device_id)

        if not self.is_muted():
            _beep(660, 0.07)
            self._tts.speak(ack, threading.Event())

        # Desktop stays awake — continues processing but won't speak via Piper
        # until shifted back. _desktop_speaks check in the cycle handles output.
        self._set_state(ServiceState.WAIT_FOR_SPEECH)

    @staticmethod
    def _build_recommendations(
        wd: dict | None,
        cpu_pct: int,
        gpu_temp: int | None,
        gpu_load: int,
        hour: int,
    ) -> list[str]:
        """
        Generate contextual recommendations from live system + weather data.
        Each condition bucket has multiple phrasings — pick one by day-of-week
        so the greeting varies across the week without being random.
        """
        import datetime
        recs: list[str] = []
        v = datetime.datetime.now().weekday()   # 0=Mon … 6=Sun

        # ── Weather ───────────────────────────────────────────────────
        if wd:
            uv    = max(wd.get("uv_now") or 0, wd.get("uv_max") or 0)
            precip = wd.get("daily_precip") or 0
            temp   = wd.get("temp", 20)
            wind   = wd.get("wind") or 0

            if uv >= 11:
                recs.append([
                    "UV is extreme today — if you're heading out, cover up completely and minimise time in the sun.",
                    "Extreme UV on the forecast. Sunscreen, hat, glasses — non-negotiable if you're going outside.",
                ][v % 2])
            elif uv >= 8:
                recs.append([
                    "UV is very high today — sun protection is essential before you step outside.",
                    "You'll want SPF and sunglasses today — UV is hitting the very high range.",
                    "High UV alert — the sun will be aggressive. Sunscreen before you leave.",
                ][v % 3])
            elif uv >= 6:
                recs.append([
                    "UV is high today — don't skip the sunscreen.",
                    "You'll need sunscreen today — UV index is elevated.",
                ][v % 2])
            # UV ≤ 5 (moderate/low) — already covered by the UV briefing line, no extra rec needed

            if precip >= 5:
                recs.append([
                    f"About {precip:.0f} millimetres of rain expected — umbrella is a must.",
                    f"It's going to be wet out there — {precip:.0f} mm of rain forecast. Take an umbrella.",
                ][v % 2])
            elif precip >= 1:
                recs.append([
                    "Light rain expected today — an umbrella wouldn't go amiss.",
                    "There's a chance of rain — maybe toss an umbrella in the bag.",
                ][v % 2])

            if temp >= 38:
                recs.append([
                    "It's scorching outside — stay hydrated and limit time in direct sun.",
                    "Extreme heat today — water bottle, shade, and slow down out there.",
                ][v % 2])
            elif temp >= 33:
                recs.append([
                    "Hot one today — push the water intake and don't overdo it outdoors.",
                    "It's going to be a sweaty day — hydrate early and often.",
                ][v % 2])
            elif temp <= 2:
                recs.append([
                    "Near freezing outside — layer up properly before heading out.",
                    "It's biting cold — coat, gloves, the works.",
                ][v % 2])
            elif temp <= 8:
                recs.append([
                    "Cold out there — a jacket is non-negotiable today.",
                    "Wrap up — it's quite cold outside.",
                ][v % 2])

            if wind >= 60:
                recs.append("Strong winds today — secure anything loose outside and drive carefully.")
            elif wind >= 40:
                recs.append("It's gusty out there — hold onto your hat.")

        # ── GPU temperature ───────────────────────────────────────────
        if gpu_temp is not None:
            if gpu_temp >= 88:
                recs.append([
                    f"GPU is running hot at {gpu_temp} degrees — give the PC a rest or check the airflow.",
                    f"The GPU temp is high at {gpu_temp} degrees. Shut down heavy workloads and let it breathe.",
                    f"GPU heat alarm — {gpu_temp} degrees is too warm for idle. Check the fans.",
                ][v % 3])
            elif gpu_temp >= 78:
                recs.append([
                    f"GPU is warm at {gpu_temp} degrees — keep an eye on ventilation.",
                    f"GPU temp is elevated — {gpu_temp} degrees. Make sure the vents aren't blocked.",
                ][v % 2])

        # ── GPU load ──────────────────────────────────────────────────
        if gpu_load >= 85:
            recs.append([
                "GPU is under heavy load right now — close anything graphics-intensive you're not using.",
                "GPU is working hard — worth closing unused applications before we start.",
            ][v % 2])

        # ── CPU load ──────────────────────────────────────────────────
        if cpu_pct >= 80:
            recs.append([
                f"CPU is running at {cpu_pct} percent — consider closing background apps before we dive in.",
                f"Heavy CPU load at {cpu_pct} percent. A quick cleanup of background processes would help.",
            ][v % 2])
        elif cpu_pct >= 60:
            recs.append(f"CPU is moderately busy at {cpu_pct} percent — worth checking what's running in the background.")

        # ── Time of day ───────────────────────────────────────────────
        if 1 <= hour < 4:
            recs.append([
                "It's very late — or very early, depending on your perspective. The work will still be there after some sleep.",
                "You're well into the night. Your brain runs better rested — just saying.",
            ][v % 2])
        elif hour == 4 or hour == 5:
            recs.append([
                "You're up before the sun — bold move. Let's make it count.",
                "Early start today — the quiet hours are productive. Let's use them.",
            ][v % 2])

        # Max 2 recommendations — avoid information overload in a greeting
        return recs[:2]

    def _speak_startup_greeting(self) -> None:
        """
        Speak a context-aware boot briefing once all modules are ready.
        Tone: calm, professional OS status report — not a flat data dump.
        """
        import datetime
        import re as _re

        now  = datetime.datetime.now()
        hour = now.hour

        # ── Time greeting ─────────────────────────────────────────────
        if   5 <= hour < 12:  salutation = "Good morning"
        elif 12 <= hour < 17: salutation = "Good afternoon"
        elif 17 <= hour < 21: salutation = "Good evening"
        else:                  salutation = "Good night"

        # ── Gather data (all fields initialized to safe defaults) ────────
        wd       = None
        pct      = 0
        gpu_load = 0
        gpu_temp = None
        weather_line = ""
        uv_line      = ""
        cpu_line     = ""
        gpu_line     = ""

        try:
            from app.services.reflex.weather_module import _get_weather_data, _uv_label
            wd = _get_weather_data()
            if wd:
                cond  = wd["condition"]
                temp  = wd["temp"]
                city  = wd["city"]
                hum   = wd["humidity"]
                wind  = wd.get("wind") or 0
                weather_line = (
                    f"Outside in {city} it's {cond.lower()}, "
                    f"{temp:.0f} degrees with {hum:.0f} percent humidity"
                )
                if wind > 20:
                    weather_line += f" and {wind:.0f} kilometre winds"
                weather_line += "."
                uv_now = wd.get("uv_now") or 0
                uv_max = wd.get("uv_max") or 0
                if uv_now > 0.5:
                    uv_line = _uv_label(uv_now) + "."
                elif uv_max > 2:
                    uv_line = f"Today's peak UV will reach {uv_max:.0f} — {_uv_label(uv_max).split('— ')[-1]}."
        except Exception:
            pass

        try:
            from app.services.reflex.system_module import _get_cpu, _get_gpu
            cpu_raw = _get_cpu()
            m = _re.search(r"(\d+) percent", cpu_raw)
            if m:
                pct   = int(m.group(1))
                state = "idle" if pct < 15 else "light" if pct < 40 else "moderate" if pct < 70 else "heavy"
                cpu_line = f"CPU is {state} at {pct} percent."

            gpu_raw = _get_gpu()
            lm = _re.search(r"(\d+)% load", gpu_raw)
            tm = _re.search(r"(\d+)[°C]C core", gpu_raw) or _re.search(r"(\d+).C core", gpu_raw)
            if lm:
                gpu_load = int(lm.group(1))
                g_state  = "quiet" if gpu_load < 15 else "active" if gpu_load < 60 else "under load"
                gtemp    = f"running at {tm.group(1)} degrees" if tm else ""
                gpu_line = f"GPU is {g_state}{', ' + gtemp if gtemp else ''}."
                if tm:
                    gpu_temp = int(tm.group(1))
        except Exception:
            pass

        # ── Assemble ──────────────────────────────────────────────────
        sentences = [f"{salutation}."]
        if weather_line:  sentences.append(weather_line)
        if uv_line:       sentences.append(uv_line)

        system_bits = [b for b in [cpu_line, gpu_line] if b]
        if system_bits:
            sentences.append("Systems check:  " + "  ".join(system_bits))

        # ── Recommendations ───────────────────────────────────────────
        for rec in self._build_recommendations(wd, pct, gpu_temp, gpu_load, hour):
            sentences.append(rec)

        sentences.append("All modules online.  I'm fully powered and at your service.")

        message = "  ".join(sentences)
        log.info("Startup greeting: %s", message)

        # Set WAIT_FOR_SPEECH before speaking so the dispatch loop stops feeding
        # the wake engine — prevents false wake detections from the TTS audio.
        self._set_state(ServiceState.WAIT_FOR_SPEECH)
        if not self.is_muted():
            self._tts.speak(message, threading.Event())

    # ------------------------------------------------------------------
    # Worker loop — always-on continuous listener
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        # Wait for all startup checks: Qwen warmup + weather cache (max 15s)
        _startup_complete.wait(timeout=15.0)
        log.info("Always-listening mode active — no wake word required")

        # Startup greeting: time of day + weather + system status
        self._speak_startup_greeting()

        while self._running:
            # Drain special commands (status, shutdown, tray actions)
            try:
                event = self._work_q.get_nowait()
                if isinstance(event, _Shutdown):
                    return
                if isinstance(event, _SpeakStatus):
                    self._do_status()
            except queue.Empty:
                pass

            # Pause if sleeping (privacy mode)
            if self._state == ServiceState.SLEEPING:
                time.sleep(0.2)
                continue

            # Don't start a new cycle if still processing the previous one
            if self._state in (ServiceState.THINKING, ServiceState.SPEAKING):
                time.sleep(0.05)
                continue

            # Run one full listen → respond cycle
            self._do_always_on_cycle()

    def _do_status(self) -> None:
        state = self._state
        msg   = f"Systems nominal. Current state: {_STATE_LABELS.get(state, state.value)}."
        self._speak(msg)

    # ------------------------------------------------------------------
    # Always-on conversation cycle  (Phase 16)
    # ------------------------------------------------------------------

    def _do_always_on_cycle(self) -> None:
        """
        Single always-on turn: listen → transcribe → answer → back to listening.

        No wake word. MARK finishes every response fully before re-listening.
        Only "stop", "wait", "sleep" and similar commands interrupt or pause.
        4-second silence ends the listening window and triggers processing.
        """
        from app.services.voice.conversation_buffer import SentenceValidator
        from app.services.voice.voice_diagnostics   import diag, VoiceSession

        validator = SentenceValidator()
        ds        = VoiceSession(tts_backend=getattr(self._tts, "backend", "sapi"))
        t_start   = time.monotonic()

        # ── 1. Wait for speech (indefinitely — always on) ─────────────────
        t_listen     = time.monotonic()
        t_speech_ref = [t_listen]

        def _on_speech():
            t_speech_ref[0] = time.monotonic()
            if self._state == ServiceState.WAIT_FOR_SPEECH:
                self._set_state(ServiceState.LISTENING)

        self._set_state(ServiceState.WAIT_FOR_SPEECH)
        wav_bytes = record_utterance(
            self._utt_q, self._stop_ev,
            on_speech_start = _on_speech,
            # No wait_timeout_s — always listening, never times out
        )
        ds.speech_detect_ms      = (t_speech_ref[0] - t_listen) * 1000
        ds.listening_duration_ms = (time.monotonic() - t_listen) * 1000

        if not wav_bytes or self._stop_ev.is_set():
            self._set_state(ServiceState.WAIT_FOR_SPEECH)
            return

        # ── 2. Transcribe ─────────────────────────────────────────────────
        self._set_state(ServiceState.THINKING)
        t_stt = time.monotonic()
        text  = transcribe(wav_bytes)
        ds.stt_latency_ms  = (time.monotonic() - t_stt) * 1000
        ds.utterance_chars = len(text)
        log.info("Utterance: %r", text[:80])

        # Update presence engine — microphone activity confirmed
        try:
            from app.services.presence.rf.rf_presence_engine import get_presence_engine
            get_presence_engine().record_microphone()
        except Exception:
            pass

        # Phase 16 revised: desktop always processes (for shift commands + context)
        # but only SPEAKS via Piper when it is the active voice device.
        # State is owned by the brain — no syncing needed with Mac.
        _desktop_speaks = is_desktop_active()

        # ── 3. Control commands ────────────────────────────────────────────
        clean = text.strip().lower().rstrip(".!?,; ")

        # Pause / stop → sleep until user says "Mark"
        _PAUSE_WORDS = {
            "stop", "pause", "quiet", "silence", "sleep",
            "stop listening", "pause listening", "go to sleep",
            "goodnight", "good night", "go quiet", "shut up",
        }
        if clean in _PAUSE_WORDS:
            log.info("Pause command: %r → sleeping (say 'Mark' to resume)", text)
            from app.services.ai.local_qwen_provider import clear_history, _history
            # Summarize session before clearing
            try:
                from app.services.identity.session_summarizer import summarize_session_async
                from app.services.identity.activity_tracker   import get_activity_tracker
                summarize_session_async(list(_history))
                get_activity_tracker().record_session_end()
            except Exception:
                pass
            clear_history()
            self._set_state(ServiceState.SLEEPING)
            self._say_quick("Paused.")
            return

        # Wait / hold — skip this turn but keep listening
        if clean in {"wait", "hold on", "one sec", "one moment", "cancel"}:
            log.info("Wait command: %r — re-listening", text)
            self._set_state(ServiceState.WAIT_FOR_SPEECH)
            return

        # ── 3d. Pending action approval — must run before social reflex ──
        if _try_approval_response(text, get_active_voice_device()):
            log.info("Approval resolved via voice: %r", text[:40])
            if _desktop_speaks:
                self._say_quick("Confirmed.")
            self._set_state(ServiceState.WAIT_FOR_SPEECH)
            return

        # ── 4a. Social reflex (hello, thanks, yes/no, wake word) ─────────
        from app.services.voice.reflex_router import match as _social_match
        _reflex = _social_match(text)

        # ── 4b. System reflex (time, weather, cpu, apps, media, …) ───────
        if not _reflex:
            from app.services.reflex.reflex_router import route as _sys_route
            _sys = _sys_route(text)
            if _sys.handled:
                log.info("Reflex(%s) %.0fms", _sys.source, _sys.latency_ms)
                _reflex = _sys.text

        if not _reflex:
            # ── 4b. Noise ──────────────────────────────────────────────────
            if validator.is_noise(text):
                log.info("Noise — discarding: %r", text)
                self._set_state(ServiceState.WAIT_FOR_SPEECH)
                return

            # ── 4c. Incomplete → continuation window ───────────────────────
            if validator.is_incomplete(text):
                log.info("Incomplete (%r) — opening continuation window", text[:60])
                _beep(700, 0.05)
                self._set_state(ServiceState.LISTENING)
                cont_wav  = record_utterance(self._utt_q, self._stop_ev, max_s=CONV_FOLLOWUP_S)
                cont_text = transcribe(cont_wav) if cont_wav else ""
                if cont_text and not validator.is_noise(cont_text):
                    text = text.rstrip(".!?,") + " " + cont_text
                    log.info("Combined: %r", text[:120])
                self._set_state(ServiceState.THINKING)

        print(f"  YOU  : {text}", flush=True)

        # ── 5. Answer ─────────────────────────────────────────────────────
        if _reflex:
            log.info("Reflex: %r → %r", text, _reflex)
            ds.reflex_used        = True
            ds.council_latency_ms = 0.0
            answer                = _reflex
            # Add reflex data to Qwen history so follow-up questions have context.
            # "GPU is 50°C" → next turn "is that normal?" → Qwen knows the reading.
            try:
                from app.services.ai.local_qwen_provider import add_to_history
                add_to_history(text, answer)
            except Exception:
                pass
        else:
            # If the council takes more than 2s (OpenRouter / slow query),
            # say a holding message so the user knows MARK is working.
            # Reflex and Qwen local (~1s) return before the threshold fires.
            _answered = threading.Event()

            def _wait_announce():
                if not _answered.wait(timeout=2.0) and not self.is_muted():
                    self._say_quick("Give me a second, boss.")

            threading.Thread(target=_wait_announce, daemon=True).start()

            t_council             = time.monotonic()
            answer                = query_council(text)
            _answered.set()                                     # cancel if already done
            ds.council_latency_ms = (time.monotonic() - t_council) * 1000

        ds.answer_chars = len(answer)
        print(f"  MARK : {answer}{' [reflex]' if ds.reflex_used else ''}", flush=True)

        # ── 5a. Shift voice mode ("use Mac", "I'm using desktop", etc.) ─────
        shift_target = parse_shift_target(text)
        if shift_target:
            self._handle_voice_shift(shift_target)
            return

        # ── 5b. Conversation handoff — "send to Mac / phone / watch" ──────
        handoff_m = _HANDOFF_RE.search(text)
        if handoff_m:
            target_kw = handoff_m.group("target").lower()
            try:
                from app.services.mesh.mesh_manager import get_mesh_manager
                mgr = get_mesh_manager()
                target_dev = next(
                    (d for d in mgr.get_all_devices()
                     if target_kw in d.type.lower() or target_kw in d.name.lower()),
                    None,
                )
                if target_dev and target_dev.state != "offline":
                    # Full handoff: transfer conversation history + speak on target
                    ok = mgr.handoff_conversation(target_dev.device_id, answer)
                    if not ok:
                        mgr.push_to_device(target_dev.device_id, answer)
                    ack = f"Continuing on {target_dev.name}. Desktop going quiet."
                    log.info("Handoff → %s — desktop entering sleep mode", target_dev.name)
                    if not self.is_muted():
                        _beep(660, 0.07)
                        self._tts.speak(ack, threading.Event())
                    # Desktop sleeps — Mac handles voice until user says "continue on desktop"
                    self._set_state(ServiceState.SLEEPING)
                    return
                else:
                    answer = f"No {target_kw} online in the mesh right now."
            except Exception as e:
                log.debug("Handoff failed: %s", e)

        # ── 6. Speak — ONLY when desktop is the active voice device ──────────
        # If Mac is active, desktop processed the query (for history/context)
        # but Piper stays silent. Mac's Samantha will speak via /mesh/voice.
        self._set_state(ServiceState.SPEAKING)
        self._interrupt.clear()

        t_tts = time.monotonic()
        if not self.is_muted() and _desktop_speaks:
            _beep(660, 0.07)
            self._tts.speak(answer, self._interrupt)
        elif not _desktop_speaks:
            log.debug("Desktop processed but not speaking — %s is active voice device",
                      get_active_voice_device())
        ds.tts_latency_ms = (time.monotonic() - t_tts) * 1000

        # ── 7. Diagnostics ────────────────────────────────────────────────
        ds.total_ms = (time.monotonic() - t_start) * 1000
        diag.record(ds)
        log.info(
            "Turn: detect=%.1fs  stt=%.1fs  llm=%.1fs  tts=%.1fs  total=%.1fs  [%s]",
            ds.speech_detect_ms     / 1000,
            ds.stt_latency_ms       / 1000,
            ds.council_latency_ms   / 1000,
            ds.tts_latency_ms       / 1000,
            ds.total_ms             / 1000,
            "reflex" if ds.reflex_used else (
                "conv" if ds.council_latency_ms < 3500 else "executive"
            ),
        )

        # ── 8. Immediately back to listening — no IDLE, no wake word ──────
        self._interrupt.clear()
        self._set_state(ServiceState.WAIT_FOR_SPEECH)

    # ------------------------------------------------------------------
    # Full conversation turn  (Phase 14)
    # ------------------------------------------------------------------

    def _do_conversation(self, wake_event) -> None:
        """
        WOKEN → LISTENING → THINKING → SPEAKING → FOLLOWUP → IDLE

        Includes:
          - Sentence validation + incomplete utterance continuation window
          - Barge-in re-listen with stop-command detection
          - 5 s follow-up mode — user says "Why?" without "MARK"
          - Per-turn latency diagnostics written to voice_diagnostics.json
        """
        from app.services.voice.conversation_buffer import SentenceValidator
        from app.services.voice.voice_diagnostics   import diag, VoiceSession

        validator = SentenceValidator()
        ds        = VoiceSession(tts_backend=getattr(self._tts, "backend", "sapi"))
        t_start   = time.monotonic()
        ds.wake_latency_ms = (t_start - wake_event.detected_at) * 1000

        self._interrupt.clear()
        self._set_state(ServiceState.WOKEN)

        # ── 1. Acknowledge — beep only (no speech: ChatGPT-style, saves 1-2s)
        if not self.is_muted():
            _beep(880, 0.12)

        # ── 2. Wait for speech onset → then record ────────────────────
        t_listen     = time.monotonic()
        t_speech_ref = [t_listen]   # mutable ref: updated by onset callback

        def _on_speech():
            t_speech_ref[0] = time.monotonic()
            if self._state == ServiceState.WAIT_FOR_SPEECH:
                self._set_state(ServiceState.LISTENING)

        self._set_state(ServiceState.WAIT_FOR_SPEECH)
        wav_bytes = record_utterance(
            self._utt_q, self._stop_ev,
            wait_timeout_s  = WAIT_FOR_SPEECH_TIMEOUT_S,
            on_speech_start = _on_speech,
        )
        now = time.monotonic()
        ds.speech_detect_ms      = (t_speech_ref[0] - t_listen) * 1000
        ds.listening_duration_ms = (now - t_listen) * 1000

        if self._interrupt.is_set():
            self._interrupt.clear()
            self._set_state(ServiceState.IDLE)
            return

        # No speech onset detected within the wait window — silently return to IDLE.
        if not wav_bytes:
            log.info("No speech detected within %.0fs — returning to IDLE", WAIT_FOR_SPEECH_TIMEOUT_S)
            self._set_state(ServiceState.IDLE)
            return

        # ── 3. STT ────────────────────────────────────────────────────
        self._set_state(ServiceState.THINKING)
        t_stt = time.monotonic()
        text  = transcribe(wav_bytes)
        ds.stt_latency_ms  = (time.monotonic() - t_stt) * 1000
        ds.utterance_chars = len(text)
        log.info("Utterance: %r", text[:80])

        # ── 2a. Pending action approval — must run before social reflex ──
        if _try_approval_response(text, get_active_voice_device()):
            log.info("Approval resolved via voice: %r", text[:40])
            self._say_quick("Confirmed.")
            self._set_state(ServiceState.IDLE)
            return

        # ── 3a. Reflex check (BEFORE noise filter) ────────────────────
        # Reflex handles short valid phrases ("Hello?", "Thanks", "Yes")
        # that MIN_WORDS=2 would otherwise reject as noise.
        from app.services.voice.reflex_router import match as _reflex_match
        _reflex = _reflex_match(text)

        if not _reflex:
            # ── 3b. Noise filter ──────────────────────────────────────
            if validator.is_noise(text):
                log.info("Noise — discarding: %r", text)
                self._speak("Signal unclear. Say that again.")
                self._set_state(ServiceState.IDLE)
                return

            # ── 3c. Incomplete → sentence continuation window ─────────
            if validator.is_incomplete(text):
                log.info("Incomplete (%r) — opening continuation window", text[:60])
                _beep(700, 0.05)
                self._set_state(ServiceState.LISTENING)
                cont_wav  = record_utterance(self._utt_q, self._stop_ev, max_s=CONV_FOLLOWUP_S)
                cont_text = transcribe(cont_wav) if cont_wav else ""
                if cont_text and not validator.is_noise(cont_text):
                    text = text.rstrip(".!?,") + " " + cont_text
                    log.info("Combined: %r", text[:120])
                self._set_state(ServiceState.THINKING)

        print(f"  YOU  : {text}", flush=True)

        # ── Fact extraction — detect and store facts from utterances ───
        try:
            from app.services.memory.structured_memory import process_utterance
            _stored = process_utterance(text, owner_name="Navid")
            if _stored:
                log.info("Facts stored from utterance: %d", len(_stored))
        except Exception as _fe:
            log.debug("Fact extraction: %s", _fe)

        # ── 4. Answer (reflex or council) ─────────────────────────────
        if _reflex:
            log.info("Reflex: %r → %r", text, _reflex)
            ds.reflex_used        = True
            ds.council_latency_ms = 0.0
            answer                = _reflex
        else:
            t_council             = time.monotonic()
            answer                = query_council(text)
            ds.council_latency_ms = (time.monotonic() - t_council) * 1000

        ds.answer_chars = len(answer)
        print(f"  MARK : {answer}{' [reflex]' if ds.reflex_used else ''}", flush=True)

        # ── 5. Speak answer (interruptible via barge-in) ──────────────
        self._set_state(ServiceState.SPEAKING)
        self._barge_in_enabled = False
        self._barge_in_count   = 0
        self._interrupt.clear()

        threading.Timer(
            BARGE_IN_DELAY_S,
            lambda: setattr(self, "_barge_in_enabled", True),
        ).start()

        t_tts = time.monotonic()
        if not self.is_muted():
            _beep(660, 0.07)
            interrupted = self._tts.speak(answer, self._interrupt)
        else:
            interrupted = False
        ds.tts_latency_ms = (time.monotonic() - t_tts) * 1000
        ds.interrupted    = interrupted
        self._barge_in_enabled = False

        # ── 6. Barge-in re-listen ─────────────────────────────────────
        if interrupted:
            self._interrupt.clear()
            _beep(880, 0.10)

            # Same onset+timeout discipline as the primary utterance —
            # prevents the 42-second LISTENING hang on accidental barge-in.
            def _on_bi_speech():
                if self._state == ServiceState.WAIT_FOR_SPEECH:
                    self._set_state(ServiceState.LISTENING)

            self._set_state(ServiceState.WAIT_FOR_SPEECH)
            bi_wav = record_utterance(
                self._utt_q, self._stop_ev,
                wait_timeout_s  = WAIT_FOR_SPEECH_TIMEOUT_S,
                on_speech_start = _on_bi_speech,
            )
            self._interrupt.clear()

            if not bi_wav:
                log.info("Barge-in: no speech in %.0fs — returning to IDLE", WAIT_FOR_SPEECH_TIMEOUT_S)
                self._set_state(ServiceState.IDLE)
                return

            self._set_state(ServiceState.THINKING)
            bi_text = transcribe(bi_wav)

            # Stop command via barge-in → go quiet immediately
            if bi_text.strip().lower().rstrip(".!?,; ") in _STOP_CMDS:
                log.info("Stop command via barge-in: %r", bi_text)
                ds.total_ms = (time.monotonic() - t_start) * 1000
                diag.record(ds)
                self._interrupt.clear()
                self._set_state(ServiceState.IDLE)
                return

            if not validator.is_noise(bi_text):
                print(f"  YOU  : {bi_text}", flush=True)
                bi_answer = query_council(bi_text)
                print(f"  MARK : {bi_answer}", flush=True)

                self._set_state(ServiceState.SPEAKING)
                self._barge_in_enabled = False
                self._barge_in_count   = 0
                self._interrupt.clear()
                threading.Timer(
                    BARGE_IN_DELAY_S,
                    lambda: setattr(self, "_barge_in_enabled", True),
                ).start()
                if not self.is_muted():
                    _beep(660, 0.07)
                    self._tts.speak(bi_answer, self._interrupt)
                self._barge_in_enabled = False

        # ── 7. FOLLOWUP — 5 s post-response window ────────────────────
        self._interrupt.clear()
        self._set_state(ServiceState.FOLLOWUP)

        fu_wav = record_utterance(
            self._utt_q, self._stop_ev,
            max_s     = FOLLOWUP_WINDOW_S,
            timeout_s = FOLLOWUP_WINDOW_S,
            followup  = True,
        )

        if fu_wav:
            self._set_state(ServiceState.THINKING)
            fu_text = transcribe(fu_wav)

            if fu_text.strip().lower().rstrip(".!?,; ") in _STOP_CMDS:
                log.info("Stop command in follow-up: %r", fu_text)
            elif not validator.is_noise(fu_text):
                ds.followup_used = True
                print(f"  YOU  : {fu_text}", flush=True)
                fu_answer = query_council(fu_text)
                print(f"  MARK : {fu_answer}", flush=True)

                self._set_state(ServiceState.SPEAKING)
                self._barge_in_enabled = False
                self._barge_in_count   = 0
                self._interrupt.clear()
                threading.Timer(
                    BARGE_IN_DELAY_S,
                    lambda: setattr(self, "_barge_in_enabled", True),
                ).start()
                if not self.is_muted():
                    _beep(660, 0.07)
                    self._tts.speak(fu_answer, self._interrupt)
                self._barge_in_enabled = False

        # ── 8. Diagnostics ────────────────────────────────────────────
        ds.total_ms = (time.monotonic() - t_start) * 1000
        diag.record(ds)
        log.info(
            "Turn: wake=%.1fs  detect=%.1fs  listen=%.1fs  "
            "stt=%.1fs  llm=%.1fs  tts=%.1fs  total=%.1fs  [%s]",
            ds.wake_latency_ms      / 1000,
            ds.speech_detect_ms     / 1000,
            ds.listening_duration_ms / 1000,
            ds.stt_latency_ms       / 1000,
            ds.council_latency_ms   / 1000,
            ds.tts_latency_ms       / 1000,
            ds.total_ms             / 1000,
            "reflex" if ds.reflex_used else (
                "conv" if ds.council_latency_ms < 3500 else "executive"
            ),
        )

        self._interrupt.clear()
        self._set_state(ServiceState.IDLE)

    def _speak(self, text: str) -> None:
        if self.is_muted():
            print(f"  MARK : {text} (muted)", flush=True)
            return
        try:
            self._tts.speak(text, self._interrupt)
        except Exception as e:
            log.error("_speak: %s", e)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def status_dict(self) -> dict:
        from app.services.voice.voice_diagnostics import diag
        return {
            "state":        self._state.value,
            "running":      self._running,
            "sleeping":     self.is_sleeping(),
            "muted":        self.is_muted(),
            "wake_engine":  self._wake_engine.status() if self._wake_engine else None,
            "stt_ready":    _stt_loaded.is_set(),
            "council_live": _council_loop is not None and _council_loop.is_running(),
            "tts_backend":  getattr(self._tts, "backend", "none"),
            "diagnostics":  diag.summary(),
        }
