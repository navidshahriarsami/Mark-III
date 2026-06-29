# MARK III — Memory Architecture

## Purpose

MARK has four distinct memory layers. Each serves a different purpose. They are never mixed.

## Memory Hierarchy

```
Session Memory    → current conversation (volatile)
    ↓
Vector Memory     → long-term experiential knowledge (ChromaDB + SQLite)
    ↓
Obsidian Vault    → authoritative documentation (structured knowledge)
    ↓
Integration APIs  → real-time truth (never stored in memory)
```

## Layer 1 — Session Memory

- **What:** Last 6 conversation turns (rolling)
- **Where:** `_history` list in `local_qwen_provider.py`
- **Persistence:** Lost on restart or "pause/sleep" command
- **Purpose:** Follow-up context ("yes, that one", "continue from there")
- **Auto-summarized:** Yes — at session end, Qwen summarizes and stores in Layer 2

## Layer 2 — Vector Memory (ChromaDB + SQLite)

- **Collections:**
  - `mark_knowledge` — MARK's own architecture, decisions, phase history
  - `conversations` — auto-summarized session highlights
  - `user_prefs` — learned owner preferences
  - `obsidian` — vault document chunks
- **Embedding:** `nomic-embed-text` via Ollama (768-dim, cosine similarity)
- **Fallback:** SQLite (`mark_memory.db`) when ChromaDB unavailable
- **Direct recall threshold:** score ≥ 0.75 bypasses LLM entirely
- **Seeded:** 34 architectural memories from project history

## Layer 3 — Obsidian Vault (Knowledge Authority)

- **What:** Markdown files in the configured vault
- **Role:** Authoritative documentation — never conversational memory
- **Indexing:** `vault_indexer.py` — incremental, polls every 60s
- **Parser:** `markdown_parser.py` — splits by heading sections, extracts tags/wikilinks
- **Config:** `OBSIDIAN_VAULT` env var or auto-detection
- **Current vault:** `idea72/Mark III/` (project folder)
- **Future:** Owner's personal Obsidian vault

## Layer 4 — Integration APIs (Real-Time Truth)

- **What:** Time, date, weather, battery, CPU, RAM, GPU, network, calendar
- **Rule:** NEVER stored in vector memory. Always retrieved live.
- **Why:** Prevents stale data. APIs are always fresher than embeddings.

## Memory Policy

| Query Type | Source |
|---|---|
| "What time is it?" | Integration API (not memory) |
| "What did we decide about the mesh?" | Vector memory (ChromaDB) |
| "What is MARK's architecture?" | Obsidian vault |
| "What's the barge-in threshold?" | Vector memory direct recall |
| "How do I plan my week?" | Qwen + profile context |

## Related Documents

- [Cognitive Pipeline](cognitive_pipeline.md)
- [Knowledge Engine](knowledge_engine.md)
- [Identity Engine](identity_engine.md)

---

[[cognitive_pipeline]] · [[knowledge_engine]] · [[identity_engine]] · [[system_overview]] · [[ADR-0004-Memory-Architecture]] · [[ADR-0006-Obsidian-Knowledge-Authority]] · [[ADR-0005-Identity-Before-Memory]]
