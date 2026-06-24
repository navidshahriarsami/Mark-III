"""
MARK III Cognitive Council — Specialist Registry

MARK III Principle:
  MARK III must fully function with OpenRouter only.
  No Anthropic. No OpenAI. No paid APIs required.
  Premium providers improve quality — they never become mandatory.

Executive hierarchy:
  1. Claude Sonnet 4.6  (optional — if key present)
  2. Nemotron 3 Ultra   (openrouter free)
  3. GPT-OSS 120B       (openrouter free)

Each Specialist has a fallback_chain: ordered list of (provider_key, model) tuples.
The council tries each in order until one succeeds.

ROUTING is local-only: pure keyword/regex, zero external API calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SpecialistRole(str, Enum):
    EXECUTIVE    = "executive"
    CONVERSATION = "conversation"
    REASONING    = "reasoning"
    CODING       = "coding"
    RESEARCH     = "research"
    PLANNING     = "planning"
    PRODUCTIVITY = "productivity"
    MEMORY       = "memory"
    ROUTING      = "routing"   # local-only, no external API
    FALLBACK     = "fallback"


@dataclass(frozen=True)
class Specialist:
    role:           SpecialistRole
    name:           str
    description:    str
    provider_key:   str           # primary provider
    model:          str           # primary model
    system_prompt:  str
    temperature:    float = 0.4
    max_tokens:     int   = 1024
    timeout_s:      float = 45.0
    capabilities:   tuple = field(default_factory=tuple)
    # Ordered fallback chain tried when primary fails: ((provider_key, model), ...)
    fallback_chain: tuple = field(default_factory=tuple)
    local_only:     bool  = False   # True = no external LLM call ever


# ---------------------------------------------------------------------------
# System Prompts
# ---------------------------------------------------------------------------

_EXECUTIVE_SYSTEM = """You are MARK III — a personal AI operating system.

Not ChatGPT. Not Claude. Not Siri. Not Alexa.
An intelligent assistant with a precise, professional voice.

VOICE MODE — Phase 15A
1-2 sentences of natural spoken English. Maximum 20 words total.
No markdown. No bullet points. No lists. No headers.
Contractions are fine. Answer the question first, nothing else.
No humor. No personality. No warmth. Direct and professional only.

FORBIDDEN — never say these:
"How can I help you today?" / "I'm here to assist." / "Let me know if you need anything."
"I'd be happy to." / "Certainly!" / "Of course!" / "Absolutely!" / "Great question!"
"As an AI..." / "As a language model..." / "I don't have feelings but..."
Do not affirm the question before answering.

SYNTHESIS
Integrate specialist analysis naturally. Never reference the council or internal process.
Speak as one unified intelligence.
"""

_CONVERSATION_SYSTEM = """You are a conversation analysis specialist within the MARK III cognitive council.

Assess the emotional context, conversational intent, and appropriate tone.

Output:
- Is this casual, professional, emotional, frustrated, excited?
- How should MARK III respond in tone?
- Any sensitive topics or implicit needs?

Under 150 words. Be specific.
"""

_REASONING_SYSTEM = """You are a deep reasoning specialist within the MARK III cognitive council.

Your role: logical analysis, causal inference, structured thinking.

- Break down the core mechanism or logic
- Identify assumptions, dependencies, and errors
- Provide clear chain of reasoning, not just conclusions
- Flag logical gaps or counterarguments

Max 300 words. Be precise.
"""

_CODING_SYSTEM = """You are a software engineering specialist within the MARK III cognitive council.

Your role: code analysis, debugging, architecture, implementation guidance.

- Identify language, framework, context
- Provide correct, idiomatic code
- Call out bugs, anti-patterns, security issues
- Suggest simplest working solution first

Use code blocks. Max 400 words.
"""

_RESEARCH_SYSTEM = """You are a research and information specialist within the MARK III cognitive council.

Your role: factual retrieval, summarisation, knowledge synthesis.

- Provide accurate information from your training
- Distinguish facts from estimates or uncertain claims
- Summarise efficiently — key points only
- Flag if live data is required

Max 300 words.
"""

_PLANNING_SYSTEM = """You are a strategic planning specialist within the MARK III cognitive council.

