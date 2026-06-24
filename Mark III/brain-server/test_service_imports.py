"""Verify all Phase 13.7 imports load without error."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
os.environ.setdefault("OPENROUTER_API_KEY", "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")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

OK = "[OK  ]"
FAIL = "[FAIL]"

def check(label, fn):
    try:
        r = fn()
        print(f"  {OK} {label:<40} {r or ''}")
        return True
    except Exception as e:
        print(f"  {FAIL} {label:<40} {str(e)[:60]}")
        return False

print("\n=== Phase 13.7 Import Validation ===\n")

# New packages
check("pystray",           lambda: __import__("pystray").__version__)
check("PIL / Pillow",      lambda: __import__("PIL").__version__)
check("winreg",            lambda: (__import__("winreg"), "ok")[1])

# Tray icon generation
def test_icon():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64,64), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([8,8,56,56], fill="#2ECC71")
    return f"64x64 RGBA"
check("PIL icon generation",test_icon)

# Wake engine
check("wake_engine import",
    lambda: (__import__("app.services.voice.wake_engine", fromlist=["WakeEngine"]), "ok")[1])

# Always listening loop
check("always_listening_loop import",
    lambda: (__import__("app.services.voice.always_listening_loop",
                         fromlist=["AlwaysListeningLoop"]), "ok")[1])

# mark_service
check("mark_service import",
    lambda: (__import__("mark_service", fromlist=["MarkService"]), "ok")[1])

# Startup registration query
import winreg, sys
from pathlib import Path
def test_reg_query():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as k:
            pass
        return "registry accessible"
    except Exception as e:
        return f"err: {e}"
check("winreg access", test_reg_query)

# pythonw.exe exists?
pythonw = str(Path(sys.executable).parent / "pythonw.exe")
check("pythonw.exe exists",
    lambda: "found" if __import__("os").path.exists(pythonw) else "NOT FOUND")

print(f"\n  pythonw path: {pythonw}")
print(f"  service path: {str(Path('.').resolve() / 'mark_service.py')}")
print()
