"""
MARK III — Action Store

SQLite persistence for the Action Engine, replacing the original SQLAlchemy
(app.models.db.ActionRecord) dependency from the dormant FastAPI scaffolding.

Mirrors the pattern established by app/services/memory/fact_store.py:
thread-safe, synchronous sqlite3, single-file DB at the brain-server root.

Called from action_queue.py's async worker via asyncio.to_thread() since
sqlite3 is blocking — never call these methods directly from the event loop.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("markiii.actions.store")

_DB_PATH = Path(__file__).parents[3] / "action_store.db"


class ActionStore:
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
                CREATE TABLE IF NOT EXISTS actions (
                    id              TEXT PRIMARY KEY,
                    action_type     TEXT NOT NULL,
                    safety_level    TEXT NOT NULL,
                    parameters_json TEXT,
                    state           TEXT NOT NULL,
                    source          TEXT,
                    device_id       TEXT,
                    session_id      TEXT,
                    context_hint    TEXT,
                    result_json     TEXT,
                    error_message   TEXT,
                    retry_count     INTEGER DEFAULT 0,
                    max_retries     INTEGER DEFAULT 0,
                    timeout_seconds REAL DEFAULT 30.0,
                    approval_id     TEXT,
                    deferred_until  REAL,
                    created_at      REAL NOT NULL,
                    updated_at      REAL NOT NULL,
                    started_at      REAL,
                    completed_at    REAL
                );
                CREATE INDEX IF NOT EXISTS idx_actions_state  ON actions(state);
                CREATE INDEX IF NOT EXISTS idx_actions_device ON actions(device_id);
                CREATE INDEX IF NOT EXISTS idx_actions_type   ON actions(action_type);
            """)
            conn.commit()
        log.info("Action store ready: %s", self._path)

    def upsert(self, action) -> None:
        """Persist an Action (from base_action.Action). Insert or update by id."""
        result_json = json.dumps(action.result.to_dict()) if action.result else None
        params_json = json.dumps(action.parameters, default=str)

        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO actions
                   (id, action_type, safety_level, parameters_json, state, source,
                    device_id, session_id, context_hint, result_json, error_message,
                    retry_count, max_retries, timeout_seconds, approval_id,
                    deferred_until, created_at, updated_at, started_at, completed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     state=excluded.state, result_json=excluded.result_json,
                     error_message=excluded.error_message, retry_count=excluded.retry_count,
                     approval_id=excluded.approval_id, deferred_until=excluded.deferred_until,
                     updated_at=excluded.updated_at, started_at=excluded.started_at,
                     completed_at=excluded.completed_at""",
                (
                    action.id, action.action_type, action.safety_level, params_json,
                    action.state, action.source, action.device_id, action.session_id,
                    action.context_hint[:200] if action.context_hint else "",
                    result_json, action.error_message, action.retry_count,
                    action.max_retries, action.timeout_seconds, action.approval_id,
                    action.deferred_until, action.created_at, action.updated_at,
                    action.started_at, action.completed_at,
                ),
            )
            conn.commit()

    def get(self, action_id: str) -> Optional[dict]:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        return dict(row) if row else None

    def list_recent(self, limit: int = 20, device_id: str = "") -> list[dict]:
        where  = "WHERE device_id=?" if device_id else ""
        params = (device_id,) if device_id else ()
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM actions {where} ORDER BY updated_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self._lock, self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
            by_state = conn.execute(
                "SELECT state, COUNT(*) c FROM actions GROUP BY state"
            ).fetchall()
        return {"total": total, "by_state": {r["state"]: r["c"] for r in by_state}}


_store: Optional[ActionStore] = None
_store_lock = threading.Lock()


def get_action_store() -> ActionStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ActionStore()
    return _store
