"""
MARK III — Action Engine base types (Phase 12B)

Defines the canonical types shared across the entire action system:
  ActionType  — what the action does
  SafetyLevel — risk classification
  ActionState — lifecycle state machine
  ActionRequest — inbound intent (from LLM suggestion, voice, API)
  ActionResult  — outcome from an executor
  Action        — full in-flight or completed record

Flow:
  LLM text  ──► ActionRouter.classify()     → ActionRequest
  API call  ──►                             → ActionRequest
                                               ↓
                             ActionRegistry.lookup(action_type)
                                               ↓
                               Action.create(request, safety_level)
                                               ↓
                                     ActionQueue.submit(action)
                                               ↓
                             PolicyEngine.evaluate(action)  ──► DENY
                                               ↓ ALLOW
                                 ActionQueue._worker → Executor.run()
                                               ↓
                                          ActionResult
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class SafetyLevel(str, Enum):
    SAFE      = "safe"
    CAUTION   = "caution"
    DANGEROUS = "dangerous"
    CRITICAL  = "critical"

    @property
    def ordinal(self) -> int:
        return {"safe": 0, "caution": 1, "dangerous": 2, "critical": 3}[self.value]

    def __ge__(self, other: "SafetyLevel") -> bool:
        return self.ordinal >= other.ordinal

    def __gt__(self, other: "SafetyLevel") -> bool:
        return self.ordinal > other.ordinal


class ActionState(str, Enum):
    PENDING           = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING           = "running"
    COMPLETED         = "completed"
    FAILED            = "failed"
    CANCELLED         = "cancelled"
    DEFERRED          = "deferred"


class ActionType(str, Enum):
    # ── SAFE ──────────────────────────────────────────────
    LAUNCH_APP    = "launch_app"     # open an application
    FOCUS_APP     = "focus_app"      # bring window to front
    CLOSE_APP     = "close_app"      # close/quit application
    OPEN_URL      = "open_url"       # open a URL in default browser
    WEB_SEARCH    = "web_search"     # web search (open results page)
    SEARCH_FILES  = "search_files"   # search filesystem (read-only)
    READ_FILE     = "read_file"      # read file contents (returned to LLM)
    OPEN_FILE     = "open_file"      # open file in default app

    # ── CAUTION ────────────────────────────────────────────
    SEND_NOTIFICATION = "send_notification"  # OS toast / push
    COPY_FILE         = "copy_file"
    CREATE_FILE       = "create_file"
    CREATE_FOLDER     = "create_folder"
    MOVE_FILE         = "move_file"
    BROWSER_CLICK     = "browser_click"
    BROWSER_FILL      = "browser_fill"
    WRITE_CLIPBOARD   = "write_clipboard"

    # ── DANGEROUS ──────────────────────────────────────────
    DELETE_FILE       = "delete_file"
    RUN_COMMAND       = "run_command"        # shell command
    INSTALL_SOFTWARE  = "install_software"
    RENAME_FILE       = "rename_file"
    KILL_PROCESS      = "kill_process"

    # ── CRITICAL ───────────────────────────────────────────
    FORMAT_DRIVE      = "format_drive"
    SYSTEM_SHUTDOWN   = "system_shutdown"
    MODIFY_REGISTRY   = "modify_registry"   # Windows registry
    SYSTEM_RESTART    = "system_restart"


# ---------------------------------------------------------------------------
# ActionRequest — inbound intent (not yet an Action in the system)
# ---------------------------------------------------------------------------

@dataclass
class ActionRequest:
    """
    What the caller wants MARK III to do.

    Created by:
      - ActionRouter.classify_intent(text)  ← LLM suggestion / voice transcript
      - API endpoint  (POST /actions/submit)
    """
    action_type:  str
    parameters:   dict[str, Any]
    source:       str                  # conversation | voice | api | schedule
    device_id:    str
    session_id:   Optional[str] = None
    context_hint: str           = ""   # human language that led to this request
    requested_by: str           = "user"


# ---------------------------------------------------------------------------
# ActionResult — executor output
# ---------------------------------------------------------------------------

@dataclass
class ActionResult:
    success:     bool
    output:      Any                   = None   # executor-specific payload
    error:       Optional[str]         = None
    latency_ms:  float                 = 0.0
    metadata:    dict[str, Any]        = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success":    self.success,
            "output":     self.output,
            "error":      self.error,
            "latency_ms": round(self.latency_ms, 1),
            "metadata":   self.metadata,
        }


# ---------------------------------------------------------------------------
# Action — the full in-flight / completed record
# ---------------------------------------------------------------------------

@dataclass
class Action:
    """
    Live record that flows through the action system.

    Persisted to the DB by ActionQueue when state changes.
    """
    id:              str
    action_type:     str
    safety_level:    str
    parameters:      dict[str, Any]
    state:           str                 # ActionState value
    source:          str
    device_id:       str
    session_id:      Optional[str]
    context_hint:    str
    created_at:      float
    updated_at:      float

    result:          Optional[ActionResult] = None
    started_at:      Optional[float]        = None
    completed_at:    Optional[float]        = None
    deferred_until:  Optional[float]        = None
    approval_id:     Optional[str]          = None
    retry_count:     int                    = 0
    max_retries:     int                    = 0
    timeout_seconds: float                  = 30.0
    error_message:   Optional[str]          = None

    # ── Factory ────────────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        request:        ActionRequest,
        safety_level:   str,
        timeout_seconds: float = 30.0,
        max_retries:    int   = 0,
    ) -> "Action":
        now = time.time()
        return cls(
            id             = str(uuid.uuid4()),
            action_type    = request.action_type,
            safety_level   = safety_level,
            parameters     = dict(request.parameters),
            state          = ActionState.PENDING.value,
            source         = request.source,
            device_id      = request.device_id,
            session_id     = request.session_id,
            context_hint   = request.context_hint,
            created_at     = now,
            updated_at     = now,
            timeout_seconds = timeout_seconds,
            max_retries    = max_retries,
        )

    # ── State helpers ──────────────────────────────────────────────────────

    def transition(self, new_state: ActionState) -> None:
        self.state      = new_state.value
        self.updated_at = time.time()
        if new_state == ActionState.RUNNING:
            self.started_at = self.updated_at
        if new_state in (ActionState.COMPLETED, ActionState.FAILED, ActionState.CANCELLED):
            self.completed_at = self.updated_at

    def is_terminal(self) -> bool:
        return self.state in (
            ActionState.COMPLETED.value,
            ActionState.FAILED.value,
            ActionState.CANCELLED.value,
        )

    def is_timed_out(self) -> bool:
        if not self.started_at:
            return False
        return (time.time() - self.started_at) > self.timeout_seconds

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "action_type":    self.action_type,
            "safety_level":   self.safety_level,
            "state":          self.state,
            "source":         self.source,
            "device_id":      self.device_id[:16] if self.device_id else "",
            "session_id":     self.session_id,
            "context_hint":   self.context_hint,
            "parameters":     self.parameters,
            "error_message":  self.error_message,
            "result":         self.result.to_dict() if self.result else None,
            "approval_id":    self.approval_id,
            "retry_count":    self.retry_count,
            "created_at":     self.created_at,
            "updated_at":     self.updated_at,
            "started_at":     self.started_at,
            "completed_at":   self.completed_at,
            "deferred_until": self.deferred_until,
        }

    @staticmethod
    def params_to_json(params: dict) -> str:
        return json.dumps(params, default=str)

    @staticmethod
    def params_from_json(s: str) -> dict:
        try:
            return json.loads(s) if s else {}
        except Exception:
            return {}
