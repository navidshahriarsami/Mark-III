# MARK III — System Overview

**Version:** 2.0 | **Status:** Active | **Owner:** Navid Shahriar Sami

## Purpose

MARK III is a personal AI operating system. It is not a chatbot, not an assistant, and not a cloud service. It is a persistent, distributed intelligence that lives across the user's own hardware, runs locally, and acts as an extension of the owner's mind.

## Design Philosophy

1. **The desktop is the permanent brain.** All intelligence lives on the desktop. Devices are interfaces.
2. **Local first.** Qwen 7B runs offline via Ollama. No internet required for core functionality.
3. **Retrieval before reasoning.** The LLM never invents factual information. It reasons over retrieved truth.
4. **One owner per installation.** Each MARK is unique to its user. No data sharing between installations.
5. **Voice is the primary interface.** MARK is always listening. No wake word. No button.

## System Boundaries

```
OUTSIDE MARK:           INSIDE MARK:
  Internet APIs  ──→   Integration Manager (cached, gated)
  Obsidian Vault ──→   Knowledge Bridge (indexed, searchable)
  User's devices ──→   Device Mesh (heartbeat, relay)
  LLM providers  ──→   Council (fallback only, not primary)
```

## Core Components

| Component | Location | Purpose |
|---|---|---|
| Voice Loop | `always_listening_loop.py` | Always-on STT → pipeline → TTS |
| Whisper STT | `faster-whisper` base int8 | Transcription + language detection |
| Piper TTS | `xtts_provider.py` | Neural voice synthesis |
| Qwen 7B | Ollama `qwen2.5:7b` | Local conversation + reasoning |
| Council | `council_manager.py` | Multi-LLM for complex tasks |
| Reflex Engine | `reflex/` | 8 modules, zero LLM for known queries |
| Integration Manager | `integrations/` | Time, weather, system facts |
| Intent Classifier | `cognition/intent_classifier.py` | Route queries before LLM |
| Context Builder | `cognition/context_builder.py` | Assemble context package |
| ChromaDB | `memory/chroma_store.py` | Semantic long-term memory |
| Obsidian Bridge | `knowledge/obsidian_bridge.py` | Vault as knowledge authority |
| Identity Manager | `identity/identity_manager.py` | Owner profile + learning |
| Device Mesh | `mesh/mesh_manager.py` | Multi-device coordination |

## Data Flow (Happy Path)

```
User speaks
    ↓ [K66 mic, 16kHz]
Whisper STT → text + language
    ↓ [<2s]
Intent Classifier → social | factual | recall | reasoning | complex
    ↓ [<2ms]
Social Reflex (if social) → instant response
    ↓ (if not social)
Integration Manager (if factual_live) → live data, no LLM
    ↓ (if not factual)
Identity Manager → owner context injected
Context Builder → memory + knowledge + profile assembled
    ↓ [<500ms sync]
Direct Recall (if score ≥ 0.75) → answer from knowledge base
    ↓ (if not high-confidence recall)
Qwen 7B → reason over assembled context
    ↓ (if complex intent)
Council → GPT-OSS 120B or Gemma for deep reasoning
    ↓
Piper TTS → voice output
    ↓ [Realtek speaker, 48kHz]
```

## Deployment

- **Desktop:** Windows 10 Pro, Python 3.11, always-on service
- **Mac:** MacBook Pro M1, device_client.py, Tailscale mesh
- **Network:** Tailscale VPN (100.94.162.25 desktop, 100.85.106.11 Mac)
- **Cost:** $99/year (Apple Developer account only)

## Related Documents

- [Cognitive Pipeline](cognitive_pipeline.md)
- [Device Mesh](device_mesh.md)
- [Memory Architecture](memory_architecture.md)
- [Identity Engine](identity_engine.md)
- [Knowledge Engine](knowledge_engine.md)

---

[[cognitive_pipeline]] · [[device_mesh]] · [[memory_architecture]] · [[identity_engine]] · [[knowledge_engine]] · [[ADR-0001-Mark-Operating-System]] · [[ADR-0002-Cognitive-Pipeline]] · [[MARK_VERSION]] · [[MARK_HOME]]
