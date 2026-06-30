"""
MARK III — App Alias Resolver

Fuzzy-corrects mis-transcribed or mis-spoken app names against a curated list
of common applications before the executor attempts to launch them.

Origin: live testing surfaced Whisper transcribing "notepad" as "node pad",
"nodepad", and "note pad" across three separate utterances — each failed to
launch (or, worse, "node pair" resolved to the real `node` binary on PATH and
opened a Node.js REPL instead of Notepad). The fix matches the spoken phrase
against known apps by string similarity and substitutes the closest one when
confidence is high enough.

Deliberately NOT exhaustive — only common desktop apps where a wrong guess is
low-risk. Unknown app names fall through unchanged so arbitrary/uninstalled
apps can still be attempted via the existing shutil.which/os.startfile path
in desktop_executor.py. This module never blocks an action; it only improves
the input before the existing resolution logic runs.
"""
from __future__ import annotations

import difflib

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
