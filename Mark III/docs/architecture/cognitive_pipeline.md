# MARK III — Cognitive Pipeline

## Purpose

The cognitive pipeline routes every utterance to the cheapest, fastest, most accurate source that can answer it. The LLM is always the last resort — never the first stop.

## Pipeline Stages

### Stage 1 — Social Reflex
- **File:** `app/services/voice/reflex_router.py`
- **Latency:** <1ms
- **Handles:** Hello, thanks, yes/no, are you there, wake word repetition
- **Rule:** Deterministic. No LLM. Hardcoded response tables.

### Stage 2 — Integration Manager
- **File:** `app/services/integrations/integration_manager.py`
- **Latency:** <10ms
- **Handles:** Time, date, weather, UV, CPU, RAM, GPU, disk, battery, IP, network, apps, media
- **Rule:** Never ask the LLM for factual system data. Always retrieve it.

### Stage 3 — Intent Classification
- **File:** `app/services/cognition/intent_classifier.py`
- **Latency:** <2ms
- **Output:** `social | factual_live | recall | conversation | reasoning | complex`
- **Rule:** Rule-based regex. Zero LLM cost. Determines routing for all subsequent stages.

### Stage 4 — Context Builder
- **File:** `app/services/cognition/context_builder.py`
- **Latency:** 200-500ms (embedding + retrieval)
- **Assembles:**
  - Owner profile (from Identity Manager)
  - Datetime context (always included, free)
  - Weather context (for reasoning/complex queries)
  - Vector memory (ChromaDB + SQLite)
  - Obsidian knowledge (if query matches knowledge router)
- **Output:** `ContextPackage` — structured context for LLM injection

### Stage 5 — Direct Recall
- **Threshold:** score ≥ 0.75 in ChromaDB or SQLite
- **Rule:** If a memory or document answers the query with high confidence, return it directly without calling the LLM.
- **Examples:** "What is the barge-in threshold?" → -20 dBFS from seeded memory

### Stage 6 — Qwen 7B
- **File:** `app/services/ai/local_qwen_provider.py`
- **Model:** `qwen2.5:7b` via Ollama
- **Latency:** 1-3s
- **Input:** Full context package (profile + memory + knowledge + datetime)
- **Rule:** Qwen reasons. It does not retrieve. It never invents system facts.
- **Max response:** 20 words for voice

### Stage 7 — Council
- **File:** `app/services/council/council_manager.py`
- **Triggers:** `complex` intent only
- **Chain:** GPT-OSS 120B → Gemma 4 31B → Llama 3.3 70B → Claude (fallback)
- **Latency:** 5-30s
- **Announcement:** "Give me a second, boss." fires at 2s threshold

## Voice Mode Constraints

- Maximum 20 words per response (enforced in `_enforce_word_limit()`)
- No markdown, no lists, no headers in voice responses
- Piper TTS renders the final text

## Routing Priority (lowest cost wins)

```
Social Reflex    (<1ms, 0 tokens)
Integration Mgr  (<10ms, 0 tokens)
Direct Recall    (<200ms, 0 tokens)
Qwen 7B          (1-3s, local)
Council          (5-30s, remote API)
```

## Related Documents

- [System Overview](system_overview.md)
- [Memory Architecture](memory_architecture.md)
- [Integration Layer](integration_layer.md)
- [Context Builder](context_builder.md)
