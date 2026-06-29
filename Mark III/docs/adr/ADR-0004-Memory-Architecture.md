# ADR-0004 — Four-Layer Memory Architecture

**Status:** Accepted
**Date:** 2026-06-28

## Decision

Memory is divided into four distinct layers with strict separation:

1. **Session memory** — current conversation, volatile, 6-turn rolling window
2. **Vector memory (ChromaDB + SQLite)** — long-term semantic knowledge
3. **Obsidian vault** — authoritative documentation, never conversational
4. **Integration APIs** — real-time data, never stored in memory

## Key Rules

- API data (time, weather, battery) is NEVER stored in vector memory. It is always retrieved live.
- Obsidian is NOT conversational memory. It is structured knowledge.
- Session memory is summarized (via Qwen) and valuable insights stored in vector memory on session end.
- ChromaDB is primary. SQLite is fallback. Both use `nomic-embed-text` 768-dim embeddings.

---

[[memory_architecture]] · [[knowledge_engine]] · [[cognitive_pipeline]] · [[ADR-0006-Obsidian-Knowledge-Authority]] · [[ADR-0005-Identity-Before-Memory]] · [[ADR-0009-Integration-Manager-Truth]]
