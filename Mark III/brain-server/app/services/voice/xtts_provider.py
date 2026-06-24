from __future__ import annotations

"""
MARK III — TTS Provider  (Phase 14 — Piper)

Fallback chain:
  1. Piper TTS    — local ONNX neural voice, ~60 ms synthesis, no server needed
  2. SAPI SpVoice — Windows built-in, always available

Install:
    pip install piper-tts

Voice model (~65 MB) downloads automatically to app/services/voice/models/
on first run.  Default voice: en_US-lessac-medium (clear, professional male).

speak(text, interrupt_ev) → bool
    Synthesise and play text.  Returns True if interrupted.
stop()
    Shut down the SAPI COM thread.
backend → "piper" | "sapi"
"""

import io
import logging
import os
import queue
import threading
import time
import urllib.request
import wave

import numpy as np

log = logging.getLogger("markiii.tts")

SPEAKER_INDEX    = 4
SAPI_VOICE_IDX   = 2
_SAPI_VOICE_NAME = "Zira"

_SVSFlagsAsync        = 1
_SVSFPurgeBeforeSpeak = 2

# Piper model — auto-downloaded to models/ on first run
_MODELS_DIR     = os.path.join(os.path.dirname(__file__), "models")
_PIPER_VOICE    = "en_US-lessac-medium"
_PIPER_ONNX     = os.path.join(_MODELS_DIR, f"{_PIPER_VOICE}.onnx")
_PIPER_JSON     = os.path.join(_MODELS_DIR, f"{_PIPER_VOICE}.onnx.json")
_PIPER_BASE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "en/en_US/lessac/medium/"
)

# WAV cache for short fixed phrases ("Listening.", "Signal unclear.", etc.)
_wav_cache:    dict[str, bytes] = {}
_CACHE_MAX_LEN = 80


# ─────────────────────────────────────────────────────────────────
# WASAPI-safe WAV playback  (resamples to device native rate)
# ─────────────────────────────────────────────────────────────────

def _play_wav_interruptible(
    wav_bytes:    bytes,
    interrupt_ev: threading.Event,
    speaker_idx:  int = SPEAKER_INDEX,
) -> bool:
    """
    Play WAV bytes through sounddevice OutputStream.
    Resamples to the device's native sample rate before each write —
    prevents the 17-second WASAPI stall from sample-rate mismatch.
    Returns True if interrupted before completion.
    """
    import sounddevice as sd

    if not wav_bytes:
        return False

    try:
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            src_sr = wf.getframerate()
            nc     = wf.getnchannels()
            raw    = wf.readframes(wf.getnframes())
    except Exception as e:
        log.error("WAV parse: %s", e)
        return False

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if nc > 1:
        audio = audio.reshape(-1, nc).mean(axis=1)

    try:
        dev_info  = sd.query_devices(speaker_idx, "output")
        device_sr = int(dev_info["default_samplerate"])
    except Exception:
        device_sr = 48000

    if src_sr != device_sr:
        n_out = int(len(audio) * device_sr / src_sr)
        audio = np.interp(
            np.linspace(0.0, 1.0, n_out),
            np.linspace(0.0, 1.0, len(audio)),
            audio,
        ).astype(np.float32)
        log.debug("Resampled audio: %d Hz → %d Hz", src_sr, device_sr)

    chunk_frames = device_sr // 5   # 200 ms blocks

    try:
        with sd.OutputStream(
            samplerate = device_sr,
            channels   = 1,
            dtype      = "float32",
            device     = speaker_idx,
        ) as stream:
            pos = 0
            while pos < len(audio):
                if interrupt_ev.is_set():
                    stream.abort()
                    return True
                chunk = audio[pos : pos + chunk_frames]
                if len(chunk) < chunk_frames:
                    chunk = np.pad(chunk, (0, chunk_frames - len(chunk)))
                stream.write(chunk)
                pos += chunk_frames
            stream.stop()
    except Exception as e:
        log.error("Playback: %s", e)
        return False

    return False


# ─────────────────────────────────────────────────────────────────
# SAPI backend  (Windows SpVoice — always available)
# ─────────────────────────────────────────────────────────────────

