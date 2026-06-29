"""
MARK III — Vault Indexer

Indexes an Obsidian vault into ChromaDB for semantic search.
Watches for file changes and performs incremental updates —
no full rebuild unless explicitly requested.

Monitors:
  - New .md files     → parse + embed
  - Modified .md files → re-embed
  - Deleted .md files  → remove from ChromaDB
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from app.services.knowledge.markdown_parser import parse_file

log = logging.getLogger("markiii.knowledge.indexer")

_STATE_FILE = Path(__file__).parents[3] / "vault_index_state.json"


class VaultIndexer:
    """
    Indexes an Obsidian vault into ChromaDB.
    Tracks file hashes to detect changes without re-reading unchanged files.
    Runs a background watcher thread for incremental updates.
    """

    def __init__(self, vault_path: Path, chroma_store, poll_interval_s: int = 60) -> None:
        self.vault_path      = vault_path
        self._chroma         = chroma_store
        self._poll_interval  = poll_interval_s
        self._file_hashes:   dict[str, str] = {}  # path → md5
        self._lock           = threading.Lock()
        self._running        = False
        self._watcher:       Optional[threading.Thread] = None
        self._load_state()

    # ── State persistence ──────────────────────────────────────────────────────

    def _load_state(self) -> None:
        if _STATE_FILE.exists():
            try:
                self._file_hashes = json.loads(_STATE_FILE.read_text())
                log.info("Vault index state loaded: %d files tracked", len(self._file_hashes))
            except Exception:
                self._file_hashes = {}

    def _save_state(self) -> None:
        try:
            _STATE_FILE.write_text(json.dumps(self._file_hashes, indent=2))
        except Exception as e:
            log.debug("State save failed: %s", e)

    @staticmethod
    def _hash(path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()

    # ── Indexing ───────────────────────────────────────────────────────────────

    def full_index(self, force: bool = False) -> dict:
        """
        Walk the entire vault and index new/changed files.
        If force=True, re-index all files regardless of hash.
        Returns stats.
        """
        if not self.vault_path.exists():
            log.warning("Vault not found: %s", self.vault_path)
            return {"error": "vault not found"}

        md_files = list(self.vault_path.rglob("*.md"))
        log.info("Vault scan: %d markdown files in %s", len(md_files), self.vault_path)

        stats = {"total": len(md_files), "indexed": 0, "skipped": 0, "errors": 0}

        for md_file in md_files:
            if self._should_skip(md_file):
                stats["skipped"] += 1
                continue
            try:
                h = self._hash(md_file)
                key = str(md_file)
                if not force and self._file_hashes.get(key) == h:
                    stats["skipped"] += 1
                    continue
                if self._index_file(md_file):
                    with self._lock:
                        self._file_hashes[key] = h
                    stats["indexed"] += 1
                else:
                    stats["errors"] += 1
            except Exception as e:
                log.debug("Index error %s: %s", md_file.name, e)
                stats["errors"] += 1

        self._save_state()
        log.info("Vault index complete: %s", stats)
        return stats

    def _index_file(self, file_path: Path) -> bool:
        """Parse and embed a single markdown file."""
        doc = parse_file(file_path)
        if doc is None or doc.is_empty:
            return False

        chunks = doc.chunks_for_embedding()
        if not chunks:
            return False

        # Remove old chunks for this file
        self._remove_file_chunks(file_path)

        # Add new chunks
        success_count = 0
        for i, (text, meta) in enumerate(chunks):
            doc_id = f"obs_{hashlib.md5(str(file_path).encode()).hexdigest()[:12]}_{i}"
            meta["chunk_index"] = i
            meta["total_chunks"] = len(chunks)
            meta["word_count"]   = doc.word_count
            if self._chroma.add(text, doc_id=doc_id, collection="obsidian", metadata=meta):
                success_count += 1

        if success_count > 0:
            log.debug("Indexed %s: %d chunks", file_path.name, success_count)
        return success_count > 0

    def _remove_file_chunks(self, file_path: Path) -> None:
        """Remove all ChromaDB chunks for a given file."""
        try:
            col = self._chroma._cols.get("obsidian")
            if not col:
                return
            file_str = str(file_path)
            results = col.get(where={"file": file_str}, include=["metadatas"])
            if results and results.get("ids"):
                col.delete(ids=results["ids"])
                log.debug("Removed %d old chunks for %s", len(results["ids"]), file_path.name)
        except Exception as e:
            log.debug("Remove chunks error: %s", e)

    def remove_file(self, file_path: Path) -> None:
        """Called when a file is deleted from the vault."""
        self._remove_file_chunks(file_path)
        with self._lock:
            self._file_hashes.pop(str(file_path), None)
        self._save_state()

    @staticmethod
    def _should_skip(path: Path) -> bool:
        """Skip hidden files, Obsidian system folders, and templates."""
        parts = path.parts
        skip_dirs = {".obsidian", ".trash", "templates", "Templates", "_attachments"}
        return any(p in skip_dirs or p.startswith(".") for p in parts)

    # ── Background watcher ─────────────────────────────────────────────────────

    def start_watching(self) -> None:
        """Start background thread that polls for vault changes."""
        self._running = True
        self._watcher = threading.Thread(
            target=self._watch_loop, daemon=True, name="vault-watcher"
        )
        self._watcher.start()
        log.info("Vault watcher started (poll every %ds)", self._poll_interval)

    def stop_watching(self) -> None:
        self._running = False

    def _watch_loop(self) -> None:
        """Poll the vault directory for changes."""
        while self._running:
            try:
                self._incremental_scan()
            except Exception as e:
                log.debug("Vault scan error: %s", e)
            time.sleep(self._poll_interval)

    def _incremental_scan(self) -> None:
        """Check for new, modified, or deleted files."""
        if not self.vault_path.exists():
            return

        current_files = {
            str(p): p
            for p in self.vault_path.rglob("*.md")
            if not self._should_skip(p)
        }

        # Detect new + modified
        changed = []
        with self._lock:
            tracked = dict(self._file_hashes)

        for path_str, path in current_files.items():
            h = self._hash(path)
            if tracked.get(path_str) != h:
                changed.append((path, h))

        # Detect deleted
        deleted = [k for k in tracked if k not in current_files]

        for path, h in changed:
            if self._index_file(path):
                with self._lock:
                    self._file_hashes[str(path)] = h
                log.info("Vault update: %s re-indexed", path.name)

        for path_str in deleted:
            self.remove_file(Path(path_str))
            log.info("Vault update: %s removed from index", Path(path_str).name)

        if changed or deleted:
            self._save_state()
