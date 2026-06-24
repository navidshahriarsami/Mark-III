"""
MARK III Reflex — Application Module

Handles: active window, running applications, is-X-running queries.
"""
from __future__ import annotations

import re
from typing import Optional

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(what('?s| is) (the )?(active|current|open|focused) (window|app|application))\b|\bwhat am i (looking at|working on)\b", re.I), "active_window"),
    (re.compile(r"\b(is|are) (chrome|firefox|edge|spotify|discord|vscode|vs code|slack|zoom|teams|word|excel|notepad|explorer)( running| open| active)?\b", re.I), "is_running"),
    (re.compile(r"\b(what('?s| is) (open|running))\b|\bshow (me )?(running )?(apps|applications|programs)\b|\blist (running )?(apps|processes)\b", re.I), "list_apps"),
]

_APP_ALIASES = {
    "chrome": "chrome", "firefox": "firefox", "edge": "msedge",
    "spotify": "spotify", "discord": "discord", "vs code": "code",
    "vscode": "code", "slack": "slack", "zoom": "zoom",
    "teams": "teams", "word": "winword", "excel": "excel",
    "notepad": "notepad", "explorer": "explorer",
}


def can_handle(text: str) -> bool:
    return any(p.search(text) for p, _ in _PATTERNS)


def handle(text: str) -> Optional[str]:
    for pattern, action in _PATTERNS:
        if pattern.search(text):
            fn = globals().get(f"_get_{action}")
            if fn:
                return fn(text)
    return None


def _get_active_window(text: str = "") -> str:
    try:
        import pygetwindow as gw
        wins = gw.getActiveWindow()
        if wins and wins.title:
            return f"Active window: {wins.title}."
        return "Could not determine active window."
    except Exception:
        try:
            import subprocess
            # Windows fallback via PowerShell
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-Process | Where-Object {$_.MainWindowTitle} | Sort-Object CPU -Descending | Select-Object -First 1).MainWindowTitle"],
                capture_output=True, text=True, timeout=3,
            )
            title = result.stdout.strip()
            if title:
                return f"Active window: {title}."
        except Exception:
            pass
        return "Active window detection unavailable."


def _get_is_running(text: str) -> str:
    try:
        import psutil
        text_lower = text.lower()
        for friendly, proc_name in _APP_ALIASES.items():
            if friendly in text_lower:
                running = any(
                    proc_name.lower() in p.name().lower()
                    for p in psutil.process_iter(["name"])
                )
                return f"{friendly.title()} is {'running' if running else 'not running'}."
        return "I couldn't identify which app you mean."
    except ImportError:
        return "psutil not installed — app detection unavailable."


def _get_list_apps(text: str = "") -> str:
    try:
        import psutil
        seen = set()
        apps = []
        skip = {"system", "idle", "registry", "smss", "csrss", "wininit", "services",
                "lsass", "svchost", "dwm", "conhost", "dllhost", "winlogon", "fontdrvhost"}
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                name = p.info["name"].replace(".exe", "")
                if name.lower() not in skip and name not in seen and p.info["memory_info"].rss > 10 * 1024 * 1024:
                    seen.add(name)
                    apps.append(name)
            except Exception:
                pass
        top = sorted(apps)[:8]
        return f"Running apps: {', '.join(top)}." if top else "No significant apps detected."
    except ImportError:
        return "psutil not installed."
