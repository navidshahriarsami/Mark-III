"""
MARK III — Profile Engine

Provides a structured profile context block before every Qwen call.
The LLM knows WHO it is talking to before any reasoning occurs.

Profile context is always injected — it is not optional.
It adapts response style, depth, and focus to the owner automatically.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("markiii.identity.profile")


def get_profile_context() -> str:
    """
    Returns a compact profile context string for injection into Qwen.
    Called by Context Builder on every non-social query.
    """
    try:
        from app.services.identity.identity_manager import get_profile
        profile = get_profile()

        lines = [f"OWNER PROFILE:"]
        name = profile.preferred_name or profile.display_name
        if name:
            lines.append(f"Name: {name}")
        if profile.occupation:
            lines.append(f"Occupation: {profile.occupation}")
        if profile.technical_level:
            lines.append(f"Technical level: {profile.technical_level}")
        if profile.current_projects:
            lines.append(f"Working on: {', '.join(profile.current_projects[:2])}")
        if profile.goals:
            lines.append(f"Goals: {', '.join(profile.goals[:2])}")

        c = profile.communication
        style_parts = []
        if c.response_length:  style_parts.append(c.response_length + " responses")
        if c.tone:             style_parts.append(c.tone + " tone")
        if style_parts:
            lines.append(f"Preferred style: {', '.join(style_parts)}")

        if profile.working_pattern.timezone:
            lines.append(f"Timezone: {profile.working_pattern.timezone}")

        if len(lines) <= 1:
            return ""   # no meaningful profile yet

        return "\n".join(lines)

    except Exception as e:
        log.debug("Profile context error: %s", e)
        return ""


def get_response_style_instruction(query: str = "") -> str:
    """
    Returns a style instruction based on the owner's communication preferences.
    Appended to Qwen's system prompt.
    """
    try:
        from app.services.identity.identity_manager import get_profile
        p = get_profile()
        c = p.communication

        instr = []
        if c.response_length == "concise":
            instr.append("Keep responses brief and direct.")
        elif c.response_length == "detailed":
            instr.append("Provide thorough, detailed explanations.")

        if c.explanation_depth == "beginner":
            instr.append("Avoid jargon. Use simple language.")
        elif c.explanation_depth == "expert":
            instr.append("Assume expert-level knowledge. Skip basics.")

        if c.tone == "casual":
            instr.append("Use casual, conversational language.")
        elif c.tone == "technical":
            instr.append("Use precise technical language.")

        if p.languages and p.languages[0] != "en":
            instr.append(f"Respond in {p.languages[0]} unless technical terms require English.")

        return " ".join(instr)
    except Exception:
        return ""
