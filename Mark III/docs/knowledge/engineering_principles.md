# MARK III — Engineering Principles

These principles guide every implementation decision.

## 1. Local First

The primary intelligence must run offline. Qwen 7B via Ollama is always available. Internet is optional, never required.

## 2. Retrieval Before Reasoning

The LLM reasons over retrieved information. It never invents facts. Integration Manager → Memory → Knowledge → LLM.

## 3. The Brain Owns State

All device state lives on the desktop brain. No device manages its own state. This prevents race conditions and survives restarts.

## 4. Zero Mandatory Paid APIs

Current cost: $99/year (Apple Developer account only). OpenRouter, Ollama, Open-Meteo, nomic-embed-text — all free. This is a deliberate design constraint.

## 5. Incremental Indexing

No full rebuilds. File hashing detects changes. Only modified documents are re-embedded. The vault index is maintained incrementally.

## 6. One Owner Per Installation

Each MARK is unique. `user_profile.json` belongs to exactly one person. No data sharing between installations.

## 7. Voice Is Primary

MARK is always listening. 2-second silence threshold. Dynamic VAD rejects keyboard clicks. The interface is the human voice.

## 8. Latency Is Respect

Social reflex: <1ms. Integration Manager: <10ms. Qwen: 1-3s. "Give me a second, boss." fires at 2s to signal work in progress.

## 9. Identity Before Memory

The owner profile is injected before any memory context. MARK knows WHO before it remembers WHAT.

## 10. Documentation Is Architecture

This repository is the source of truth. Every architectural decision must be captured in `docs/adr/`. Conversation history is not architecture.

---

[[vision]] · [[system_overview]] · [[cognitive_pipeline]] · [[ADR-0001-Mark-Operating-System]] · [[ADR-0002-Cognitive-Pipeline]] · [[MARK_VERSION]] · [[MARK_HOME]]
