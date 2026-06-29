"""
MARK III — Fact Store

Authoritative SQLite database for structured factual memory.
Every device retrieves facts from here. No local fact storage on clients.

This is Tier 1 memory — exact, versioned, authoritative.
ChromaDB (Tier 2) handles semantic/conceptual memory.

Schema:
  facts        — current fact values (one row per fact)
  fact_history — every revision of every fact

Categories (subject.predicate pattern):
  project.budget       → "Project Orphans", 10000, AUD
  project.deadline     → "PathwayAU MVP", "2026-09-01"
  person.email         → "John Smith", "john@example.com"
  preference.ide       → "MARK", "Cursor / VS Code"
  device.ip            → "Desktop", "192.168.4.85"
  organisation.name    → "Celluloid Solutions", "company"
  task.priority        → "MARK Mobile iOS", "high"
  goal.milestone       → "Architecture Freeze", "completed"
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("markiii.memory.facts")

_DB_PATH = Path(__file__).parents[3] / "structured_memory.db"


@dataclass
class Fact:
    id:          str
    category:    str          # "project.budget"
    subject:     str          # "Project Orphans"
    predicate:   str          # "budget"
    value:       str          # "10000" (normalized)
    raw_value:   str          # "10 thousand dollars" (original)
    unit:        str          # "AUD"
    confidence:  float        # 0.0-1.0
    confirmed:   bool         # True = user confirmed
    source:      str          # "voice" | "mobile" | "manual"
    revision:    int          # version number
    created_at:  str
    updated_at:  str
    owner_id:    str          # from UserProfile

    def display(self) -> str:
        val = f"{self.value} {self.unit}".strip() if self.unit else self.value
        return f"{self.subject} → {self.predicate}: {val}"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "category": self.category,
            "subject": self.subject, "predicate": self.predicate,
            "value": self.value, "raw_value": self.raw_value,
            "unit": self.unit, "confidence": self.confidence,
            "confirmed": self.confirmed, "source": self.source,
            "revision": self.revision,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


class FactStore:
    """
    Thread-safe SQLite store for structured facts.
    All MARK clients retrieve from this store via the brain server.
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._path = db_path
        self._lock = threading.RLock()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS facts (
                    id          TEXT PRIMARY KEY,
                    category    TEXT NOT NULL,
                    subject     TEXT NOT NULL,
                    predicate   TEXT NOT NULL,
                    value       TEXT NOT NULL,
                    raw_value   TEXT,
                    unit        TEXT DEFAULT '',
                    confidence  REAL DEFAULT 1.0,
                    confirmed   INTEGER DEFAULT 0,
                    source      TEXT DEFAULT 'voice',
                    revision    INTEGER DEFAULT 1,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    owner_id    TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS fact_history (
                    fact_id     TEXT NOT NULL,
                    revision    INTEGER NOT NULL,
                    value       TEXT,
                    raw_value   TEXT,
                    unit        TEXT,
                    changed_at  TEXT NOT NULL,
                    change_reason TEXT,
                    PRIMARY KEY (fact_id, revision)
                );

                CREATE INDEX IF NOT EXISTS idx_subject   ON facts(subject);
                CREATE INDEX IF NOT EXISTS idx_category  ON facts(category);
                CREATE INDEX IF NOT EXISTS idx_predicate ON facts(predicate);
                CREATE INDEX IF NOT EXISTS idx_confirmed ON facts(confirmed);
            """)
            conn.commit()
        log.info("Fact store ready: %s", self._path)

    # ── Write ──────────────────────────────────────────────────────────────────

    def upsert(
        self,
        subject:    str,
        predicate:  str,
        value:      str,
        raw_value:  str   = "",
        unit:       str   = "",
        confidence: float = 1.0,
        confirmed:  bool  = True,
        source:     str   = "voice",
        category:   str   = "",
        owner_id:   str   = "",
    ) -> Fact:
        """
        Insert or update a fact. If the fact already exists, creates a new revision.
        Returns the current fact.
        """
        if not category:
            category = self._infer_category(subject, predicate)
        now = datetime.now().isoformat(timespec="seconds")

        with self._lock, self._conn() as conn:
            existing = conn.execute(
                "SELECT * FROM facts WHERE subject=? AND predicate=? ORDER BY revision DESC LIMIT 1",
                (subject.strip(), predicate.strip()),
            ).fetchone()

            if existing:
                new_rev = existing["revision"] + 1
                # Archive old revision
                conn.execute(
                    "INSERT OR IGNORE INTO fact_history VALUES (?,?,?,?,?,?,?)",
                    (existing["id"], existing["revision"], existing["value"],
                     existing["raw_value"], existing["unit"], now, "updated"),
                )
                # Update
                conn.execute(
                    """UPDATE facts SET value=?, raw_value=?, unit=?, confidence=?,
                       confirmed=?, source=?, revision=?, updated_at=?
                       WHERE id=?""",
                    (value, raw_value or value, unit, confidence, int(confirmed),
                     source, new_rev, now, existing["id"]),
                )
                fact_id = existing["id"]
                revision = new_rev
                created_at = existing["created_at"]
                if value != existing["value"]:
                    log.info("Fact updated: %s.%s = %s (rev %d)", subject, predicate, value, new_rev)
            else:
                fact_id  = str(uuid.uuid4())[:12]
                revision = 1
                created_at = now
                conn.execute(
                    """INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fact_id, category, subject.strip(), predicate.strip(),
                     value, raw_value or value, unit, confidence,
                     int(confirmed), source, revision, created_at, now, owner_id),
                )
                log.info("Fact stored: %s.%s = %s", subject, predicate, value)

            conn.commit()

        return Fact(
            id=fact_id, category=category, subject=subject, predicate=predicate,
            value=value, raw_value=raw_value or value, unit=unit,
            confidence=confidence, confirmed=confirmed, source=source,
            revision=revision, created_at=created_at, updated_at=now,
            owner_id=owner_id,
        )

    def confirm(self, fact_id: str) -> bool:
        """Mark a fact as confirmed by the user."""
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE facts SET confirmed=1 WHERE id=?", (fact_id,))
            conn.commit()
        return True

    def delete(self, fact_id: str) -> bool:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM facts WHERE id=?", (fact_id,))
            conn.commit()
        return True

    # ── Read ───────────────────────────────────────────────────────────────────

    def get(self, subject: str, predicate: str) -> Optional[Fact]:
        """Exact lookup by subject + predicate."""
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM facts WHERE subject=? AND predicate=? ORDER BY revision DESC LIMIT 1",
                (subject.strip(), predicate.strip()),
            ).fetchone()
        return self._row_to_fact(row) if row else None

    def search(self, subject: str = "", predicate: str = "", category: str = "") -> list[Fact]:
        """Flexible search by any combination of fields."""
        conditions, params = [], []
        if subject:    conditions.append("LOWER(subject) LIKE ?");   params.append(f"%{subject.lower()}%")
        if predicate:  conditions.append("LOWER(predicate) LIKE ?"); params.append(f"%{predicate.lower()}%")
        if category:   conditions.append("category=?");              params.append(category)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM facts {where} ORDER BY confirmed DESC, confidence DESC, updated_at DESC",
                params,
            ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def get_history(self, fact_id: str) -> list[dict]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM fact_history WHERE fact_id=? ORDER BY revision DESC",
                (fact_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all(self, confirmed_only: bool = False) -> list[Fact]:
        where = "WHERE confirmed=1" if confirmed_only else ""
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM facts {where} ORDER BY category, subject",
            ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def stats(self) -> dict:
        with self._lock, self._conn() as conn:
            total     = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            confirmed = conn.execute("SELECT COUNT(*) FROM facts WHERE confirmed=1").fetchone()[0]
            cats      = conn.execute("SELECT category, COUNT(*) as c FROM facts GROUP BY category").fetchall()
        return {
            "total": total, "confirmed": confirmed,
            "by_category": {r["category"]: r["c"] for r in cats},
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_fact(row: sqlite3.Row) -> Fact:
        return Fact(
            id=row["id"], category=row["category"],
            subject=row["subject"], predicate=row["predicate"],
            value=row["value"], raw_value=row["raw_value"] or row["value"],
            unit=row["unit"] or "", confidence=row["confidence"],
            confirmed=bool(row["confirmed"]), source=row["source"],
            revision=row["revision"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            owner_id=row["owner_id"] or "",
        )

    @staticmethod
    def _infer_category(subject: str, predicate: str) -> str:
        """Infer category from subject and predicate keywords."""
        pred_l = predicate.lower()
        subj_l = subject.lower()
        if any(w in pred_l for w in ("budget", "cost", "price", "amount", "revenue")):
            return "project.budget"
        if any(w in pred_l for w in ("deadline", "due", "date", "launch")):
            return "project.deadline"
        if any(w in pred_l for w in ("email", "phone", "contact")):
            return "person.contact"
        if any(w in pred_l for w in ("ide", "editor", "language", "framework", "tool")):
            return "preference.tool"
        if any(w in pred_l for w in ("goal", "objective", "milestone")):
            return "goal.milestone"
        if any(w in pred_l for w in ("ip", "host", "port", "address")):
            return "device.network"
        if any(w in subj_l for w in ("project", "app", "system", "platform")):
            return "project.info"
        return "general.fact"


# ─── Singleton ────────────────────────────────────────────────────────────────

_store: Optional[FactStore] = None
_store_lock = threading.Lock()


def get_fact_store() -> FactStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = FactStore()
    return _store
