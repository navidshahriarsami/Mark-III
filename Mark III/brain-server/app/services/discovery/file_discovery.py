"""
MARK III — File Discovery

Builds a searchable index of files across user-meaningful directories, so
voice file search is an instant SQLite lookup instead of a live filesystem
walk on every query (the previous behavior in file_executor.py — slow and
gets slower as the index would need to be rebuilt from scratch every time).

Scope decision: indexes the user's personal directories (Desktop, Documents,
Downloads, Pictures, Videos, Music, OneDrive) — not the entire filesystem.
Indexing every drive/directory on the machine would mean scanning Windows
system files, every node_modules in every repo, and multi-terabyte AppData
caches: slow, mostly noise, and not what "find my file" voice queries need.

ROOTS below is the whole policy — edit this list to expand or narrow scope.
Excluded directory names are skipped at any depth (node_modules, .git, etc.).
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("markiii.discovery.files")

# Directories indexed, by Windows special-folder env var. Edit this list to
# change scope — this is the single source of truth for "every directory".
_ROOT_ENV_VARS = ["USERPROFILE"]
_ROOT_SUBDIRS  = [
    "Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive",
]

# Skipped at any depth — noise that would otherwise dominate the index.
_EXCLUDE_DIR_NAMES = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "$RECYCLE.BIN", "System Volume Information", ".cache", "AppData",
    "dist", "build", ".next", "target", "bin", "obj",
}

MAX_FILES   = 250_000   # safety cap — stop indexing past this regardless of scope
MAX_DEPTH   = 12         # safety cap on recursion depth per root


def _get_roots() -> list[Path]:
    home = Path(os.path.expanduser("~"))
    roots = []
    for sub in _ROOT_SUBDIRS:
        p = home / sub
        if p.exists() and p.is_dir():
            roots.append(p)
    return roots


def scan_files() -> list[dict]:
    """
    Walk all configured roots and return a list of
    {path, name, ext, size, mtime} dicts. Never raises — best-effort
    background infrastructure, not a user-facing action.
    """
    t0 = time.monotonic()
    results: list[dict] = []
    roots = _get_roots()

    for root in roots:
        root_depth = len(root.parts)
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                # Prune excluded directories in-place (os.walk respects this)
                dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIR_NAMES]

                depth = len(Path(dirpath).parts) - root_depth
                if depth > MAX_DEPTH:
                    dirnames[:] = []
                    continue

                for fname in filenames:
                    if len(results) >= MAX_FILES:
                        log.warning("File scan hit MAX_FILES cap (%d) — stopping", MAX_FILES)
                        return results
                    fpath = Path(dirpath) / fname
                    try:
                        stat = fpath.stat()
                        results.append({
                            "path":  str(fpath),
                            "name":  fname,
                            "ext":   fpath.suffix.lower().lstrip("."),
                            "size":  stat.st_size,
                            "mtime": stat.st_mtime,
                        })
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError) as e:
            log.debug("Skipping unreadable path under %s: %s", root, e)
            continue

    log.info(
        "File scan complete: %d files across %d roots in %.1fs",
        len(results), len(roots), time.monotonic() - t0,
    )
    return results


def run_and_store() -> int:
    """Scan and persist to the discovery store. Returns count of files stored."""
    from app.services.discovery.discovery_store import get_discovery_store

    store   = get_discovery_store()
    scan_id = store.log_scan_start("files")
    try:
        files = scan_files()
        count = store.replace_files(files)
        store.log_scan_end(scan_id, count)
        return count
    except Exception as e:
        store.log_scan_end(scan_id, 0, error=str(e))
        log.error("File discovery scan failed: %s", e)
        return 0
