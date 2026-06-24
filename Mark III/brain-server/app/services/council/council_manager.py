"""
MARK III Cognitive Council — Council Manager

Central orchestrator for Phase 14 multi-LLM reasoning.

Flow:
  1. classify_query()   → QueryAnalysis (which specialists to activate)
  2. parallel calls     → list[SpecialistResponse] (all specialists run concurrently)
  3. vote()             → VotingResult (filter low-quality responses)
  4. synthesize()       → Executive produces final answer
  5. return CouncilSession (full audit trail: cost, latency, who said what)

MARK III remains the single intelligence.
LLMs are cognitive modules — specialists — not speakers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("markiii.council.manager")

# ── Phase 15A: voice response word limit ──────────────────────────────────────
_MAX_VOICE_WORDS = 20

# ── Phase 15A: conversation tier (Gemma → Llama) ─────────────────────────────
# Used for low-complexity queries instead of the Executive (GPT-OSS).
# Target latency: 1-3s.  Falls through to Executive if both providers fail.

@dataclass(frozen=True)
class _ConvSpec:
    """Lightweight specialist-like object for the conversation tier."""
    role:          str   = "conversation"
    system_prompt: str   = (
        "You are MARK III — a personal AI assistant.\n\n"
        "VOICE MODE: 1-2 sentences only. Direct. Professional. No markdown. "
        "No lists. No humor. No filler phrases. Answer immediately. "
        "Maximum 20 words total."
    )
    max_tokens:    int   = 128
    temperature:   float = 0.5
    timeout_s:     float = 10.0
    fallback_chain: tuple = field(default_factory=tuple)
    local_only:    bool  = False

_CONV_SPEC  = _ConvSpec()
_CONV_CHAIN = [
    ("openrouter", "google/gemma-4-31b-it:free"),
    ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
]


def _enforce_word_limit(text: str, limit: int = _MAX_VOICE_WORDS) -> str:
    """
    Truncate voice response to `limit` words.
    Prefers to end at a sentence boundary inside the limit.
    """
    words = text.split()
    if len(words) <= limit:
        return text
    truncated = " ".join(words[:limit])
    for end in (".", "!", "?"):
        idx = truncated.rfind(end)
        if idx > len(truncated) // 2:
            return truncated[:idx + 1]
    return truncated.rstrip(",;") + "."


async def _call_conversation(query: str, context_hint: str) -> tuple[str, str, str, dict]:
    """
    Phase 15C: Qwen local → Gemma 4 → Llama 3.3 70B.
    Returns (answer_text, provider_key, model_used, diagnostics_dict).
    Empty answer means all providers failed — caller falls through to Executive.

    Fallback chain:
        1. Qwen3:4b (Ollama local) — 0.8-2s, no internet required
        2. Gemma 4 31B (OpenRouter free) — 1-4s
        3. Llama 3.3 70B (OpenRouter free) — 1-4s
    """
    user_prompt = f"USER: {query}"
    if context_hint:
        user_prompt = f"CONTEXT: {context_hint}\n\n{user_prompt}"

    diag: dict = {
        "provider":      "",
        "model":         "",
        "tokens":        0,
        "latency_ms":    0.0,
        "fallback_used": False,
    }

    # ── Phase 15C: Qwen local (Ollama) — try first ───────────────────────
    try:
        from app.services.ai.local_qwen_provider import (
            generate as _qwen_generate,
            model_name as _qwen_model,
        )
        _qm = _qwen_model()
        logger.info("Conversation tier: trying Qwen local (%s)", _qm)
        text, tokens, ms = await _qwen_generate(query, context_hint)
        if text.strip():
            diag.update(provider="local_qwen", model=_qm, tokens=tokens, latency_ms=ms)
            logger.info(
                "  Qwen local -> OK  tokens=%d  ms=%.0f  words=%d",
                tokens, ms, len(text.split()),
            )
            return text.strip(), "local_qwen", _qm, diag
        logger.info("  Qwen local -> no result — falling through to OpenRouter")
        diag["fallback_used"] = True
    except Exception as e:
        logger.warning("  Qwen local -> exception: %s — falling through", e)
        diag["fallback_used"] = True

    # ── OpenRouter fallback chain ─────────────────────────────────────────
    logger.info(
        "Conversation tier (OpenRouter): %s",
        " → ".join(f"{pk}/{m.split('/')[-1]}" for pk, m in _CONV_CHAIN),
    )

    for idx, (provider_key, model) in enumerate(_CONV_CHAIN):
        logger.info(
            "  Conv %d/%d: %s/%s",
            idx + 1, len(_CONV_CHAIN), provider_key, model,
        )
        t0     = time.monotonic()
        result = await _call_provider(provider_key, model, _CONV_SPEC, user_prompt)
        ms     = (time.monotonic() - t0) * 1000
        if result.strip():
            diag.update(
                provider=provider_key, model=model,
                latency_ms=ms,
                fallback_used=True,
            )
            logger.info(
                "  Conv final: %s/%s  ms=%.0f  words=%d",
                provider_key, model, ms, len(result.split()),
            )
            return result.strip(), provider_key, model, diag
        logger.info("  Conv %d/%d -> no result, trying next", idx + 1, len(_CONV_CHAIN))

    logger.warning("Conversation tier: all providers failed")
    return "", "", "", diag


# ---------------------------------------------------------------------------
# Session result
# ---------------------------------------------------------------------------

@dataclass
class CouncilSession:
    query:               str
    final_answer:        str
    roles_activated:     list[str]
    specialist_responses: list           # list[SpecialistResponse]
    executive_response:  object          # SpecialistResponse
    routing_analysis:    object          # QueryAnalysis
    voting_result:       object          # VotingResult
    total_cost_usd:      float
    total_latency_ms:    float
    specialists_used:    int
    specialists_accepted: int
    device_id:           str = ""

    def to_dict(self) -> dict:
        return {
            "query":               self.query,
            "final_answer":        self.final_answer,
            "roles_activated":     self.roles_activated,
            "total_cost_usd":      round(self.total_cost_usd, 6),
            "total_latency_ms":    round(self.total_latency_ms, 1),
            "specialists_used":    self.specialists_used,
            "specialists_accepted": self.specialists_accepted,
            "routing": {
                "complexity":  self.routing_analysis.complexity,
                "domain_tags": self.routing_analysis.domain_tags,
                "reasoning":   self.routing_analysis.reasoning,
                "via_llm":     False,
            },
            "responses": [
                {
                    "role":       r.role,
                    "name":       r.name,
                    "model":      r.model,
                    "provider":   r.provider,
                    "latency_ms": round(r.latency_ms, 1),
                    "cost_usd":   round(r.cost_usd, 6),
                    "tokens_in":  r.tokens_in,
                    "tokens_out": r.tokens_out,
                    "error":      r.error,
                    "text_preview": (r.text[:120] + "...") if len(r.text) > 120 else r.text,
                }
                for r in self.specialist_responses
            ],
        }


# ---------------------------------------------------------------------------
# Provider dispatch
# ---------------------------------------------------------------------------

def _get_provider(key: str):
    """Resolve a provider_key to a BaseProvider instance, or None if unavailable."""
    from app.services.ai.base_provider    import ProviderName
    from app.services.ai.provider_manager import get_provider_manager
    mgr = get_provider_manager()
    mapping = {
        "claude":     ProviderName.CLAUDE,
        "openai":     ProviderName.OPENAI,
        "openrouter": ProviderName.OPENROUTER,
        "local":      ProviderName.LOCAL,
    }
    pname = mapping.get(key)
    if pname is None:
        return None
    p = mgr._providers.get(pname)
    return p if (p and p.is_enabled()) else None


async def _call_provider(provider_key: str, model: str, specialist, user_prompt: str) -> str:
    """
    Call a specific (provider, model) pair. Returns text or "" on failure.
    Never raises.
    """
    from app.services.ai.base_provider    import GenerateRequest, TaskTier
    from app.services.ai.provider_manager import get_provider_manager

    provider = _get_provider(provider_key)
    if provider is None:
        logger.info(
            "  [provider] %s/%s → SKIP (not enabled or package missing)",
            provider_key, model,
        )
        return ""

    logger.info("  [provider] %s/%s → calling …", provider_key, model)

    req = GenerateRequest(
        system_prompt  = specialist.system_prompt,
        user_prompt    = user_prompt,
        task_tier      = TaskTier.FAST,
        max_tokens     = specialist.max_tokens,
        temperature    = specialist.temperature,
        task_label     = f"council.{specialist.role}",
        model_override = model,
    )

    try:
        resp = await asyncio.wait_for(
            provider.generate_async(req),
            timeout=specialist.timeout_s,
        )
        if resp.error:
            logger.info(
                "  [provider] %s/%s → FAIL (%s)",
                provider_key, model, resp.error,
            )
            return ""
        logger.info(
            "  [provider] %s/%s → OK  (%d chars, %.0f ms)",
            provider_key, model, len(resp.text), resp.latency_ms,
        )
        return resp.text
    except asyncio.TimeoutError:
        logger.warning(
            "  [provider] %s/%s → TIMEOUT (%.0fs)",
            provider_key, model, specialist.timeout_s,
        )
        return ""
    except Exception as exc:
        logger.error(
            "  [provider] %s/%s → EXCEPTION: %s",
            provider_key, model, exc,
        )
        return ""


async def _call_specialist_raw(specialist, user_prompt: str) -> str:
    """
    Call a specialist using its fallback chain.
    Tries primary (provider_key, model) first, then each fallback in order.
    Returns first successful non-empty text, or "" if all fail.
    Never raises.
    """
    if getattr(specialist, "local_only", False):
        return ""

    # Build ordered attempt list: primary + fallback_chain
    attempts = [(specialist.provider_key, specialist.model)]
    attempts += list(getattr(specialist, "fallback_chain", ()))

    for provider_key, model in attempts:
        text = await _call_provider(provider_key, model, specialist, user_prompt)
        if text.strip():
            if provider_key != specialist.provider_key:
                logger.info(
                    "Specialist %s used fallback provider=%s model=%s",
                    specialist.role, provider_key, model,
                )
            return text

    logger.warning("Specialist %s: all %d providers failed", specialist.role, len(attempts))
    return ""


async def _call_specialist(specialist, user_prompt: str) -> "SpecialistResponse":
    """
    Call a specialist using its fallback chain, return a structured SpecialistResponse.
    Tries primary provider first, then each fallback in order.
    """
    from app.services.council.voting_engine import SpecialistResponse

    if getattr(specialist, "local_only", False):
        return SpecialistResponse(
            role="routing", name="Routing", text="", model="local-rules",
            provider="local", latency_ms=0, cost_usd=0,
            error="local-only specialist — no LLM call",
        )

    t0 = time.monotonic()

    attempts = [(specialist.provider_key, specialist.model)]
    attempts += list(getattr(specialist, "fallback_chain", ()))

    text       = ""
    error      = None
    used_pkey  = specialist.provider_key
    used_model = specialist.model

    for provider_key, model in attempts:
        result = await _call_provider(provider_key, model, specialist, user_prompt)
        if result.strip():
            text       = result
            used_pkey  = provider_key
            used_model = model
            error      = None
            break
        error = f"all {len(attempts)} providers failed"

    ms = (time.monotonic() - t0) * 1000

    return SpecialistResponse(
        role       = specialist.role.value if hasattr(specialist.role, "value") else specialist.role,
        name       = specialist.name,
        text       = text,
        model      = used_model,
        provider   = used_pkey,
        latency_ms = ms,
        cost_usd   = 0.0,
        error      = error if not text else None,
    )


# ---------------------------------------------------------------------------
# Council Manager
# ---------------------------------------------------------------------------

class CognitiveCouncil:
    """
    Singleton orchestrator for multi-LLM reasoning.
    MARK III calls `consult()` when a query benefits from specialist analysis.
    """

    _cost_total:  float = 0.0
    _call_count:  int   = 0
    _error_count: int   = 0

    async def consult(
        self,
        query:        str,
        context_hint: str = "",
        device_id:    str = "",
        manual_roles: Optional[list[str]] = None,
        force_llm_routing: bool = False,
    ) -> CouncilSession:
        """
        Full council consultation:
          1. Route query to specialists
          2. Run specialists in parallel
          3. Vote (filter bad responses)
          4. Executive synthesis
          5. Return CouncilSession
        """
        from app.services.council.model_router    import classify_query, SpecialistRole
        from app.services.council.specialist_registry import get_specialist, SpecialistRole as SR
        from app.services.council.voting_engine    import vote
        from app.services.council.consensus_engine import synthesize, ConsensusInput

        wall_start = time.monotonic()

        # Step 1: Route
        if manual_roles:
            from app.services.council.model_router import QueryAnalysis
            roles = []
            if SR.EXECUTIVE.value not in manual_roles:
                roles.append(SR.EXECUTIVE)
            for rn in manual_roles:
                try:
                    roles.append(SR(rn))
                except ValueError:
                    pass
            analysis = QueryAnalysis(
                roles       = roles,
                complexity  = "medium",
                domain_tags = [],
                reasoning   = "manual override",
            )
        else:
            analysis = await classify_query(
                text         = query,
                context_hint = context_hint,
                force_llm    = force_llm_routing,
            )

        roles_to_call = [r for r in analysis.roles if r != SR.EXECUTIVE]

        logger.info(
            "Council  query=%r  complexity=%s  selected_specialists=%s",
            query[:80], analysis.complexity, [r.value for r in roles_to_call],
        )

        # ── Phase 16: low + medium → Qwen local first (90% local target) ──
        # Only "high" complexity (deep coding, multi-step reasoning) hits OpenRouter
        # specialists. Everything else goes to Qwen → Gemma fallback → Executive.
        if analysis.complexity in ("low", "medium") and not manual_roles:
            logger.info("Routing: complexity=%s → Qwen local (90%% local target)", analysis.complexity)
            conv_text, conv_provider, conv_model, conv_diag = await _call_conversation(
                query, context_hint,
            )
            if conv_text:
                conv_text = _enforce_word_limit(conv_text)
                wall_ms   = (time.monotonic() - wall_start) * 1000
                from app.services.council.voting_engine import SpecialistResponse, VotingResult
                conv_resp = SpecialistResponse(
                    role       = "conversation",
                    name       = "Conversation",
                    text       = conv_text,
                    model      = conv_model,
                    provider   = conv_provider,
                    latency_ms = conv_diag.get("latency_ms", wall_ms),
                    cost_usd   = 0.0,
                    tokens_out = conv_diag.get("tokens", 0),
                )
                empty_vote = VotingResult(
                    accepted        = [],
                    rejected        = [],
                    total_responses = 0,
                    total_accepted  = 0,
                )
                self._call_count += 1
                logger.info(
                    "Council  done  tier=conversation  provider=%s  model=%s  "
                    "words=%d  tokens=%d  llm_ms=%.0f  total_ms=%.0f  fallback=%s",
                    conv_provider, conv_model,
                    len(conv_text.split()),
                    conv_diag.get("tokens", 0),
                    conv_diag.get("latency_ms", 0),
                    wall_ms,
                    conv_diag.get("fallback_used", False),
                )
                return CouncilSession(
                    query                = query,
                    final_answer         = conv_text,
                    roles_activated      = ["conversation"],
                    specialist_responses = [conv_resp],
                    executive_response   = conv_resp,
                    routing_analysis     = analysis,
                    voting_result        = empty_vote,
                    total_cost_usd       = 0.0,
                    total_latency_ms     = wall_ms,
                    specialists_used     = 0,
                    specialists_accepted = 0,
                    device_id            = device_id,
                )
            logger.info("Conversation tier failed — falling through to Executive")
            roles_to_call = []

        # Step 2: Parallel specialist calls (exclude EXECUTIVE — it runs in step 4)
        tasks = [
            _call_specialist(get_specialist(role), query)
            for role in roles_to_call
            if role != SR.ROUTING  # ROUTING is internal only
        ]
        specialist_responses = list(await asyncio.gather(*tasks)) if tasks else []

        # Step 3: Vote
        voting_result = vote(specialist_responses, query)

        logger.info(
            "Council  accepted=%d/%d  rejected=%s",
            voting_result.total_accepted,
            voting_result.total_responses,
            list(voting_result.reasons.keys()),
        )

        # Step 4: Executive synthesis
        inp = ConsensusInput(
            query         = query,
            voting_result = voting_result,
            context_hint  = context_hint,
            device_id     = device_id,
        )
        final_answer, exec_resp = await synthesize(inp)

        # Phase 15A: enforce word limit on Executive output too
        final_answer = _enforce_word_limit(final_answer)

        # Step 5: Aggregate costs
        total_cost = sum(r.cost_usd for r in specialist_responses) + exec_resp.cost_usd
        wall_ms    = (time.monotonic() - wall_start) * 1000

        self._cost_total  += total_cost
        self._call_count  += 1

        session = CouncilSession(
            query                = query,
            final_answer         = final_answer,
            roles_activated      = [r.value for r in analysis.roles],
            specialist_responses = specialist_responses + [exec_resp],
            executive_response   = exec_resp,
            routing_analysis     = analysis,
            voting_result        = voting_result,
            total_cost_usd       = total_cost,
            total_latency_ms     = wall_ms,
            specialists_used     = len(specialist_responses),
            specialists_accepted = voting_result.total_accepted,
            device_id            = device_id,
        )

        logger.info(
            "Council  done  tier=executive  words=%d  cost=$%.5f  ms=%.0f",
            len(final_answer.split()), total_cost, wall_ms,
        )

        return session

    def stats(self) -> dict:
        return {
            "total_calls":   self._call_count,
            "total_cost_usd": round(self._cost_total, 6),
            "error_count":   self._error_count,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_council: Optional[CognitiveCouncil] = None


def get_council() -> CognitiveCouncil:
    global _council
    if _council is None:
        _council = CognitiveCouncil()
    return _council
