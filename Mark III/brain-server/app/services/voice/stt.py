"""
MARK III — Speech-to-Text Engine (Phase 11)

Converts raw audio (WAV bytes or file path) to text transcript.
Completely decoupled from the conversation engine.

Supported engines:
  Faster-Whisper (primary) — local, runs on CPU/GPU, no API cost
    pip install faster-whisper

Graceful degradation:
  If faster-whisper is not installed, transcribe() returns an empty result
  with a clear error message. The voice pipeline falls back to API-based
  transcription (e.g. upload to /voice/transcribe endpoint and use a
  cloud STT service).

Thread safety:
  The Whisper model is loaded once and reused. Model loading is slow
  (~1–5s depending on size). Inference is thread-safe via a lock.
  All transcription is run via asyncio.to_thread() to avoid blocking
  the event loop.

Model size vs. accuracy vs. speed (on CPU):
  tiny:   ~39M params,  ~10s audio in ~1s,  WER ~14%
  base:   ~74M params,  ~10s audio in ~2s,  WER ~10%
  small:  ~244M params, ~10s audio in ~5s,  WER ~6%
  medium: ~769M params, ~10s audio in ~15s, WER ~4%
  large:  ~1550M params,~10s audio in ~30s, WER ~3%

Recommended default: "base" for real-time desktop use.
Use "small" or "medium" for higher accuracy when latency is acceptable.
"""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("markiii.voice.stt")

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------

try:
    from faster_whisper import WhisperModel
    _WHISPER_AVAILABLE = True
except ImportError:
    _WHISPER_AVAILABLE = False
    logger.info(
        "faster-whisper not installed — STT disabled. "
        "Install: pip install faster-whisper"
    )


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class TranscriptResult:
    text:        str
    language:    str           # detected language code, e.g. "en"
    confidence:  float         # average segment probability, 0.0–1.0
    latency_ms:  float
    engine:      str
    segments:    list[dict]    # [{start, end, text, probability}]
    error:       Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    def to_dict(self) -> dict:
        return {
            "text":       self.text,
            "language":   self.language,
            "confidence": round(self.confidence, 3),
            "latency_ms": round(self.latency_ms, 1),
            "engine":     self.engine,
            "error":      self.error,
        }


_EMPTY_RESULT = TranscriptResult(
    text="", language="", confidence=0.0, latency_ms=0.0,
    engine="none", segments=[], error=None,
)

_UNAVAILABLE_RESULT = TranscriptResult(
    text="", language="", confidence=0.0, latency_ms=0.0,
    engine="none", segments=[],
    error="faster-whisper not installed. Run: pip install faster-whisper",
)


# ---------------------------------------------------------------------------
# Faster-Whisper engine
# ---------------------------------------------------------------------------