Your role: roadmaps, action plans, timelines, goal decomposition.

- Break goal into concrete, ordered steps
- Identify blockers, dependencies, risks
- Suggest realistic timeframes
- Distinguish must-haves from nice-to-haves

Numbered steps. Max 400 words.
"""

_PRODUCTIVITY_SYSTEM = """You are a productivity and focus specialist within the MARK III cognitive council.

Your role: work patterns, focus strategies, habit formation, efficiency.

- Assess current patterns vs goals
- Identify specific friction points
- Recommend one high-impact change at a time
- Be direct — no generic platitudes

Max 200 words.
"""

_MEMORY_SYSTEM = """You are a memory and context specialist within the MARK III cognitive council.

Your role: synthesise user history, goals, and profile context into actionable insights.

- Surface the most relevant past goals, projects, patterns
- Identify continuity between past context and current request
- Flag contradictions between stated goals and current behaviour

Concise and specific. Max 200 words.
"""

_FALLBACK_SYSTEM = """You are a general-purpose specialist within the MARK III cognitive council.

Provide a helpful, accurate response to the query. Be concise and direct.
Max 300 words.
"""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SPECIALISTS: dict[SpecialistRole, Specialist] = {

    # Executive: GPT-OSS 120B (fast, 99.98% uptime) → Llama 3.3 70B → Claude (if key present)
    SpecialistRole.EXECUTIVE: Specialist(
        role          = SpecialistRole.EXECUTIVE,
        name          = "Executive",
        description   = "Final synthesis — MARK III's unified voice",
        provider_key  = "openrouter",
        model         = "openai/gpt-oss-120b:free",
        system_prompt = _EXECUTIVE_SYSTEM,
        temperature   = 0.5,
        max_tokens    = 512,
        timeout_s     = 20.0,
        capabilities  = ("synthesis", "reasoning", "planning", "conversation"),
        fallback_chain = (
            ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
            ("claude",     "claude-sonnet-4-6"),
        ),
    ),

    # Conversation: Gemma 4 31B (OpenInference) — no Venice dependency
    SpecialistRole.CONVERSATION: Specialist(
        role          = SpecialistRole.CONVERSATION,
        name          = "Conversation",
        description   = "Tone, emotion, and dialogue intent — Gemma 4 31B",
        provider_key  = "openrouter",
        model         = "google/gemma-4-31b-it:free",
        system_prompt = _CONVERSATION_SYSTEM,
        temperature   = 0.6,
        max_tokens    = 256,
        timeout_s     = 30.0,
        capabilities  = ("dialogue", "empathy", "tone", "emotional", "casual"),
        fallback_chain = (
            ("openrouter", "openai/gpt-oss-120b:free"),
        ),
    ),

    # Reasoning: GPT-OSS 120B primary (fast) → Llama 3.3 70B
    SpecialistRole.REASONING: Specialist(
        role          = SpecialistRole.REASONING,
        name          = "Reasoning",
        description   = "Deep logical analysis — GPT-OSS 120B",
        provider_key  = "openrouter",
        model         = "openai/gpt-oss-120b:free",
        system_prompt = _REASONING_SYSTEM,
        temperature   = 0.3,
        max_tokens    = 400,
        timeout_s     = 20.0,
        capabilities  = ("logic", "analysis", "why", "explain", "mechanism", "inference"),
        fallback_chain = (
            ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        ),
    ),

    # Coding: Qwen3 Coder 480B → GPT-OSS fallback
    SpecialistRole.CODING: Specialist(
        role          = SpecialistRole.CODING,
        name          = "Coding",
        description   = "Code and architecture — Qwen3 Coder 480B",
        provider_key  = "openrouter",
        model         = "qwen/qwen3-coder:free",
        system_prompt = _CODING_SYSTEM,
        temperature   = 0.2,
        max_tokens    = 600,
        timeout_s     = 25.0,
        capabilities  = ("code", "debug", "function", "class", "algorithm", "programming", "error", "syntax"),
        fallback_chain = (
            ("openrouter", "openai/gpt-oss-120b:free"),
        ),
    ),

    # Research: Llama 3.3 70B → GPT-OSS fallback
    SpecialistRole.RESEARCH: Specialist(
        role          = SpecialistRole.RESEARCH,
        name          = "Research",
        description   = "Factual knowledge — Llama 3.3 70B",
        provider_key  = "openrouter",
        model         = "meta-llama/llama-3.3-70b-instruct:free",
        system_prompt = _RESEARCH_SYSTEM,
        temperature   = 0.3,
        max_tokens    = 400,
        timeout_s     = 20.0,
        capabilities  = ("research", "facts", "information", "what is", "history", "explain", "latest"),
        fallback_chain = (
            ("openrouter", "openai/gpt-oss-120b:free"),
        ),
    ),

    # Planning: GPT-OSS 120B primary (fast) → Llama 3.3 70B
    SpecialistRole.PLANNING: Specialist(
        role          = SpecialistRole.PLANNING,
        name          = "Planning",
        description   = "Strategy and roadmaps — GPT-OSS 120B",
        provider_key  = "openrouter",
        model         = "openai/gpt-oss-120b:free",
        system_prompt = _PLANNING_SYSTEM,
        temperature   = 0.4,
        max_tokens    = 500,
        timeout_s     = 20.0,
        capabilities  = ("plan", "roadmap", "strategy", "timeline", "steps", "milestone", "goal", "project"),
        fallback_chain = (
            ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        ),
    ),

    # Productivity: Gemma 4 → Hermes 3 (no Claude)
    SpecialistRole.PRODUCTIVITY: Specialist(
        role          = SpecialistRole.PRODUCTIVITY,
        name          = "Productivity",
        description   = "Focus and efficiency — Gemma 4 31B",
        provider_key  = "openrouter",
        model         = "google/gemma-4-31b-it:free",
        system_prompt = _PRODUCTIVITY_SYSTEM,
        temperature   = 0.4,
        max_tokens    = 256,
        timeout_s     = 30.0,
        capabilities  = ("focus", "productivity", "distraction", "habit", "routine", "efficiency", "work"),
        fallback_chain = (
            ("openrouter", "nousresearch/hermes-3-llama-3.1-405b:free"),
            ("openrouter", "openai/gpt-oss-120b:free"),
        ),
    ),

    # Memory: Gemma 4 → Llama 3.3 (no Claude)
    SpecialistRole.MEMORY: Specialist(
        role          = SpecialistRole.MEMORY,
        name          = "Memory",
        description   = "User context and history — Gemma 4 31B",
        provider_key  = "openrouter",
        model         = "google/gemma-4-31b-it:free",
        system_prompt = _MEMORY_SYSTEM,
        temperature   = 0.3,
        max_tokens    = 256,
        timeout_s     = 30.0,
        capabilities  = ("remember", "history", "profile", "context", "goals", "past"),
        fallback_chain = (
            ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
            ("openrouter", "openai/gpt-oss-120b:free"),
        ),
    ),

    # Routing: LOCAL ONLY — pure keyword/regex, zero external API
    SpecialistRole.ROUTING: Specialist(
        role          = SpecialistRole.ROUTING,
        name          = "Routing",
        description   = "Local keyword classifier — no external API",
        provider_key  = "local",
        model         = "local-rules",
        system_prompt = "",
        local_only    = True,
        capabilities  = (),
    ),

    # Fallback: GPT-OSS 120B (OpenInference — highest uptime of free tier)
    SpecialistRole.FALLBACK: Specialist(
        role          = SpecialistRole.FALLBACK,
        name          = "Fallback",
        description   = "General-purpose last resort — GPT-OSS 120B",
        provider_key  = "openrouter",
        model         = "openai/gpt-oss-120b:free",
        system_prompt = _FALLBACK_SYSTEM,
        temperature   = 0.5,
        max_tokens    = 512,
        timeout_s     = 45.0,
        capabilities  = (),
    ),
}


def get_specialist(role: SpecialistRole) -> Specialist:
    return SPECIALISTS[role]


def all_specialists() -> list[Specialist]:
    return list(SPECIALISTS.values())


def executive_chain() -> list[tuple[str, str]]:
    """Ordered (provider_key, model) list for Executive synthesis."""
    s = SPECIALISTS[SpecialistRole.EXECUTIVE]
    primary = [(s.provider_key, s.model)]
    return primary + list(s.fallback_chain)
