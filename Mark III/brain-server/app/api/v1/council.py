"""
MARK III — Cognitive Council API (Phase 14)

Endpoints:
  POST /council/consult            — query the full council
  GET  /council/health             — health of all specialist providers
  GET  /council/stats              — cost + call tracking
  GET  /council/specialists        — list all registered specialists
  POST /council/test               — force specific specialist roles (dev/debug)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger("markiii.api.council")
router = APIRouter(prefix="/council", tags=["council"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ConsultRequest(BaseModel):
    query:        str
    context_hint: str = ""
    device_id:    str = ""
    force_roles:  Optional[list[str]] = None
    force_llm_routing: bool = False


class TestRequest(BaseModel):
    query:   str
    roles:   list[str]
    device_id: str = ""


# ---------------------------------------------------------------------------
# POST /council/consult
# ---------------------------------------------------------------------------

@router.post("/consult")
async def consult(req: ConsultRequest):
    """
    Route a query through the Cognitive Council.
    Returns the final synthesised answer + full audit trail.
    """
    from app.services.council.council_manager import get_council

    council = get_council()
    session = await council.consult(
        query             = req.query,
        context_hint      = req.context_hint,
        device_id         = req.device_id,
        manual_roles      = req.force_roles,
        force_llm_routing = req.force_llm_routing,
    )

    return {
        "answer":    session.final_answer,
        "council":   session.to_dict(),
    }


# ---------------------------------------------------------------------------
# POST /council/test
# ---------------------------------------------------------------------------

@router.post("/test")
async def test_council(req: TestRequest):
    """Force specific specialist roles for debugging."""
    from app.services.council.council_manager import get_council

    council = get_council()
    session = await council.consult(
        query        = req.query,
        device_id    = req.device_id,
        manual_roles = req.roles,
    )

    return {
        "answer":  session.final_answer,
        "council": session.to_dict(),
    }


# ---------------------------------------------------------------------------
# GET /council/specialists
# ---------------------------------------------------------------------------

@router.get("/specialists")
async def list_specialists():
    """Return all registered specialists with their configuration."""
    from app.services.council.specialist_registry import all_specialists

    return {
        "specialists": [
            {
                "role":         s.role.value,
                "name":         s.name,
                "description":  s.description,
                "provider":     s.provider_key,
                "model":        s.model,
                "temperature":  s.temperature,
                "max_tokens":   s.max_tokens,
                "timeout_s":    s.timeout_s,
                "capabilities": list(s.capabilities),
            }
            for s in all_specialists()
        ]
    }


# ---------------------------------------------------------------------------
# GET /council/health
# ---------------------------------------------------------------------------

@router.get("/health")
async def council_health():
    """Return health + availability of all specialist providers."""
    from app.services.ai.provider_manager import get_provider_manager
    from app.services.ai.base_provider    import ProviderName

    mgr    = get_provider_manager()
    health = await mgr.health_all()

    # Annotate which specialists depend on which provider
    from app.services.council.specialist_registry import all_specialists
    provider_specialists: dict[str, list[str]] = {}
    for s in all_specialists():
        provider_specialists.setdefault(s.provider_key, []).append(s.role.value)

    return {
        "providers": {
            name: {
                **info,
                "specialists": provider_specialists.get(name, []),
            }
            for name, info in health.items()
        }
    }


# ---------------------------------------------------------------------------
# GET /council/stats
# ---------------------------------------------------------------------------

@router.get("/stats")
async def council_stats():
    """Return aggregate call and cost statistics."""
    from app.services.council.council_manager import get_council
    from app.services.ai.provider_manager     import get_provider_manager

    return {
        "council":   get_council().stats(),
        "providers": get_provider_manager().usage_summary(),
    }


# ---------------------------------------------------------------------------
# GET /council/route
# ---------------------------------------------------------------------------

@router.get("/route")
async def preview_routing(
    query: str = Query(...),
    force_llm: bool = Query(False),
):
    """Preview which specialists would be activated for a query (no LLM calls)."""
    from app.services.council.model_router import classify_query

    analysis = await classify_query(text=query, force_llm=force_llm)

    return {
        "query":       query,
        "roles":       [r.value for r in analysis.roles],
        "complexity":  analysis.complexity,
        "domain_tags": analysis.domain_tags,
        "reasoning":   analysis.reasoning,
        "via_llm":     False,
    }
