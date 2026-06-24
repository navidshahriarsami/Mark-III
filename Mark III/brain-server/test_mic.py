"""Test mic capture from K66 (device index 1) — 3 second sample."""
import sys, io, wave, time
import sounddevice as sd
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MIC_IDX = 1  # Microphone (K66)
SR      = 16000
DUR     = 3.0
CHUNK   = int(SR * 0.03)

print(f"Recording {DUR}s from mic {MIC_IDX} (K66) ...")
print("Speak or stay silent — just testing capture.")

chunks = []

def cb(indata, frames, time_info, status):
    if status:
        print(f"  Status: {status}")
    mono = indata[:, 0]
    pcm  = (mono * 32767).astype(np.int16)
    chunks.append(pcm.tobytes())
    rms  = float(np.sqrt(np.mean(mono.astype(np.float32)**2)))
    db   = 20 * np.log10(rms + 1e-9)
    bar  = "#" * max(0, int((db + 60) * 0.8))
    print(f"  {db:+6.1f} dBFS  {bar[:40]}", end="\r")

with sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                    blocksize=CHUNK, device=MIC_IDX, callback=cb):
    time.sleep(DUR)

print()
raw = b"".join(chunks)
buf = io.BytesIO()
with wave.open(buf, "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(SR)
    wf.writeframes(raw)
wav_bytes = buf.getvalue()

print(f"\n  Captured {len(wav_bytes)/1024:.1f} KB  ({DUR:.0f}s at {SR}Hz)")

# STT test
print("\n  Running Whisper 'base' on captured audio ...")
print("  (First run downloads model ~150MB from Hugging Face)\n")

t0 = time.monotonic()
from faster_whisper import WhisperModel
import tempfile, os
model = WhisperModel("base", device="cpu", compute_type="int8")
print(f"  Model loaded in {(time.monotonic()-t0):.1f}s")

with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
    f.write(wav_bytes)
    tmp = f.name

t1 = time.monotonic()
segments, info = model.transcribe(tmp, language="en", vad_filter=True, beam_size=3)
text = " ".join(s.text.strip() for s in segments).strip()
ms   = (time.monotonic() - t1) * 1000
os.unlink(tmp)

print(f"  STT latency   : {ms:.0f}ms")
print(f"  Detected lang : {info.language}")
print(f"  Transcript    : {repr(text) if text else '(silence detected)'}")
print("\n  Voice pipeline: OK" if True else "")
