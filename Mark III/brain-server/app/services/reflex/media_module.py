"""
MARK III Reflex — Media Module

Handles: Spotify status, now playing, play/pause/skip.
Uses Windows media session API via winsdk if available,
falls back to Spotify web API / process detection.
"""
from __future__ import annotations

import re
import subprocess
from typing import Optional

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(what('?s| is) (playing|the song)|current song|now playing)\b", re.I), "now_playing"),
    (re.compile(r"\bpause (the |my )?(music|song|track|spotify)\b|\bstop (playing|music)\b",   re.I), "pause"),
    (re.compile(r"\b(play|resume) (music|spotify|the song|track)\b",                           re.I), "play"),
    (re.compile(r"\b(next|skip) (song|track|music)\b",                                         re.I), "skip"),
    (re.compile(r"\b(previous|last|back) (song|track)\b|\bgo back\b",                          re.I), "previous"),
]


def can_handle(text: str) -> bool:
    return any(p.search(text) for p, _ in _PATTERNS)


def handle(text: str) -> Optional[str]:
    for pattern, action in _PATTERNS:
        if pattern.search(text):
            fn = globals().get(f"_do_{action}")
            if fn:
                return fn()
    return None


def _spotify_running() -> bool:
    try:
        import psutil
        return any("spotify" in p.name().lower() for p in psutil.process_iter(["name"]))
    except Exception:
        return False


def _do_now_playing() -> str:
    try:
        # Try Windows Media Session via PowerShell (works for Spotify, YouTube, etc.)
        result = subprocess.run(
            ["powershell", "-Command",
             "$session = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]"
             "::RequestAsync().GetAwaiter().GetResult().GetCurrentSession();"
             "if ($session) { $info = $session.TryGetMediaPropertiesAsync().GetAwaiter().GetResult();"
             "\"$($info.Title) by $($info.Artist)\" } else { \"\" }"],
            capture_output=True, text=True, timeout=4,
        )
        title = result.stdout.strip()
        if title and "by" in title:
            return f"Playing: {title}."
    except Exception:
        pass

    if _spotify_running():
        return "Spotify is running but I can't read the current track. Try the Spotify API integration."
    return "No media is currently playing."


def _do_pause() -> str:
    try:
        # Send media key via PowerShell
        subprocess.run(
            ["powershell", "-Command",
             "$wsh = New-Object -ComObject wscript.shell; $wsh.SendKeys([char]179)"],
            timeout=2,
        )
        return "Paused."
    except Exception:
        return "Could not send pause command."


def _do_play() -> str:
    try:
        subprocess.run(
            ["powershell", "-Command",
             "$wsh = New-Object -ComObject wscript.shell; $wsh.SendKeys([char]179)"],
            timeout=2,
        )
        return "Resuming playback."
    except Exception:
        return "Could not send play command."


def _do_skip() -> str:
    try:
        subprocess.run(
            ["powershell", "-Command",
             "$wsh = New-Object -ComObject wscript.shell; $wsh.SendKeys([char]176)"],
            timeout=2,
        )
        return "Skipping to next track."
    except Exception:
        return "Could not send skip command."


def _do_previous() -> str:
    try:
        subprocess.run(
            ["powershell", "-Command",
             "$wsh = New-Object -ComObject wscript.shell; $wsh.SendKeys([char]177)"],
            timeout=2,
        )
        return "Going to previous track."
    except Exception:
        return "Could not send previous command."
