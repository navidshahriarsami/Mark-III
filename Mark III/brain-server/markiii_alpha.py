"""
MARK III — Alpha Mode
Phase 13.5: Bring MARK III to life.

Voice pipeline:
  PTT:       Ctrl+Alt+Space  (hold = speak, release = process)
  Wake word: "hey mycroft"   (openwakeword built-in; custom MARK model = future)
  STT:       faster-whisper base  (~150MB download on first run)
  LLM:       Cognitive Council  (OpenRouter free tier — no paid key needed)
  TTS:       pyttsx3 / Windows SAPI  (built-in voices)

Usage:
  python markiii_alpha.py              -- PTT + wake word
  python markiii_alpha.py --ptt-only   -- PTT only (skip wake word)
  python markiii_alpha.py --voice en   -- force English STT

Controls (while running):
  Ctrl+Alt+Space   Push-to-Talk (hold to speak, release to process)
  Ctrl+C           Exit
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import queue
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────────
# Bootstrap
# ─────────────────────────────────────────────────────────────────

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Brain-server root on sys.path
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

os.environ.setdefault(
    "OPENROUTER_API_KEY",
    "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",
)
os.environ.setdefault("VOICE_ENABLED", "true")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("markiii.alpha")

# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────

MIC_INDEX      = 1      # Microphone (K66)  — detected earlier
SPEAKER_INDEX  = 4      # Speakers (Realtek)
SAMPLE_RATE    = 16000
WHISPER_SIZE   = "base" # base ≈ 2s/10s audio on CPU; good accuracy
WHISPER_DEVICE = "cpu"
SILENCE_DB     = -38.0  # dBFS threshold for silence detection
SILENCE_DUR    = 1.2    # seconds of silence to end utterance
MAX_RECORD_S   = 30.0

PTT_COMBO      = frozenset([
    "ctrl",
    "alt",
    "<96>",  # Space bar
])

SAPI_VOICE_IDX = 2      # 0=David 1=Hazel 2=Zira

CONTEXT_HINT   = (
    "You are MARK III — a personal AI operating system running on the user's Windows desktop. "
    "You respond via voice so be concise and natural. 2–4 sentences max unless a detailed "
    "answer is clearly needed. Today is 2026-06-21."
)

# ─────────────────────────────────────────────────────────────────
# Imports — hardware
# ─────────────────────────────────────────────────────────────────

try:
    import sounddevice as sd
    import numpy as np
    _AUDIO_OK = True
except ImportError:
    _AUDIO_OK = False
    print("[FATAL] sounddevice not installed. Run: pip install sounddevice numpy")
    sys.exit(1)

try:
    from faster_whisper import WhisperModel
    _STT_OK = True
except ImportError:
    _STT_OK = False
    print("[FATAL] faster-whisper not installed. Run: pip install faster-whisper")
    sys.exit(1)

try:
    import pyttsx3
    _TTS_OK = True
except ImportError:
    _TTS_OK = False
    print("[WARN] pyttsx3 not installed — TTS disabled. MARK will reply in text only.")

try:
    from pynput import keyboard as pynput_kb
    _PTT_OK = True
except ImportError:
    _PTT_OK = False
    print("[FATAL] pynput not installed. Run: pip install pynput")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────
# Council import
# ─────────────────────────────────────────────────────────────────

try:
    from app.services.council.council_manager import get_council
    _COUNCIL_OK = True
except Exception as e:
    _COUNCIL_OK = False
    print(f"[WARN] Council unavailable ({e}) — will use fallback response")


# ─────────────────────────────────────────────────────────────────
# Shared state
# ─────────────────────────────────────────────────────────────────

class AlphaState:
    def __init__(self) -> None:
        self.running      = True
        self.recording    = threading.Event()   # set while PTT held
        self.stop_record  = threading.Event()   # set to end recording
        self.processing   = threading.Event()   # set while council thinking
        self.speaking     = threading.Event()   # set while TTS playing

        self.work_queue: queue.Queue[bytes] = queue.Queue(maxsize=1)
        self.utterance_count = 0
        self.latencies: list[dict] = []

        # Press tracking for PTT combo
        self._pressed: set[str] = set()
        self._ptt_active = False

    def record_latency(self, label: str, ms: float) -> None:
        self.latencies.append({"label": label, "ms": round(ms, 1)})


STATE = AlphaState()


# ─────────────────────────────────────────────────────────────────
# TTS — Windows SAPI via pyttsx3 (dedicated thread)
# SAPI is COM-based; must init and run in the same thread.
# ─────────────────────────────────────────────────────────────────

_tts_q:     queue.Queue = queue.Queue()
_tts_ready  = threading.Event()

def _tts_worker() -> None:
    """Dedicated TTS thread — owns the pyttsx3 engine for its lifetime."""
    if not _TTS_OK:
        _tts_ready.set()
        return
    try:
        import pyttsx3 as _p3
        engine = _p3.init()
        voices = engine.getProperty("voices")
        if voices and SAPI_VOICE_IDX < len(voices):
            engine.setProperty("voice", voices[SAPI_VOICE_IDX].id)
        engine.setProperty("rate",   165)
        engine.setProperty("volume", 0.95)
        log.info("TTS thread ready: %d voices", len(voices))
    except Exception as e:
        log.error("TTS init failed: %s", e)
        engine = None
    _tts_ready.set()

    while STATE.running or not _tts_q.empty():
        try:
            text = _tts_q.get(timeout=0.4)
        except queue.Empty:
            continue
        if text is None:
            break
        STATE.speaking.set()
        try:
            if engine:
                engine.say(text)
                engine.runAndWait()
            else:
                print(f"\n  MARK: {text}\n")
        except Exception as e:
            log.error("TTS speak error: %s", e)
            print(f"\n  MARK: {text}\n")
        finally:
            STATE.speaking.clear()


def _init_tts() -> None:
    t = threading.Thread(target=_tts_worker, daemon=True, name="tts-worker")
    t.start()
    _tts_ready.wait(timeout=10)


def speak(text: str) -> None:
    """Queue text for TTS. Returns immediately."""
    _tts_q.put(text)


def speak_sync(text: str) -> None:
    """Queue text and block until the queue drains."""
    _tts_q.put(text)
    while not _tts_q.empty() or STATE.speaking.is_set():
        time.sleep(0.05)


def speak_async(text: str) -> None:
    """Fire-and-forget: just queue the text."""
    _tts_q.put(text)


# ─────────────────────────────────────────────────────────────────
# STT — faster-whisper
# ─────────────────────────────────────────────────────────────────

_whisper:     Optional[WhisperModel] = None
_whisper_lock = threading.Lock()

def _init_whisper() -> None:
    global _whisper
    print("  Loading Whisper model (base) — first run downloads ~150MB ...")
    t0 = time.monotonic()
    with _whisper_lock:
        _whisper = WhisperModel(WHISPER_SIZE, device=WHISPER_DEVICE, compute_type="int8")
    print(f"  Whisper ready ({(time.monotonic()-t0):.1f}s)")


def transcribe(wav_bytes: bytes, language: Optional[str] = None) -> str:
    """Transcribe WAV bytes. Returns cleaned text string."""
    if not _whisper:
        return ""
    import tempfile
    t0 = time.monotonic()
    with _whisper_lock:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp = f.name
        segments, info = _whisper.transcribe(
            tmp,
            language    = language,
            vad_filter  = True,
            beam_size   = 3,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
    ms = (time.monotonic() - t0) * 1000
    STATE.record_latency("stt", ms)
    log.info("STT %dms: %r", ms, text[:60])
    try:
        os.unlink(tmp)
    except OSError:
        pass
    return text


# ─────────────────────────────────────────────────────────────────
# Recording — sounddevice
# ─────────────────────────────────────────────────────────────────

def record_ptt(stop_ev: threading.Event) -> bytes:
    """Record from mic until stop_ev is set. Returns WAV bytes."""
    chunks: list[bytes] = []
    q: queue.Queue = queue.Queue()
    t0 = time.monotonic()

    def callback(indata, frames, time_info, status):
        mono = indata[:, 0]
        pcm  = (mono * 32767).astype(np.int16)
        q.put(pcm.tobytes())

    with sd.InputStream(
        samplerate = SAMPLE_RATE,
        channels   = 1,
        dtype      = "float32",
        blocksize  = int(SAMPLE_RATE * 0.03),
        device     = MIC_INDEX,
        callback   = callback,
    ):
        while not stop_ev.is_set():
            if (time.monotonic() - t0) >= MAX_RECORD_S:
                break
            time.sleep(0.02)

    while not q.empty():
        chunks.append(q.get_nowait())

    raw = b"".join(chunks)
    ms  = (time.monotonic() - t0) * 1000
    STATE.record_latency("record", ms)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(raw)
    return buf.getvalue()


def record_until_silence() -> bytes:
    """Record from mic until silence detected. Returns WAV bytes."""
    chunks: list[bytes] = []
    q: queue.Queue = queue.Queue()
    done_ev   = threading.Event()
    t0        = time.monotonic()

    silence_samples = int(SILENCE_DUR * SAMPLE_RATE)
    consec_silence  = [0]
    speech_started  = [False]

    def callback(indata, frames, time_info, status):
        mono = indata[:, 0]
        pcm  = (mono * 32767).astype(np.int16)
        q.put(pcm.tobytes())

        rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2)))
        db  = 20 * np.log10(rms + 1e-9)
        if db > SILENCE_DB:
            speech_started[0] = True
            consec_silence[0] = 0
        else:
            consec_silence[0] += len(pcm)
            if speech_started[0] and consec_silence[0] >= silence_samples:
                done_ev.set()

    with sd.InputStream(
        samplerate = SAMPLE_RATE,
        channels   = 1,
        dtype      = "float32",
        blocksize  = int(SAMPLE_RATE * 0.03),
        device     = MIC_INDEX,
        callback   = callback,
    ):
        done_ev.wait(timeout=MAX_RECORD_S)

    while not q.empty():
        chunks.append(q.get_nowait())

    raw = b"".join(chunks)
    ms  = (time.monotonic() - t0) * 1000
    STATE.record_latency("record", ms)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(raw)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────
# Council — async query
# ─────────────────────────────────────────────────────────────────

_council_loop: Optional[asyncio.AbstractEventLoop] = None


def _council_thread_main() -> None:
    """Dedicated thread running the asyncio event loop for council calls."""
    global _council_loop
    _council_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_council_loop)
    _council_loop.run_forever()


def query_council(text: str) -> str:
    """Query the Cognitive Council. Runs in the council thread's event loop."""
    if not _COUNCIL_OK or not _council_loop:
        return f"I heard you say: {text}. Council is offline — check your API key."

    t0 = time.monotonic()

    async def _consult() -> str:
        council = get_council()
        session = await council.consult(
            query        = text,
            context_hint = CONTEXT_HINT,
            device_id    = "alpha",
        )
        return session.final_answer

    future = asyncio.run_coroutine_threadsafe(_consult(), _council_loop)
    try:
        answer = future.result(timeout=180)
    except Exception as e:
        log.error("Council error: %s", e)
        answer = "I encountered an error reaching the council. Please try again."

    ms = (time.monotonic() - t0) * 1000
    STATE.record_latency("council", ms)
    return answer


