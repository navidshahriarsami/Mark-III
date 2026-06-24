from __future__ import annotations

# Limit OpenBLAS / OMP threads BEFORE any numpy or CTranslate2 import.
import os as _os
_os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
_os.environ.setdefault("OMP_NUM_THREADS",      "1")
_os.environ.setdefault("MKL_NUM_THREADS",      "1")
_os.environ.setdefault("NUMEXPR_NUM_THREADS",  "1")

"""
MARK III — Always-On Service (Phase 13.7)

Entry point for the always-running MARK III assistant.

Features:
  - System tray icon (green/blue/orange/red)
  - Always listening for "MARK" wake word
  - No terminal window when launched via pythonw.exe
  - Auto-start at Windows login (HKCU Run)
  - Health monitoring + auto-restart on crash
  - Privacy modes: sleep / mute

Launch:
  pythonw.exe mark_service.py        ← no console (production)
  python mark_service.py --console   ← console visible (debug)
  python mark_service.py --install   ← register Windows startup
  python mark_service.py --uninstall ← remove Windows startup
  python mark_service.py --status    ← print startup status

On first boot MARK says:
  "MARK III online. Say 'MARK' to begin."
"""

import argparse
import logging
import os
import sys
import threading
import time
import winreg
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────────
# Bootstrap — must happen before any brain-server imports
# ─────────────────────────────────────────────────────────────────

_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

os.environ.setdefault(
    "OPENROUTER_API_KEY",
    "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",
)
os.environ.setdefault("VOICE_ENABLED", "true")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# ─────────────────────────────────────────────────────────────────
# Logging — file log when no console, stderr when console
# ─────────────────────────────────────────────────────────────────

_LOG_FILE = _HERE / "markiii_service.log"

def _setup_logging(console: bool) -> None:
    handlers = [logging.FileHandler(_LOG_FILE, encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level   = logging.INFO,
        format  = "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers = handlers,
    )

log = logging.getLogger("markiii.service")

# ─────────────────────────────────────────────────────────────────
# Windows startup registration
# ─────────────────────────────────────────────────────────────────

_STARTUP_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_NAME = "MARKIII"


def _get_pythonw() -> str:
    """Path to pythonw.exe (no console window)."""
    return str(Path(sys.executable).parent / "pythonw.exe")


def register_startup() -> str:
    """Register MARK III in HKCU Run. Returns the registered command."""
    pythonw = _get_pythonw()
    script  = str(_HERE / "mark_service.py")
    cmd     = f'"{pythonw}" "{script}"'

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, _STARTUP_NAME, 0, winreg.REG_SZ, cmd)

    return cmd


def unregister_startup() -> None:
    """Remove MARK III from HKCU Run."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _STARTUP_NAME)
    except FileNotFoundError:
        pass


def is_registered() -> bool:
    """Return True if MARK III is in HKCU Run."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_READ
        ) as key:
            winreg.QueryValueEx(key, _STARTUP_NAME)
            return True
    except FileNotFoundError:
        return False


# ─────────────────────────────────────────────────────────────────
# Tray icon — PIL circles
# ─────────────────────────────────────────────────────────────────

_COLORS = {
    "green":  "#2ECC71",
    "blue":   "#3498DB",
    "orange": "#E67E22",
    "red":    "#E74C3C",
    "yellow": "#F39C12",
}

_STATE_ICON = {
    "idle":             "green",
    "sleeping":         "yellow",
    "muted":            "yellow",
    "woken":            "blue",
    "wait_for_speech":  "blue",
    "listening":        "blue",
    "thinking":         "blue",
    "speaking":         "orange",
    "followup":         "blue",
    "stopping":         "orange",
    "offline":          "red",
}

_STATE_LABEL = {
    "idle":             "MARK III — Listening",
    "sleeping":         "MARK III — Sleeping",
    "muted":            "MARK III — Muted",
    "woken":            "MARK III — Woken",
    "wait_for_speech":  "MARK III — Waiting for speech …",
    "listening":        "MARK III — Listening to you …",
    "thinking":         "MARK III — Thinking …",
    "speaking":         "MARK III — Speaking",
    "followup":         "MARK III — Follow-up …",
    "stopping":         "MARK III — Stopping",
    "offline":          "MARK III — Offline",
}

