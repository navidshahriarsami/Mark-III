"""MARK III — Documentation Manager — creates and updates markdown documentation."""
from __future__ import annotations
import logging
from pathlib import Path
log = logging.getLogger("markiii.governance.docs")

_DOCS = Path(__file__).parents[4] / "docs"


def update_architecture_doc(subsystem: str, content_addition: str) -> bool:
    """Append content to an existing architecture doc. Returns True if found."""
    path = _DOCS / "architecture" / f"{subsystem}.md"
    if not path.exists():
        log.warning("Architecture doc not found: %s", path)
        return False
    existing = path.read_text(encoding="utf-8", errors="ignore")
    path.write_text(existing.rstrip() + "\n\n" + content_addition + "\n", encoding="utf-8")
    log.info("Architecture doc updated: %s", path.name)
    return True


def create_architecture_doc(name: str, title: str, content: str) -> Path:
    """Create a new architecture document."""
    _DOCS_ARCH = _DOCS / "architecture"
    _DOCS_ARCH.mkdir(parents=True, exist_ok=True)
    path = _DOCS_ARCH / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    log.info("Architecture doc created: %s", path.name)
    return path


def list_architecture_docs() -> list[str]:
    path = _DOCS / "architecture"
    if not path.exists():
        return []
    return [p.stem for p in sorted(path.glob("*.md"))]
