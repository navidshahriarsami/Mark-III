"""
MARK III — Text-to-Speech Engine (Phase 11)

Converts MARK III's text responses to audio (WAV bytes).
Completely decoupled from the conversation engine.

Supported engines:
  Piper (primary) — local, fast, high-quality, runs on CPU
    Install: download piper binary from https://github.com/rhasspy/piper/releases
    Models:  en_US-amy-medium.onnx (default, ~63MB)
    Output:  16-bit PCM WAV at 22050Hz

  ElevenLabs (cloud, premium quality)
    pip install elevenlabs (optional)
    Requires API key in config.
    Falls back to Piper if ElevenLabs fails.

Graceful degradation:
  Piper not found → ElevenLabs → None (no audio, text only)

Interrupt support:
  synthesis() returns WAV bytes. Playback interruption is handled by
  audio_manager.play_wav_bytes() which checks a stop_event per chunk.
  TTS itself is not interruptible (it's a one-shot call), but the
  output can be discarded before playback begins if interrupted.

Future compatibility:
  For streaming TTS (chunk-by-chunk audio as tokens arrive), add
  a synthesize_stream() method that yields WAV chunks. ElevenLabs
  supports this via websocket; Piper can be pipelined with sentence
  boundaries.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger("markiii.voice.tts")

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------

try:
    from elevenlabs import ElevenLabs as _ElevenLabsClient
    from elevenlabs import VoiceSettings as _VoiceSettings
    _ELEVENLABS_AVAILABLE = True
except ImportError:
    _ELEVENLABS_AVAILABLE = False
    logger.info("elevenlabs SDK not installed. Install: pip install elevenlabs")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SynthesisResult:
    wav_bytes:   bytes
    engine:      str
    latency_ms:  float
    duration_s:  float
    error:       Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return len(self.wav_bytes) == 0

    def to_dict(self) -> dict:
        return {
            "engine":     self.engine,
            "latency_ms": round(self.latency_ms, 1),
            "duration_s": round(self.duration_s, 2),
            "bytes":      len(self.wav_bytes),
            "error":      self.error,
        }


_EMPTY_RESULT = SynthesisResult(
    wav_bytes=b"", engine="none", latency_ms=0.0, duration_s=0.0, error=None,
)


def _wav_duration(wav_bytes: bytes) -> float:
    """Return duration in seconds of WAV bytes."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Piper TTS (local)
# ---------------------------------------------------------------------------

