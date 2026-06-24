"""
MARK III — Actions API (Phase 12B)

Endpoints:
  POST /actions/submit         — submit an action request
  GET  /actions/{id}           — get action status + result
  GET  /actions/               — list recent actions for a device
  POST /actions/{id}/cancel    — cancel a pending action
  POST /actions/approve        — approve or deny a pending approval
  GET  /actions/pending        — list pending approvals for a device
  GET  /actions/registry       — list all registered action types
  POST /actions/classify       — classify text intent (dev/debug)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.database import get_db
from app.services.actions.action_queue import get_action_queue
from app.services.actions.action_registry import all_entries
from app.services.actions.action_router import classify_intent
from app.services.actions.approval_manager import get_approval_manager
from app.services.actions.base_action import ActionRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/actions", tags=["actions"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class SubmitActionRequest(BaseModel):
    action_type:   str
    parameters:    dict             = {}
    source:        str              = "api"
    device_id:     str
    session_id:    Optional[str]    = None
    context_hint:  str              = ""


class ApproveRequest(BaseModel):
    approval_id:  Optional[str] = None
    action_id:    Optional[str] = None
    verdict:      str                    # "approved" | "denied"
    responded_by: str           = "api"


class ClassifyRequest(BaseModel):
    text:       str
    device_id:  str
    source:     str           = "conversation"
    session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# POST /actions/submit
# ---------------------------------------------------------------------------

@router.post("/submit")
async def submit_action(body: SubmitActionRequest, db=Depends(get_db)):
    """
    Submit an action to the queue.

    Returns immediately with action_id and initial state.
    Poll GET /actions/{id} for status.
    """
    queue = get_action_queue()
    try:
        request = ActionRequest(
            action_type  = body.action_type,
            parameters   = body.parameters,
            source       = body.source,
            device_id    = body.device_id,
            session_id   = body.session_id,
            context_hint = body.context_hint,
        )
        action = await queue.submit(request)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "action_id":    action.id,
        "action_type":  action.action_type,
        "safety_level": action.safety_level,
        "state":        action.state,
        "submitted_at": action.created_at,
    }


# ---------------------------------------------------------------------------
# GET /actions/{action_id}
# ---------------------------------------------------------------------------

@router.get("/{action_id}")
async def get_action(action_id: str):
    """Get current status and result for an action."""
    queue  = get_action_queue()
    action = queue.get_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    return action.to_dict()


# ---------------------------------------------------------------------------
# GET /actions/
# ---------------------------------------------------------------------------

@router.get("/")
async def list_actions(
    device_id: str  = Query(...),
    limit:     int  = Query(20, ge=1, le=100),
    state:     Optional[str] = Query(None),
):
    """List recent actions for a device."""
    queue   = get_action_queue()
    active  = [a for a in queue.list_active()  if a.device_id == device_id]
    recent  = [a for a in queue.list_recent(limit * 2) if a.device_id == device_id]

    combined = {a.id: a for a in (active + recent)}
    results  = sorted(combined.values(), key=lambda a: a.updated_at, reverse=True)

    if state:
        results = [a for a in results if a.state == state]

    return {
        "actions": [a.to_dict() for a in results[:limit]],
        "total":   len(results),
    }


# ---------------------------------------------------------------------------
# POST /actions/{action_id}/cancel
# ---------------------------------------------------------------------------

@router.post("/{action_id}/cancel")
async def cancel_action(action_id: str):
    """Cancel a pending or awaiting_approval action."""
    queue   = get_action_queue()
    success = await queue.cancel(action_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Action not found or cannot be cancelled in its current state",
        )
    return {"cancelled": True, "action_id": action_id}


# ---------------------------------------------------------------------------
# POST /actions/approve
# ---------------------------------------------------------------------------

@router.post("/approve")
async def approve_action(body: ApproveRequest, db=Depends(get_db)):
    """
    Approve or deny a pending action that requires human consent.

    Supply either approval_id OR action_id.
    verdict must be "approved" or "denied".
    """
    if body.verdict not in ("approved", "denied"):
        raise HTTPException(status_code=400, detail="verdict must be 'approved' or 'denied'")

    mgr     = get_approval_manager()
    success = False

    if body.approval_id:
        success = mgr.respond(body.approval_id, body.verdict, body.responded_by)
    elif body.action_id:
        success = mgr.respond_by_action(body.action_id, body.verdict, body.responded_by)
    else:
        raise HTTPException(status_code=400, detail="Supply approval_id or action_id")

    if not success:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")

    # Persist approval verdict to DB
    if body.approval_id:
        try:
            from sqlalchemy import select
            from app.models.db import ActionApproval
            import time
            row = (await db.execute(
                select(ActionApproval).where(ActionApproval.id == body.approval_id)
            )).scalar_one_or_none()
            if row:
                row.verdict      = body.verdict
                row.responded_by = body.responded_by
                row.responded_at = time.time()
                await db.commit()
        except Exception as exc:
            logger.warning("Failed to persist approval verdict: %s", exc)

    return {"recorded": True, "verdict": body.verdict}


# ---------------------------------------------------------------------------
# GET /actions/pending
# ---------------------------------------------------------------------------

@router.get("/pending/approvals")
async def pending_approvals(device_id: str = Query(...)):
    """
    Return all pending approvals for a device.

    Mobile polls this endpoint to display the approval UI banner.
    """
    mgr     = get_approval_manager()
    pending = mgr.pending_for_device(device_id)
    return {
        "pending": [
            {
                "approval_id":  p.approval_id,
                "action_id":    p.action_id,
                "prompt":       p.prompt,
                "requested_at": p.requested_at,
            }
            for p in pending
        ],
        "count": len(pending),
    }


# ---------------------------------------------------------------------------
# GET /actions/registry
# ---------------------------------------------------------------------------

@router.get("/registry/all")
async def get_registry():
    """List all registered action types with their safety levels and descriptions."""
    return {
        "actions": [
            {
                "action_type":    e.action_type,
                "safety_level":   e.safety_level.value,
                "executor":       e.executor_key,
                "description":    e.description,
                "timeout":        e.timeout,
                "required_params": list(e.required_params),
                "optional_params": list(e.optional_params),
            }
            for e in all_entries()
        ]
    }


# ---------------------------------------------------------------------------
# POST /actions/classify
# ---------------------------------------------------------------------------

@router.post("/classify")
async def classify_action(body: ClassifyRequest):
    """
    Dev/debug endpoint: classify a text string and return detected intent.

    Returns null if no action intent detected.
    """
    request = classify_intent(
        text       = body.text,
        device_id  = body.device_id,
        source     = body.source,
        session_id = body.session_id,
    )
    if not request:
        return {"intent": None, "message": "No action intent detected"}
    return {
        "intent": {
            "action_type": request.action_type,
            "parameters":  request.parameters,
            "context_hint": request.context_hint,
        }
    }
