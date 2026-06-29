"""
MARK III — ChromaDB Vector Store

Replaces the SQLite vector store for long-term semantic memory.
Uses nomic-embed-text via Ollama for embeddings.

Collections:
  mark_knowledge   — architecture decisions, phases, preferences (seeded)
  conversations    — summarised conversation history
  obsidian         — Obsidian vault documents
  user_prefs       — persistent user preferences and patterns
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("markiii.memory.chroma")

_DB_PATH     = Path(__file__).parents[3] / "chroma_db"
_EMBED_MODEL = "nomic-embed-text"
_OLLAMA_BASE = "http://localhost:11434"

_COLLECTIONS = ["mark_knowledge", "conversations", "obsidian", "user_prefs"]


@dataclass
class ChromaResult:
    id:        str
    content:   str
    source:    str    # collection name
    score:     float  # 1 - distance (higher = more similar)
    metadata:  dict


# ─── Embedding ────────────────────────────────────────────────────────────────

def _embed(text: str) -> Optional[list[float]]:
    try:
        r = httpx.post(
            f"{_OLLAMA_BASE}/api/embed",
            json={"model": _EMBED_MODEL, "input": text},
            timeout=8.0,
        )
        r.raise_for_status()
        return r.json()["embeddings"][0]
    except Exception as e:
        log.warning("Embedding failed: %s", e)
        return None


# ─── ChromaStore ──────────────────────────────────────────────────────────────

class ChromaStore:
    """
    ChromaDB-backed semantic memory for MARK III.

    Each domain has its own collection for clean separation:
    - mark_knowledge : architecture, decisions, phases
    - conversations  : summarised long-term conversation history
    - obsidian       : Obsidian vault (auto-indexed)
    - user_prefs     : preferences, patterns, recurring workflows
    """

    def __init__(self) -> None:
        import chromadb
        self._client = chromadb.PersistentClient(path=str(_DB_PATH))
        self._cols: dict = {}
        for name in _COLLECTIONS:
            self._cols[name] = self._client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
        log.info("ChromaDB ready at %s (%d collections)", _DB_PATH, len(self._cols))

    # ── Write ──────────────────────────────────────────────────────────────────

    def add(
        self,
        content:    str,
        doc_id:     str,
        collection: str  = "mark_knowledge",
        metadata:   dict = None,
    ) -> bool:
        """Add or update a document. doc_id is idempotent."""
        vec = _embed(content)
        if vec is None:
            return False
        col = self._cols.get(collection)
        if col is None:
            log.warning("Unknown collection: %s", collection)
            return False
        meta = metadata or {}
        meta["source"] = collection
        try:
            col.upsert(ids=[doc_id], embeddings=[vec], documents=[content], metadatas=[meta])
            return True
        except Exception as e:
            log.warning("ChromaDB upsert failed: %s", e)
            return False

    def remove(self, doc_id: str, collection: str = "mark_knowledge") -> None:
        col = self._cols.get(collection)
        if col:
            try:
                col.delete(ids=[doc_id])
            except Exception:
                pass

    # ── Read ───────────────────────────────────────────────────────────────────

    def search(
        self,
        query:       str,
        top_k:       int   = 5,
        collections: list  = None,
        min_score:   float = 0.3,
    ) -> list[ChromaResult]:
        """
        Semantic search across one or more collections.
        Returns results merged and sorted by score.
        """
        vec = _embed(query)
        if vec is None:
            return []

        targets = [self._cols[c] for c in (collections or _COLLECTIONS) if c in self._cols]
        results: list[ChromaResult] = []

        for col in targets:
            try:
                r = col.query(
                    query_embeddings=[vec],
                    n_results=min(top_k, col.count() or 1),
                    include=["documents", "metadatas", "distances"],
                )
                for doc, meta, dist in zip(
                    r["documents"][0], r["metadatas"][0], r["distances"][0]
                ):
                    score = 1.0 - dist  # cosine: 0=identical, 2=opposite → convert
                    if score >= min_score:
                        results.append(ChromaResult(
                            id       = meta.get("id", ""),
                            content  = doc,
                            source   = meta.get("source", col.name),
                            score    = score,
                            metadata = meta,
                        ))
            except Exception as e:
                log.debug("ChromaDB search error in %s: %s", col.name, e)

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def count(self, collection: str = "mark_knowledge") -> int:
        col = self._cols.get(collection)
        return col.count() if col else 0

    def stats(self) -> dict:
        return {c: self._cols[c].count() for c in _COLLECTIONS}


# ─── Singleton ────────────────────────────────────────────────────────────────

_store: Optional[ChromaStore] = None
_lock  = threading.Lock()


def get_chroma_store() -> ChromaStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = ChromaStore()
    return _store
