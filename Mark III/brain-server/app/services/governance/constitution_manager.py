"""
MARK III — Constitution Manager

Loads and validates the MARK III Constitution from CLAUDE.md.
Reports whether Article XV engineering directive is in force.

The constitution is the permanent foundation of MARK's engineering governance.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("markiii.governance.constitution")
_CONSTITUTION_PATH = Path(__file__).parents[4] / "CLAUDE.md"


@dataclass
class ConstitutionStatus:
    present:        bool
    article_xv:     bool
    invariants:     list[str]
    summary:        str


def validate() -> ConstitutionStatus:
    """Read CLAUDE.md and validate constitutional requirements."""
    if not _CONSTITUTION_PATH.exists():
        log.critical("CLAUDE.md missing — MARK III Constitution not in force.")
        return ConstitutionStatus(
            present=False, article_xv=False, invariants=[],
            summary="CRITICAL: Constitution missing. Engineering directive NOT enforced.",
        )

    text       = _CONSTITUTION_PATH.read_text(encoding="utf-8", errors="ignore")
    article_xv = "ARTICLE XV" in text

    # Extract invariant list (lines after "ARCHITECTURE INVARIANTS")
    invariants: list[str] = []
    in_section = False
    for line in text.splitlines():
        if "ARCHITECTURE INVARIANTS" in line:
            in_section = True
            continue
        if in_section:
            if line.startswith("##"):
                break
            stripped = line.strip().lstrip("0123456789. ")
            if stripped:
                invariants.append(stripped)

    if not article_xv:
        summary = "Constitution present but Article XV missing."
        log.warning(summary)
    else:
        summary = f"Constitution valid. {len(invariants)} invariants. Article XV in force."
        log.info(summary)

    return ConstitutionStatus(
        present    = True,
        article_xv = article_xv,
        invariants = invariants,
        summary    = summary,
    )


def get_invariants() -> list[str]:
    """Return the list of architectural invariants from the constitution."""
    return validate().invariants
