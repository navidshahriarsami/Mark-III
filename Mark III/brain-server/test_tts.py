"""Test TTS and basic audio pipeline."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print("Testing MARK III TTS (Windows SAPI) ...")

import pyttsx3
engine = pyttsx3.init()
voices = engine.getProperty("voices")
print(f"  Voices available: {len(voices)}")
for i, v in enumerate(voices):
    print(f"    [{i}] {v.id.split(chr(92))[-1]}")

# Use Zira (female, index 2) — clearer for assistant
engine.setProperty("voice", voices[2].id)  # Zira
engine.setProperty("rate", 160)
engine.setProperty("volume", 0.95)

print("\n  Speaking test phrase ...")
t0 = time.monotonic()
engine.say(
    "MARK III is online and fully operational. "
    "The cognitive council is ready. "
    "Hold Control, Alt, and Space to speak."
)
engine.runAndWait()
ms = (time.monotonic() - t0) * 1000

print(f"  TTS latency: {ms:.0f}ms")
print("  Done. If you heard the phrase, TTS is working.")

import sounddevice as sd
import numpy as np
print("\n  Playing 880Hz tone (0.2s) on speaker index 4 ...")
sr  = 22050
dur = 0.2
t   = np.linspace(0, dur, int(sr * dur), endpoint=False)
env = np.minimum(1.0, np.minimum(t / 0.01, (dur - t) / 0.01))
sig = (np.sin(2 * np.pi * 880 * t) * 0.3 * env).astype(np.float32)
sd.play(sig, samplerate=sr, device=4, blocking=True)
print("  Tone done.")
