"""
MARK III — Audio Manager (Phase 11)

Device-aware audio I/O abstraction over sounddevice.

Responsibilities:
  - Enumerate microphones and speakers
  - Record audio from a specific device (or system default)
  - Play audio to a specific device (or system default)
  - Voice Activity Detection (energy-based VAD)
  - Push-to-talk mode (record while signal held, stop on release)
  - Volume-gated recording (stop when silence exceeds threshold)

Graceful degradation:
  sounddevice is optional. If not installed, all functions return empty
  results or raise AudioNotAvailable. The voice pipeline degrades to
  API-only mode (mobile PTT, no local mic).

Thread safety:
  Recording runs in a background thread via sounddevice callbacks.
  Recorded chunks are placed in a thread-safe queue.
  Playback is blocking (sounddevice.play + wait) — call from a thread
  or wrap in asyncio.to_thread().
"""

from __future__ import annotations

import asyncio
import io
import logging
import queue
import threading
import time
import wave
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("markiii.voice.audio")

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------

try:
    import numpy as np
    import sounddevice as sd
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False
    logger.info("sounddevice not installed — audio I/O disabled. Install: pip install sounddevice numpy")


class AudioNotAvailable(RuntimeError):
    """Raised when sounddevice is not installed or no device found."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class AudioDevice:
    index:       int
    name:        str
    device_type: str         # input | output | both
    channels:    int
    sample_rate: float
    is_default:  bool

    def to_dict(self) -> dict:
        return {
            "index":       self.index,
            "name":        self.name,
            "device_type": self.device_type,
            "channels":    self.channels,
            "sample_rate": self.sample_rate,
            "is_default":  self.is_default,
        }


@dataclass
class RecordingResult:
    audio_bytes: bytes       # WAV bytes, 16-bit PCM
    duration_s:  float
    sample_rate: int
    channels:    int
    peak_db:     float       # peak amplitude in dBFS
    was_clipped: bool        # any sample >= 0.99 of max


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------

def list_microphones() -> list[AudioDevice]:
    """Return all input-capable audio devices."""
    if not _SD_AVAILABLE:
        return []
    devices  = sd.query_devices()
    defaults = sd.default.device
    default_in = defaults[0] if isinstance(defaults, (list, tuple)) else defaults
    result = []
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            result.append(AudioDevice(
                index       = i,
                name        = dev["name"],
                device_type = "input",
                channels    = dev["max_input_channels"],
                sample_rate = dev["default_samplerate"],
                is_default  = (i == default_in),
            ))
    return result


def list_speakers() -> list[AudioDevice]:
    """Return all output-capable audio devices."""
    if not _SD_AVAILABLE:
        return []
    devices  = sd.query_devices()
    defaults = sd.default.device
    default_out = defaults[1] if isinstance(defaults, (list, tuple)) else defaults
    result = []
    for i, dev in enumerate(devices):
        if dev["max_output_channels"] > 0:
            result.append(AudioDevice(
                index       = i,
                name        = dev["name"],
                device_type = "output",
                channels    = dev["max_output_channels"],
                sample_rate = dev["default_samplerate"],
                is_default  = (i == default_out),
            ))
    return result


def get_device_info(index: int) -> Optional[dict]:
    if not _SD_AVAILABLE:
        return None
    try:
        return dict(sd.query_devices(index))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Voice Activity Detection
# ---------------------------------------------------------------------------

class EnergyVAD:
    """
    Simple energy-based Voice Activity Detection.

    Uses a rolling dBFS window. Speech is detected when energy exceeds
    silence_db. Silence is confirmed after silence_duration consecutive
    seconds below the threshold.

    This is deliberately simple — no WebRTC VAD dependency.
    For higher accuracy, replace with webrtcvad or silero-vad.
    """

    def __init__(
        self,
        silence_db:       float = -40.0,
        silence_duration: float = 1.5,
        sample_rate:      int   = 16000,
    ) -> None:
        self.silence_db       = silence_db
        self.silence_duration = silence_duration
        self.sample_rate      = sample_rate
        self._silence_samples = int(silence_duration * sample_rate)
        self._consecutive_silence = 0
        self._speech_detected = False

    def process(self, chunk: "np.ndarray") -> tuple[bool, bool]:
        """
        Process one audio chunk.

        Returns:
            (is_speech, end_of_utterance)
            end_of_utterance is True when silence follows speech.
        """
        if not _SD_AVAILABLE:
            return False, False

        # RMS energy → dBFS
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
        if rms < 1e-9:
            db = -96.0
        else:
            db = 20 * np.log10(rms / 32768.0)   # relative to 16-bit max

        is_speech = db > self.silence_db

        if is_speech:
            self._speech_detected = True
            self._consecutive_silence = 0
            return True, False
        else:
            self._consecutive_silence += len(chunk)
            end = (
                self._speech_detected and
                self._consecutive_silence >= self._silence_samples
            )
            if end:
                self._speech_detected = False
                self._consecutive_silence = 0
            return False, end

    def reset(self) -> None:
        self._consecutive_silence = 0
        self._speech_detected = False


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record_until_silence(
    mic_index:        Optional[int]  = None,
    sample_rate:      int   = 16000,
    silence_db:       float = -40.0,
    silence_duration: float = 1.5,
    max_duration:     float = 30.0,
    stop_event:       Optional[threading.Event] = None,
) -> RecordingResult:
    """
    Record from microphone until silence is detected.

    Blocking call — run via asyncio.to_thread() in async code.

    Args:
        mic_index:        sounddevice device index, None = system default
        sample_rate:      Hz (16000 matches Whisper's native rate)
        silence_db:       dBFS below which = silence
        silence_duration: seconds of consecutive silence to end recording
        max_duration:     hard cutoff
        stop_event:       set this to abort recording early (push-to-talk release)

    Returns:
        RecordingResult with WAV bytes
    """
    if not _SD_AVAILABLE:
        raise AudioNotAvailable("sounddevice not installed")

    CHUNK    = int(sample_rate * 0.03)   # 30ms chunks
    vad      = EnergyVAD(silence_db, silence_duration, sample_rate)
    buf:     list[bytes] = []
    q:       queue.Queue = queue.Queue()
    done_ev              = threading.Event()
    peak     = 0.0
    clipped  = False
    t_start  = time.monotonic()

    def callback(indata, frames, time_info, status):
        nonlocal peak, clipped
        if status:
            logger.debug("Audio callback status: %s", status)
        chunk = indata[:, 0]                        # mono
        peak  = max(peak, float(np.abs(chunk).max()))
        if peak >= 0.99:
            clipped = True
        pcm16 = (chunk * 32767).astype(np.int16)
        q.put(pcm16.tobytes())
        _, end_of_utterance = vad.process(pcm16)
        if end_of_utterance:
            done_ev.set()

    device_kwargs = {} if mic_index is None else {"device": mic_index}

    with sd.InputStream(
        samplerate = sample_rate,
        channels   = 1,
        dtype      = "float32",
        blocksize  = CHUNK,
        callback   = callback,
        **device_kwargs,
    ):
        while not done_ev.is_set():
            if stop_event and stop_event.is_set():
                break
            if (time.monotonic() - t_start) >= max_duration:
                break
            time.sleep(0.01)

    # Drain queue
    chunks = []
    while not q.empty():
        try:
            chunks.append(q.get_nowait())
        except queue.Empty:
            break
    buf = b"".join(chunks)

    duration_s = time.monotonic() - t_start
    peak_db    = 20 * np.log10(peak + 1e-9)

    # Wrap in WAV container
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(buf)
    wav_bytes = wav_buf.getvalue()

    return RecordingResult(
        audio_bytes = wav_bytes,
        duration_s  = duration_s,
        sample_rate = sample_rate,
        channels    = 1,
        peak_db     = peak_db,
        was_clipped = clipped,
    )


async def record_until_silence_async(
    mic_index:        Optional[int]  = None,
    sample_rate:      int   = 16000,
    silence_db:       float = -40.0,
    silence_duration: float = 1.5,
    max_duration:     float = 30.0,
    stop_event:       Optional[threading.Event] = None,
) -> RecordingResult:
    """Async wrapper for record_until_silence."""
    return await asyncio.to_thread(
        record_until_silence,
        mic_index, sample_rate, silence_db, silence_duration, max_duration, stop_event,
    )


def record_push_to_talk(
    stop_event:   threading.Event,
    mic_index:    Optional[int] = None,
    sample_rate:  int  = 16000,
    max_duration: float = 30.0,
) -> RecordingResult:
    """Record while stop_event is NOT set (button held). Stop on release."""
    return record_until_silence(
        mic_index        = mic_index,
        sample_rate      = sample_rate,
        silence_db       = 0.0,           # don't use silence detection for PTT
        silence_duration = 9999,          # PTT: only stop_event stops recording
        max_duration     = max_duration,
        stop_event       = stop_event,
    )


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

def play_wav_bytes(
    wav_bytes:      bytes,
    speaker_index:  Optional[int]          = None,
    stop_event:     Optional[threading.Event] = None,
) -> None:
    """
    Play WAV bytes through the specified speaker.

    Blocking. Checks stop_event every 50ms for interrupt support.
    Run via asyncio.to_thread() in async code.
    """
    if not _SD_AVAILABLE:
        raise AudioNotAvailable("sounddevice not installed")

    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        sample_rate = wf.getframerate()
        channels    = wf.getnchannels()
        sampwidth   = wf.getsampwidth()
        raw         = wf.readframes(wf.getnframes())

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels)

    device_kwargs = {} if speaker_index is None else {"device": speaker_index}

    # Play in chunks to support mid-playback interruption
    CHUNK_FRAMES = sample_rate // 10   # 100ms chunks
    pos = 0
    while pos < len(audio):
        if stop_event and stop_event.is_set():
            logger.debug("Playback interrupted by stop_event")
            break
        chunk = audio[pos:pos + CHUNK_FRAMES]
        sd.play(chunk, samplerate=sample_rate, blocking=True, **device_kwargs)
        pos += CHUNK_FRAMES


async def play_wav_bytes_async(
    wav_bytes:      bytes,
    speaker_index:  Optional[int]          = None,
    stop_event:     Optional[threading.Event] = None,
) -> None:
    """Async wrapper for play_wav_bytes."""
    await asyncio.to_thread(play_wav_bytes, wav_bytes, speaker_index, stop_event)


def play_tone(
    frequency:    float = 880.0,
    duration_s:   float = 0.15,
    volume:       float = 0.3,
    speaker_index: Optional[int] = None,
) -> None:
    """
    Play a short beep to signal wake word detection or end of speech.
    frequency: 880 Hz = wake-up tone, 440 Hz = end-of-utterance.
    """
    if not _SD_AVAILABLE:
        return
    sr      = 44100
    t       = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    # Gentle fade in/out to avoid clicks
    fade    = np.minimum(1.0, np.minimum(t / 0.01, (duration_s - t) / 0.01))
    samples = (np.sin(2 * np.pi * frequency * t) * volume * fade).astype(np.float32)
    device_kwargs = {} if speaker_index is None else {"device": speaker_index}
    sd.play(samples, samplerate=sr, blocking=True, **device_kwargs)


async def play_tone_async(
    frequency:    float = 880.0,
    duration_s:   float = 0.15,
    volume:       float = 0.3,
    speaker_index: Optional[int] = None,
) -> None:
    await asyncio.to_thread(play_tone, frequency, duration_s, volume, speaker_index)


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------

def audio_available() -> bool:
    return _SD_AVAILABLE


def audio_status() -> dict:
    if not _SD_AVAILABLE:
        return {"available": False, "reason": "sounddevice not installed"}
    try:
        mics     = list_microphones()
        speakers = list_speakers()
        return {
            "available":      True,
            "microphones":    len(mics),
            "speakers":       len(speakers),
            "default_mic":    next((m.name for m in mics if m.is_default), None),
            "default_speaker": next((s.name for s in speakers if s.is_default), None),
        }
    except Exception as e:
        return {"available": False, "reason": str(e)}