# ─────────────────────────────────────────────────────────────────
# Worker — STT → Council → TTS
# ─────────────────────────────────────────────────────────────────

def worker_loop() -> None:
    """Runs in a dedicated thread. Processes audio from work_queue."""
    while STATE.running:
        try:
            wav_bytes = STATE.work_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        STATE.processing.set()
        try:
            # 1. STT
            t_stt = time.monotonic()
            text  = transcribe(wav_bytes)
            if not text or len(text.strip()) < 2:
                _beep(440, 0.1)  # low beep = nothing heard
                continue

            print(f"\n  YOU  : {text}")

            # 2. Council
            answer = query_council(text)
            print(f"  MARK : {answer}\n")

            # 3. TTS — queue and wait for playback to finish
            _beep(660, 0.08)
            speak(answer)
            while STATE.speaking.is_set() or not _tts_q.empty():
                time.sleep(0.05)

            STATE.utterance_count += 1
        except Exception as e:
            log.error("Worker error: %s", e)
        finally:
            STATE.processing.clear()


# ─────────────────────────────────────────────────────────────────
# Audio feedback
# ─────────────────────────────────────────────────────────────────

def _beep(freq: float = 880.0, dur: float = 0.12) -> None:
    """Short audio cue via sounddevice."""
    try:
        sr  = 22050
        t   = np.linspace(0, dur, int(sr * dur), endpoint=False)
        env = np.minimum(1.0, np.minimum(t / 0.01, (dur - t) / 0.01))
        sig = (np.sin(2 * np.pi * freq * t) * 0.25 * env).astype(np.float32)
        sd.play(sig, samplerate=sr, device=SPEAKER_INDEX, blocking=False)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────
