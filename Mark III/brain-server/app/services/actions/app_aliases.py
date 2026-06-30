"""
MARK III — App Alias Resolver

Two layers of resolution, tried in order:

  1. Discovery index (app_discovery.py) — the REAL apps actually installed on
     this machine, found by scanning Start Menu shortcuts + Get-StartApps.
     This is the primary path: resolve_app_target() returns the exact launch
     path MARK found on disk, e.g. Slack -> C:\\Users\\...\\AppData\\Local\\
     slack\\slack.exe. Most consumer apps (Slack, Discord, Spotify) are never
     on PATH and don't register in the Windows "App Paths" registry key that
     os.startfile() checks — Start Menu shortcuts are the one thing every
     installer creates, so this is what actually finds them.

  2. Static curated list (this file) — a small set of common aliases (vscode
     -> code, calc -> calculator) used as a fallback before the discovery
     index has completed its first scan, or for generic PATH-resolvable names
     the discovery scan wouldn't necessarily surface as a distinct app.

Origin: live testing surfaced Whisper transcribing "notepad" as "node pad",
"nodepad", and "note pad" across three separate utterances — each failed to
launch (or, worse, "node pair" resolved to the real `node` binary on PATH and
opened a Node.js REPL instead of Notepad). The fix matches the spoken phrase
against known apps by string similarity and substitutes the closest one when
confidence is high enough.

Unknown app names fall through unchanged so arbitrary/uninstalled apps can
still be attempted via the existing shutil.which/os.startfile path in
desktop_executor.py. This module never blocks an action; it only improves
the input before the existing resolution logic runs.
"""
from __future__ import annotations

import difflib
import logging

log = logging.getLogger("markiii.actions.aliases")

# canonical spoken phrase → actual launch target (what shutil.which/os.startfile expects)
# "node" is deliberately excluded — it's a real PATH binary (Node.js REPL) that
# would otherwise out-compete "notepad" for garbled transcriptions like "node pad".
_KNOWN_APPS: dict[str, str] = {
    "notepad":              "notepad",
    "chrome":                "chrome",
    "google chrome":         "chrome",
    "code":                  "code",
    "vscode":                "code",
    "vs code":                "code",
    "visual studio code":    "code",
    "cursor":                "cursor",
    "explorer":              "explorer",
    "file explorer":         "explorer",
    "calculator":            "calc",
    "calc":                  "calc",
    "spotify":                "spotify",
    "slack":                  "slack",
    "discord":                "discord",
    "firefox":                "firefox",
    "edge":                   "msedge",
    "microsoft edge":         "msedge",
    "outlook":                "outlook",
    "word":                   "winword",
    "microsoft word":         "winword",
    "excel":                  "excel",
    "microsoft excel":        "excel",
    "powerpoint":             "powerpnt",
    "terminal":               "wt",
    "windows terminal":       "wt",
    "powershell":             "powershell",
    "command prompt":         "cmd",
    "cmd":                    "cmd",
    "task manager":           "taskmgr",
    "control panel":          "control",
    "paint":                  "mspaint",
}

_CUTOFF = 0.65   # calibrated against real mis-transcriptions; see commit history for analysis


def resolve_app_name(raw_name: str) -> str:
    """
    Fuzzy-resolve a possibly mis-heard app name against known apps.

    Returns the corrected launch target if a confident match is found,
    otherwise returns raw_name unchanged.
    """
    normalized = raw_name.lower().strip()
    if not normalized:
        return raw_name

    if normalized in _KNOWN_APPS:
        return _KNOWN_APPS[normalized]

    collapsed = normalized.replace(" ", "")

    candidates = list(_KNOWN_APPS.keys())
    match = difflib.get_close_matches(normalized, candidates, n=1, cutoff=_CUTOFF)
    if match:
        return _KNOWN_APPS[match[0]]

    collapsed_map = {k.replace(" ", ""): k for k in candidates}
    match2 = difflib.get_close_matches(collapsed, list(collapsed_map.keys()), n=1, cutoff=_CUTOFF)
    if match2:
        return _KNOWN_APPS[collapsed_map[match2[0]]]

    return raw_name


_SOURCE_PRIORITY = {"shortcut": 0, "startapp_exe": 1, "uwp": 2}


def resolve_app_target(raw_name: str) -> tuple[str, "str | None"]:
    """
    Discovery-aware resolution. Returns (display_name, exact_launch_target).

    target is the real path/URI MARK found on disk for this app, or None if
    no confident match exists in the discovery index — caller should fall
    back to resolve_app_name() + its own shutil.which/os.startfile logic.
    """
    try:
        from app.services.discovery.discovery_store import get_discovery_store
        store = get_discovery_store()
    except Exception as e:
        log.debug("Discovery store unavailable: %s", e)
        return raw_name, None

    normalized = raw_name.lower().strip()
    if not normalized:
        return raw_name, None

    matches = store.search_apps(normalized, limit=10)

    if not matches:
        all_names = store.get_all_app_names()
        if all_names:
            close = difflib.get_close_matches(normalized, all_names, n=1, cutoff=_CUTOFF)
            if close:
                matches = store.search_apps(close[0], limit=10)

    if not matches:
        return raw_name, None

    best = min(matches, key=lambda a: _SOURCE_PRIORITY.get(a["source"], 9))
    log.debug("Discovery resolved %r -> %s (%s)", raw_name, best["target"], best["source"])
    return best["name"], best["target"]
