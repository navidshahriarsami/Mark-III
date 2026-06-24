"""
MARK III Cognitive Council — Consensus Engine

Assembles accepted specialist outputs into a structured brief,
then calls the Executive using its fallback chain:
  1. Claude Sonnet 4.6  (if key present)
  2. Nemotron 3 Ultra   (openrouter free)
  3. GPT-OSS 120B       (openrouter free — OpenInference, 99.98% uptime)

MARK III always has a voice. No single provider is mandatory.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .specialist_registry import SpecialistRole, get_specialist, executive_chain
from .voting_engine        import SpecialistResponse, VotingResult

logger = logging.getLogger("markiii.council.consensus")


@dataclass
class ConsensusInput:
    query:         str
    voting_result: VotingResult
    context_hint:  str = ""
    device_id:     str = ""


async def synthesize(inp: ConsensusInput) -> tuple[str, SpecialistResponse]:
    """
    Build the Executive prompt from accepted specialist outputs,
    then call the Executive using its provider fallback chain.
    Returns (final_text, executive_response).
    """
    from app.services.council.council_manager import _call_provider

    executive = get_specialist(SpecialistRole.EXECUTIVE)

    # Build specialist brief (exclude any prior Executive response)
    brief_parts: list[str] = []
    for resp in inp.voting_result.accepted:
        if resp.role == SpecialistRole.EXECUTIVE.value:
            continue
        brief_parts.append(f"[{resp.name.upper()} SPECIALIST]\n{resp.text.strip()}")

    if brief_parts:
        specialist_brief = "\n\n".join(brief_parts)
        user_prompt = (
            f"USER QUERY:\n{inp.query}\n\n"
            f"SPECIALIST INPUTS:\n{specialist_brief}\n\n"
            + (f"CONTEXT:\n{inp.context_hint}\n\n" if inp.context_hint else "")
            + "Now produce MARK III's final response."
        )
    else:
        user_prompt = (
            f"USER QUERY:\n{inp.query}\n\n"
            + (f"CONTEXT:\n{inp.context_hint}\n\n" if inp.context_hint else "")
            + "Respond as MARK III."
        )

    # Try Executive fallback chain
    chain = executive_chain()
    t0    = time.monotonic()
    text  = ""
    used_provider = chain[0][0]
    used_model    = chain[0][1]

    logger.info(
        "Executive chain (%d): %s",
        len(chain),
        " → ".join(f"{pk}/{m}" for pk, m in chain),
    )

    for idx, (provider_key, model) in enumerate(chain):
        logger.info(
            "Executive attempt %d/%d: %s/%s",
            idx + 1, len(chain), provider_key, model,
        )
        result = await _call_provider(provider_key, model, executive, user_prompt)
        if result.strip():
            text          = result
            used_provider = provider_key
            used_model    = model
            logger.info(
                "Executive final: %s/%s  (attempt %d/%d)",
                provider_key, model, idx + 1, len(chain),
            )
            break
        logger.info(
            "Executive attempt %d/%d → no result, trying next",
            idx + 1, len(chain),
        )

    ms = (time.monotonic() - t0) * 1000

    if not text:
        text = "All reasoning systems are unreachable. Try again in a moment."
        logger.warning("Executive: all %d providers in chain failed.", len(chain))

    exec_resp = SpecialistResponse(
        role       = SpecialistRole.EXECUTIVE.value,
        name       = "Executive",
        text       = text,
        model      = used_model,
        provider   = used_provider,
        latency_ms = ms,
        cost_usd   = 0.0,
        error      = None if text != "All reasoning systems are unreachable. Try again in a moment." else "all providers failed",
    )

    return text, exec_resp
