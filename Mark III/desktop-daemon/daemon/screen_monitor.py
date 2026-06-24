"""
MARK III — Windows Screen Monitor

Primary data source for the distraction engine. Polls the active window
every 10 seconds using pywin32 for zero-overhead process/title detection.
Falls back to mss + pytesseract OCR on the browser address-bar region only
when the foreground process is a known browser.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import win32gui
import win32process
import psutil
import mss
import pytesseract
from PIL import Image

logger = logging.getLogger("markiii.screen_monitor")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Tesseract install path — update if installed elsewhere
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# Browser process names that trigger the OCR address-bar fallback
BROWSER_PROCESSES = frozenset({
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "vivaldi.exe",
})

# Relative crop: top N pixels of the browser window for address bar OCR.
# Adjust if a browser renders the omnibar outside this band.
ADDRESS_BAR_HEIGHT_PX = 80


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class WindowSnapshot:
    pid: int
    process_name: str           # e.g. "chrome.exe"
    window_title: str           # Raw Win32 title string
    ocr_address_bar: str        # Non-empty only for browsers
    is_browser: bool

    @property
    def combined_text(self) -> str:
        """Single string that the detector pattern-matches against."""
        return f"{self.window_title} {self.ocr_address_bar}".lower()


# ---------------------------------------------------------------------------
# Win32 helpers
# ---------------------------------------------------------------------------

def _get_foreground_pid() -> Optional[int]:
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return pid


def _get_window_title(pid: int) -> str:
    hwnd = win32gui.GetForegroundWindow()
    try:
        return win32gui.GetWindowText(hwnd)
    except Exception:
        return ""


def _get_process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Returns (left, top, right, bottom) in screen coordinates."""
    try:
        return win32gui.GetWindowRect(hwnd)
    except Exception:
        return (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# OCR — address bar only
# ---------------------------------------------------------------------------

def _ocr_address_bar(hwnd: int) -> str:
    """
    Capture a thin horizontal strip at the top of the browser window and
    run Tesseract in single-line (PSM 7) mode to extract URL/tab text.
    Returns empty string on any failure.
    """
    left, top, right, bottom = _get_window_rect(hwnd)
    if right <= left or bottom <= top:
        return ""

    region = {
        "left":   left,
        "top":    top,
        "width":  right - left,
        "height": min(ADDRESS_BAR_HEIGHT_PX, bottom - top),
    }

    try:
        with mss.mss() as sct:
            raw = sct.grab(region)
        img = Image.frombytes("RGB", (raw.width, raw.height), raw.rgb)

        # Upscale 2× — Tesseract accuracy improves significantly at higher DPI
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

        text = pytesseract.image_to_string(
            img,
            config="--psm 7 --oem 3",   # PSM 7 = single text line
        )
        return text.strip()
    except Exception as exc:
        logger.debug("OCR failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Public snapshot function
# ---------------------------------------------------------------------------

async def capture_snapshot() -> Optional[WindowSnapshot]:
    """
    Async-safe wrapper around synchronous Win32/OCR calls.
    Offloads blocking I/O to the default thread executor so the event loop
    is not stalled during mss grabs or Tesseract invocations.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _capture_snapshot_sync)


def _capture_snapshot_sync() -> Optional[WindowSnapshot]:
    pid = _get_foreground_pid()
    if pid is None:
        return None

    process_name = _get_process_name(pid)
    window_title = _get_window_title(pid)
    is_browser    = process_name in BROWSER_PROCESSES
    ocr_bar       = ""

    if is_browser:
        hwnd = win32gui.GetForegroundWindow()
        ocr_bar = _ocr_address_bar(hwnd)
        logger.debug("OCR address bar: %r", ocr_bar)

    return WindowSnapshot(
        pid=pid,
        process_name=process_name,
        window_title=window_title,
        ocr_address_bar=ocr_bar,
        is_browser=is_browser,
    )
