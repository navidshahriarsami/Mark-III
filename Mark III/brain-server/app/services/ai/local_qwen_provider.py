"""
MARK III Phase 15C — Local Qwen Provider (Ollama)

Runs Qwen2.5:3b locally via Ollama for fast conversational voice responses
without internet or OpenRouter.

Model: qwen2.5:3b  (~1.9 GB)  — NO thinking mode, fast CPU inference.
Why not qwen3:4b: qwen3:4b's thinking chain adds 100-150 tokens of internal
reasoning per response (5-8s on CPU). qwen2.5:3b has no thinking mode and
responds in 1-2s, which is the right trade-off for voice.

Target latency: 0.8-2s for short voice responses (≤ 20 words).

Fallback chain:
    Qwen local (this module)
    → Gemma 4 31B  (OpenRouter free)
    → Llama 3.3 70B (OpenRouter free)
    → Executive GPT-OSS (OpenRouter free)

Install:
    winget install Ollama.Ollama
    ollama pull qwen2.5:3b

Health check fires at MARK startup (via council loop), result cached.
If Ollama is not running, returns "" immediately — council uses OpenRouter.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

# Safety net: strip any thinking-mode blocks that slip through
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

log = logging.getLogger("markiii.ai.qwen_local")

_OLLAMA_BASE        = "http://localhost:11434"
_MODEL              = "qwen2.5:7b"
_HEALTH_TIMEOUT_S   = 2.0    # fast ping — fail quickly if Ollama is not running
_GENERATE_TIMEOUT_S = 12.0   # generous for first cold inference after idle

# Cached availability state: None = never checked, True = ok, False = unavailable
_available: Optional[bool] = None

# ── Conversation history ───────────────────────────────────────────────────────
# Maintains last N turns so Qwen can understand "yes, please do that" and
# other context-dependent follow-ups.
_MAX_HISTORY_TURNS = 6          # last 6 exchanges (12 messages)
_history: list[dict] = []       # [{"role": "user"|"assistant", "content": "..."}]
_history_lock = __import__("threading").Lock()


def add_to_history(user_text: str, assistant_text: str) -> None:
    """Add a completed exchange to the conversation history."""
    with _history_lock:
        _history.append({"role": "user",      "content": f"USER: {user_text}"})
        _history.append({"role": "assistant", "content": assistant_text})
        # Keep last N turns only
        max_msgs = _MAX_HISTORY_TURNS * 2
        while len(_history) > max_msgs:
            _history.pop(0)


def clear_history() -> None:
    """Clear conversation history (called on pause/sleep/stop)."""
    with _history_lock:
        _history.clear()
    log.debug("Conversation history cleared")

# Voice-mode system prompt — strict word limit, no questions, no humor
_VOICE_SYSTEM = (
    "You are MARK III — a personal AI operating system built for your user.\n"
    "You run locally on Qwen2.5:3b via Ollama on the user's own machine.\n\n"
    "IDENTITY (critical — never break this):\n"
    "- You are MARK III. Not Claude. Not Anthropic. Not ChatGPT. Not OpenAI. Not Gwen.\n"
    "- If asked 'which AI are you', 'which model', 'who made you', 'what LLM': say you are MARK III running on a local Qwen model.\n"
    "- Never claim to be Claude, Anthropic, GPT, Gemini, or any other AI brand.\n\n"
    "STRICT RULES:\n"
    "- Maximum 15 words in your response\n"
    "- One short declarative sentence only\n"
    "- No questions back to the user\n"
    "- No humor, no sarcasm, no jokes, no wit\n"
    "- No preamble: never say 'Sure!', 'Of course!', 'Great!', 'Certainly!'\n"
    "- No markdown, no lists, no headers\n"
    "- Professional and immediate — answer without commentary"
)


# ─────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────

async def _ping() -> bool:
    """
    Quick health check: GET /api/tags with a 2-second timeout.
    Verifies both that Ollama is running and that the model is pulled.
    """
    global _available
    try:
        import httpx
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT_S) as client:
            resp = await client.get(f"{_OLLAMA_BASE}/api/tags")
        ok = resp.status_code == 200
        if ok:
            tags  = resp.json().get("models", [])
            names = [m.get("name", "") for m in tags]
            if not any(_MODEL in n for n in names):
                log.warning(
                    "Ollama running but model %r not found — run: ollama pull %s",
                    _MODEL, _MODEL,
                )
                _available = False
                return False
            log.info("Qwen local: Ollama ready  model=%s", _MODEL)
        _available = ok
        return ok
    except Exception as e:
        log.warning("Ollama not reachable: %s", e)
        _available = False
        return False


async def _warmup() -> None:
    """
    Fire a short dummy generation to load the model weights into RAM.
    Called once after the health check passes so the first real voice
    query doesn't incur model-load latency.
    """
    try:
        import httpx
        payload = {
            "model": _MODEL,
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False,
            "options": {"num_predict": 5, "temperature": 0.1},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(f"{_OLLAMA_BASE}/api/chat", json=payload)
        log.info("Qwen local: warmup complete")
    except Exception as e:
        log.debug("Qwen warmup skipped: %s", e)


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

async def generate(
    user_prompt: str,
    context_hint: str = "",
    system: str = _VOICE_SYSTEM,
) -> tuple[str, int, float]:
    """
    Generate a short voice response from the local model.

    Returns (text, tokens_out, latency_ms).
    Returns ("", 0, 0.0) on any failure — caller falls through to OpenRouter.
    """
    global _available

    # Lazy health check on first call
    if _available is None:
        if not await _ping():
            return "", 0, 0.0

    if _available is False:
        return "", 0, 0.0

    user_msg = f"CONTEXT: {context_hint}\n\nUSER: {user_prompt}" if context_hint else f"USER: {user_prompt}"

    # Phase 18: inject language instruction if non-English detected
    effective_system = system
    try:
        from app.services.integrations.language_service import get_current, build_language_instruction
        lang_instr = build_language_instruction(get_current())
        if lang_instr:
            effective_system = system + "\n\n" + lang_instr
    except Exception:
        pass

    # Build message list: system + conversation history + current turn
    with _history_lock:
        history_snapshot = list(_history)

    messages = [{"role": "system", "content": effective_system}]
    messages.extend(history_snapshot)
    messages.append({"role": "user", "content": user_msg})

    payload = {
        "model": _MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": 60,      # 60 tokens ≈ 30 words — plenty for voice responses
            "temperature": 0.4,
            "stop":        ["\n\n", "---", "**", "##"],
        },
    }

    t0 = time.monotonic()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=_GENERATE_TIMEOUT_S) as client:
            resp = await client.post(f"{_OLLAMA_BASE}/api/chat", json=payload)

        if resp.status_code != 200:
            log.warning("Qwen local HTTP %d — marking unavailable", resp.status_code)
            _available = False
            return "", 0, 0.0

        data       = resp.json()
        raw_text   = data.get("message", {}).get("content", "")
        tokens_out = data.get("eval_count", 0)
        ms         = (time.monotonic() - t0) * 1000

        # Strip any thinking blocks (safety net for other models)
        text = _THINK_RE.sub("", raw_text).strip()

        if not text:
            log.warning("Qwen local: empty response (raw=%r)", raw_text[:80])
            return "", 0, ms

        log.info("Qwen local  model=%s  tokens=%d  ms=%.0f  history=%d", _MODEL, tokens_out, ms, len(history_snapshot) // 2)
        _available = True
        # Record this exchange in conversation history
        add_to_history(user_prompt, text)
        return text, tokens_out, ms

    except Exception as e:
        ms = (time.monotonic() - t0) * 1000
        log.warning("Qwen local generate failed (%.0fms): %s", ms, e)
        _available = False
        return "", 0, ms


async def health_check() -> bool:
    """
    Public health check — runs at MARK startup via the council asyncio loop.
    Verifies Ollama is reachable and the model is pulled, then warms it up.
    """
    ok = await _ping()
    if ok:
        await _warmup()
    return ok


def is_available() -> bool:
    """Synchronous check on last known state. None → False (treat as unknown)."""
    return _available is True


def model_name() -> str:
    return _MODEL
