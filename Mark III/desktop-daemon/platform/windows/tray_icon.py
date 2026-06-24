"""
MARK III — Windows System Tray Integration

Thread model:
  Main thread  → pystray event loop (Windows requires this)
  DaemonThread → asyncio event loop owning all async subsystems

Cross-thread calls use DaemonThread.submit() which wraps
asyncio.run_coroutine_threadsafe() and returns a concurrent.futures.Future.

The MarkIIIDaemon instance is the only shared object between threads.
All methods called on it from pystray callbacks are async and submitted
via DaemonThread.submit() — no direct attribute mutation from the tray thread.
"""

import asyncio
import logging
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw
import pystray

if TYPE_CHECKING:
    from daemon.main import MarkIIIDaemon

logger = logging.getLogger("markiii.tray")

# ---------------------------------------------------------------------------
# Icon rendering
# ---------------------------------------------------------------------------

_ICON_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "markiii_icon.png"

_STATUS_COLOURS = {
    "connected":    (0,   200, 150),   # teal-green
    "disconnected": (255,  76,  76),   # red
    "syncing":      (255, 165,   0),   # amber
}


def _build_icon_image(status: str = "disconnected") -> Image.Image:
    if _ICON_PATH.exists():
        return Image.open(_ICON_PATH).resize((64, 64)).convert("RGBA")

    img  = Image.new("RGBA", (64, 64), (28, 28, 28, 255))
    draw = ImageDraw.Draw(img)

    # "M" glyph — two verticals joined by a chevron
    lw = 5
    draw.line([(10, 10), (10, 54)],  fill=(210, 210, 210), width=lw)
    draw.line([(10, 10), (32, 36)],  fill=(210, 210, 210), width=lw)
    draw.line([(54, 10), (32, 36)],  fill=(210, 210, 210), width=lw)
    draw.line([(54, 10), (54, 54)],  fill=(210, 210, 210), width=lw)

    # Status dot — bottom-right corner
    colour = _STATUS_COLOURS.get(status, (255, 76, 76))
    draw.ellipse([(44, 44), (60, 60)], fill=(*colour, 255))

    return img


# ---------------------------------------------------------------------------
# Daemon thread — owns the asyncio event loop
# ---------------------------------------------------------------------------

class DaemonThread(threading.Thread):

    def __init__(self, daemon: "MarkIIIDaemon") -> None:
        super().__init__(name="markiii-daemon", daemon=True)
        self._daemon = daemon
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_until_complete(self._daemon.run())
        except Exception:
            logger.exception("Daemon loop crashed unexpectedly.")
        finally:
            # Cancel any dangling tasks before closing
            pending = asyncio.all_tasks(self._loop)
            for t in pending:
                t.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self._loop.close()
            logger.info("Daemon event loop closed.")

    def submit(self, coro) -> "asyncio.Future":
        """
        Schedule a coroutine on the daemon loop from any thread.
        Returns a concurrent.futures.Future — call .result() to block,
        or attach .add_done_callback() for fire-and-forget.
        """
        if self._loop is None or self._loop.is_closed():
            raise RuntimeError("Daemon loop is not running.")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def request_stop(self) -> None:
        """
        Ask the daemon to shut down gracefully by setting its stop event.
        This is non-blocking — the daemon drains its tasks asynchronously.
        """
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                self._loop.create_task,
                self._daemon.request_stop(),
            )


# ---------------------------------------------------------------------------
# Tray application
# ---------------------------------------------------------------------------

class MarkIIITray:

    def __init__(self, daemon_thread: DaemonThread) -> None:
        self._thread = daemon_thread
        self._status = "disconnected"
        self._icon: pystray.Icon | None = None
        self._sync_lock = threading.Lock()   # prevent overlapping manual syncs

    # --- Status label (evaluated lazily by pystray on each menu open) ---

    def _status_label(self, item) -> str:
        labels = {
            "connected":    "● Connected",
            "disconnected": "○ Disconnected",
            "syncing":      "◌ Syncing…",
        }
        return labels.get(self._status, "○ Unknown")

    # --- Menu ---

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                "MARK III",
                action=None,
                enabled=False,
            ),
            pystray.MenuItem(
                self._status_label,
                action=None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Trigger Manual Sync",
                action=self._on_manual_sync,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Exit",
                action=self._on_exit,
                default=False,
            ),
        )

    # --- Callbacks — run on pystray's internal thread ---

    def _on_manual_sync(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if not self._sync_lock.acquire(blocking=False):
            logger.info("Sync already in progress — ignoring duplicate request.")
            return

        logger.info("Manual sync triggered from tray.")
        self.set_status("syncing")

        future = self._thread.submit(self._thread._daemon.reload_config())

        def _done(f):
            self._sync_lock.release()
            exc = f.exception()
            if exc:
                logger.error("Config reload failed: %s", exc)
                self.set_status("disconnected")
            else:
                self.set_status("connected")
                logger.info("Manual sync complete — icon set to connected.")

        future.add_done_callback(_done)

    def _on_exit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        logger.info("Exit requested from tray.")

        # 1. Ask the daemon to drain its tasks gracefully
        self._thread.request_stop()

        # 2. Give it up to 5 s to finish, then stop the tray regardless
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            logger.warning("Daemon did not exit within 5 s — forcing tray stop.")

        # 3. Stop pystray — unblocks run() on the main thread
        icon.stop()

    # --- Public API ---

    def set_status(self, status: str) -> None:
        """Safe to call from any thread."""
        self._status = status
        if self._icon:
            self._icon.icon  = _build_icon_image(status)
            self._icon.title = f"MARK III — {status.capitalize()}"

    def run(self) -> None:
        """
        Blocking — must be called from the MAIN thread on Windows.
        Starts the daemon background thread, then hands control to pystray.
        """
        self._thread.start()
        if not self._thread._ready.wait(timeout=8):
            logger.error("Daemon thread did not start within 8 s — aborting.")
            sys.exit(1)

        logger.info("Daemon thread ready. Starting system tray icon.")

        self._icon = pystray.Icon(
            name="MARK III",
            icon=_build_icon_image("disconnected"),
            title="MARK III — Disconnected",
            menu=self._build_menu(),
        )

        # pystray.Icon.run() blocks here until _on_exit calls icon.stop()
        self._icon.run()
        logger.info("Tray exited cleanly.")


# ---------------------------------------------------------------------------
# Public entry point — called from daemon/main.py
# ---------------------------------------------------------------------------

def launch(daemon: "MarkIIIDaemon") -> None:
    """
    Wire up the daemon and tray, then block on the tray event loop.
    Call this from the main thread only.
    """
    daemon_thread = DaemonThread(daemon)
    tray = MarkIIITray(daemon_thread)

    # Plumb brain-server connectivity directly into the tray icon dot.
    # These are called from the daemon's async context (DaemonThread),
    # so they must be thread-safe — set_status() only touches self._status
    # and self._icon which are safe for cross-thread attribute writes on CPython.
    daemon.on_connect    = lambda: tray.set_status("connected")
    daemon.on_disconnect = lambda: tray.set_status("disconnected")

    tray.run()
