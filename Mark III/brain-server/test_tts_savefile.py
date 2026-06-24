"""Test pyttsx3 save_to_file → WAV → sounddevice interruptible playback."""
import sys, os, time, io, wave, threading
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pyttsx3
import numpy as np
import sounddevice as sd

print("Testing interruptible TTS (pyttsx3 save_to_file + sounddevice)...\n")

engine = pyttsx3.init()
voices = engine.getProperty("voices")
engine.setProperty("voice", voices[2].id)   # Zira
engine.setProperty("rate", 160)
engine.setProperty("volume", 0.95)

import tempfile
with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
    path = f.name

TEXT = "MARK III is now running as an always-on service. Say MARK at any time to begin."

print(f"  Synthesizing: {repr(TEXT[:50])}")
t0 = time.monotonic()
engine.save_to_file(TEXT, path)
engine.runAndWait()
synth_ms = (time.monotonic() - t0) * 1000
print(f"  Synthesis: {synth_ms:.0f}ms")

with open(path, "rb") as f:
    wav_bytes = f.read()
os.unlink(path)
engine.stop()

print(f"  WAV bytes: {len(wav_bytes)/1024:.1f} KB")

# Now play interruptibly
interrupt_ev = threading.Event()

def _play(wav_bytes, interrupt_ev):
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        sr  = wf.getframerate()
        nc  = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if nc > 1:
        audio = audio.reshape(-1, nc)

    chunk = sr // 5  # 200ms
    pos = 0
    while pos < len(audio):
        if interrupt_ev.is_set():
            sd.stop()
            print("\n  [INTERRUPTED] mid-playback stop confirmed.")
            return True
        sd.play(audio[pos:pos+chunk], samplerate=sr, device=4, blocking=True)
        pos += chunk
    print("\n  [COMPLETE] Played to end.")
    return False

print("  Playing (will interrupt after 3s) ...")
t1 = time.monotonic()

# Auto-interrupt after 3 seconds
timer = threading.Timer(3.0, interrupt_ev.set)
timer.start()

_play(wav_bytes, interrupt_ev)
play_ms = (time.monotonic() - t1) * 1000
timer.cancel()

print(f"\n  Play duration: {play_ms:.0f}ms")
print(f"  Synthesis latency: {synth_ms:.0f}ms")
print("\n  Interruptible TTS: OK")
