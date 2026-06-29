"""
MARK III — Version Manager

Reads and updates MARK_VERSION.md.
Called by the governance system when a phase is completed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("markiii.governance.version")
_VERSION_PATH = Path(__file__).parents[4] / "MARK_VERSION.md"


@dataclass
class VersionInfo:
    version: str
    phase:   str
    date:    str
    raw:     str


def get_version() -> VersionInfo:
    """Read current version from MARK_VERSION.md."""
    if not _VERSION_PATH.exists():
        return VersionInfo("0.0.0", "unknown", "", "")
    text = _VERSION_PATH.read_text(encoding="utf-8", errors="ignore")
    vm = re.search(r"\*\*Version[:\s]+([0-9]+\.[0-9]+\.[0-9]+)", text, re.I)
    pm = re.search(r"\*\*Phase[:\s]+(.+)", text, re.I)
    dm = re.search(r"\*\*(Updated|Date)[:\s]+(.+)", text, re.I)
    return VersionInfo(
        version = vm.group(1) if vm else "0.0.0",
        phase   = pm.group(1).strip() if pm else "unknown",
        date    = dm.group(2).strip() if dm else "",
        raw     = text,
    )


def bump_patch(phase_name: str, summary: str) -> str:
    """Increment patch version and update the phase line. Returns new version string."""
    info = get_version()
    parts = info.version.split(".")
    try:
        parts[2] = str(int(parts[2]) + 1)
    except (IndexError, ValueError):
        parts = ["0", "18", "2"]
    new_version = ".".join(parts)

    from datetime import date
    today = date.today().isoformat()

    text = _VERSION_PATH.read_text(encoding="utf-8", errors="ignore")
    # Update version line
    text = re.sub(r"\*\*Version[:\s]+[0-9]+\.[0-9]+\.[0-9]+\*\*", f"**Version:** {new_version}**", text)
    # Update phase line
    text = re.sub(r"\*\*Phase[:\s]+.+", f"**Phase:** {phase_name}**", text)
    # Update date line
    text = re.sub(r"\*\*(Updated|Date)[:\s]+.+", f"**Updated:** {today}**", text)

    _VERSION_PATH.write_text(text, encoding="utf-8")
    log.info("Version bumped: %s → %s (%s)", info.version, new_version, phase_name)
    return new_version
