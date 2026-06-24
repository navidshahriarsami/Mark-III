"""
MARK III Phase 13.5 — Task 3: Device Registration
Register the current desktop machine as the primary MARK III device.
Saves voice_diagnostics.json with full system profile.
"""
import sys, os, json, time, io, wave, socket
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

print("\n" + "=" * 60)
print("  MARK III — Device Registration")
print("=" * 60)

# --- Collect device info ---
hostname = socket.gethostname()
device_id = f"desktop-{hostname.lower().replace(' ', '-')}"

import sounddevice as sd
devs = sd.query_devices()
def_in  = sd.query_devices(kind="input")
def_out = sd.query_devices(kind="output")

mic_index     = 1    # Microphone (K66)
speaker_index = 4    # Speakers (Realtek)

mics    = [{"index": i, "name": d["name"]} for i,d in enumerate(devs) if d["max_input_channels"] > 0]
speakers= [{"index": i, "name": d["name"]} for i,d in enumerate(devs) if d["max_output_channels"] > 0]

# --- Test recording ---
print(f"\n  Recording 2s test from mic {mic_index} (K66) ...")
import numpy as np, queue, threading

chunks = []
q      = queue.Queue()
done   = threading.Event()

def cb(indata, frames, time_info, status):
    mono = indata[:,0]
    pcm  = (mono * 32767).astype(np.int16)
    q.put(pcm.tobytes())
    rms  = float(np.sqrt(np.mean(mono.astype(np.float32)**2)))
    db   = 20 * np.log10(rms + 1e-9)
    bar  = "#" * max(0, int((db + 60) * 0.7))
    print(f"  {db:+6.1f} dBFS  {bar[:35]}", end="\r")

with sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                    blocksize=int(16000*0.03), device=mic_index, callback=cb):
    time.sleep(2.0)

while not q.empty():
    chunks.append(q.get_nowait())
raw = b"".join(chunks)
buf = io.BytesIO()
with wave.open(buf, "wb") as wf:
    wf.setnchannels(1); wf.setsampwidth(2)
    wf.setframerate(16000); wf.writeframes(raw)
wav_bytes = buf.getvalue()

print(f"\n  Recorded {len(wav_bytes)/1024:.1f} KB  OK")

# --- Test playback (880Hz tone) ---
print("  Playing 440Hz tone (0.15s) ...")
sr  = 22050
dur = 0.15
t   = np.linspace(0, dur, int(sr*dur), endpoint=False)
env = np.minimum(1.0, np.minimum(t/0.01, (dur-t)/0.01))
sig = (np.sin(2*np.pi*440*t)*0.25*env).astype(np.float32)
sd.play(sig, samplerate=sr, device=speaker_index, blocking=True)
print("  Playback OK")

# --- TTS test ---
print("  Testing TTS ...")
import pyttsx3
tts = pyttsx3.init()
voices = tts.getProperty("voices")
tts.setProperty("voice", voices[2].id)  # Zira
tts.setProperty("rate", 165)
tts.say("Device registered.")
tts.runAndWait()
print("  TTS OK")
tts.stop()

# --- Build diagnostics ---
diagnostics = {
    "registered_at":   time.strftime("%Y-%m-%dT%H:%M:%S"),
    "device_id":       device_id,
    "hostname":        hostname,
    "platform":        sys.platform,
    "device_type":     "desktop",
    "capabilities":    ["microphone", "speaker", "push_to_talk"],
    "mic_index":       mic_index,
    "mic_name":        def_in["name"],
    "speaker_index":   speaker_index,
    "speaker_name":    def_out["name"],
    "all_mics":        mics,
    "all_speakers":    speakers,
    "tts_engine":      "pyttsx3/sapi",
    "tts_voices":      [v.id.split("\\")[-1] for v in voices],
    "stt_engine":      "faster_whisper",
    "stt_model":       "base",
    "sample_rate":     16000,
    "packages": {
        "sounddevice":   "0.5.5",
        "numpy":         "2.4.6",
        "faster_whisper":"1.2.1",
        "pynput":        "installed",
        "pyttsx3":       "installed",
        "openwakeword":  "0.6.0",
    },
    "ffmpeg_path": r"C:\Users\Celluloid Solutions\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe",
    "test_recording_kb": round(len(wav_bytes)/1024, 1),
    "status":          "registered",
}

out_path = "voice_diagnostics.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(diagnostics, f, indent=2)

print(f"\n  Device ID    : {device_id}")
print(f"  Mic          : [{mic_index}] {def_in['name']}")
print(f"  Speaker      : [{speaker_index}] {def_out['name']}")
print(f"  Saved        : {out_path}")
print("\n  Registration complete.")
print("=" * 60 + "\n")
