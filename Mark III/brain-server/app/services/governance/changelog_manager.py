"""
MARK III — Changelog Manager

Prepends new entries to CHANGELOG.md when a phase is completed.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

log = logging.getLogger("markiii.governance.changelog")
_CHANGELOG_PATH = Path(__file__).parents[4] / "CHANGELOG.md"


def prepend_entry(version: str, phase_name: str, change_type: str, bullets: list[str]) -> None:
    """
    Add a new entry to CHANGELOG.md, immediately after the header.

    Args:
        version:     e.g. "0.18.2"
        phase_name:  e.g. "Knowledge Governance System"
        change_type: e.g. "Major feature" | "Structural" | "Bug fix"
        bullets:     list of bullet point strings (no leading dash)
    """
    if not _CHANGELOG_PATH.exists():
        log.warning("CHANGELOG.md not found")
        return

    today   = date.today().isoformat()
    lines   = [f"- {b}" for b in bullets]
    section = (
        f"\n## [{version}] — {today} — {phase_name}\n\n"
        f"**Type:** {change_type}\n\n"
        + "\n".join(lines)
        + "\n\n---\n"
    )

    text  = _CHANGELOG_PATH.read_text(encoding="utf-8", errors="ignore")
    # Insert after the first "---" separator (after the file header)
    idx   = text.find("\n---\n")
    if idx == -1:
        text = text + section
    else:
        text = text[:idx + 5] + section + text[idx + 5:]

    _CHANGELOG_PATH.write_text(text, encoding="utf-8")
    log.info("Changelog updated: [%s] %s", version, phase_name)


def get_latest_version() -> str:
    """Return the latest version string from CHANGELOG.md."""
    import re
    if not _CHANGELOG_PATH.exists():
        return "0.0.0"
    text = _CHANGELOG_PATH.read_text(encoding="utf-8", errors="ignore")
    m    = re.search(r"\[([0-9]+\.[0-9]+\.[0-9]+)\]", text)
    return m.group(1) if m else "0.0.0"
