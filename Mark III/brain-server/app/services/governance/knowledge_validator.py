"""MARK III — Knowledge Validator — validates implementation vs documentation sync."""
from __future__ import annotations
import logging
from pathlib import Path
log = logging.getLogger("markiii.governance.validator")

def validate_sync() -> dict:
    """Check that key implementation files have corresponding documentation."""
    _SERVICES = Path(__file__).parents[3] / "services"
    _DOCS     = Path(__file__).parents[4] / "docs"
    results   = {"synced": [], "undocumented": [], "orphan_docs": []}
    # Service → expected doc mapping
    mapping = {
        "voice/always_listening_loop.py": "docs/architecture/cognitive_pipeline.md",
        "mesh/mesh_manager.py":           "docs/architecture/device_mesh.md",
        "memory/fact_store.py":           "docs/architecture/memory_architecture.md",
        "identity/identity_manager.py":   "docs/architecture/identity_engine.md",
        "knowledge/obsidian_bridge.py":   "docs/architecture/knowledge_engine.md",
    }
    repo = Path(__file__).parents[4]
    for src, doc in mapping.items():
        src_p = _SERVICES / src
        doc_p = repo / doc
        if src_p.exists() and doc_p.exists():
            results["synced"].append(src)
        elif src_p.exists() and not doc_p.exists():
            results["undocumented"].append(src)
        elif not src_p.exists() and doc_p.exists():
            results["orphan_docs"].append(doc)
    return results
