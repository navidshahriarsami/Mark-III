"""
MARK III — Repository Observer

Watches the repository for changes to engineering knowledge:
  docs/architecture/    ADRs, roadmaps, knowledge
  docs/adr/
  docs/roadmap/
  docs/knowledge/
  docs/api/
  MARK_VERSION.md
  CHANGELOG.md
  MARK_III_MANIFEST.md
  MARK_HOME.md
  CLAUDE.md

When a watched file changes:
  1. Log the change as a governance event
  2. Trigger ChromaDB re-index for the changed file
  3. Refresh knowledge cache

Extends vault_indexer: vault_indexer handles 60s polling for Obsidian content.
Repository Observer adds governance-level event tracking.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

log = logging.getLogger("markiii.governance.observer")

_REPO_ROOT   = Path(__file__).parents[4]
_STATE_PATH  = _REPO_ROOT / "brain-server" / "repo_observer_state.json"
_EVENTS_PATH = _REPO_ROOT / "brain-server" / "repo_observer_events.json"

_WATCH_PATTERNS = [
    "docs/architecture/*.md",
    "docs/adr/*.md",
    "docs/roadmap/*.md",
    "docs/knowledge/*.md",
    "docs/api/*.md",
    "MARK_VERSION.md",
    "CHANGELOG.md",
    "MARK_III_MANIFEST.md",
    "MARK_HOME.md",
    "CLAUDE.md",
]


@dataclass
class RepositoryEvent:
    timestamp: str
    event:     str          # "modified" | "created" | "deleted"
    path:      str
    domain:    str          # "architecture" | "adr" | "roadmap" | "meta"


class RepositoryObserver:
    """
    File-hash watchdog for repository documentation.
    Runs in a background thread; poll interval default 30s.
    """

    def __init__(self, poll_interval: int = 30) -> None:
        self._interval = poll_interval
        self._hashes:  dict[str, str]  = {}
        self._events:  list[dict]      = []
        self._running  = False
        self._thread:  threading.Thread | None = None
        self._lock     = threading.Lock()
        self._load_state()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._loop, name="repo-observer", daemon=True)
        self._thread.start()
        log.info("Repository Observer started (interval=%ds)", self._interval)

    def stop(self) -> None:
        self._running = False

    def get_recent_events(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return list(self._events[-limit:])

    # ── Internal ──────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                self._scan()
            except Exception as e:
                log.debug("Observer scan error: %s", e)
            time.sleep(self._interval)

    def _scan(self) -> None:
        changed: list[Path] = []
        for pattern in _WATCH_PATTERNS:
            for path in _REPO_ROOT.glob(pattern):
                rel  = str(path.relative_to(_REPO_ROOT))
                h    = _file_hash(path)
                prev = self._hashes.get(rel)
                if h != prev:
                    event_type = "created" if prev is None else "modified"
                    self._hashes[rel] = h
                    changed.append(path)
                    self._record_event(event_type, rel, _classify_path(rel))
                    log.info("Repo change detected: %s [%s]", rel, event_type)

        if changed:
            self._save_state()
            self._trigger_reindex(changed)

    def _trigger_reindex(self, paths: list[Path]) -> None:
        """Re-embed changed markdown files into ChromaDB."""
        try:
            from app.services.knowledge.obsidian_bridge import get_obsidian_bridge
            bridge = get_obsidian_bridge()
            for p in paths:
                if p.suffix == ".md":
                    bridge.index_file(str(p))
        except Exception as e:
            log.debug("Re-index error: %s", e)

    def _record_event(self, event: str, path: str, domain: str) -> None:
        ev = RepositoryEvent(
            timestamp = datetime.now().isoformat(timespec="seconds"),
            event     = event,
            path      = path,
            domain    = domain,
        )
        with self._lock:
            self._events.append(asdict(ev))
            if len(self._events) > 500:
                self._events = self._events[-500:]
        try:
            _EVENTS_PATH.write_text(
                json.dumps({"events": self._events[-100:]}, indent=2)
            )
        except Exception:
            pass

    def _load_state(self) -> None:
        try:
            if _STATE_PATH.exists():
                self._hashes = json.loads(_STATE_PATH.read_text())
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            _STATE_PATH.write_text(json.dumps(self._hashes, indent=2))
        except Exception:
            pass


def _file_hash(path: Path) -> str:
    try:
        return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
    except Exception:
        return ""


def _classify_path(rel_path: str) -> str:
    if "/adr/" in rel_path:        return "adr"
    if "/architecture/" in rel_path: return "architecture"
    if "/roadmap/" in rel_path:    return "roadmap"
    if "/knowledge/" in rel_path:  return "knowledge"
    if "/api/" in rel_path:        return "api"
    return "meta"


# ── Singleton ─────────────────────────────────────────────────────────────────

_observer: RepositoryObserver | None = None
_obs_lock = threading.Lock()


def get_repository_observer() -> RepositoryObserver:
    global _observer
    if _observer is None:
        with _obs_lock:
            if _observer is None:
                _observer = RepositoryObserver()
    return _observer
