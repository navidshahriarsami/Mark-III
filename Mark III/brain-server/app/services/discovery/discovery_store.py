"""
MARK III — Discovery Store

SQLite persistence for MARK's self-built knowledge of the machine it runs on:
  - Installed applications (Start Menu shortcuts, UWP/Store apps)
  - Indexed files across user-meaningful directories

This is what makes app launch and file search instant and reliable instead
of guessing via shutil.which()/os.startfile() or walking the filesystem live
on every query. Mirrors the fact_store.py / action_store.py pattern: plain
sqlite3, thread-safe, single-file DB at the brain-server root.

MARK builds this itself, in the background, on its own machine. Nothing here
depends on Claude or any external search.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("markiii.discovery.store")

_DB_PATH = Path(__file__).parents[3] / "discovery_store.db"


class DiscoveryStore:
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
                CREATE TABLE IF NOT EXISTS apps (
                    name        TEXT NOT NULL,
                    name_norm   TEXT NOT NULL,
                    target      TEXT NOT NULL,
                    source      TEXT NOT NULL,
                    indexed_at  REAL NOT NULL,
                    PRIMARY KEY (name_norm, target)
                );
                CREATE INDEX IF NOT EXISTS idx_apps_norm ON apps(name_norm);

                CREATE TABLE IF NOT EXISTS files (
                    path        TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    name_norm   TEXT NOT NULL,
                    ext         TEXT,
                    size        INTEGER,
                    mtime       REAL,
                    indexed_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_files_norm ON files(name_norm);
                CREATE INDEX IF NOT EXISTS idx_files_ext  ON files(ext);

                CREATE TABLE IF NOT EXISTS scan_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_type   TEXT NOT NULL,
                    started_at  REAL NOT NULL,
                    finished_at REAL,
                    item_count  INTEGER,
                    error       TEXT
                );
            """)
            conn.commit()
        log.info("Discovery store ready: %s", self._path)

    # ── Apps ──────────────────────────────────────────────────────────────────

    def replace_apps(self, apps: list[dict]) -> int:
        """
        Atomically replace the entire apps table with a fresh scan result.
        Each app dict: {name, target, source}
        """
        import time
        now = time.time()
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM apps")
            conn.executemany(
                "INSERT OR IGNORE INTO apps (name, name_norm, target, source, indexed_at) VALUES (?,?,?,?,?)",
                [(a["name"], a["name"].lower().strip(), a["target"], a["source"], now) for a in apps],
            )
            conn.commit()
        log.info("Apps index replaced: %d apps", len(apps))
        return len(apps)

    def search_apps(self, query: str, limit: int = 5) -> list[dict]:
        """Substring search against normalized app names."""
        q = f"%{query.lower().strip()}%"
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM apps WHERE name_norm LIKE ? ORDER BY LENGTH(name_norm) ASC LIMIT ?",
                (q, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_app_names(self) -> list[str]:
        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT DISTINCT name_norm FROM apps").fetchall()
        return [r["name_norm"] for r in rows]

    def get_app_by_norm(self, name_norm: str) -> Optional[dict]:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM apps WHERE name_norm = ? LIMIT 1", (name_norm,)
            ).fetchone()
        return dict(row) if row else None

    # ── Files ─────────────────────────────────────────────────────────────────

    def replace_files(self, files: list[dict]) -> int:
        """
        Atomically replace the entire files table with a fresh scan result.
        Each file dict: {path, name, ext, size, mtime}
        """
        import time
        now = time.time()
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM files")
            conn.executemany(
                """INSERT OR IGNORE INTO files
                   (path, name, name_norm, ext, size, mtime, indexed_at)
                   VALUES (?,?,?,?,?,?,?)""",
                [
                    (f["path"], f["name"], f["name"].lower(), f.get("ext", ""),
                     f.get("size", 0), f.get("mtime", 0), now)
                    for f in files
                ],
            )
            conn.commit()
        log.info("Files index replaced: %d files", len(files))
        return len(files)

    def search_files(self, query: str, limit: int = 50) -> list[dict]:
        q = f"%{query.lower().strip()}%"
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM files WHERE name_norm LIKE ? ORDER BY LENGTH(name_norm) ASC LIMIT ?",
                (q, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Scan log ──────────────────────────────────────────────────────────────

    def log_scan_start(self, scan_type: str) -> int:
        import time
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO scan_log (scan_type, started_at) VALUES (?, ?)",
                (scan_type, time.time()),
            )
            conn.commit()
            return cur.lastrowid

    def log_scan_end(self, scan_id: int, item_count: int, error: str = "") -> None:
        import time
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE scan_log SET finished_at=?, item_count=?, error=? WHERE id=?",
                (time.time(), item_count, error, scan_id),
            )
            conn.commit()

    def stats(self) -> dict:
        with self._lock, self._conn() as conn:
            apps_n  = conn.execute("SELECT COUNT(*) FROM apps").fetchone()[0]
            files_n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            last_scan = conn.execute(
                "SELECT * FROM scan_log ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return {
            "apps_indexed": apps_n,
            "files_indexed": files_n,
            "last_scan": dict(last_scan) if last_scan else None,
        }


_store: Optional[DiscoveryStore] = None
_store_lock = threading.Lock()


def get_discovery_store() -> DiscoveryStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = DiscoveryStore()
    return _store
