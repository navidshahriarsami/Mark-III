"""
MARK III — Wake Word Detector (Phase 11)

Listens to a continuous audio stream and fires a callback when the wake word
is detected. Two engines supported:

  OpenWakeWord (primary, free, local)
    pip install openwakeword
    Models: "hey_jarvis", "alexa", or custom .tflite/.onnx models.
    We use "hey_jarvis" as a proxy until a "hey mark" model is trained,
    or load a custom model from config.

  Porcupine (fallback, requires Picovoice access key)
    pip install pvporcupine
    Supports custom wake words (.ppn files) including "hey MARK".

Graceful degradation:
  If neither engine is installed, wake word detection is disabled.
  The voice pipeline falls back to push-to-talk mode only.

Usage:
  detector = WakeWordDetector.create()
  async for event in detector.stream(mic_index=0):
      # event fired when wake word heard
      print("Wake word detected!")
      break

The detector does NOT record audio for STT — it only signals the wake event.
The audio manager handles subsequent recording.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional

logger = logging.getLogger("markiii.voice.wakeword")

# ---------------------------------------------------------------------------
# Optional dependency guards
# ---------------------------------------------------------------------------

try:
    import openwakeword
    from openwakeword.model import Model as OWWModel
    _OWW_AVAILABLE = True
except ImportError:
    _OWW_AVAILABLE = False
    logger.info("openwakeword not installed. Install: pip install openwakeword")

try:
    import pvporcupine
    _PORCUPINE_AVAILABLE = True
except ImportError:
    _PORCUPINE_AVAILABLE = False
    logger.info("pvporcupine not installed. Install: pip install pvporcupine")

try:
    import numpy as np
    import sounddevice as sd
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False


# ---------------------------------------------------------------------------
# Event type
# ---------------------------------------------------------------------------

@dataclass
class WakeEvent:
    engine:      str          # openwakeword | porcupine
    keyword:     str          # which wake word matched
    confidence:  float        # 0.0–1.0
    ts:          float        # unix timestamp


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseWakeWordDetector:
    """All wake word detectors implement this interface."""

    name: str = "base"

    def is_available(self) -> bool:
        return False

    async def stream(
        self,
        mic_index:      Optional[int]  = None,
        sample_rate:    int   = 16000,
        stop_event:     Optional[asyncio.Event] = None,
        confidence_threshold: float = 0.5,
    ) -> AsyncIterator[WakeEvent]:
        """Yield WakeEvents continuously until stop_event is set."""
        if False:
            yield  # make this an async generator

    def status(self) -> dict:
        return {"engine": self.name, "available": self.is_available()}


# ---------------------------------------------------------------------------
# OpenWakeWord engine
# ---------------------------------------------------------------------------

class OpenWakeWordDetector(BaseWakeWordDetector):
    """
    Uses the openwakeword library for local wake word detection.

    Default model "hey_jarvis" is a stand-in. For production, train or
    obtain a "hey_mark" model and set it via config.
    """

    name = "openwakeword"

    # openwakeword inference frame size: 80ms @ 16kHz = 1280 samples
    FRAME_SAMPLES = 1280
    SAMPLE_RATE   = 16000

    def __init__(self, model_path: Optional[str] = None) -> None:
        self._model_path = model_path   # path to .tflite or .onnx, None = bundled
        self._model: Optional[OWWModel] = None

    def is_available(self) -> bool:
        return _OWW_AVAILABLE and _SD_AVAILABLE

    def _load(self) -> OWWModel:
        if self._model is None:
            kwargs = {}
            if self._model_path:
                kwargs["wakeword_models"] = [self._model_path]
            else:
                # Download bundled models on first use
                openwakeword.utils.download_models()
                kwargs["wakeword_models"] = ["hey_jarvis"]
            self._model = OWWModel(**kwargs)
        return self._model

    async def stream(
        self,
        mic_index:           Optional[int]  = None,
        sample_rate:         int   = SAMPLE_RATE,
        stop_event:          Optional[asyncio.Event] = None,
        confidence_threshold: float = 0.5,
    ) -> AsyncIterator[WakeEvent]:
        if not self.is_available():
            logger.warning("OpenWakeWord not available")
            return

        event_q: asyncio.Queue = asyncio.Queue()
        loop     = asyncio.get_event_loop()
        model    = await asyncio.to_thread(self._load)
        chunk_q: queue.Queue = queue.Queue()

        def audio_callback(indata, frames, time_info, status):
            chunk_q.put(indata[:, 0].copy())

        def detection_thread():
            device_kw = {} if mic_index is None else {"device": mic_index}
            with sd.InputStream(
                samplerate = self.SAMPLE_RATE,
                channels   = 1,
                dtype      = "float32",
                blocksize  = self.FRAME_SAMPLES,
                callback   = audio_callback,
                **device_kw,
            ):
                logger.info("OpenWakeWord listening (frame=%d samples)", self.FRAME_SAMPLES)
                while not (stop_event and stop_event.is_set()):
                    try:
                        chunk = chunk_q.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    # oww expects int16
                    pcm16 = (chunk * 32767).astype(np.int16)
                    scores = model.predict(pcm16)

                    for keyword, score in scores.items():
                        if score >= confidence_threshold:
                            ev = WakeEvent(
                                engine     = "openwakeword",
                                keyword    = keyword,
                                confidence = float(score),
                                ts         = time.time(),
                            )
                            loop.call_soon_threadsafe(event_q.put_nowait, ev)

        thread = threading.Thread(target=detection_thread, daemon=True)
        thread.start()

        try:
            while not (stop_event and stop_event.is_set()):
                try:
                    ev = await asyncio.wait_for(event_q.get(), timeout=0.5)
                    yield ev
                except asyncio.TimeoutError:
                    continue
        finally:
            thread.join(timeout=2.0)

    def status(self) -> dict:
        return {
            "engine":    self.name,
            "available": self.is_available(),
            "model":     self._model_path or "bundled:hey_jarvis",
        }


# ---------------------------------------------------------------------------
# Porcupine engine
# ---------------------------------------------------------------------------

class PorcupineDetector(BaseWakeWordDetector):
    """
    Uses Picovoice Porcupine for high-accuracy wake word detection.
    Requires an access key from console.picovoice.ai (free tier available).
    Supports custom .ppn keyword files (e.g. trained "MARK" or "hey MARK").
    """

    name = "porcupine"
    SAMPLE_RATE  = 16000

    def __init__(
        self,
        access_key:   str,
        keyword_path: Optional[str] = None,
        sensitivity:  float = 0.5,
    ) -> None:
        self._access_key  = access_key
        self._keyword_path = keyword_path
        self._sensitivity  = sensitivity

    def is_available(self) -> bool:
        return _PORCUPINE_AVAILABLE and _SD_AVAILABLE and bool(self._access_key)

    async def stream(
        self,
        mic_index:           Optional[int]  = None,
        sample_rate:         int   = SAMPLE_RATE,
        stop_event:          Optional[asyncio.Event] = None,
        confidence_threshold: float = 0.5,
    ) -> AsyncIterator[WakeEvent]:
        if not self.is_available():
            logger.warning("Porcupine not available (missing key or library)")
            return

        event_q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def run_porcupine():
            kw_kwargs = {}
            if self._keyword_path:
                kw_kwargs["keyword_paths"]  = [self._keyword_path]
                kw_kwargs["sensitivities"]  = [self._sensitivity]
            else:
                kw_kwargs["keywords"]       = ["jarvis"]   # built-in proxy
                kw_kwargs["sensitivities"]  = [self._sensitivity]

            handle = pvporcupine.create(
                access_key = self._access_key,
                **kw_kwargs,
            )
            frame_len   = handle.frame_length
            chunk_q: queue.Queue = queue.Queue()

            def audio_cb(indata, frames, time_info, status):
                chunk_q.put(indata[:, 0].copy())

            device_kw = {} if mic_index is None else {"device": mic_index}
            with sd.InputStream(
                samplerate = handle.sample_rate,
                channels   = 1,
                dtype      = "float32",
                blocksize  = frame_len,
                callback   = audio_cb,
                **device_kw,
            ):
                logger.info("Porcupine listening (frame=%d samples)", frame_len)
                try:
                    while not (stop_event and stop_event.is_set()):
                        try:
                            chunk = chunk_q.get(timeout=0.1)
                        except queue.Empty:
                            continue
                        pcm16 = (chunk * 32767).astype(np.int16)[:frame_len]
                        result = handle.process(pcm16)
                        if result >= 0:
                            kw = (
                                self._keyword_path.split("/")[-1].replace(".ppn", "")
                                if self._keyword_path else "jarvis"
                            )
                            ev = WakeEvent(
                                engine     = "porcupine",
                                keyword    = kw,
                                confidence = self._sensitivity,
                                ts         = time.time(),
                            )
                            loop.call_soon_threadsafe(event_q.put_nowait, ev)
                finally:
                    handle.delete()

        thread = threading.Thread(target=run_porcupine, daemon=True)
        thread.start()

        try:
            while not (stop_event and stop_event.is_set()):
                try:
                    ev = await asyncio.wait_for(event_q.get(), timeout=0.5)
                    yield ev
                except asyncio.TimeoutError:
                    continue
        finally:
            thread.join(timeout=2.0)

    def status(self) -> dict:
        return {
            "engine":       self.name,
            "available":    self.is_available(),
            "keyword_path": self._keyword_path or "built-in:jarvis",
            "sensitivity":  self._sensitivity,
        }


# ---------------------------------------------------------------------------
# Null detector (graceful degradation)
# ---------------------------------------------------------------------------

class NullWakeWordDetector(BaseWakeWordDetector):
    """Returned when no wake word engine is available. Logs a clear message."""

    name = "none"

    def is_available(self) -> bool:
        return False

    async def stream(self, **kwargs) -> AsyncIterator[WakeEvent]:
        logger.warning(
            "No wake word engine available. "
            "Install openwakeword (pip install openwakeword) or "
            "pvporcupine (pip install pvporcupine) to enable always-listening mode."
        )
        if False:
            yield  # make async generator


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_detector(
    engine:           str             = "openwakeword",
    model_path:       Optional[str]   = None,
    porcupine_key:    str             = "",
    keyword_path:     Optional[str]   = None,
) -> BaseWakeWordDetector:
    """
    Create the best available detector based on config.

    Falls back gracefully:
      openwakeword requested → try OWW → try Porcupine → Null
      porcupine requested    → try Porcupine → try OWW → Null
    """
    if engine == "openwakeword":
        if _OWW_AVAILABLE and _SD_AVAILABLE:
            return OpenWakeWordDetector(model_path)
        logger.warning("openwakeword not available, trying porcupine")
        if _PORCUPINE_AVAILABLE and _SD_AVAILABLE and porcupine_key:
            return PorcupineDetector(porcupine_key, keyword_path)
    elif engine == "porcupine":
        if _PORCUPINE_AVAILABLE and _SD_AVAILABLE and porcupine_key:
            return PorcupineDetector(porcupine_key, keyword_path)
        logger.warning("porcupine not available (check key), trying openwakeword")
        if _OWW_AVAILABLE and _SD_AVAILABLE:
            return OpenWakeWordDetector(model_path)

    return NullWakeWordDetector()


def detector_status() -> dict:
    return {
        "openwakeword": {"installed": _OWW_AVAILABLE},
        "porcupine":    {"installed": _PORCUPINE_AVAILABLE},
        "sounddevice":  {"installed": _SD_AVAILABLE},
    }