class _SAPIThread:
    """SAPI SpVoice in a dedicated COM apartment thread."""

    def __init__(self) -> None:
        self._q      : queue.Queue = queue.Queue()
        self._ready    = threading.Event()
        self._sapi     = None
        self._thread   = threading.Thread(
            target=self._run, daemon=True, name="tts-sapi",
        )
        self._thread.start()
        self._ready.wait(timeout=15)

    def _run(self) -> None:
        try:
            import win32com.client
            self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
            voices = self._sapi.GetVoices()
            picked = None
            for i in range(voices.Count):
                token = voices.Item(i)
                if _SAPI_VOICE_NAME in token.GetDescription():
                    picked = token
                    break
            if picked is None and voices.Count > SAPI_VOICE_IDX:
                picked = voices.Item(SAPI_VOICE_IDX)
            if picked:
                self._sapi.Voice = picked
                log.info("SAPI voice: %s", picked.GetDescription())
            self._sapi.Rate   = 1
            self._sapi.Volume = 95
            log.info("SpVoice ready")
        except Exception as e:
            log.error("SpVoice init: %s", e)
        self._ready.set()

        while True:
            item = self._q.get()
            if item is None:
                break
            fn, args = item
            try:
                fn(*args)
            except Exception as e:
                log.error("SAPI task: %s", e)

    def _do_speak(
        self, text: str, interrupt_ev: threading.Event, done_q: queue.Queue,
    ) -> None:
        interrupted = False
        try:
            if self._sapi:
                self._sapi.Speak(text, _SVSFlagsAsync)
                while True:
                    if interrupt_ev.is_set():
                        self._sapi.Speak("", _SVSFlagsAsync | _SVSFPurgeBeforeSpeak)
                        interrupted = True
                        break
                    if self._sapi.Status.RunningState != 2:
                        break
                    time.sleep(0.05)
            else:
                log.error("SAPI not available")
        except Exception as e:
            log.error("SAPI speak: %s", e)
        finally:
            done_q.put(interrupted)

    def speak(self, text: str, interrupt_ev: threading.Event) -> bool:
        done_q: queue.Queue[bool] = queue.Queue()
        self._q.put((self._do_speak, (text, interrupt_ev, done_q)))
        try:
            return done_q.get(timeout=120)
        except queue.Empty:
            return False

    def stop(self) -> None:
        self._q.put(None)


# ─────────────────────────────────────────────────────────────────
# Piper backend  (local ONNX, ~60 ms synthesis)
# ─────────────────────────────────────────────────────────────────

def _ensure_model() -> None:
    """Download ONNX + JSON config if not already in models/."""
    os.makedirs(_MODELS_DIR, exist_ok=True)
    for fname in (f"{_PIPER_VOICE}.onnx", f"{_PIPER_VOICE}.onnx.json"):
        dest = os.path.join(_MODELS_DIR, fname)
        if os.path.isfile(dest):
            continue
        url = _PIPER_BASE_URL + fname
        log.info("Downloading Piper voice model: %s ...", fname)
        try:
            urllib.request.urlretrieve(url, dest)
            log.info("Saved: %s", dest)
        except Exception as e:
            log.error("Download failed (%s): %s", fname, e)
            raise


class _PiperBackend:
    """
    Piper TTS  —  local ONNX inference via piper-tts.

    pip install piper-tts
    Model downloads automatically on first instantiation.
    """

    def __init__(self) -> None:
        _ensure_model()
        from piper.voice import PiperVoice
        log.info("Loading Piper voice: %s", _PIPER_VOICE)
        self._voice = PiperVoice.load(_PIPER_ONNX)
        log.info("Piper ready  voice=%s  sr=%d Hz", _PIPER_VOICE, self._voice.config.sample_rate)
        self._warmup()

    def _warmup(self) -> None:
        """
        Synthesise one phrase during init to trigger ONNX JIT compilation.
        This eliminates the ~1.5 s first-call latency and pre-warms the cache.
        """
        try:
            wav = self.synthesize("Listening.")
            _wav_cache["listening."] = wav
            log.info("Piper ONNX warmed up; 'Listening.' cached")
        except Exception as e:
            log.debug("Piper warmup: %s", e)

    def synthesize(self, text: str) -> bytes:
        """Synthesise text → WAV bytes (Piper native sample rate)."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._voice.synthesize_wav(text, wf)
        return buf.getvalue()

    def speak(self, text: str, interrupt_ev: threading.Event) -> bool:
        key          = text.strip().lower()
        should_cache = len(text) <= _CACHE_MAX_LEN and "\n" not in text

        if should_cache and key in _wav_cache:
            wav = _wav_cache[key]
        else:
            wav = self.synthesize(text)
            if should_cache:
                _wav_cache[key] = wav

        return _play_wav_interruptible(wav, interrupt_ev)


# ─────────────────────────────────────────────────────────────────
# Public API: XTTSProvider  (now Piper-primary)
# ─────────────────────────────────────────────────────────────────

class XTTSProvider:
    """
    MARK III TTS provider.

    Selects the best available backend at startup:
        Piper TTS  →  SAPI SpVoice (fallback)

    speak(text, interrupt_ev) → bool
    stop()
    backend → "piper" | "sapi"
    """

    def __init__(self, speaker_idx: int = SPEAKER_INDEX) -> None:
        self._speaker_idx = speaker_idx
        self._sapi        = _SAPIThread()
        self._piper: _PiperBackend | None = None
        self._backend     = "sapi"
        self._init_piper()

    def _init_piper(self) -> None:
        try:
            self._piper   = _PiperBackend()
            self._backend = "piper"
        except ImportError:
            log.info(
                "TTS: piper-tts not installed — using SAPI.  "
                "Run: pip install piper-tts"
            )
        except Exception as e:
            log.warning("TTS: Piper init failed (%s) — using SAPI", e)

    def speak(self, text: str, interrupt_ev: threading.Event) -> bool:
        if self._backend == "piper" and self._piper:
            try:
                return self._piper.speak(text, interrupt_ev)
            except Exception as e:
                log.warning("Piper speak failed (%s) — falling back to SAPI", e)
        return self._sapi.speak(text, interrupt_ev)

    def stop(self) -> None:
        self._sapi.stop()

    @property
    def backend(self) -> str:
        return self._backend
