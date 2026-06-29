"""MARK III — Roadmap Manager — reads and updates roadmap documents."""
from __future__ import annotations
import logging, re
from datetime import date
from pathlib import Path
log = logging.getLogger("markiii.governance.roadmap")

_COMPLETED = Path(__file__).parents[4] / "docs" / "roadmap" / "completed_phases.md"
_FUTURE    = Path(__file__).parents[4] / "docs" / "roadmap" / "future.md"


def mark_phase_complete(phase_name: str, version: str, bullets: list[str]) -> None:
    """Prepend a completed phase entry to completed_phases.md."""
    if not _COMPLETED.exists():
        return
    today   = date.today().isoformat()
    lines   = "\n".join(f"- {b}" for b in bullets)
    section = f"\n## {phase_name}\n**Completed:** {today} | **Version:** {version}\n\n{lines}\n"
    text    = _COMPLETED.read_text(encoding="utf-8", errors="ignore")
    idx     = text.find("\n## ")
    if idx == -1:
        _COMPLETED.write_text(text + section, encoding="utf-8")
    else:
        _COMPLETED.write_text(text[:idx] + section + text[idx:], encoding="utf-8")
    log.info("Roadmap updated: phase '%s' marked complete", phase_name)


def get_future_phases() -> list[str]:
    """Return list of future phase headings."""
    if not _FUTURE.exists():
        return []
    text = _FUTURE.read_text(encoding="utf-8", errors="ignore")
    return re.findall(r"^## (.+)$", text, re.M)


def get_completed_phases() -> list[str]:
    """Return list of completed phase headings."""
    if not _COMPLETED.exists():
        return []
    text = _COMPLETED.read_text(encoding="utf-8", errors="ignore")
    return re.findall(r"^## (.+)$", text, re.M)
