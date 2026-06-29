"""MARK III — Knowledge Index Manager — manages ChromaDB knowledge index refresh."""
from __future__ import annotations
import logging, threading
log = logging.getLogger("markiii.governance.index")


def refresh_all() -> dict:
    """Trigger full re-index of the Obsidian vault / docs/ folder."""
    try:
        from app.services.knowledge.vault_indexer import get_vault_indexer
        idx  = get_vault_indexer()
        idx.full_index()
        return {"status": "refreshed"}
    except Exception as e:
        log.warning("Index refresh error: %s", e)
        return {"error": str(e)}


def refresh_file(path: str) -> bool:
    """Re-index a single file."""
    try:
        from app.services.knowledge.obsidian_bridge import get_obsidian_bridge
        get_obsidian_bridge().index_file(path)
        return True
    except Exception as e:
        log.debug("File re-index error (%s): %s", path, e)
        return False


def get_index_stats() -> dict:
    """Return stats about the current knowledge index."""
    try:
        from app.services.memory.chroma_store import get_chroma_store
        store = get_chroma_store()
        return store.collection_stats()
    except Exception as e:
        return {"error": str(e)}
