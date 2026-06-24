"""
MARK III — Agents API (Phase 13)

Endpoints:
  GET  /agents/                    — list all registered agents + last run info
  GET  /agents/history             — recent agent run log for a device
  POST /agents/{agent_id}/trigger  — manually trigger an agent
  GET  /agents/{agent_id}/status   — status of a specific agent for a device
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc

from app.database import get_db
from app.models.db import AgentRun

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# GET /agents/
# ---------------------------------------------------------------------------

@router.get("/")
async def list_agents():
    """Return all registered agents with their configuration."""
    from app.services.agents.agent_manager import get_agent_manager
    manager = get_agent_manager()
    return {"agents": manager.list_agents()}


# ---------------------------------------------------------------------------
# GET /agents/history
# ---------------------------------------------------------------------------

@router.get("/history")
async def agent_history(
    device_id: str  = Query(...),
    limit:     int  = Query(30, ge=1, le=100),
    agent_id:  Optional[str] = Query(None),
    db         = Depends(get_db),
):
    """Return recent agent run history for a device."""
    q = (
        select(AgentRun)
        .where(AgentRun.device_id == device_id)
        .order_by(desc(AgentRun.ran_at))
        .limit(limit)
    )
    if agent_id:
        q = q.where(AgentRun.agent_id == agent_id)

    rows = (await db.execute(q)).scalars().all()
    return {
        "history": [
            {
                "id":          r.id,
                "agent_id":    r.agent_id,
                "ran_at":      r.ran_at,
                "success":     r.success,
                "title":       r.title,
                "text_snippet": r.text_snippet,
                "delivery":    json.loads(r.delivery or "[]"),
                "priority":    r.priority,
                "latency_ms":  r.latency_ms,
                "error":       r.error,
            }
            for r in rows
        ],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# POST /agents/{agent_id}/trigger
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/trigger")
async def trigger_agent(
    agent_id:  str,
    device_id: str = Query(...),
):
    """
    Manually trigger an agent.
    Bypasses should_run() and min_interval — useful for testing and admin.
    """
    from app.services.agents.agent_manager import get_agent_manager
    manager = get_agent_manager()

    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found. Available: {list(manager._agents.keys())}",
        )

    result = await manager.manual_trigger(agent_id, device_id)
    if not result:
        raise HTTPException(status_code=500, detail="Agent execution failed — check server logs")

    return {
        "triggered":  True,
        "agent_id":   result.agent_id,
        "title":      result.title,
        "text":       result.text,
        "delivery":   result.delivery,
        "success":    result.success,
        "latency_ms": round(result.latency_ms, 1),
        "error":      result.error,
    }


# ---------------------------------------------------------------------------
# GET /agents/{agent_id}/status
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/status")
async def agent_status(
    agent_id:  str,
    device_id: str = Query(...),
    db         = Depends(get_db),
):
    """Return last run info for a specific agent + device."""
    from app.services.agents.agent_manager import get_agent_manager
    manager = get_agent_manager()
    agent   = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    last_run = (await db.execute(
        select(AgentRun)
        .where(AgentRun.agent_id  == agent_id)
        .where(AgentRun.device_id == device_id)
        .order_by(desc(AgentRun.ran_at))
        .limit(1)
    )).scalar_one_or_none()

    return {
        "agent_id":           agent_id,
        "name":               agent.name,
        "description":        agent.description,
        "min_interval_hours": agent.min_interval_hours,
        "last_run": {
            "ran_at":      last_run.ran_at,
            "success":     last_run.success,
            "title":       last_run.title,
            "priority":    last_run.priority,
            "latency_ms":  last_run.latency_ms,
        } if last_run else None,
    }
