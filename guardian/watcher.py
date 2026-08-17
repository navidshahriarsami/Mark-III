"""
Guardian Watcher — supervises the creature based on camera presence.

Runs at login (from the Startup folder). Watches for the Insta360 Link over USB
and manages Guardian's lifecycle so Guardian NEVER holds the camera across a
physical replug (which knocks the gimbal offline):

  • camera plugged in  → wait for it to finish its boot calibration (gimbal comes
                         up alive), then start Guardian
  • camera unplugged   → stop Guardian immediately, freeing the handle so the
                         gimbal re-initializes cleanly on the next replug

Result: Guardian always starts on a fresh, gimbal-alive camera. Unplug/replug the
cable anytime — the creature stops, then wakes itself back up a few seconds after
you plug it back in. No manual restart, no stuck-looking-down.

Launched silently (no console) by start_guardian.bat. It in turn launches
guardian.py silently and logs to guardian.log.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE     = Path(__file__).parent
PYTHON   = sys.executable
GUARDIAN = str(HERE / "guardian.py")
LOG      = str(HERE / "guardian.log")

VID, PID = 0x2E1A, 0x4C01          # Insta360 Link
SETTLE_S = 8                       # after detection, let the camera boot-calibrate first
POLL_S   = 3                       # how often to check camera presence
CREATE_NO_WINDOW = 0x08000000      # run child python with no console window


def camera_present() -> bool:
    """True if the Insta360 Link is enumerated on USB."""
    try:
        import libusb_package
        return libusb_package.find(idVendor=VID, idProduct=PID) is not None
    except Exception:
        # Fallback to Windows PnP query if libusb isn't available.
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-PnpDevice -PresentOnly | "
                 "Where-Object { $_.InstanceId -like '*VID_2E1A&PID_4C01*' }).Count"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            return bool(out) and int(out or "0") > 0
        except Exception:
            return False


def _running(proc) -> bool:
    return proc is not None and proc.poll() is None


def _start():
    log = open(LOG, "a", buffering=1)
    log.write(f"\n[watcher] starting Guardian at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    return subprocess.Popen(
        [PYTHON, GUARDIAN],
        stdout=log, stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )


def _stop(proc) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _dbg(msg: str) -> None:
    try:
        with open(HERE / "watcher.log", "a", buffering=1) as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def main() -> None:
    proc = None
    _dbg("watcher started")
    while True:
        present = camera_present()
        running = _running(proc)
        if present and not running:
            _dbg(f"camera present, guardian not running — settling {SETTLE_S}s")
            time.sleep(SETTLE_S)
            if camera_present():
                proc = _start()
                _dbg(f"started guardian pid={proc.pid}")
        elif not present and running:
            _dbg("camera gone — stopping guardian")
            _stop(proc)
            proc = None
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
