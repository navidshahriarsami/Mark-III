"""MARK III Phase 13.5 — Audio device discovery and system check."""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print("=" * 60)
print("  MARK III — System Validation Report")
print("=" * 60)

# --- Package checks ---
print("\n  PACKAGES:")
packages = [
    ("sounddevice",    "sounddevice"),
    ("numpy",          "numpy"),
    ("faster_whisper", "faster_whisper"),
    ("pynput",         "pynput"),
    ("pygetwindow",    "pygetwindow"),
    ("pyperclip",      "pyperclip"),
    ("plyer",          "plyer"),
    ("send2trash",     "send2trash"),
    ("pyttsx3",        "pyttsx3"),
    ("keyboard",       "keyboard"),
]

for pkg_name, import_name in packages:
    try:
        m = __import__(import_name)
        ver = getattr(m, "__version__", "ok")
        print(f"    [OK] {pkg_name:<20} {ver}")
    except ImportError as e:
        print(f"    [MISS] {pkg_name:<18} {e}")

# --- ffmpeg check ---
import subprocess, shutil
ffmpeg_path = shutil.which("ffmpeg")
print(f"\n    [{'OK' if ffmpeg_path else 'MISS'}] ffmpeg             {ffmpeg_path or 'not found in PATH'}")

# --- Audio devices ---
print("\n  AUDIO DEVICES:")
try:
    import sounddevice as sd
    devices = sd.query_devices()
    inputs  = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    outputs = [(i, d) for i, d in enumerate(devices) if d["max_output_channels"] > 0]

    print(f"  Input devices ({len(inputs)}):")
    for i, d in inputs:
        print(f"    [{i:2d}] {d['name'][:50]}")

    print(f"  Output devices ({len(outputs)}):")
    for i, d in outputs:
        print(f"    [{i:2d}] {d['name'][:50]}")

    try:
        def_in  = sd.query_devices(kind="input")
        def_out = sd.query_devices(kind="output")
        print(f"\n  Default input : [{def_in['index'] if 'index' in def_in else '?'}] {def_in['name']}")
        print(f"  Default output: [{def_out['index'] if 'index' in def_out else '?'}] {def_out['name']}")
    except Exception as e:
        print(f"  Default device query failed: {e}")

except Exception as e:
    print(f"  ERROR: {e}")

# --- TTS check (pyttsx3 / SAPI fallback) ---
print("\n  TTS (pyttsx3 / Windows SAPI):")
try:
    import pyttsx3
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    print(f"    [OK] pyttsx3 ready — {len(voices)} voice(s) available")
    for v in voices[:3]:
        print(f"         {v.id.split('\\')[-1]}")
    engine.stop()
except Exception as e:
    print(f"    [FAIL] pyttsx3: {e}")

print("\n" + "=" * 60)
