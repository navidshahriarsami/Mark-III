"""
MARK III — ADR Manager

Creates, validates, and indexes Architecture Decision Records.

ADR filename convention:
  ADR-XXXX-Short-Title.md

Every ADR must contain:
  - Status (Accepted / Proposed / Deprecated / Superseded)
  - Context (why this decision was needed)
  - Decision (what was decided)
  - Consequences (what changes as a result)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

log = logging.getLogger("markiii.governance.adr")
_ADR_DIR = Path(__file__).parents[4] / "docs" / "adr"


@dataclass
class ADR:
    number:  int
    title:   str
    status:  str
    path:    str
    content: str = ""


def list_adrs() -> list[ADR]:
    """Return all ADRs sorted by number."""
    if not _ADR_DIR.exists():
        return []
    adrs = []
    for path in sorted(_ADR_DIR.glob("ADR-*.md")):
        m = re.match(r"ADR-(\d+)-(.+)\.md", path.name)
        if not m:
            continue
        text   = path.read_text(encoding="utf-8", errors="ignore")
        status = _extract_status(text)
        adrs.append(ADR(
            number  = int(m.group(1)),
            title   = m.group(2).replace("-", " "),
            status  = status,
            path    = str(path),
        ))
    return adrs


def next_adr_number() -> int:
    """Return the next available ADR number."""
    existing = list_adrs()
    return max((a.number for a in existing), default=0) + 1


def create_adr(title: str, context: str, decision: str, consequences: str) -> Path:
    """
    Create a new ADR file and return its path.
    """
    _ADR_DIR.mkdir(parents=True, exist_ok=True)
    number   = next_adr_number()
    slug     = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-")
    filename = f"ADR-{number:04d}-{slug}.md"
    path     = _ADR_DIR / filename
    today    = date.today().isoformat()

    content = f"""# ADR-{number:04d} — {title}

**Status:** Accepted
**Date:** {today}
**Author:** Navid Shahriar Sami

## Context

{context}

## Decision

{decision}

## Consequences

{consequences}
"""
    path.write_text(content, encoding="utf-8")
    log.info("ADR created: %s", filename)
    return path


def validate_adr(path: Path) -> list[str]:
    """Return a list of validation errors for an ADR file."""
    errors = []
    if not path.exists():
        return [f"File not found: {path}"]
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "## Context" not in text:    errors.append("Missing ## Context section")
    if "## Decision" not in text:   errors.append("Missing ## Decision section")
    if "## Consequences" not in text: errors.append("Missing ## Consequences section")
    if "**Status:**" not in text:   errors.append("Missing **Status:** field")
    return errors


def _extract_status(text: str) -> str:
    m = re.search(r"\*\*Status:\*\*\s*(.+)", text)
    return m.group(1).strip() if m else "Unknown"