# PTT — Ctrl+Alt+Space
# ─────────────────────────────────────────────────────────────────

_ptt_stop_ev:     Optional[threading.Event]  = None
_ptt_record_thread: Optional[threading.Thread] = None


def _key_name(key) -> str:
    """Normalize a pynput Key or KeyCode to a short string."""
    if hasattr(key, "char") and key.char:
        return key.char.lower()
    name = str(key).lower().replace("key.", "")
    return name


def _is_ptt_combo() -> bool:
    p = STATE._pressed
    return (
        ("ctrl_l" in p or "ctrl_r" in p or "ctrl" in p) and
        ("alt_l"  in p or "alt_r"  in p or "alt"  in p) and
        ("space"  in p)
    )


def _ptt_start() -> None:
    global _ptt_stop_ev, _ptt_record_thread
    if STATE._ptt_active or STATE.processing.is_set():
        return
    if STATE.work_queue.full():
        return

    STATE._ptt_active = True
    _ptt_stop_ev = threading.Event()

    _beep(880, 0.12)   # high beep = recording starts

    def _record():
        try:
            wav = record_ptt(_ptt_stop_ev)
            STATE.work_queue.put_nowait(wav)
        except queue.Full:
            pass
        except Exception as e:
            log.error("PTT record error: %s", e)

    _ptt_record_thread = threading.Thread(target=_record, daemon=True)
    _ptt_record_thread.start()
    print("  [REC]  Ctrl+Alt+Space held — speaking ...", end="", flush=True)


