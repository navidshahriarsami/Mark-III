"""
MARK III — Conversation API (Phase 10)

Endpoints:
  POST /conversation/start           — create a new session
  POST /conversation/message         — send a message, get a response
  GET  /conversation/history         — paginated message list for a session
  GET  /conversation/sessions        — all sessions for a device
  GET  /conversation/search          — search sessions + messages
  GET  /conversation/stream          — SSE streaming (future web/voice)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.ai import conversation_engine as engine

logger = logging.getLogger("markiii.api.conversation")
router = APIRouter(prefix="/conversation", tags=["conversation"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class StartSessionRequest(BaseModel):
    device_id: str
    title: str = "New conversation"


class StartSessionResponse(BaseModel):
    session_id: str
    title: str
    created_at: float


class MessageRequest(BaseModel):
    session_id: str
    device_id: str
    message: str


class MessageResponse(BaseModel):
    session_id: str
    message_id: int
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    context_refs: list[dict]
    error: Optional[str] = None


class MessageItem(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    context_hash: Optional[str]
    ts: float


class SessionItem(BaseModel):
    id: str
    device_id: str
    title: str
    topic_summary: Optional[str]
    message_count: int
    is_active: bool
    provider_used: str
    total_cost_usd: float
    created_at: float
    updated_at: float


class SearchResult(BaseModel):
    session_id: str
    title: str
    message: str
    role: str
    ts: float
    updated_at: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session_dict(s) -> dict:
    return {
        "id":            s.id,
        "device_id":     s.device_id,
        "title":         s.title,
        "topic_summary": s.topic_summary,
        "message_count": s.message_count,
        "is_active":     s.is_active,
        "provider_used": s.provider_used,
        "total_cost_usd": s.total_cost_usd,
        "created_at":    s.created_at,
        "updated_at":    s.updated_at,
    }


def _message_dict(m) -> dict:
    return {
        "id":           m.id,
        "session_id":   m.session_id,
        "role":         m.role,
        "content":      m.content,
        "provider":     m.provider or "",
        "model":        m.model or "",
        "input_tokens":  m.input_tokens or 0,
        "output_tokens": m.output_tokens or 0,
        "cost_usd":     m.cost_usd or 0.0,
        "latency_ms":   m.latency_ms or 0.0,
        "context_hash": m.context_hash,
        "ts":           m.ts,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/start", response_model=StartSessionResponse)
async def start_session(
    body: StartSessionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new conversation session and return the session_id."""
    session = await engine.create_session(body.device_id, body.title, db)
    return {"session_id": session.id, "title": session.title, "created_at": session.created_at}


@router.post("/message", response_model=MessageResponse)
async def send_message(
    body: MessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a user message in a session.
    MARK III assembles context, calls the provider, and persists both turns.
    Returns the assistant's response with full metadata.
    """
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    try:
        result = await engine.generate_response(
            session_id   = body.session_id,
            user_message = body.message.strip(),
            device_id    = body.device_id,
            db           = db,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("generate_response error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_history(
    session_id: str = Query(...),
    limit:      int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated message history for a session, oldest first."""
    messages = await engine.get_history(session_id, limit, db)
    return {"session_id": session_id, "messages": [_message_dict(m) for m in messages]}


@router.get("/sessions")
async def list_sessions(
    device_id: str = Query(...),
    limit:     int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Return all sessions for a device, most recent first."""
    sessions = await engine.list_sessions(device_id, limit, db)
    return {"sessions": [_session_dict(s) for s in sessions]}


@router.get("/search")
async def search_conversations(
    device_id: str = Query(...),
    q:         str = Query(..., min_length=2),
    limit:     int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Search across session titles and message content.
    Returns one entry per matching session with a message excerpt.
    """
    results = await engine.search_conversations(device_id, q, limit, db)
    return {"query": q, "results": results}


@router.get("/stream")
async def stream_message(
    session_id: str = Query(...),
    device_id:  str = Query(...),
    message:    str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    SSE streaming endpoint.
    Intended for web clients and future voice/earbud integrations.
    Mobile app uses the non-streaming /message endpoint instead.
    """
    if not message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    async def event_generator():
        async for chunk in engine.stream_response(
            session_id   = session_id,
            user_message = message.strip(),
            device_id    = device_id,
            db           = db,
        ):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
