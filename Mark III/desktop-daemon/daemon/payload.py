"""
MARK III — Snapshot Payload Builder

Translates a raw WindowSnapshot into a structured, semantically-classified
SnapshotPayload before it leaves the daemon. The brain server receives clean
data it can act on directly — no raw Win32 strings.

Classification taxonomy:
  browser       — any known browser process
  ide           — code editors / IDEs
  terminal      — shells and CLIs
  communication — Slack, Teams, Discord, email clients
  productivity  — Office, Notion, Obsidian, PDF viewers
  media         — Spotify, VLC, media players
  distraction   — matches the blocked keywords list
  system        — Windows UI, Task Manager, Explorer
  unknown       — everything else
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from daemon.screen_monitor import WindowSnapshot


# ---------------------------------------------------------------------------
# Classification rules — checked in order, first match wins
# ---------------------------------------------------------------------------

_RULES: list[tuple[str, set[str], set[str]]] = [
    # (classification, process_name_fragments, title_keyword_fragments)
    (
        "ide",
        {"code.exe", "pycharm64.exe", "idea64.exe", "webstorm64.exe",
         "rider64.exe", "sublime_text.exe", "notepad++.exe", "vim.exe",
         "nvim.exe", "cursor.exe"},
        set(),
    ),
    (
        "terminal",
        {"powershell.exe", "pwsh.exe", "cmd.exe", "windowsterminal.exe",
         "wt.exe", "conhost.exe", "bash.exe", "wsl.exe", "mintty.exe"},
        set(),
    ),
    (
        "communication",
        {"slack.exe", "teams.exe", "discord.exe", "thunderbird.exe",
         "outlook.exe", "zoom.exe", "skype.exe"},
        set(),
    ),
    (
        "productivity",
        {"winword.exe", "excel.exe", "powerpnt.exe", "onenote.exe",
         "acrobat.exe", "acrord32.exe", "notion.exe", "obsidian.exe",
         "lowriter.exe", "scalc.exe"},
        set(),
    ),
    (
        "media",
        {"spotify.exe", "vlc.exe", "wmplayer.exe", "groove.exe",
         "musicbee.exe", "foobar2000.exe", "itunes.exe"},
        set(),
    ),
    (
        "system",
        {"explorer.exe", "taskmgr.exe", "mmc.exe", "regedit.exe",
         "control.exe", "systemsettings.exe", "searchhost.exe"},
        set(),
    ),
    (
        "browser",
        {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
         "opera.exe", "vivaldi.exe", "iexplore.exe"},
        set(),
    ),
]

_DISTRACTION_KEYWORDS = {
    "youtube", "reddit", "twitter", "x.com", "facebook", "instagram",
    "tiktok", "twitch", "discord", "9gag", "netflix", "buzzfeed",
    "gaming", "steam", "epic games",
}


def _classify(snapshot: WindowSnapshot) -> str:
    proc  = snapshot.process_name.lower()
    title = snapshot.window_title.lower()
    ocr   = snapshot.ocr_address_bar.lower()
    combined = f"{title} {ocr}"

    # Distraction check first — overrides even legitimate apps
    if any(kw in combined for kw in _DISTRACTION_KEYWORDS):
        return "distraction"

    for classification, processes, keywords in _RULES:
        if proc in processes:
            return classification
        if keywords and any(kw in combined for kw in keywords):
            return classification

    return "unknown"


def _extract_domain(text: str) -> Optional[str]:
    """Pull the first domain-like token from OCR or title text."""
    match = re.search(r"([a-z0-9-]+\.[a-z]{2,}(?:\.[a-z]{2})?)", text.lower())
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Payload dataclass
# ---------------------------------------------------------------------------

@dataclass
class SnapshotPayload:
    device_id:      str
    ts:             float
    process_name:   str
    window_title:   str
    classification: str
    is_browser:     bool
    active_domain:  Optional[str]  = None
    ocr_text:       Optional[str]  = None


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_snapshot_payload(
    snapshot: WindowSnapshot,
    device_id: str,
) -> SnapshotPayload:
    classification = _classify(snapshot)
    domain = None

    if snapshot.is_browser:
        # Prefer OCR address bar; fall back to extracting domain from title
        domain = (
            _extract_domain(snapshot.ocr_address_bar)
            or _extract_domain(snapshot.window_title)
        )

    return SnapshotPayload(
        device_id      = device_id,
        ts             = time.time(),
        process_name   = snapshot.process_name,
        window_title   = snapshot.window_title[:200],
        classification = classification,
        is_browser     = snapshot.is_browser,
        active_domain  = domain,
        ocr_text       = snapshot.ocr_address_bar[:200] if snapshot.ocr_address_bar else None,
    )
