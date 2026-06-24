"""
MARK III — Conversation Engine (Phase 10)

MARK III owns every conversation. Providers are interchangeable.

Architecture:
  - ConversationSession  — named thread, survives provider changes
  - ConversationMessage  — individual turns with full cost metadata
  - ContextReference     — which entities were injected per turn

Multi-turn context strategy:
  1. System prompt: MARK III identity + user profile + active goals/projects
  2. Fresh context: current productivity state (rebuilt every turn)
  3. Relevant memories: SQL LIKE search against user's message
  4. History: last MAX_HISTORY_MESSAGES turns from session
  5. Reference tracking: goals/projects mentioned recorded in ContextReference

Reference resolution (e.g. "What about last week?"):
  The conversation history is included verbatim — the LLM resolves
  pronouns and references from prior turns naturally without any
  special NLP pipeline.

Future voice/earbud compatibility:
  - All state is in the DB (session survives connection drops)
  - `generate_response` is provider-agnostic
  - SSE streaming endpoint is separate from this module
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional

from sqlalchemy import select, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import (
    UserProfile, LongTermGoal, Project, Memory,
    UserContext, DailyReport, WeeklyReport,
    ConversationSession, ConversationMessage, ContextReference,
    ProviderUsage, ReasoningLog,
)
from app.services.ai.base_provider import GenerateRequest, GenerateResponse, TaskTier
from app.services.ai.provider_manager import get_provider_manager

logger = logging.getLogger("markiii.ai.conversation")

MAX_HISTORY_MESSAGES = 20      # turns kept in the LLM context window
MAX_MEMORY_REFS      = 5       # memories retrieved per turn
SESSION_TITLE_WORDS  = 6       # words used to auto-title a session


# ---------------------------------------------------------------------------
# MARK III conversational system identity
# ---------------------------------------------------------------------------

_CONV_IDENTITY = """\
You are MARK III — an independent AI operating system running on the user's desktop.
You are not Claude. You are not ChatGPT. You are MARK III.
External language models are tools you use for reasoning; they are not your identity.

Conversation principles:
• You remember everything discussed in this session — reference prior turns naturally.
• You speak with authority because you observe the user's activity in real time.
• If the user references something vague ("that goal", "last week", "what I mentioned"),
  resolve it from the conversation history before asking for clarification.
