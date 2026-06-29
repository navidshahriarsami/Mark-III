"""
MARK III — Session Summarizer

At the end of each conversation session, generates a concise summary
of what was discussed and stores meaningful insights into ChromaDB.

Does NOT store raw conversations — only valuable extracts.
Uses Qwen to generate the summary (lightweight, local).

Stored summary contains:
  - Topics discussed
  - Decisions made
  - New preferences discovered
  - Pending actions
  - New knowledge gained
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime

log = logging.getLogger("markiii.identity.session")


def summarize_session_async(session_turns: list[dict]) -> None:
    """
    Summarize the session in a background thread.
    Called at session end — non-blocking.

    session_turns: list of {"role": "user"|"assistant", "content": "..."}
    """
    if not session_turns or len(session_turns) < 2:
        return
    threading.Thread(
        target=_do_summarize,
        args=(session_turns,),
        daemon=True,
        name="session-summarizer",
    ).start()


def _do_summarize(turns: list[dict]) -> None:
    try:
        # Build conversation text
        conv = "\n".join(
            f"{'User' if t['role'] == 'user' else 'MARK'}: {t['content'][:200]}"
            for t in turns[-20:]  # last 20 turns max
        )

        prompt = (
            f"Summarize this conversation in 3-5 bullet points.\n"
            f"Focus only on: decisions made, new knowledge, preferences revealed, pending tasks.\n"
            f"Skip pleasantries. Be specific.\n\n"
            f"Conversation:\n{conv}\n\n"
            f"Summary:"
        )

        # Use Qwen local for summarization
        import httpx
        r = httpx.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "qwen2.5:7b",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_predict": 200, "temperature": 0.2},
            },
            timeout=30.0,
        )

        if r.status_code != 200:
            return

        summary = r.json().get("message", {}).get("content", "").strip()
        if not summary or len(summary) < 20:
            return

        # Store in ChromaDB as a conversation summary
        from app.services.memory.chroma_store import get_chroma_store
        doc_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        get_chroma_store().add(
            content    = summary,
            doc_id     = doc_id,
            collection = "conversations",
            metadata   = {
                "type":       "session_summary",
                "date":       datetime.now().isoformat(timespec="seconds"),
                "turn_count": str(len(turns)),
            },
        )
        log.info("Session summary stored: %d chars", len(summary))

        # Run pattern extraction on the summary
        try:
            from app.services.identity.pattern_extractor import (
                extract_from_summary, apply_patterns_to_profile,
            )
            patterns = extract_from_summary(summary, use_qwen=False)
            apply_patterns_to_profile(patterns)
            if patterns:
                log.debug("Extracted %d patterns from session", len(patterns))
        except Exception as pe:
            log.debug("Pattern extraction error: %s", pe)

        # Record session end for habit detection
        try:
            from app.services.identity.habit_detector import get_habit_detector
            h = datetime.now().hour
            if h >= 20 or h <= 3:
                get_habit_detector().observe_late_work()
        except Exception:
            pass

    except Exception as e:
        log.debug("Session summarize error: %s", e)