def _ptt_stop() -> None:
    global _ptt_stop_ev, _ptt_record_thread
    if not STATE._ptt_active:
        return
    STATE._ptt_active = False
    if _ptt_stop_ev:
        _ptt_stop_ev.set()
    print(" done.")


def on_press(key) -> None:
    name = _key_name(key)
    STATE._pressed.add(name)
    if _is_ptt_combo() and not STATE._ptt_active:
        _ptt_start()


def on_release(key) -> None:
    name = _key_name(key)
    STATE._pressed.discard(name)
    if STATE._ptt_active and not _is_ptt_combo():
        _ptt_stop()


# ─────────────────────────────────────────────────────────────────
# Wake word (openwakeword — "hey mycroft" built-in)
# ─────────────────────────────────────────────────────────────────

def _wake_word_thread() -> None:
    """Runs in background. Listens for wake word, then records utterance."""
    try:
        import openwakeword
        from openwakeword.model import Model as OWWModel
        openwakeword.utils.download_models()
        model = OWWModel(wakeword_models=["hey_mycroft"], inference_framework="onnx")
        CHUNK  = 1280   # 80ms at 16kHz
        log.info("Wake word engine ready (hey_mycroft)")
    except Exception as e:
        log.warning("Wake word engine unavailable (%s) — PTT only", e)
        return

    try:
        with sd.InputStream(
            samplerate = 16000,
            channels   = 1,
            dtype      = "int16",
            blocksize  = CHUNK,
            device     = MIC_INDEX,
        ) as stream:
            while STATE.running:
                # Always drain buffer to avoid stale audio on resume
                audio_chunk, _ = stream.read(CHUNK)

                if STATE.processing.is_set() or STATE._ptt_active:
                    continue  # skip inference; don't trigger wake word during PTT

                audio_flat = audio_chunk[:, 0]
                pred       = model.predict(audio_flat)

                score = pred.get("hey_mycroft", 0.0)
                if score > 0.5:
                    log.info("Wake word detected (hey_mycroft score=%.2f)", score)
                    print("\n  [WAKE] Hey Mycroft detected — listening ...")
                    _beep(880, 0.12)

                    if not STATE.processing.is_set() and not STATE.work_queue.full():
                        wav = record_until_silence()
                        try:
                            STATE.work_queue.put_nowait(wav)
                        except queue.Full:
                            pass

    except Exception as e:
        log.error("Wake word thread crashed: %s", e)


