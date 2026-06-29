# ADR-0007 — Context Builder as LLM Interface

**Status:** Accepted
**Date:** 2026-06-28

## Decision

The LLM receives a pre-built context package, not raw user queries. The Context Builder assembles everything before Qwen is invoked.

Context package contents:
- Owner profile summary
- Datetime context (always)
- Weather context (for reasoning/complex)
- Memory results (ChromaDB + SQLite)
- Knowledge results (Obsidian vault)
- Active device
- Detected language

## Consequence

Qwen never searches. It only reasons. This eliminates hallucination on factual queries and makes responses consistent regardless of LLM knowledge cutoff.

---

[[cognitive_pipeline]] · [[memory_architecture]] · [[knowledge_engine]] · [[identity_engine]] · [[ADR-0002-Cognitive-Pipeline]] · [[ADR-0008-Qwen-Reasoning-Only]] · [[ADR-0009-Integration-Manager-Truth]]