_ICON_CACHE: dict[str, object] = {}


def _make_icon(color_name: str, size: int = 64):
    """Create a PIL Image circle icon in the given color."""
    from PIL import Image, ImageDraw
    key = (color_name, size)
    if key not in _ICON_CACHE:
        img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        m    = size // 8
        draw.ellipse([m, m, size - m, size - m], fill=_COLORS.get(color_name, "#888888"))
        _ICON_CACHE[key] = img
    return _ICON_CACHE[key]


# ─────────────────────────────────────────────────────────────────
# Mark Service
# ─────────────────────────────────────────────────────────────────

class MarkService:
    """
    Top-level service: tray icon + always-listening loop + health monitor.
    """

    def __init__(self, console: bool = False, sensitivity: float = 0.7) -> None:
        self._console     = console
        self._sensitivity = sensitivity
        self._icon        = None   # pystray.Icon
        self._loop        = None   # AlwaysListeningLoop
        self._running     = False
        self._current_state = "idle"

    # ------------------------------------------------------------------
    # Tray menu actions
    # ------------------------------------------------------------------

    def _on_pause(self, icon, item) -> None:
        if self._loop:
            self._loop.sleep()

    def _on_resume(self, icon, item) -> None:
        if self._loop:
            self._loop.wake_up()

    def _on_mute(self, icon, item) -> None:
        if self._loop:
            self._loop.toggle_mute()

    def _on_diagnostics(self, icon, item) -> None:
        if self._loop:
            info = self._loop.status_dict()
            msg = (
                f"State: {info['state']}. "
                f"Wake engine: {'ready' if info.get('wake_engine', {}).get('loaded') else 'loading'}. "
                f"STT: {'ready' if info['stt_ready'] else 'loading'}. "
                f"Council: {'online' if info['council_live'] else 'offline'}."
            )
            log.info("Diagnostics: %s", info)
            # Speak diagnostics
            if self._loop:
                threading.Thread(
                    target=self._loop._say_quick, args=(msg,), daemon=True
                ).start()

    def _on_restart(self, icon, item) -> None:
        log.info("Restart requested from tray")
        threading.Thread(target=self._do_restart, daemon=True).start()

    def _do_restart(self) -> None:
        if self._loop:
            self._loop.restart()

    def _on_exit(self, icon, item) -> None:
        log.info("Exit requested from tray")
        self._shutdown()

    # ------------------------------------------------------------------
    # State change callback (called from always_listening_loop)
    # ------------------------------------------------------------------

    def _on_state_change(self, state) -> None:
        state_val = state.value if hasattr(state, "value") else str(state)
        self._current_state = state_val
        if self._icon:
            color_name = _STATE_ICON.get(state_val, "green")
            label      = _STATE_LABEL.get(state_val, f"MARK III — {state_val}")
            try:
                self._icon.icon  = _make_icon(color_name)
                self._icon.title = label
            except Exception as e:
                log.debug("Tray update error: %s", e)

    # ------------------------------------------------------------------
    # Health monitor — restarts loop if it crashes
    # ------------------------------------------------------------------

    def _health_monitor(self) -> None:
        while self._running:
            time.sleep(30)
            if not self._running:
                break
            if self._loop and not self._loop._running:
                log.warning("Loop not running — restarting ...")
                try:
                    self._loop.start()
                except Exception as e:
                    log.error("Restart failed: %s", e)
                    self._on_state_change("offline")

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def _start_loop(self) -> None:
        # Phase 16A: start device mesh before voice loop
        try:
            from app.services.mesh.mesh_manager import get_mesh_manager
            get_mesh_manager().start()
            log.info("Mesh Manager started (port 8765)")
        except Exception as e:
            log.warning("Mesh Manager failed to start: %s", e)

        from app.services.voice.always_listening_loop import AlwaysListeningLoop
        self._loop = AlwaysListeningLoop(
            on_state_change  = self._on_state_change,
            wake_sensitivity = self._sensitivity,
        )
        self._loop.start()

    def _shutdown(self) -> None:
        self._running = False
        if self._loop:
            self._loop.stop()
        if self._icon:
            self._icon.stop()

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    def run(self) -> None:
        import pystray

        self._running = True

        # Build tray menu
        def _menu_is_sleeping(item):
            return self._loop.is_sleeping() if self._loop else False

        def _menu_is_muted(item):
            return self._loop.is_muted() if self._loop else False

        menu = pystray.Menu(
            pystray.MenuItem(
                lambda item: _STATE_LABEL.get(self._current_state, "MARK III"),
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Pause Listening",
                self._on_pause,
                checked=_menu_is_sleeping,
                enabled=lambda item: not (self._loop and self._loop.is_sleeping()),
            ),
            pystray.MenuItem(
                "Resume",
                self._on_resume,
                enabled=lambda item: bool(self._loop and self._loop.is_sleeping()),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Mute / Unmute",
                self._on_mute,
                checked=_menu_is_muted,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Diagnostics", self._on_diagnostics),
            pystray.MenuItem("Restart MARK", self._on_restart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._on_exit),
        )

        self._icon = pystray.Icon(
            name  = "MARKIII",
            icon  = _make_icon("green"),
            title = "MARK III — Starting …",
            menu  = menu,
        )

        # Start always-listening loop in background
        threading.Thread(
            target=self._start_loop, daemon=True, name="loop-start"
        ).start()

        # Start health monitor
        threading.Thread(
            target=self._health_monitor, daemon=True, name="health"
        ).start()

        # Run tray (blocks main thread — required by pystray on Windows)
        log.info("MARK III service starting (tray icon)")
        self._icon.run()
        log.info("MARK III service exited")


# ─────────────────────────────────────────────────────────────────
# CLI entry points
# ─────────────────────────────────────────────────────────────────

def _cmd_install() -> None:
    cmd = register_startup()
    print(f"[OK] MARK III registered in Windows startup.")
    print(f"     Command: {cmd}")
    print(f"     MARK will start automatically after your next login.")


def _cmd_uninstall() -> None:
    unregister_startup()
    print("[OK] MARK III removed from Windows startup.")


def _cmd_status() -> None:
    registered = is_registered()
    print(f"Windows startup: {'REGISTERED' if registered else 'not registered'}")
    print(f"Log file: {_LOG_FILE}")
    if _LOG_FILE.exists():
        lines = _LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"\nLast 10 log lines:")
        for line in lines[-10:]:
            print(f"  {line}")


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MARK III Always-On Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mark_service.py                    -- run service (console visible)
  pythonw mark_service.py                   -- run service (no console)
  python mark_service.py --install          -- register Windows startup
  python mark_service.py --uninstall        -- remove Windows startup
  python mark_service.py --status           -- show startup status + log
  python mark_service.py --sensitivity 0.9  -- more sensitive wake word
        """,
    )
    parser.add_argument("--install",     action="store_true", help="Register Windows startup")
    parser.add_argument("--uninstall",   action="store_true", help="Remove Windows startup")
    parser.add_argument("--status",      action="store_true", help="Show status and log")
    parser.add_argument("--console",     action="store_true", help="Show console output")
    parser.add_argument("--sensitivity", type=float, default=0.7,
                        help="Wake word sensitivity 0.0–1.0 (default 0.7)")
    args = parser.parse_args()

    if args.install:
        _cmd_install()
        return

    if args.uninstall:
        _cmd_uninstall()
        return

    if args.status:
        _cmd_status()
        return

    # Detect if running without console (pythonw.exe)
    is_pythonw = "pythonw" in sys.executable.lower()
    console    = args.console or (not is_pythonw)

    _setup_logging(console)

    if console:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print()
        print("╔══════════════════════════════════════════════════════╗")
        print("║       MARK III — Always-On Service  v0.14.0         ║")
        print("╠══════════════════════════════════════════════════════╣")
        print("║  Wake word : 'MARK'  (say it clearly)               ║")
        print("║  Tray icon : right-click for menu                   ║")
        print("║  Log file  : markiii_service.log                    ║")
        print("╚══════════════════════════════════════════════════════╝")
        print()

    service = MarkService(console=console, sensitivity=args.sensitivity)
    service.run()


if __name__ == "__main__":
    main()