class PiperTTS:
    """
    Local TTS using the Piper binary (https://github.com/rhasspy/piper).

    Piper is a fast, high-quality neural TTS that runs on CPU.
    Latency: ~150-500ms for typical responses on a modern CPU.

    Model files (.onnx + .onnx.json config) must be downloaded separately.
    See: https://huggingface.co/rhasspy/piper-voices

    Usage:
        echo "Hello MARK" | piper --model en_US-amy-medium.onnx --output_file out.wav
    """

    def __init__(
        self,
        binary:      str = "piper",
        model:       str = "en_US-amy-medium.onnx",
        model_config: str = "",                        # auto-derived if empty
        length_scale: float = 1.0,                     # speaking rate (1.0 = normal)
        noise_scale:  float = 0.667,                   # variation
        noise_w:      float = 0.8,                     # phoneme duration variation
    ) -> None:
        self._binary       = binary
        self._model        = model
        self._model_config = model_config or (model.replace(".onnx", ".onnx.json") if model.endswith(".onnx") else "")
        self._length_scale = length_scale
        self._noise_scale  = noise_scale
        self._noise_w      = noise_w
        self._available: Optional[bool] = None

    @property
    def is_available(self) -> bool:
        if self._available is None:
            self._available = self._check()
        return self._available

    def _check(self) -> bool:
        """Check if piper binary is on PATH and model file exists."""
        try:
            result = subprocess.run(
                [self._binary, "--version"],
                capture_output=True, timeout=5,
            )
            binary_ok = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            binary_ok = False

        if not binary_ok:
            logger.info(
                "Piper binary '%s' not found. "
                "Download from https://github.com/rhasspy/piper/releases",
                self._binary,
            )
            return False

        model_ok = os.path.isfile(self._model)
        if not model_ok:
            logger.info(
                "Piper model '%s' not found. "
                "Download from https://huggingface.co/rhasspy/piper-voices",
                self._model,
            )
            return False

        return True

    def synthesize(self, text: str) -> SynthesisResult:
        """Synthesize text to WAV bytes using Piper. Blocking."""
        if not self.is_available:
            return SynthesisResult(
                wav_bytes=b"", engine="piper", latency_ms=0.0, duration_s=0.0,
                error="Piper not available (binary or model missing)",
            )

        t0 = time.monotonic()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out_f:
            out_path = out_f.name

        try:
            cmd = [
                self._binary,
                "--model",        self._model,
                "--output_file",  out_path,
                "--length_scale", str(self._length_scale),
                "--noise_scale",  str(self._noise_scale),
                "--noise_w",      str(self._noise_w),
            ]
            if self._model_config and os.path.isfile(self._model_config):
                cmd += ["--config", self._model_config]

            proc = subprocess.run(
                cmd,
                input     = text.encode("utf-8"),
                capture_output = True,
                timeout   = 30,
            )

            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", errors="replace")[:200]
                return SynthesisResult(
                    wav_bytes=b"", engine="piper", latency_ms=0.0, duration_s=0.0,
                    error=f"Piper error (rc={proc.returncode}): {err}",
                )

            with open(out_path, "rb") as f:
                wav_bytes = f.read()

        except subprocess.TimeoutExpired:
            return SynthesisResult(
                wav_bytes=b"", engine="piper", latency_ms=0.0, duration_s=0.0,
                error="Piper timed out",
            )
        except Exception as e:
            return SynthesisResult(
                wav_bytes=b"", engine="piper", latency_ms=0.0, duration_s=0.0,
                error=str(e),
            )
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass

        latency_ms = (time.monotonic() - t0) * 1000
        duration_s = _wav_duration(wav_bytes)
        logger.info(
            "Piper TTS  chars=%d  latency=%.0fms  duration=%.2fs",
            len(text), latency_ms, duration_s,
        )
        return SynthesisResult(
            wav_bytes  = wav_bytes,
            engine     = "piper",
            latency_ms = latency_ms,
            duration_s = duration_s,
        )

    async def synthesize_async(self, text: str) -> SynthesisResult:
        return await asyncio.to_thread(self.synthesize, text)

    def status(self) -> dict:
        return {
            "engine":    "piper",
            "available": self.is_available,
            "binary":    self._binary,
            "model":     self._model,
        }


# ---------------------------------------------------------------------------
# ElevenLabs TTS (cloud)
# ---------------------------------------------------------------------------

class ElevenLabsTTS:
    """
    Cloud TTS via ElevenLabs API.
    High quality, realistic voices. Requires API key and internet.
    Falls back gracefully on error.
    """

    def __init__(self, api_key: str, voice_id: str) -> None:
        self._api_key  = api_key
        self._voice_id = voice_id
        self._client: Optional[_ElevenLabsClient] = None

    @property
    def is_available(self) -> bool:
        return _ELEVENLABS_AVAILABLE and bool(self._api_key)

    def _get_client(self) -> _ElevenLabsClient:
        if self._client is None:
            self._client = _ElevenLabsClient(api_key=self._api_key)
        return self._client

    def synthesize(self, text: str) -> SynthesisResult:
        if not self.is_available:
            return SynthesisResult(
                wav_bytes=b"", engine="elevenlabs", latency_ms=0.0, duration_s=0.0,
                error="ElevenLabs not available (missing key or library)",
            )

        t0 = time.monotonic()
        try:
            client = self._get_client()
            # generate() returns an iterator of bytes chunks
            audio_chunks = client.generate(
                text  = text,
                voice = self._voice_id,
                model = "eleven_turbo_v2",    # lowest latency model
            )
            raw_mp3 = b"".join(audio_chunks)

            # Convert MP3 to WAV for consistent playback
            wav_bytes = _mp3_to_wav(raw_mp3)

        except Exception as e:
            return SynthesisResult(
                wav_bytes=b"", engine="elevenlabs", latency_ms=0.0, duration_s=0.0,
                error=str(e),
            )

        latency_ms = (time.monotonic() - t0) * 1000
        duration_s = _wav_duration(wav_bytes)
        logger.info(
            "ElevenLabs TTS  chars=%d  latency=%.0fms  duration=%.2fs",
            len(text), latency_ms, duration_s,
        )
        return SynthesisResult(
            wav_bytes  = wav_bytes,
            engine     = "elevenlabs",
            latency_ms = latency_ms,
            duration_s = duration_s,
        )

    async def synthesize_async(self, text: str) -> SynthesisResult:
        return await asyncio.to_thread(self.synthesize, text)

    def status(self) -> dict:
        return {
            "engine":   "elevenlabs",
            "available": self.is_available,
            "voice_id": self._voice_id,
        }


