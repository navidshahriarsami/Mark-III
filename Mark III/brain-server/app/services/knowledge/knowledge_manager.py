"""
MARK III — Knowledge Manager

Orchestrates all knowledge sources for the cognitive pipeline.
Called by the Context Builder to enrich context before Qwen.

Priority:
  1. Obsidian vault  (authoritative documentation)
  2. ChromaDB vector (experiential memory)
  3. SQLite vector   (fallback)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("markiii.knowledge.manager")


@dataclass
class KnowledgeContext:
    obsidian_results: list  = field(default_factory=list)
    vector_results:   list  = field(default_factory=list)
    combined_text:    str   = ""
    sources:          list  = field(default_factory=list)

    def to_context_string(self) -> str:
        if not self.combined_text:
            return ""
        return f"KNOWLEDGE BASE:\n{self.combined_text}"


def query_knowledge(
    text:            str,
    top_k:           int   = 4,
    min_score:       float = 0.35,
    include_obsidian: bool = True,
    include_vector:   bool = True,
) -> KnowledgeContext:
    """
    Query all knowledge sources and return a merged context.
    Called synchronously from the worker thread before async council call.
    """
    ctx = KnowledgeContext()
    parts: list[str] = []

    # ── Obsidian vault ────────────────────────────────────────────────────────
    if include_obsidian:
        try:
            from app.services.knowledge.obsidian_bridge import get_obsidian_bridge
            from app.services.knowledge.knowledge_router import should_query_vault
            bridge = get_obsidian_bridge()
            if bridge.is_available() and bridge._ready and should_query_vault(text):
                results = bridge.search(text, top_k=top_k, min_score=min_score)
                ctx.obsidian_results = results
                for r in results:
                    src = f"[{r.title}]"
                    if r.heading:
                        src += f" › {r.heading}"
                    parts.append(f"{src}\n{r.content.strip()}")
                    ctx.sources.append(f"obsidian:{r.source}")
                if results:
                    log.info("Obsidian: %d results (top score %.2f)", len(results), results[0].score)
        except Exception as e:
            log.debug("Obsidian query error: %s", e)

    # ── ChromaDB vector memory ─────────────────────────────────────────────────
    if include_vector:
        try:
            from app.services.memory.chroma_store import get_chroma_store
            results = get_chroma_store().search(
                text, top_k=top_k, min_score=min_score,
                collections=["mark_knowledge", "user_prefs", "conversations"],
            )
            ctx.vector_results = results
            for r in results:
                # Avoid duplicating content already found in Obsidian
                if r.content not in ctx.combined_text:
                    parts.append(r.content.strip())
                    ctx.sources.append(f"chroma:{r.source}")
            if results:
                log.debug("ChromaDB: %d results", len(results))
        except Exception as e:
            log.debug("ChromaDB query error: %s", e)

    ctx.combined_text = "\n\n".join(p for p in parts if p)
    return ctx


def initialize_knowledge_base(vault_path: str = "") -> dict:
    """
    Called at MARK startup to initialize the knowledge base.
    Detects and indexes the Obsidian vault if available.
    """
    from app.services.knowledge.obsidian_bridge import get_obsidian_bridge

    bridge = get_obsidian_bridge()

    if vault_path:
        bridge.set_vault(vault_path)

    if not bridge.is_available():
        log.info("Knowledge base: no Obsidian vault found — set OBSIDIAN_VAULT env var")
        return {"status": "no_vault"}

    log.info("Knowledge base: initializing vault index...")
    stats = bridge.setup(auto_watch=True)
    log.info("Knowledge base ready: %s", stats)
    return {"status": "ready", **stats}
