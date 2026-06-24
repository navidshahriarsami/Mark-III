"""
MARK III — Action Registry (Phase 12B)

Single source of truth mapping action_type → execution config.

Each entry defines:
  executor_key    — which executor handles this type
  safety_level    — minimum safety classification
  timeout         — seconds before action is killed
  max_retries     — how many times to retry on failure
  description     — human-readable, shown in approvals
  params_schema   — required/optional parameter names

Executors are imported lazily (inside get_executor()) to avoid
circular imports and to support graceful degradation when platform
packages are unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Type

from app.services.actions.base_action import ActionType, SafetyLevel


# ---------------------------------------------------------------------------
# Registry entry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegistryEntry:
    action_type:    str
    executor_key:   str           # desktop | browser | file | notification
    safety_level:   SafetyLevel
    timeout:        float         # seconds
    max_retries:    int
    description:    str
    required_params: tuple[str, ...] = field(default_factory=tuple)
    optional_params: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Registry table
# ---------------------------------------------------------------------------

_REGISTRY: list[RegistryEntry] = [
    # ── SAFE: Desktop ─────────────────────────────────────────────────────
    RegistryEntry(
        ActionType.LAUNCH_APP, "desktop", SafetyLevel.SAFE, 15.0, 1,
        "Open an application",
        required_params=("app_name",),
        optional_params=("path",),
    ),
    RegistryEntry(
        ActionType.FOCUS_APP, "desktop", SafetyLevel.SAFE, 10.0, 1,
        "Bring an application window to the foreground",
        required_params=("app_name",),
    ),
    RegistryEntry(
        ActionType.CLOSE_APP, "desktop", SafetyLevel.SAFE, 10.0, 0,
        "Close/quit an application",
        required_params=("app_name",),
    ),

    # ── SAFE: Browser ─────────────────────────────────────────────────────
    RegistryEntry(
        ActionType.OPEN_URL, "browser", SafetyLevel.SAFE, 10.0, 1,
        "Open a URL in the default browser",
        required_params=("url",),
    ),
    RegistryEntry(
        ActionType.WEB_SEARCH, "browser", SafetyLevel.SAFE, 10.0, 1,
        "Search the web and open results",
        required_params=("query",),
        optional_params=("engine",),
    ),

    # ── SAFE: File (read-only) ─────────────────────────────────────────────
    RegistryEntry(
        ActionType.SEARCH_FILES, "file", SafetyLevel.SAFE, 20.0, 1,
        "Search for files matching a pattern",
        required_params=("pattern",),
        optional_params=("root_path", "max_results"),
    ),
    RegistryEntry(
        ActionType.READ_FILE, "file", SafetyLevel.SAFE, 15.0, 1,
        "Read file contents and return to context",
        required_params=("path",),
        optional_params=("max_bytes",),
    ),
    RegistryEntry(
        ActionType.OPEN_FILE, "file", SafetyLevel.SAFE, 10.0, 1,
        "Open a file in its default application",
        required_params=("path",),
    ),

    # ── CAUTION: Notifications ────────────────────────────────────────────
    RegistryEntry(
        ActionType.SEND_NOTIFICATION, "notification", SafetyLevel.CAUTION, 10.0, 1,
        "Send a desktop or push notification",
        required_params=("title", "body"),
        optional_params=("device_id", "sound"),
    ),

    # ── CAUTION: File mutations ───────────────────────────────────────────
    RegistryEntry(
        ActionType.COPY_FILE, "file", SafetyLevel.CAUTION, 30.0, 1,
        "Copy a file to a new location",
        required_params=("src", "dst"),
    ),
    RegistryEntry(
        ActionType.CREATE_FILE, "file", SafetyLevel.CAUTION, 15.0, 0,
        "Create a new file with optional content",
        required_params=("path",),
        optional_params=("content",),
    ),
    RegistryEntry(
        ActionType.CREATE_FOLDER, "file", SafetyLevel.CAUTION, 10.0, 0,
        "Create a new directory",
        required_params=("path",),
    ),
    RegistryEntry(
        ActionType.MOVE_FILE, "file", SafetyLevel.CAUTION, 30.0, 0,
        "Move a file to a new location",
        required_params=("src", "dst"),
    ),

    # ── CAUTION: Browser automation ───────────────────────────────────────
    RegistryEntry(
        ActionType.BROWSER_CLICK, "browser", SafetyLevel.CAUTION, 15.0, 1,
        "Click an element on the active browser page",
        required_params=("selector",),
        optional_params=("url",),
    ),
    RegistryEntry(
        ActionType.BROWSER_FILL, "browser", SafetyLevel.CAUTION, 15.0, 1,
        "Fill a form field in the browser",
        required_params=("selector", "value"),
        optional_params=("url",),
    ),
    RegistryEntry(
        ActionType.WRITE_CLIPBOARD, "desktop", SafetyLevel.CAUTION, 5.0, 0,
        "Write text to the clipboard",
        required_params=("text",),
    ),

    # ── DANGEROUS ─────────────────────────────────────────────────────────
    RegistryEntry(
        ActionType.DELETE_FILE, "file", SafetyLevel.DANGEROUS, 30.0, 0,
        "Permanently delete a file or directory",
        required_params=("path",),
        optional_params=("recursive",),
    ),
    RegistryEntry(
        ActionType.RUN_COMMAND, "desktop", SafetyLevel.DANGEROUS, 60.0, 0,
        "Execute a shell command",
        required_params=("command",),
        optional_params=("cwd", "timeout"),
    ),
    RegistryEntry(
        ActionType.INSTALL_SOFTWARE, "desktop", SafetyLevel.DANGEROUS, 300.0, 0,
        "Install software via package manager",
        required_params=("package",),
        optional_params=("manager",),
    ),
    RegistryEntry(
        ActionType.RENAME_FILE, "file", SafetyLevel.DANGEROUS, 15.0, 0,
        "Rename a file or directory",
        required_params=("path", "new_name"),
    ),
    RegistryEntry(
        ActionType.KILL_PROCESS, "desktop", SafetyLevel.DANGEROUS, 10.0, 0,
        "Terminate a running process by name or PID",
        required_params=("target",),
        optional_params=("force",),
    ),

    # ── CRITICAL ──────────────────────────────────────────────────────────
    RegistryEntry(
        ActionType.SYSTEM_SHUTDOWN, "desktop", SafetyLevel.CRITICAL, 10.0, 0,
        "Shut down the system",
        optional_params=("delay_seconds",),
    ),
    RegistryEntry(
        ActionType.SYSTEM_RESTART, "desktop", SafetyLevel.CRITICAL, 10.0, 0,
        "Restart the system",
        optional_params=("delay_seconds",),
    ),
    RegistryEntry(
        ActionType.MODIFY_REGISTRY, "desktop", SafetyLevel.CRITICAL, 15.0, 0,
        "Modify the Windows registry (Windows only)",
        required_params=("key", "value_name", "value_data"),
        optional_params=("value_type",),
    ),
    RegistryEntry(
        ActionType.FORMAT_DRIVE, "desktop", SafetyLevel.CRITICAL, 600.0, 0,
        "Format a drive (DESTRUCTIVE — irreversible)",
        required_params=("drive",),
    ),
]

# Index for O(1) lookup
_INDEX: dict[str, RegistryEntry] = {e.action_type: e for e in _REGISTRY}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup(action_type: str) -> Optional[RegistryEntry]:
    return _INDEX.get(action_type)


def lookup_required(action_type: str) -> RegistryEntry:
    entry = _INDEX.get(action_type)
    if not entry:
        raise KeyError(f"Unknown action type: '{action_type}'")
    return entry


def safety_level_for(action_type: str) -> SafetyLevel:
    entry = lookup(action_type)
    return entry.safety_level if entry else SafetyLevel.DANGEROUS  # fail safe


def all_entries() -> list[RegistryEntry]:
    return list(_REGISTRY)


def entries_by_safety(level: SafetyLevel) -> list[RegistryEntry]:
    return [e for e in _REGISTRY if e.safety_level == level]


def validate_params(action_type: str, params: dict[str, Any]) -> list[str]:
    """Return list of missing required parameter names (empty = valid)."""
    entry = lookup(action_type)
    if not entry:
        return []
    return [p for p in entry.required_params if p not in params]


# ---------------------------------------------------------------------------
# Executor factory (lazy import to break circular deps + optional packages)
# ---------------------------------------------------------------------------

def get_executor(executor_key: str):
    """
    Return an executor instance by key.

    Imported here to avoid circular imports.  All executors are singletons.
    """
    if executor_key == "desktop":
        from app.services.actions.executors.desktop_executor import get_desktop_executor
        return get_desktop_executor()
    if executor_key == "browser":
        from app.services.actions.executors.browser_executor import get_browser_executor
        return get_browser_executor()
    if executor_key == "file":
        from app.services.actions.executors.file_executor import get_file_executor
        return get_file_executor()
    if executor_key == "notification":
        from app.services.actions.executors.notification_executor import get_notification_executor
        return get_notification_executor()
    raise KeyError(f"Unknown executor key: '{executor_key}'")