# ─────────────────────────────────────────────────────────────────
# Latency report
# ─────────────────────────────────────────────────────────────────

def print_latency_report() -> None:
    if not STATE.latencies:
        return
    print("\n" + "=" * 55)
    print("  MARK III — Latency Report")
    print("=" * 55)
    by_label: dict[str, list[float]] = {}
    for entry in STATE.latencies:
        by_label.setdefault(entry["label"], []).append(entry["ms"])
    for label, vals in by_label.items():
        avg = sum(vals) / len(vals)
        mx  = max(vals)
        print(f"  {label:<12} avg {avg:>7.0f}ms   max {mx:>7.0f}ms   n={len(vals)}")
    total = sum(v for vs in by_label.values() for v in vs)
    print(f"\n  {'TOTAL':<12} {total:.0f}ms cumulative across {STATE.utterance_count} utterance(s)")
    print("=" * 55 + "\n")


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def main(ptt_only: bool = False, language: Optional[str] = None) -> None:
    global _council_loop

    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║           MARK III — Alpha Mode   v0.14.0           ║")
    print("╠══════════════════════════════════════════════════════╣")
    print("║  PTT : Ctrl+Alt+Space  (hold to speak, release)     ║")
    if not ptt_only:
        print("║  Wake: 'hey mycroft'   (always listening)           ║")
    print("║  Exit: Ctrl+C                                        ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    # TTS
    print("  Initializing TTS ...")
    _init_tts()

    # Whisper
    _init_whisper()

    # Council loop thread
    ct = threading.Thread(target=_council_thread_main, daemon=True, name="council-loop")
    ct.start()
    time.sleep(0.2)  # let loop start

    # Worker thread
    wt = threading.Thread(target=worker_loop, daemon=True, name="worker")
    wt.start()

    # Wake word thread
    if not ptt_only:
        wwt = threading.Thread(target=_wake_word_thread, daemon=True, name="wake-word")
        wwt.start()

    # Keyboard listener (PTT)
    listener = pynput_kb.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    # Ready
    print()
    print("  MARK III is ready. Say something.\n")
    speak_async("MARK III online. Ready.")

    try:
        while STATE.running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        STATE.running = False
        listener.stop()
        if _council_loop:
            _council_loop.call_soon_threadsafe(_council_loop.stop)
        print_latency_report()
        print("  MARK III offline.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MARK III Alpha Mode")
    parser.add_argument("--ptt-only",  action="store_true", help="Disable wake word")
    parser.add_argument("--voice",     default=None,        help="Force STT language (e.g. 'en')")
    args = parser.parse_args()
    main(ptt_only=args.ptt_only, language=args.voice)