def _mp3_to_wav(mp3_bytes: bytes) -> bytes:
    """Convert MP3 bytes to WAV bytes via ffmpeg subprocess."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as mp3f:
        mp3f.write(mp3_bytes)
        mp3_path = mp3f.name
    wav_path = mp3_path.replace(".mp3", ".wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3_path, "-ar", "22050", "-ac", "1", wav_path],
            capture_output=True, timeout=10,
        )
        if os.path.isfile(wav_path):
            with open(wav_path, "rb") as f:
                return f.read()
        return mp3_bytes   # fallback: return raw mp3 if ffmpeg missing
    except Exception:
        return mp3_bytes   # graceful degradation: return mp3 bytes
    finally:
        for p in (mp3_path, wav_path):
            try:
                os.unlink(p)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Null TTS
# ---------------------------------------------------------------------------

class NullTTS:
    @property
    def is_available(self) -> bool:
        return False

    def synthesize(self, text: str) -> SynthesisResult:
        return SynthesisResult(
            wav_bytes=b"", engine="none", latency_ms=0.0, duration_s=0.0,
            error="No TTS engine available. Install piper or configure ElevenLabs.",
        )

    async def synthesize_async(self, text: str) -> SynthesisResult:
        return self.synthesize(text)

    def status(self) -> dict:
        return {"engine": "none", "available": False}


# ---------------------------------------------------------------------------
# Composite TTS: try primary, fall back to secondary
# ---------------------------------------------------------------------------

class CompositeTTS:
    """
    Tries primary engine first; falls back to secondary on error.
    Allows Piper as primary with ElevenLabs as cloud backup, or vice versa.
    """

    def __init__(
        self,
        primary:   PiperTTS | ElevenLabsTTS | NullTTS,
        secondary: PiperTTS | ElevenLabsTTS | NullTTS,
    ) -> None:
        self._primary   = primary
        self._secondary = secondary

    @property
    def is_available(self) -> bool:
        return self._primary.is_available or self._secondary.is_available

    def synthesize(self, text: str) -> SynthesisResult:
        result = self._primary.synthesize(text)
        if result.error and self._secondary.is_available:
            logger.warning("Primary TTS failed (%s), trying secondary", result.error[:60])
            result = self._secondary.synthesize(text)
        return result

    async def synthesize_async(self, text: str) -> SynthesisResult:
        result = await self._primary.synthesize_async(text)
        if result.error and self._secondary.is_available:
            logger.warning("Primary TTS failed (%s), trying secondary", result.error[:60])
            result = await self._secondary.synthesize_async(text)
        return result

    def status(self) -> dict:
        return {
            "engine":    "composite",
            "available": self.is_available,
            "primary":   self._primary.status(),
            "secondary": self._secondary.status(),
        }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_tts_engine: Optional[CompositeTTS | NullTTS] = None


def get_tts_engine(
    engine:          str = "piper",
    piper_binary:    str = "piper",
    piper_model:     str = "en_US-amy-medium.onnx",
    piper_config:    str = "",
    elevenlabs_key:  str = "",
    elevenlabs_voice: str = "",
) -> CompositeTTS | NullTTS:
    """
    Return the singleton TTS engine.
    Primary engine determined by `engine` config value.
    """
    global _tts_engine
    if _tts_engine is None:
        piper = PiperTTS(piper_binary, piper_model, piper_config)
        el    = ElevenLabsTTS(elevenlabs_key, elevenlabs_voice) if elevenlabs_key else NullTTS()

        if engine == "elevenlabs":
            primary, secondary = el, piper
        else:
            primary, secondary = piper, el

        if primary.is_available or secondary.is_available:
            _tts_engine = CompositeTTS(primary, secondary)
        else:
            _tts_engine = NullTTS()

    return _tts_engine


def reset_tts_engine() -> None:
    global _tts_engine
    _tts_engine = None


def tts_available() -> bool:
    engine = get_tts_engine()
    return engine.is_available