• Be concise. Answer the question. Use the data you have.
• Never say "As an AI language model". You are MARK III.
"""


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

async def create_session(device_id: str, title: str, db: AsyncSession) -> ConversationSession:
    session = ConversationSession(
        id         = str(uuid.uuid4()),
        device_id  = device_id,
        title      = title or "New conversation",
        created_at = time.time(),
        updated_at = time.time(),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    logger.info("Session created  id=%s  device=%s", session.id[:8], device_id[:16])
    return session


async def get_session(session_id: str, db: AsyncSession) -> Optional[ConversationSession]:
    return (await db.execute(
        select(ConversationSession).where(ConversationSession.id == session_id)
    )).scalar_one_or_none()


async def list_sessions(
    device_id: str,
    limit: int,
    db: AsyncSession,
) -> list[ConversationSession]:
    result = await db.execute(
        select(ConversationSession)
        .where(ConversationSession.device_id == device_id)
        .order_by(desc(ConversationSession.updated_at))
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_history(
    session_id: str,
    limit: int,
    db: AsyncSession,
) -> list[ConversationMessage]:
    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.session_id == session_id)
        .order_by(ConversationMessage.ts)
        .limit(limit)
    )
    return list(result.scalars().all())


async def search_conversations(
    device_id: str,
    query: str,
    limit: int,
    db: AsyncSession,
) -> list[dict]:
    pattern = f"%{query}%"
    msgs = (await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.device_id == device_id)
        .where(ConversationMessage.content.ilike(pattern))
        .order_by(desc(ConversationMessage.ts))
        .limit(limit)
    )).scalars().all()

    # Group by session
    seen_sessions: set[str] = set()
    results = []
    for m in msgs:
        sess = await db.get(ConversationSession, m.session_id)
        if sess and sess.id not in seen_sessions:
            seen_sessions.add(sess.id)
            results.append({
                "session_id":   sess.id,
                "title":        sess.title,
                "message":      m.content[:200],
                "role":         m.role,
                "ts":           m.ts,
                "updated_at":   sess.updated_at,
            })
    return results


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

async def _load_fresh_context(device_id: str, db: AsyncSession) -> dict:
    """Build the user context dict injected at every turn."""

    # Profile
    prow = (await db.execute(
        select(UserProfile).where(UserProfile.device_id == device_id)
    )).scalar_one_or_none()

    profile_lines = []
    if prow:
        if prow.name:    profile_lines.append(f"Name:    {prow.name}")
        if prow.career:  profile_lines.append(f"Career:  {prow.career}")
        if prow.interests:
            profile_lines.append(f"Interests: {', '.join(prow.interests[:5])}")
        if prow.learning_objectives:
            profile_lines.append(f"Learning: {', '.join((prow.learning_objectives or [])[:3])}")

    # Active goals
    goals = (await db.execute(
        select(LongTermGoal)
        .where(LongTermGoal.device_id == device_id)
        .where(LongTermGoal.status == "active")
        .order_by(LongTermGoal.updated_at.desc())
        .limit(8)
    )).scalars().all()

    # Active projects
    projects = (await db.execute(
        select(Project)
        .where(Project.device_id == device_id)
        .where(Project.status.in_(["active", "planning"]))
        .order_by(Project.updated_at.desc())
        .limit(8)
    )).scalars().all()

    # Live productivity context
    ctx_row = (await db.execute(
        select(UserContext)
        .where(UserContext.device_id == device_id)
        .order_by(UserContext.ts.desc())
        .limit(1)
    )).scalar_one_or_none()

    # Daily report (use cache)
    today = datetime.now().strftime("%Y-%m-%d")
    daily = (await db.execute(
        select(DailyReport)
        .where(DailyReport.device_id == device_id)
        .where(DailyReport.date == today)
        .order_by(DailyReport.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    return {
        "profile":  profile_lines,
        "goals":    goals,
        "projects": projects,
        "context":  ctx_row,
        "daily":    daily,
    }


async def _retrieve_relevant_memories(
    device_id: str,
    user_message: str,
    db: AsyncSession,
) -> list[Memory]:
    """Return memories whose title/content matches keywords from the user message."""
    words = [w for w in user_message.lower().split() if len(w) > 3][:6]
    if not words:
        # Fallback: most important recent memories
        result = await db.execute(
            select(Memory)
            .where(Memory.device_id == device_id)
            .order_by(Memory.importance.desc(), Memory.ts.desc())
            .limit(MAX_MEMORY_REFS)
        )
        return list(result.scalars().all())

    # Search for any keyword match
    filters = [
        or_(
            Memory.title.ilike(f"%{w}%"),
            Memory.content.ilike(f"%{w}%"),
        )
        for w in words
    ]
    result = await db.execute(
        select(Memory)
        .where(Memory.device_id == device_id)
        .where(or_(*filters))
        .order_by(Memory.importance.desc(), Memory.ts.desc())
        .limit(MAX_MEMORY_REFS)
    )
    found = list(result.scalars().all())

    # Pad with high-importance memories if sparse
    if len(found) < 3:
        extra = (await db.execute(
            select(Memory)
            .where(Memory.device_id == device_id)
            .where(Memory.importance >= 4)
            .order_by(Memory.ts.desc())
            .limit(MAX_MEMORY_REFS - len(found))
        )).scalars().all()
        seen = {m.id for m in found}
        found += [m for m in extra if m.id not in seen]

    return found[:MAX_MEMORY_REFS]


def _build_system_prompt(ctx: dict, memories: list[Memory]) -> str:
    lines = [_CONV_IDENTITY, ""]

    # User profile
    if ctx["profile"]:
        lines.append("USER PROFILE")
        lines.extend(f"  {l}" for l in ctx["profile"])
        lines.append("")

    # Active goals
    if ctx["goals"]:
        lines.append("ACTIVE GOALS")
        for g in ctx["goals"]:
            td   = f"  due {g.target_date}" if g.target_date else ""
            lines.append(f"  [{g.category}] {g.title}  {g.progress}%{td}")
        lines.append("")

    # Active projects
    if ctx["projects"]:
        lines.append("ACTIVE PROJECTS")
        for p in ctx["projects"]:
            dl   = f"  deadline {p.deadline}" if p.deadline else ""
            lines.append(f"  [{p.status}] {p.name}  {p.progress}%{dl}")
        lines.append("")

    # Relevant memories
    if memories:
        lines.append("RELEVANT MEMORIES")
        for m in memories:
            lines.append(f"  [{m.memory_type}] {m.title}: {m.content[:120]}")
        lines.append("")

    # Live context
    c = ctx["context"]
    if c:
        lines.append("LIVE PRODUCTIVITY CONTEXT")
        lines.append(f"  State:      {c.productivity_state}")
        lines.append(f"  Task:       {c.current_task}")
        lines.append(f"  App:        {c.dominant_app}")
        lines.append(f"  Work block: {'yes' if c.is_work_block else 'no'}")
        lines.append("")

    # Daily summary
    d = ctx["daily"]
    if d:
        lines.append(f"TODAY ({datetime.now().strftime('%A %d %B')})")
        lines.append(f"  Focus score:  {d.focus_score}%")
        lines.append(f"  Productive:   {round(d.productive_minutes)}m")
        lines.append(f"  Distracted:   {round(d.distraction_minutes)}m")
        lines.append("")

    return "\n".join(lines)


def _build_llm_messages(
    history: list[ConversationMessage],
    user_message: str,
) -> list[dict]:
    """Build the messages array for the LLM API call."""
    msgs = []

    # Include history (last MAX_HISTORY_MESSAGES turns)
    window = history[-MAX_HISTORY_MESSAGES:]
    for m in window:
        if m.role in ("user", "assistant"):
            msgs.append({"role": m.role, "content": m.content})

    # Current user message
    msgs.append({"role": "user", "content": user_message})
    return msgs


def _context_hash(ctx: dict) -> str:
    """Short hash of injected context for auditability."""
    summary = {
        "goals":    [g.id for g in ctx["goals"]],
        "projects": [p.id for p in ctx["projects"]],
        "ctx_ts":   round(ctx["context"].ts) if ctx["context"] else 0,
    }
    return hashlib.md5(json.dumps(summary, sort_keys=True).encode()).hexdigest()[:8]


def _auto_title(user_message: str) -> str:
    """Create a short session title from the first user message."""
    words = user_message.strip().split()
    title = " ".join(words[:SESSION_TITLE_WORDS])
    if len(words) > SESSION_TITLE_WORDS:
        title += "…"
    return title or "New conversation"


# ---------------------------------------------------------------------------
# Core: generate response for a session turn
# ---------------------------------------------------------------------------

async def generate_response(
    session_id: str,
    user_message: str,
    device_id: str,
    db: AsyncSession,
) -> dict:
    """
    Process one user turn in a conversation session.

    Returns:
        {
            session_id, message_id,
            text, provider, model,
            input_tokens, output_tokens, cost_usd, latency_ms,
            context_refs: [{ref_type, ref_id, ref_title}]
        }
    """
    t0 = time.monotonic()

    # Load session
    session = await get_session(session_id, db)
    if not session:
        raise ValueError(f"Session not found: {session_id}")

    # Load conversation history
    history = await get_history(session_id, MAX_HISTORY_MESSAGES * 2, db)

    # Assemble fresh context
    ctx      = await _load_fresh_context(device_id, db)
    memories = await _retrieve_relevant_memories(device_id, user_message, db)

    # Build system prompt + LLM messages
    system_prompt = _build_system_prompt(ctx, memories)
    llm_messages  = _build_llm_messages(history, user_message)
    ctx_hash      = _context_hash(ctx)

    # Determine task tier — conversations use FAST by default, DEEP for complex topics
    tier = _select_tier(user_message, history)

    # --- Persist user message ---
    user_msg = ConversationMessage(
        session_id    = session_id,
        device_id     = device_id,
        role          = "user",
        content       = user_message,
        ts            = time.time(),
        context_hash  = ctx_hash,
    )
    db.add(user_msg)
    await db.flush()   # get user_msg.id

    # --- Call provider or Cognitive Council ---
    mgr           = get_provider_manager()
    council_meta  = None

    try:
        from app.services.council.model_router    import classify_query
        from app.services.council.council_manager import get_council
        from app.services.ai.base_provider        import ProviderName

        analysis = await classify_query(user_message)
        use_council = (
            len(analysis.roles) > 2        # more than just [executive] or [executive, conversation]
            and analysis.complexity in ("medium", "high")
        )

        if use_council:
            # Build a context hint from the system prompt summary
            hint_lines = []
            if ctx["profile"]:
                hint_lines.append("User: " + " | ".join(ctx["profile"][:3]))
            if ctx["context"]:
                hint_lines.append(f"State: {ctx['context'].productivity_state}")
            context_hint = "\n".join(hint_lines)

            council  = get_council()
            session_ = await council.consult(
                query        = user_message,
                context_hint = context_hint,
                device_id    = device_id,
            )
            from app.services.ai.base_provider import GenerateResponse
            resp = GenerateResponse(
                text          = session_.final_answer,
                provider      = ProviderName.CLAUDE,
                model         = f"council/{session_.specialists_used}specialists",
                input_tokens  = 0,
                output_tokens = 0,
                latency_ms    = session_.total_latency_ms,
                cost_usd      = session_.total_cost_usd,
            )
            council_meta = {
                "roles":     session_.roles_activated,
                "complexity": analysis.complexity,
                "specialists_used": session_.specialists_used,
                "specialists_accepted": session_.specialists_accepted,
                "total_cost_usd": round(session_.total_cost_usd, 6),
            }
            logger.info(
                "Council answered  roles=%s  ms=%.0f  cost=$%.5f  device=%s",
                session_.roles_activated, session_.total_latency_ms, session_.total_cost_usd, device_id[:16],
            )
        else:
            resp = await _call_multiturn(system_prompt, llm_messages, tier, device_id, mgr)

    except Exception as exc:
        logger.warning("Council routing failed (%s) — falling back to direct provider", exc)
        resp = await _call_multiturn(system_prompt, llm_messages, tier, device_id, mgr)

    latency_ms = (time.monotonic() - t0) * 1000

    # --- Persist assistant message ---
    asst_msg = ConversationMessage(
        session_id    = session_id,
        device_id     = device_id,
        role          = "assistant",
        content       = resp.text or (resp.error or "I encountered an error. Please try again."),
        provider      = resp.provider.value,
        model         = resp.model,
        input_tokens  = resp.input_tokens,
        output_tokens = resp.output_tokens,
        cost_usd      = resp.cost_usd,
        latency_ms    = latency_ms,
        context_hash  = ctx_hash,
        ts            = time.time(),
    )
    db.add(asst_msg)
    await db.flush()

    # --- Context references ---
    refs = []
    for g in ctx["goals"]:
        db.add(ContextReference(
            message_id = asst_msg.id,
            session_id = session_id,
            ref_type   = "goal",
            ref_id     = str(g.id),
            ref_title  = g.title,
            ts         = time.time(),
        ))
        refs.append({"ref_type": "goal", "ref_id": str(g.id), "ref_title": g.title})

    for p in ctx["projects"]:
        db.add(ContextReference(
            message_id = asst_msg.id,
            session_id = session_id,
            ref_type   = "project",
            ref_id     = str(p.id),
            ref_title  = p.name,
            ts         = time.time(),
        ))
        refs.append({"ref_type": "project", "ref_id": str(p.id), "ref_title": p.name})

    for m in memories:
        db.add(ContextReference(
            message_id = asst_msg.id,
            session_id = session_id,
            ref_type   = "memory",
            ref_id     = str(m.id),
            ref_title  = m.title,
            ts         = time.time(),
        ))

    # --- Update session ---
    session.message_count  += 2
    session.updated_at      = time.time()
    session.total_cost_usd += resp.cost_usd
    if resp.provider:
        session.provider_used = resp.provider.value
    # Auto-title from first user message if still default
    if session.title in ("New conversation", "") and session.message_count == 2:
        session.title = _auto_title(user_message)

    # --- Provider usage log ---
    db.add(ProviderUsage(
        provider      = resp.provider.value,
        model         = resp.model,
        task_type     = "conversation",
        input_tokens  = resp.input_tokens,
        output_tokens = resp.output_tokens,
        cost_usd      = resp.cost_usd,
        ts            = time.time(),
    ))
    db.add(ReasoningLog(
        device_id     = device_id,
        task_type     = "conversation",
        provider      = resp.provider.value,
        model         = resp.model,
        latency_ms    = latency_ms,
        input_tokens  = resp.input_tokens,
        output_tokens = resp.output_tokens,
        cost_usd      = resp.cost_usd,
        error         = resp.error,
        ts            = time.time(),
    ))

    await db.commit()

    # --- Action intent detection ---
    # Classify the USER's message for actionable intent.
    # LLMs suggest; the Router decides; Executors act.
    action_submitted = None
    try:
        from app.services.actions.action_router import classify_intent
        from app.services.actions.action_queue import get_action_queue
        intent = classify_intent(
            text       = user_message,
            device_id  = device_id,
            source     = "conversation",
            session_id = session_id,
        )
        if intent:
            queue          = get_action_queue()
            queued_action  = await queue.submit(intent)
            action_submitted = {
                "action_id":   queued_action.id,
                "action_type": queued_action.action_type,
                "safety_level": queued_action.safety_level,
                "state":       queued_action.state,
            }
            logger.info(
                "Conversation action detected: %s [%s] device=%s",
                intent.action_type, queued_action.safety_level, device_id[:16],
            )
    except Exception as exc:
        logger.debug("Action classification skipped: %s", exc)

    return {
        "session_id":      session_id,
        "message_id":      asst_msg.id,
        "text":            asst_msg.content,
        "provider":        resp.provider.value,
        "model":           resp.model,
        "input_tokens":    resp.input_tokens,
        "output_tokens":   resp.output_tokens,
        "cost_usd":        resp.cost_usd,
        "latency_ms":      round(latency_ms, 1),
        "context_refs":    refs,
        "error":           resp.error,
        "action":          action_submitted,
        "council":         council_meta,
    }


async def _call_multiturn(
    system_prompt: str,
    messages: list[dict],
    tier: TaskTier,
    device_id: str,
    mgr,
) -> GenerateResponse:
    """
    Call the provider with a full multi-turn messages array.
    Each provider's generate_async interface accepts a single-turn GenerateRequest.
    For multi-turn we call the provider directly.
    """
    from app.config import settings
    from app.services.ai.base_provider import ProviderName

    preferred = ProviderName(settings.ai_preferred_provider)
    order = [preferred] + [n for n in [ProviderName.CLAUDE, ProviderName.OPENAI, ProviderName.LOCAL]
                           if n != preferred]

    model_fast = {
        ProviderName.CLAUDE: "claude-haiku-4-5-20251001",
        ProviderName.OPENAI: "gpt-4o-mini",
        ProviderName.LOCAL:  settings.local_fast_model,
    }
    model_deep = {
        ProviderName.CLAUDE: "claude-sonnet-4-6",
        ProviderName.OPENAI: "gpt-4o",
        ProviderName.LOCAL:  settings.local_deep_model,
    }

    last_error = "No providers available."

    for name in order:
        provider = mgr._providers.get(name)
        if not provider or not provider.is_enabled():
            continue

        model = model_deep[name] if tier == TaskTier.DEEP else model_fast[name]
        t0    = time.monotonic()

        try:
            if name == ProviderName.CLAUDE:
                import anthropic as _ant
                client = provider._get_client()
                msg = await client.messages.create(
                    model       = model,
                    max_tokens  = 1024,
                    temperature = 0.45,
                    system      = system_prompt,
                    messages    = messages,
                )
                latency = (time.monotonic() - t0) * 1000
                text    = msg.content[0].text if msg.content else ""
                in_tok  = msg.usage.input_tokens
                out_tok = msg.usage.output_tokens
                cost    = provider.estimate_cost(in_tok, out_tok, model)
                provider._health.calls_total += 1
                provider._health.avg_latency = provider._health.avg_latency * 0.9 + latency * 0.1

            elif name == ProviderName.OPENAI:
                client = provider._get_client()
                resp = await client.chat.completions.create(
                    model       = model,
                    max_tokens  = 1024,
                    temperature = 0.45,
                    messages    = [{"role": "system", "content": system_prompt}] + messages,
                )
                latency = (time.monotonic() - t0) * 1000
                text    = resp.choices[0].message.content or ""
                in_tok  = resp.usage.prompt_tokens
                out_tok = resp.usage.completion_tokens
                cost    = provider.estimate_cost(in_tok, out_tok, model)
                provider._health.calls_total += 1

            elif name == ProviderName.LOCAL:
                import httpx
                payload = {
                    "model":       model,
                    "max_tokens":  1024,
                    "temperature": 0.45,
                    "messages":    [{"role": "system", "content": system_prompt}] + messages,
                }
                async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as hclient:
                    r = await hclient.post(f"{settings.local_model_url.rstrip('/')}/v1/chat/completions", json=payload)
                    r.raise_for_status()
                    data = r.json()
                latency = (time.monotonic() - t0) * 1000
                text    = data["choices"][0]["message"]["content"]
                usage   = data.get("usage", {})
                in_tok  = usage.get("prompt_tokens", 0)
                out_tok = usage.get("completion_tokens", 0)
                cost    = 0.0

            else:
                continue

            from app.services.ai.base_provider import GenerateResponse
            return GenerateResponse(
                text          = text,
                provider      = name,
                model         = model,
                input_tokens  = in_tok,
                output_tokens = out_tok,
                latency_ms    = latency,
                cost_usd      = cost,
            )

        except Exception as e:
            last_error = str(e)
            logger.warning("Provider %s failed in conversation: %s", name.value, e)
            if hasattr(provider, "_health"):
                provider._health.calls_error += 1

    from app.services.ai.base_provider import GenerateResponse, ProviderName as PN
    return GenerateResponse(
        text="MARK III is operating without an AI provider. "
             "Add ANTHROPIC_API_KEY or OPENAI_API_KEY to .env to enable conversations.",
        provider=PN.CLAUDE, model="none",
        input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0,
        error=f"All providers failed: {last_error}",
    )


# ---------------------------------------------------------------------------
# SSE streaming (for web / voice clients)
# ---------------------------------------------------------------------------

async def stream_response(
    session_id: str,
    user_message: str,
    device_id: str,
    db: AsyncSession,
) -> AsyncIterator[str]:
    """
    Yields SSE-formatted events for streaming clients.
    Mobile uses the non-streaming endpoint; this is for web/voice/future.

    Event format:
      data: {"type": "token",  "text": "..."}
      data: {"type": "done",   "message_id": 42, "cost_usd": 0.0001}
      data: {"type": "error",  "text": "..."}
    """
    from app.config import settings
    from app.services.ai.base_provider import ProviderName

    session = await get_session(session_id, db)
    if not session:
        yield f'data: {json.dumps({"type": "error", "text": "Session not found."})}\n\n'
        return

    history  = await get_history(session_id, MAX_HISTORY_MESSAGES * 2, db)
    ctx      = await _load_fresh_context(device_id, db)
    memories = await _retrieve_relevant_memories(device_id, user_message, db)

    system_prompt = _build_system_prompt(ctx, memories)
    llm_messages  = _build_llm_messages(history, user_message)
    ctx_hash      = _context_hash(ctx)
    tier          = _select_tier(user_message, history)

    # Persist user message
    user_msg = ConversationMessage(
        session_id   = session_id,
        device_id    = device_id,
        role         = "user",
        content      = user_message,
        ts           = time.time(),
        context_hash = ctx_hash,
    )
    db.add(user_msg)
    await db.flush()

    preferred = ProviderName(settings.ai_preferred_provider)

    # Try Claude streaming first
    if preferred == ProviderName.CLAUDE and settings.anthropic_api_key:
        async for chunk in _stream_claude(
            session, user_msg, ctx, memories,
            system_prompt, llm_messages, tier, device_id, db, ctx_hash
        ):
            yield chunk
        return

    # Try OpenAI streaming
    if preferred == ProviderName.OPENAI and settings.openai_api_key:
        async for chunk in _stream_openai(
            session, user_msg, ctx, memories,
            system_prompt, llm_messages, tier, device_id, db, ctx_hash
        ):
            yield chunk
        return

    # No streaming provider — fall back to non-streaming
    try:
        mgr  = get_provider_manager()
        resp = await _call_multiturn(system_prompt, llm_messages, tier, device_id, mgr)
        full_text = resp.text or resp.error or "No response."
        # Emit whole response as single token chunk so client receives it
        yield f'data: {json.dumps({"type": "token", "text": full_text})}\n\n'
        await _finalize_stream(
            session, user_msg, full_text, resp,
            ctx, memories, device_id, db, ctx_hash
        )
        yield f'data: {json.dumps({"type": "done", "cost_usd": resp.cost_usd})}\n\n'
    except Exception as e:
        yield f'data: {json.dumps({"type": "error", "text": str(e)})}\n\n'


async def _stream_claude(session, user_msg, ctx, memories, system_prompt, messages,
                          tier, device_id, db, ctx_hash):
    """Generator that yields SSE events from Claude streaming."""
    from app.config import settings
    from app.services.ai.base_provider import ProviderName, GenerateResponse
    from app.services.ai.provider_manager import get_provider_manager
    import anthropic

    model_map = {"fast": "claude-haiku-4-5-20251001", "deep": "claude-sonnet-4-6"}
    model = model_map["deep"] if tier == TaskTier.DEEP else model_map["fast"]

    mgr      = get_provider_manager()
    provider = mgr._providers.get(ProviderName.CLAUDE)
    if not provider:
        return

    client     = provider._get_client()
    full_text  = ""
    in_tok     = 0
    out_tok    = 0
    t0         = time.monotonic()

    events = []
    try:
        async with client.messages.stream(
            model       = model,
            max_tokens  = 1024,
            temperature = 0.45,
            system      = system_prompt,
            messages    = messages,
        ) as stream:
            async for text_chunk in stream.text_stream:
                full_text += text_chunk
                events.append(f'data: {json.dumps({"type": "token", "text": text_chunk})}\n\n')

            final = await stream.get_final_message()
            in_tok  = final.usage.input_tokens
            out_tok = final.usage.output_tokens

    except Exception as e:
        events.append(f'data: {json.dumps({"type": "error", "text": str(e)})}\n\n')
        for ev in events:
            yield ev
        return

    latency = (time.monotonic() - t0) * 1000
    cost    = provider.estimate_cost(in_tok, out_tok, model)

    resp = GenerateResponse(
        text=full_text, provider=ProviderName.CLAUDE, model=model,
        input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency, cost_usd=cost,
    )
    await _finalize_stream(session, user_msg, full_text, resp, ctx, memories, device_id, db, ctx_hash)

    events.append(f'data: {json.dumps({"type": "done", "cost_usd": cost, "model": model})}\n\n')
    for ev in events:
        yield ev


async def _stream_openai(session, user_msg, ctx, memories, system_prompt, messages,
                          tier, device_id, db, ctx_hash):
    """Generator that yields SSE events from OpenAI streaming."""
    from app.config import settings
    from app.services.ai.base_provider import ProviderName, GenerateResponse
    from app.services.ai.provider_manager import get_provider_manager

    model_map = {"fast": "gpt-4o-mini", "deep": "gpt-4o"}
    model = model_map["deep"] if tier == TaskTier.DEEP else model_map["fast"]

    mgr      = get_provider_manager()
    provider = mgr._providers.get(ProviderName.OPENAI)
    if not provider:
        return

    client    = provider._get_client()
    full_text = ""
    events    = []
    t0        = time.monotonic()

    try:
        stream = await client.chat.completions.create(
            model       = model,
            max_tokens  = 1024,
            temperature = 0.45,
            stream      = True,
            messages    = [{"role": "system", "content": system_prompt}] + messages,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full_text += delta
                events.append(f'data: {json.dumps({"type": "token", "text": delta})}\n\n')

    except Exception as e:
        events.append(f'data: {json.dumps({"type": "error", "text": str(e)})}\n\n')
        for ev in events:
            yield ev
        return

    latency = (time.monotonic() - t0) * 1000
    cost    = provider.estimate_cost(0, 0, model)   # approximate; no usage in stream

    resp = GenerateResponse(
        text=full_text, provider=ProviderName.OPENAI, model=model,
        input_tokens=0, output_tokens=0, latency_ms=latency, cost_usd=cost,
    )
    await _finalize_stream(session, user_msg, full_text, resp, ctx, memories, device_id, db, ctx_hash)

    events.append(f'data: {json.dumps({"type": "done", "cost_usd": cost, "model": model})}\n\n')
    for ev in events:
        yield ev


async def _finalize_stream(session, user_msg, full_text, resp, ctx, memories, device_id, db, ctx_hash):
    """Persist assistant message and update session after streaming completes."""
    from app.models.db import ProviderUsage, ReasoningLog

    asst_msg = ConversationMessage(
        session_id    = session.id,
        device_id     = device_id,
        role          = "assistant",
        content       = full_text,
        provider      = resp.provider.value,
        model         = resp.model,
        input_tokens  = resp.input_tokens,
        output_tokens = resp.output_tokens,
        cost_usd      = resp.cost_usd,
        latency_ms    = resp.latency_ms,
        context_hash  = ctx_hash,
        ts            = time.time(),
    )
    db.add(asst_msg)
    await db.flush()

    for g in ctx["goals"]:
        db.add(ContextReference(
            message_id=asst_msg.id, session_id=session.id,
            ref_type="goal", ref_id=str(g.id), ref_title=g.title, ts=time.time(),
        ))
    for m in memories:
        db.add(ContextReference(
            message_id=asst_msg.id, session_id=session.id,
            ref_type="memory", ref_id=str(m.id), ref_title=m.title, ts=time.time(),
        ))

    session.message_count  += 2
    session.updated_at      = time.time()
    session.total_cost_usd += resp.cost_usd
    session.provider_used   = resp.provider.value
    if session.title in ("New conversation", "") and user_msg:
        session.title = _auto_title(user_msg.content)

    db.add(ProviderUsage(
        provider=resp.provider.value, model=resp.model, task_type="conversation",
        input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
        cost_usd=resp.cost_usd, ts=time.time(),
    ))
    await db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select_tier(user_message: str, history: list[ConversationMessage]) -> TaskTier:
    """
    Use DEEP tier for complex analytical requests.
    Default to FAST for conversational exchanges.
    """
    deep_keywords = {
        "career", "goals", "strategy", "analyse", "analyze", "advice",
        "weekly", "review", "recommend", "priorities", "plan", "guidance",
        "should i", "what should", "help me decide",
    }
    lower = user_message.lower()
    if any(kw in lower for kw in deep_keywords):
        return TaskTier.DEEP
    # Multi-turn deep context (session already has substantial history)
    if len(history) >= 6:
        return TaskTier.FAST
    return TaskTier.FAST
