"""
MARK III — Approval Manager (Phase 12B)

Manages the approval lifecycle for DANGEROUS and CRITICAL actions.

Flow:
  1. ActionQueue detects verdict == REQUIRE_APPROVAL
  2. Calls approval_manager.request_approval(action)
     → Creates ActionApproval DB row (pending)
     → Notifies user via: voice prompt | push notification | API polling
  3. User responds via: mobile UI | voice "yes"/"no" | API POST /actions/approve
  4. approval_manager.respond() updates DB row + unblocks the waiting queue
  5. ActionQueue receives verdict:
     → approved: continue to executor
     → denied:   fail the action with reason

Approval prompt format:
  "MARK wants to delete 'report.pdf'. Allow? (yes/no)"

Timeout:
  Default 120s.  After timeout, action is auto-denied.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_SECONDS = 120.0


# ---------------------------------------------------------------------------
# Approval record (in-memory)
# ---------------------------------------------------------------------------

@dataclass
class PendingApproval:
    approval_id:  str
    action_id:    str
    device_id:    str
    prompt:       str
    requested_at: float
    _event:       asyncio.Event
    verdict:      Optional[str] = None  # "approved" | "denied"
    responded_at: Optional[float] = None
    responded_by: Optional[str]   = None  # mobile | voice | api


# ---------------------------------------------------------------------------
# Human-readable prompt builder
# ---------------------------------------------------------------------------

def build_approval_prompt(action_type: str, parameters: dict, safety_level: str) -> str:
    """Build a concise natural-language approval prompt."""
    desc_map = {
        "delete_file":      lambda p: f"delete '{_short_path(p.get('path', '?'))}'",
        "run_command":      lambda p: f"run the command: {p.get('command', '?')[:60]}",
        "install_software": lambda p: f"install '{p.get('package', '?')}'",
        "kill_process":     lambda p: f"kill process '{p.get('target', '?')}'",
        "rename_file":      lambda p: f"rename '{_short_path(p.get('path', '?'))}' → '{p.get('new_name', '?')}'",
        "move_file":        lambda p: f"move '{_short_path(p.get('src', '?'))}' to '{_short_path(p.get('dst', '?'))}'",
        "system_shutdown":  lambda p: "shut down your computer",
        "system_restart":   lambda p: "restart your computer",
        "modify_registry":  lambda p: f"modify registry key '{p.get('key', '?')[:40]}'",
        "format_drive":     lambda p: f"FORMAT drive '{p.get('drive', '?')}' — THIS IS IRREVERSIBLE",
        "copy_file":        lambda p: f"copy '{_short_path(p.get('src', '?'))}' to '{_short_path(p.get('dst', '?'))}'",
        "browser_click":    lambda p: f"click '{p.get('selector', '?')}' on the browser page",
        "browser_fill":     lambda p: f"fill '{p.get('selector', '?')}' in the browser",
        "send_notification": lambda p: f"send you a notification: {p.get('body', '?')[:60]}",
    }
    fn = desc_map.get(action_type)
    action_str = fn(parameters) if fn else f"perform '{action_type}'"
    level_tag = f" [{safety_level.upper()}]" if safety_level in ("dangerous", "critical") else ""
    return f"MARK III wants to {action_str}.{level_tag} Allow?"


def _short_path(path: str) -> str:
    if len(path) <= 40:
        return path
    parts = path.replace("\\", "/").split("/")
    return "…/" + "/".join(parts[-2:]) if len(parts) >= 2 else path[-40:]


# ---------------------------------------------------------------------------
# ApprovalManager
# ---------------------------------------------------------------------------

class ApprovalManager:
    """
    Manages pending approvals in memory.

    For persistence, the ActionQueue writes ActionApproval rows to the DB.
    This class owns the asyncio.Event objects that unblock the queue.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}   # approval_id → record
        self._by_action: dict[str, str] = {}              # action_id → approval_id

    # ------------------------------------------------------------------
    # Request
    # ------------------------------------------------------------------

    def create_approval(
        self, action_id: str, device_id: str, action_type: str,
        parameters: dict, safety_level: str,
    ) -> PendingApproval:
        """
        Create a PendingApproval and return it.

        The ActionQueue persists the DB row; this class owns the Event.
        """
        approval_id = str(uuid.uuid4())
        prompt      = build_approval_prompt(action_type, parameters, safety_level)

        record = PendingApproval(
            approval_id  = approval_id,
            action_id    = action_id,
            device_id    = device_id,
            prompt       = prompt,
            requested_at = time.time(),
            _event       = asyncio.Event(),
        )
        self._pending[approval_id]   = record
        self._by_action[action_id]   = approval_id
        logger.info("Approval requested: %s | %s", approval_id[:8], prompt)
        return record

    # ------------------------------------------------------------------
    # Wait (blocks queue worker until user responds or timeout)
    # ------------------------------------------------------------------

    async def wait_for_response(
        self,
        approval_id: str,
        timeout:     float = APPROVAL_TIMEOUT_SECONDS,
    ) -> Optional[str]:
        """
        Wait for user response.
        Returns "approved" | "denied" | None (timeout → auto-deny).
        """
        record = self._pending.get(approval_id)
        if not record:
            return None
        try:
            await asyncio.wait_for(record._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.info("Approval %s timed out after %ss — auto-denied", approval_id[:8], timeout)
            self._resolve(approval_id, "denied", "timeout")
        return record.verdict

    # ------------------------------------------------------------------
    # Respond (called by mobile API / voice handler)
    # ------------------------------------------------------------------

    def respond(
        self,
        approval_id:  str,
        verdict:      str,      # "approved" | "denied"
        responded_by: str = "api",
    ) -> bool:
        """
        Record the user's response and unblock the waiting queue worker.
        Returns True if the approval was found and updated.
        """
        if not self._resolve(approval_id, verdict, responded_by):
            return False
        record = self._pending.get(approval_id)
        if record:
            record._event.set()
        return True

    def respond_by_action(
        self, action_id: str, verdict: str, responded_by: str = "api"
    ) -> bool:
        approval_id = self._by_action.get(action_id)
        if not approval_id:
            return False
        return self.respond(approval_id, verdict, responded_by)

    # ------------------------------------------------------------------
    # Voice shortcut
    # ------------------------------------------------------------------

    def handle_voice_response(self, device_id: str, text: str) -> bool:
        """
        Parse "yes" / "no" from voice transcript and resolve pending approval
        for this device (if any).
        """
        text = text.lower().strip()
        if any(w in text for w in ("yes", "yeah", "yep", "allow", "approve", "confirm", "do it", "go ahead")):
            verdict = "approved"
        elif any(w in text for w in ("no", "nope", "deny", "cancel", "stop", "block", "don't")):
            verdict = "denied"
        else:
            return False

        # Find the most recent pending approval for this device
        candidate = None
        latest    = 0.0
        for rec in self._pending.values():
            if rec.device_id == device_id and rec.verdict is None and rec.requested_at > latest:
                candidate = rec
                latest    = rec.requested_at

        if not candidate:
            return False

        return self.respond(candidate.approval_id, verdict, "voice")

    # ------------------------------------------------------------------
    # Inspect
    # ------------------------------------------------------------------

    def get(self, approval_id: str) -> Optional[PendingApproval]:
        return self._pending.get(approval_id)

    def pending_for_device(self, device_id: str) -> list[PendingApproval]:
        return [
            r for r in self._pending.values()
            if r.device_id == device_id and r.verdict is None
        ]

    def all_pending(self) -> list[PendingApproval]:
        return [r for r in self._pending.values() if r.verdict is None]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve(self, approval_id: str, verdict: str, responded_by: str) -> bool:
        record = self._pending.get(approval_id)
        if not record:
            return False
        if record.verdict is not None:
            return False   # already resolved
        record.verdict      = verdict
        record.responded_at = time.time()
        record.responded_by = responded_by
        logger.info(
            "Approval %s → %s (by %s) after %.1fs",
            approval_id[:8], verdict, responded_by,
            record.responded_at - record.requested_at,
        )
        return True

    def cleanup_old(self, max_age_seconds: float = 3600.0) -> int:
        """Remove resolved approvals older than max_age_seconds."""
        cutoff = time.time() - max_age_seconds
        to_remove = [
            aid for aid, r in self._pending.items()
            if r.verdict is not None and r.requested_at < cutoff
        ]
        for aid in to_remove:
            record = self._pending.pop(aid, None)
            if record:
                self._by_action.pop(record.action_id, None)
        return len(to_remove)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager: Optional[ApprovalManager] = None

def get_approval_manager() -> ApprovalManager:
    global _manager
    if _manager is None:
        _manager = ApprovalManager()
    return _manager
