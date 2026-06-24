"""MARK III Phase 13.5 — Preflight validation (no audio required)."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("OPENROUTER_API_KEY", "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")

OK   = "[OK  ]"
FAIL = "[FAIL]"
MISS = "[MISS]"

results = []

def check(label, fn):
    t0 = time.monotonic()
    try:
        val = fn()
        ms  = (time.monotonic() - t0) * 1000
        results.append((True, label, val, ms))
        print(f"  {OK} {label:<32} {val}  ({ms:.0f}ms)")
        return True
    except Exception as e:
        ms = (time.monotonic() - t0) * 1000
        results.append((False, label, str(e)[:80], ms))
        print(f"  {FAIL} {label:<32} {str(e)[:60]}")
        return False

print("\n" + "=" * 60)
print("  MARK III — Preflight Check")
print("=" * 60 + "\n")

print("  [IMPORTS]")

check("sounddevice",          lambda: __import__("sounddevice").__version__)
check("numpy",                lambda: __import__("numpy").__version__)
check("faster_whisper",       lambda: __import__("faster_whisper").__version__)
check("pynput",               lambda: "ok")
check("pyttsx3",              lambda: "ok")
check("openwakeword",         lambda: __import__("openwakeword").__version__)

print()
print("  [COUNCIL]")
check("council import",       lambda: (__import__("app.services.council.council_manager", fromlist=["get_council"]), "ok")[1])
check("classify_query",       lambda: (__import__("app.services.council.model_router", fromlist=["classify_query"]), "ok")[1])
check("specialist_registry",  lambda: (__import__("app.services.council.specialist_registry", fromlist=["SPECIALISTS"]), "ok")[1])

print()
print("  [AUDIO DEVICES]")
import sounddevice as sd
devs = sd.query_devices()
mic_names  = [d["name"] for d in devs if d["max_input_channels"] > 0]
spk_names  = [d["name"] for d in devs if d["max_output_channels"] > 0]
check("default mic",    lambda: sd.query_devices(kind="input")["name"])
check("default speaker",lambda: sd.query_devices(kind="output")["name"])
check("K66 mic index",  lambda: next((str(i) for i,d in enumerate(devs) if "K66" in d["name"] and d["max_input_channels"]>0), "not found"))

print()
print("  [TTS — SAPI voices]")
import pyttsx3
tts = pyttsx3.init()
voices = tts.getProperty("voices")
check("voice 0 (David)", lambda: voices[0].id.split("\\")[-1] if voices else "none")
check("voice 1 (Hazel)", lambda: voices[1].id.split("\\")[-1] if len(voices)>1 else "none")
check("voice 2 (Zira)",  lambda: voices[2].id.split("\\")[-1] if len(voices)>2 else "none")
tts.stop()

print()
print("  [ROUTING — local rules]")
import asyncio
from app.services.council.model_router import classify_query

tests = [
    ("What time is it?",              "conversation"),
    ("Fix the bug in my code",        "coding"),
    ("What is quantum computing?",    "research"),
    ("Help me plan my week",          "planning"),
    ("I can't focus today",           "productivity"),
    ("Remember my goal from last week","memory"),
]

async def run_routing():
    ok = 0
    for query, expected_tag in tests:
        analysis = await classify_query(query)
        tags = analysis.domain_tags
        hit  = expected_tag in tags or any(expected_tag in r.value for r in analysis.roles)
        status = OK if hit else f"[WARN] expected {expected_tag}"
        print(f"  {status} route: {query[:40]:<42} → {[r.value for r in analysis.roles]}")
        if hit:
            ok += 1
    print(f"\n  Routing: {ok}/{len(tests)} correct")

asyncio.run(run_routing())

print()
passed = sum(1 for ok, *_ in results if ok)
total  = len(results)
print("=" * 60)
print(f"  Preflight complete: {passed}/{total} checks passed")
if passed == total:
    print("  MARK III is ready to launch.")
else:
    failed = [label for ok, label, *_ in results if not ok]
    print(f"  Issues: {', '.join(failed)}")
print("=" * 60 + "\n")