class FasterWhisperSTT:
    """
    Local transcription using faster-whisper (CTranslate2-based Whisper).

    The model is lazy-loaded on first transcription call.
    Subsequent calls reuse the loaded model.
    A threading.Lock prevents concurrent inference on the same model instance.
    """

    def __init__(
        self,
        model_size:    str = "base",
        device:        str = "cpu",
        compute_type:  str = "int8",
    ) -> None:
        self._model_size   = model_size
        self._device       = device
        self._compute_type = compute_type
        self._model: Optional[WhisperModel] = None
        self._lock = threading.Lock()
        self._loaded = False

    @property
    def is_available(self) -> bool:
        return _WHISPER_AVAILABLE

    def _load(self) -> None:
        if self._loaded:
            return
        logger.info(
            "Loading Whisper model  size=%s  device=%s  compute_type=%s",
            self._model_size, self._device, self._compute_type,
        )
        t0 = time.monotonic()
        self._model = WhisperModel(
            self._model_size,
            device       = self._device,
            compute_type = self._compute_type,
        )
        self._loaded = True
        logger.info("Whisper model loaded in %.1fs", time.monotonic() - t0)

    def transcribe_bytes(
        self,
        wav_bytes:           bytes,
        language:            Optional[str] = None,
        initial_prompt:      Optional[str] = None,
        vad_filter:          bool = True,
        beam_size:           int = 5,
    ) -> TranscriptResult:
        """
        Transcribe WAV bytes synchronously.

        Args:
            wav_bytes:      WAV audio (16-bit PCM, any sample rate — Whisper resamples)
            language:       force language detection ('en', 'fr', …) or None = auto-detect
            initial_prompt: context hint (e.g. "User is asking about productivity")
            vad_filter:     skip silent audio chunks (faster, uses Silero VAD internally)
            beam_size:      beam search width; 1 = greedy (fastest), 5 = default

        Returns:
            TranscriptResult
        """
        if not _WHISPER_AVAILABLE:
            return _UNAVAILABLE_RESULT

        t0 = time.monotonic()

        try:
            with self._lock:
                self._load()

                # Write to temp file — faster-whisper accepts file path or numpy array
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(wav_bytes)
                    tmp_path = tmp.name

                segments, info = self._model.transcribe(
                    tmp_path,
                    language       = language,
                    initial_prompt = initial_prompt,
                    vad_filter     = vad_filter,
                    beam_size      = beam_size,
                    word_timestamps = False,
                )

                seg_list = []
                full_text_parts = []
                total_prob = 0.0

                for seg in segments:
                    seg_list.append({
                        "start":       round(seg.start, 2),
                        "end":         round(seg.end, 2),
                        "text":        seg.text.strip(),
                        "probability": round(seg.avg_logprob, 3),
                    })
                    full_text_parts.append(seg.text.strip())
                    total_prob += seg.avg_logprob

                text       = " ".join(full_text_parts).strip()
                avg_logprob = total_prob / len(seg_list) if seg_list else 0.0
                # Convert log-prob to approximate confidence (0–1)
                confidence  = min(1.0, max(0.0, (avg_logprob + 1.0)))

        except Exception as e:
            logger.error("Whisper transcription error: %s", e)
            return TranscriptResult(
                text="", language="", confidence=0.0,
                latency_ms=(time.monotonic() - t0) * 1000,
                engine="faster_whisper", segments=[], error=str(e),
            )

        latency_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "Transcribed  text=%r  lang=%s  conf=%.2f  latency=%.0fms",
            text[:60], info.language, confidence, latency_ms,
        )

        return TranscriptResult(
            text       = text,
            language   = info.language,
            confidence = confidence,
            latency_ms = latency_ms,
            engine     = "faster_whisper",
            segments   = seg_list,
        )

    async def transcribe_bytes_async(
        self,
        wav_bytes: bytes,
        **kwargs,
    ) -> TranscriptResult:
        """Async wrapper — runs transcription in a thread pool."""
        return await asyncio.to_thread(self.transcribe_bytes, wav_bytes, **kwargs)

    def status(self) -> dict:
        return {
            "engine":       "faster_whisper",
            "available":    self.is_available,
            "model_size":   self._model_size,
            "device":       self._device,
            "compute_type": self._compute_type,
            "model_loaded": self._loaded,
        }


# ---------------------------------------------------------------------------
# Null STT (graceful degradation)
# ---------------------------------------------------------------------------

class NullSTT:
    """Returned when no STT engine is available."""

    @property
    def is_available(self) -> bool:
        return False

    def transcribe_bytes(self, wav_bytes: bytes, **kwargs) -> TranscriptResult:
        return _UNAVAILABLE_RESULT

    async def transcribe_bytes_async(self, wav_bytes: bytes, **kwargs) -> TranscriptResult:
        return _UNAVAILABLE_RESULT

    def status(self) -> dict:
        return {"engine": "none", "available": False,
                "reason": "faster-whisper not installed"}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_stt_engine: Optional[FasterWhisperSTT | NullSTT] = None


def get_stt_engine(
    model_size:   str = "base",
    device:       str = "cpu",
    compute_type: str = "int8",
) -> FasterWhisperSTT | NullSTT:
    """
    Return the singleton STT engine.
    First call initializes with the given parameters.
    Subsequent calls return the cached instance.
    """
    global _stt_engine
    if _stt_engine is None:
        if _WHISPER_AVAILABLE:
            _stt_engine = FasterWhisperSTT(model_size, device, compute_type)
        else:
            _stt_engine = NullSTT()
    return _stt_engine


def reset_stt_engine() -> None:
    """Force re-initialization on next get_stt_engine() call."""
    global _stt_engine
    _stt_engine = None


def stt_available() -> bool:
    return _WHISPER_AVAILABLE


def wav_bytes_duration(wav_bytes: bytes) -> float:
    """Return duration in seconds of WAV audio bytes."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0
