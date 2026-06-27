"""
MARK III — Vector Memory Store

SQLite-backed semantic memory using Ollama embeddings (nomic-embed-text).
Enables MARK to recall decisions, architecture, user preferences, and
phase history across context window boundaries.

Usage:
    from app.services.memory.vector_store import get_memory_store
    store = get_memory_store()

    # Store a memory
    store.remember("Qwen 2.5:7b is the local LLM — 2.5:3b was too weak", category="architecture")

    # Recall relevant memories
    results = store.recall("which LLM model does MARK use?", top_k=5)
    for r in results:
        print(r.content, r.score)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import numpy as np

log = logging.getLogger("markiii.memory.vector")

_DB_PATH = Path(__file__).parents[3] / "mark_memory.db"
_EMBED_MODEL = "nomic-embed-text"
_EMBED_DIM   = 768   # nomic-embed-text output dimension
_OLLAMA_BASE = "http://localhost:11434"


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class Memory:
    id:         int
    content:    str
    category:   str    # architecture | decision | fix | preference | phase | context
    tags:       list[str]
    phase:      str
    score:      float  # cosine similarity — only set when returned from recall()
    created_at: str
    updated_at: str


# ─── Embedding ────────────────────────────────────────────────────────────────

def _embed(text: str) -> Optional[np.ndarray]:
    """Get embedding vector from Ollama nomic-embed-text."""
    try:
        r = httpx.post(
            f"{_OLLAMA_BASE}/api/embed",
            json={"model": _EMBED_MODEL, "input": text},
            timeout=10.0,
        )
        r.raise_for_status()
        vec = r.json()["embeddings"][0]
        arr = np.array(vec, dtype=np.float32)
        # Normalise for cosine similarity
        norm = np.linalg.norm(arr)
        return arr / norm if norm > 0 else arr
    except Exception as e:
        log.warning("Embedding failed: %s", e)
        return None


def _vec_to_blob(vec: np.ndarray) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec.tolist())


def _blob_to_vec(blob: bytes) -> np.ndarray:
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # both normalised so dot = cosine


# ─── VectorStore ──────────────────────────────────────────────────────────────

class VectorStore:
    """
    SQLite vector memory for MARK III.

    Schema:
        memories (id, content, category, tags_json, phase, embedding, created_at, updated_at)
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path))

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    content     TEXT    NOT NULL,
                    category    TEXT    NOT NULL DEFAULT 'context',
                    tags_json   TEXT    NOT NULL DEFAULT '[]',
                    phase       TEXT    NOT NULL DEFAULT '',
                    embedding   BLOB,
                    created_at  TEXT    NOT NULL,
                    updated_at  TEXT    NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON memories(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_phase    ON memories(phase)")
            conn.commit()
        log.info("Vector store ready: %s", self._path)

    # ── Write ──────────────────────────────────────────────────────────────────

    def remember(
        self,
        content:  str,
        category: str        = "context",
        tags:     list[str]  = None,
        phase:    str        = "",
    ) -> int:
        """
        Store a memory with its embedding.
        Returns the new memory ID.
        """
        tags     = tags or []
        now      = datetime.now().isoformat(timespec="seconds")
        vec      = _embed(content)
        blob     = _vec_to_blob(vec) if vec is not None else None

        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO memories (content, category, tags_json, phase, embedding, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (content, category, json.dumps(tags), phase, blob, now, now),
            )
            conn.commit()
            mid = cur.lastrowid

        log.debug("Remembered [%s] id=%d: %s", category, mid, content[:60])
        return mid

    def update(self, memory_id: int, content: str) -> None:
        """Update an existing memory's content and re-embed."""
        now  = datetime.now().isoformat(timespec="seconds")
        vec  = _embed(content)
        blob = _vec_to_blob(vec) if vec is not None else None
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE memories SET content=?, embedding=?, updated_at=? WHERE id=?",
                (content, blob, now, memory_id),
            )
            conn.commit()

    def forget(self, memory_id: int) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            conn.commit()

    # ── Read ───────────────────────────────────────────────────────────────────

    def recall(
        self,
        query:    str,
        top_k:   int  = 5,
        category: str = "",
        min_score: float = 0.3,
    ) -> list[Memory]:
        """
        Semantic search: find memories most relevant to the query.
        Returns up to top_k results sorted by cosine similarity.
        """
        q_vec = _embed(query)
        if q_vec is None:
            return self._fallback_search(query, top_k, category)

        with self._lock, self._conn() as conn:
            where = "WHERE embedding IS NOT NULL"
            params: list = []
            if category:
                where += " AND category=?"
                params.append(category)
            rows = conn.execute(
                f"SELECT id, content, category, tags_json, phase, embedding, created_at, updated_at FROM memories {where}",
                params,
            ).fetchall()

        scored = []
        for row in rows:
            blob = row[5]
            if blob:
                vec   = _blob_to_vec(blob)
                score = _cosine(q_vec, vec)
                if score >= min_score:
                    scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, row in scored[:top_k]:
            results.append(Memory(
                id=row[0], content=row[1], category=row[2],
                tags=json.loads(row[3]), phase=row[4],
                score=score,
                created_at=row[6], updated_at=row[7],
            ))
        return results

    def _fallback_search(self, query: str, top_k: int, category: str) -> list[Memory]:
        """Keyword fallback when Ollama is unavailable."""
        terms = query.lower().split()
        with self._lock, self._conn() as conn:
            where = "WHERE " + " OR ".join(["LOWER(content) LIKE ?" for _ in terms])
            params = [f"%{t}%" for t in terms]
            if category:
                where += " AND category=?"
                params.append(category)
            rows = conn.execute(
                f"SELECT id, content, category, tags_json, phase, created_at, updated_at FROM memories {where} LIMIT ?",
                params + [top_k],
            ).fetchall()
        return [Memory(id=r[0], content=r[1], category=r[2],
                       tags=json.loads(r[3]), phase=r[4], score=0.0,
                       created_at=r[5], updated_at=r[6]) for r in rows]

    def get_by_category(self, category: str) -> list[Memory]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT id, content, category, tags_json, phase, created_at, updated_at FROM memories WHERE category=? ORDER BY updated_at DESC",
                (category,),
            ).fetchall()
        return [Memory(id=r[0], content=r[1], category=r[2],
                       tags=json.loads(r[3]), phase=r[4], score=1.0,
                       created_at=r[5], updated_at=r[6]) for r in rows]

    def stats(self) -> dict:
        with self._lock, self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_cat = conn.execute(
                "SELECT category, COUNT(*) FROM memories GROUP BY category"
            ).fetchall()
        return {"total": total, "by_category": dict(by_cat)}


# ─── Singleton ────────────────────────────────────────────────────────────────

_store: Optional[VectorStore] = None
_store_lock = threading.Lock()


def get_memory_store() -> VectorStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = VectorStore()
    return _store
