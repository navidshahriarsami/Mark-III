"""
MARK III — File Executor (Phase 12B)

Handles:
  SAFE:      search_files, read_file, open_file
  CAUTION:   copy_file, create_file, create_folder, move_file
  DANGEROUS: delete_file, rename_file

All paths are resolved with pathlib.  Symlinks are not followed
for deletions (symlink itself is removed, not its target).

Safety rails:
  - Blocked root paths: system dirs (C:\\Windows, /etc, /sys, /proc)
  - Max file read: 1MB by default (configurable per call)
  - Recursive delete requires explicit recursive=True parameter
  - Files are moved to recycle bin on Windows if send2trash is available,
    otherwise permanently deleted (after policy approval)
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import pathlib
import platform
import shutil
import time
from typing import Optional

from app.services.actions.base_action import Action, ActionResult, ActionType

logger = logging.getLogger(__name__)

_PLATFORM = platform.system()

# Optional: send2trash for safer deletion on Windows/macOS
try:
    import send2trash
    _TRASH_AVAILABLE = True
except ImportError:
    _TRASH_AVAILABLE = False

# Optional: open file in default app
try:
    import subprocess
    _SUBPROCESS_AVAILABLE = True
except ImportError:
    _SUBPROCESS_AVAILABLE = False

# Paths that are never touched
_BLOCKED_ROOTS: set[str] = {
    # Windows
    "C:\\Windows", "C:\\Windows\\System32", "C:\\Program Files",
    # macOS / Linux
    "/etc", "/sys", "/proc", "/dev", "/boot", "/usr/bin", "/bin", "/sbin",
}

MAX_READ_BYTES = 1_000_000   # 1MB


class FileExecutor:

    async def run(self, action: Action) -> ActionResult:
        t0 = time.monotonic()
        try:
            result = await self._dispatch(action)
        except Exception as exc:
            result = ActionResult(success=False, error=str(exc))
        result.latency_ms = (time.monotonic() - t0) * 1000
        return result

    async def _dispatch(self, action: Action) -> ActionResult:
        t = action.action_type
        p = action.parameters

        if t == ActionType.SEARCH_FILES:
            return await asyncio.to_thread(
                self._search_files,
                p["pattern"],
                p.get("root_path"),
                int(p.get("max_results", 50)),
            )
        if t == ActionType.READ_FILE:
            return await asyncio.to_thread(
                self._read_file, p["path"], int(p.get("max_bytes", MAX_READ_BYTES))
            )
        if t == ActionType.OPEN_FILE:
            return await asyncio.to_thread(self._open_file, p["path"])
        if t == ActionType.COPY_FILE:
            return await asyncio.to_thread(self._copy_file, p["src"], p["dst"])
        if t == ActionType.CREATE_FILE:
            return await asyncio.to_thread(
                self._create_file, p["path"], p.get("content", "")
            )
        if t == ActionType.CREATE_FOLDER:
            return await asyncio.to_thread(self._create_folder, p["path"])
        if t == ActionType.MOVE_FILE:
            return await asyncio.to_thread(self._move_file, p["src"], p["dst"])
        if t == ActionType.DELETE_FILE:
            return await asyncio.to_thread(
                self._delete_file, p["path"], bool(p.get("recursive", False))
            )
        if t == ActionType.RENAME_FILE:
            return await asyncio.to_thread(self._rename_file, p["path"], p["new_name"])

        return ActionResult(success=False, error=f"Unknown file action: {t}")

    # ------------------------------------------------------------------
    # Guard
    # ------------------------------------------------------------------

    def _guard(self, path_str: str) -> Optional[str]:
        """Return error string if path is blocked, else None."""
        try:
            p = pathlib.Path(path_str).resolve()
        except Exception:
            return f"Invalid path: {path_str!r}"
        for blocked in _BLOCKED_ROOTS:
            try:
                p.relative_to(blocked)
                return f"Access to '{blocked}' is not permitted"
            except ValueError:
                pass
        return None

    # ------------------------------------------------------------------
    # SAFE: search files
    # ------------------------------------------------------------------

    def _search_files(
        self, pattern: str, root_path: Optional[str], max_results: int
    ) -> ActionResult:
        # No explicit root requested — query MARK's own background-built file
        # index (discovery_engine.md) instead of walking the filesystem live.
        # Indexed scope: Desktop/Documents/Downloads/Pictures/Videos/Music/
        # OneDrive (see file_discovery.py _ROOT_SUBDIRS). Falls through to a
        # live walk below if the index is empty (not yet scanned) or a
        # specific root_path was given that's outside the indexed scope.
        if not root_path:
            try:
                from app.services.discovery.discovery_store import get_discovery_store
                store = get_discovery_store()
                hits  = store.search_files(pattern, limit=max_results)
                if hits:
                    return ActionResult(
                        success  = True,
                        output   = [h["path"] for h in hits],
                        metadata = {"count": len(hits), "source": "discovery_index", "pattern": pattern},
                    )
                if store.stats().get("files_indexed", 0) > 0:
                    # Index is built and simply has no match — trust it, skip the slow walk.
                    return ActionResult(
                        success  = True,
                        output   = [],
                        metadata = {"count": 0, "source": "discovery_index", "pattern": pattern},
                    )
            except Exception:
                pass   # index unavailable — fall through to live walk

        root = pathlib.Path(root_path) if root_path else pathlib.Path.home()
        if not root.exists():
            return ActionResult(success=False, error=f"Root path does not exist: {root}")

        matches: list[str] = []
        try:
            for p in root.rglob("*"):
                if fnmatch.fnmatch(p.name, pattern) or pattern.lower() in p.name.lower():
                    matches.append(str(p))
                    if len(matches) >= max_results:
                        break
        except PermissionError:
            pass

        return ActionResult(
            success  = True,
            output   = matches,
            metadata = {"count": len(matches), "source": "live_walk", "root": str(root), "pattern": pattern},
        )

    # ------------------------------------------------------------------
    # SAFE: read file
    # ------------------------------------------------------------------

    def _read_file(self, path_str: str, max_bytes: int) -> ActionResult:
        err = self._guard(path_str)
        if err:
            return ActionResult(success=False, error=err)

        p = pathlib.Path(path_str)
        if not p.exists():
            return ActionResult(success=False, error=f"File not found: {path_str}")
        if not p.is_file():
            return ActionResult(success=False, error=f"Not a file: {path_str}")

        size = p.stat().st_size
        truncated = size > max_bytes
        try:
            with p.open("rb") as f:
                raw = f.read(max_bytes)
            content = raw.decode("utf-8", errors="replace")
            return ActionResult(
                success  = True,
                output   = content,
                metadata = {
                    "path":      path_str,
                    "size":      size,
                    "truncated": truncated,
                    "bytes_read": len(raw),
                },
            )
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # SAFE: open in default app
    # ------------------------------------------------------------------

    def _open_file(self, path_str: str) -> ActionResult:
        p = pathlib.Path(path_str)
        if not p.exists():
            return ActionResult(success=False, error=f"File not found: {path_str}")
        try:
            if _PLATFORM == "Windows":
                os.startfile(str(p))
            elif _PLATFORM == "Darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
            return ActionResult(success=True, output=f"Opened {p.name}")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # CAUTION: copy file
    # ------------------------------------------------------------------

    def _copy_file(self, src_str: str, dst_str: str) -> ActionResult:
        for path in (src_str, dst_str):
            err = self._guard(path)
            if err:
                return ActionResult(success=False, error=err)

        src = pathlib.Path(src_str)
        dst = pathlib.Path(dst_str)
        if not src.exists():
            return ActionResult(success=False, error=f"Source not found: {src}")
        try:
            if dst.is_dir():
                dst = dst / src.name
            shutil.copy2(str(src), str(dst))
            return ActionResult(success=True, output=f"Copied to {dst}")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # CAUTION: create file
    # ------------------------------------------------------------------

    def _create_file(self, path_str: str, content: str) -> ActionResult:
        err = self._guard(path_str)
        if err:
            return ActionResult(success=False, error=err)

        p = pathlib.Path(path_str)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ActionResult(
                success=True, output=f"Created {p.name}", metadata={"path": str(p)}
            )
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # CAUTION: create folder
    # ------------------------------------------------------------------

    def _create_folder(self, path_str: str) -> ActionResult:
        err = self._guard(path_str)
        if err:
            return ActionResult(success=False, error=err)

        p = pathlib.Path(path_str)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return ActionResult(success=True, output=f"Created folder {p.name}")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # CAUTION: move file
    # ------------------------------------------------------------------

    def _move_file(self, src_str: str, dst_str: str) -> ActionResult:
        for path in (src_str, dst_str):
            err = self._guard(path)
            if err:
                return ActionResult(success=False, error=err)

        src = pathlib.Path(src_str)
        dst = pathlib.Path(dst_str)
        if not src.exists():
            return ActionResult(success=False, error=f"Source not found: {src}")
        try:
            if dst.is_dir():
                dst = dst / src.name
            shutil.move(str(src), str(dst))
            return ActionResult(success=True, output=f"Moved to {dst}")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # DANGEROUS: delete file
    # ------------------------------------------------------------------

    def _delete_file(self, path_str: str, recursive: bool) -> ActionResult:
        err = self._guard(path_str)
        if err:
            return ActionResult(success=False, error=err)

        p = pathlib.Path(path_str)
        if not p.exists():
            return ActionResult(success=False, error=f"Path not found: {path_str}")

        try:
            if _TRASH_AVAILABLE:
                send2trash.send2trash(str(p))
                return ActionResult(success=True, output=f"Moved '{p.name}' to Trash")

            if p.is_dir():
                if not recursive:
                    return ActionResult(
                        success=False,
                        error=f"'{p.name}' is a directory — set recursive=True to delete it",
                    )
                shutil.rmtree(str(p))
            else:
                p.unlink()
            return ActionResult(
                success=True,
                output=f"Permanently deleted '{p.name}'",
                metadata={"path": str(p), "warning": "Deletion is permanent (send2trash not installed)"},
            )
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # DANGEROUS: rename file
    # ------------------------------------------------------------------

    def _rename_file(self, path_str: str, new_name: str) -> ActionResult:
        err = self._guard(path_str)
        if err:
            return ActionResult(success=False, error=err)

        p     = pathlib.Path(path_str)
        new_p = p.parent / new_name
        if not p.exists():
            return ActionResult(success=False, error=f"Path not found: {path_str}")
        if new_p.exists():
            return ActionResult(success=False, error=f"Target already exists: {new_p}")
        try:
            p.rename(new_p)
            return ActionResult(success=True, output=f"Renamed to '{new_name}'")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_executor: Optional[FileExecutor] = None

def get_file_executor() -> FileExecutor:
    global _executor
    if _executor is None:
        _executor = FileExecutor()
    return _executor
