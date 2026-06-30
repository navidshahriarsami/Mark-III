# MARK III — Version File

This file is the authoritative version record for MARK III.
Every new Claude session must read this file first.

---

## Current Version

| Field | Value |
|---|---|
| **Software Version** | 0.20.0 |
| **Architecture Version** | 3.1 (Governed Knowledge + Universal Actions) |
| **Current Phase** | Phase 17 — Universal Action System |
| **Current Milestone** | Voice-triggered actions with tiered, capability-based approval |
| **Last Updated** | 2026-06-30 |

---

## Completed Phases

| Phase | Name | Status |
|---|---|---|
| 14 | Voice Pipeline | ✅ Complete |
| 15A | Reflex + Conversation Tier | ✅ Complete |
| 15B | Dynamic VAD | ✅ Complete |
| 15C | Qwen Local LLM | ✅ Complete |
| 15D | Always-On + 8 Reflex Modules | ✅ Complete |
| 16A | Device Mesh Core | ✅ Complete |
| 16B | Mac Mic Relay + Samantha TTS | ✅ Complete |
| 16C | Presence Layer | ✅ Complete |
| 16D | Brain Owns State (voice mode refactor) | ✅ Complete |
| 18 | Qwen 7B + Integration Manager + Language Detection | ✅ Complete |
| 18+ | ChromaDB + Intent Classifier + Context Builder | ✅ Complete |
| 18+ | Obsidian Knowledge Bridge | ✅ Complete |
| Identity | User Profile + Learning Engine + Session Summarizer | ✅ Complete |
| Memory | Authoritative Recall Engine — structured fact store | ✅ Complete |
| Constitution | Knowledge Governance System + CLAUDE.md | ✅ Complete |
| 17 | Universal Action System — voice-triggered actions, tiered approval | ✅ Complete |

---

## Active Development

| Phase | Name | Status |
|---|---|---|
| 16B-iOS | MARK Mobile — Native Swift iOS App | 🔵 Next |
| 17A | MARK Connect (self-hosted relay, replaces Tailscale) | 📋 Planned |
| 13-Integration | Proactive Agent System — integration path undecided | 📋 Deferred |

---

## Breaking Changes

| Version | Change |
|---|---|
| 0.16.0 | Brain owns active device state — Mac no longer manages its own state |
| 0.15D | Always-on mode — wake word removed from primary pipeline |
| 0.15C | Qwen replaces OpenRouter as primary conversation model |
| 0.18.0 | Integration Manager — LLM no longer answers factual queries |
| 0.20.0 | Universal Action System live — voice can now execute, not just answer. CRITICAL actions require desktop-only approval (capability-gated, not hardcoded) |

---

## Upcoming Features

- MARK Mobile iOS (native Swift, CoreLocation, background GPS)
- Universal Actions (open apps, screenshots, automations)
- MARK Connect relay (WireGuard VPN, replaces Tailscale for commercial use)
- Voice enrollment (speaker authentication, single-user security)
- Google Calendar integration
- Emergency/wellness monitoring layer

---

## Repository Structure

```
idea72/Mark III/
├── brain-server/           ← Desktop brain (Python, FastAPI)
│   ├── mark_service.py     ← Entry point
│   ├── app/services/
│   │   ├── voice/          ← STT, TTS, always-on loop
│   │   ├── ai/             ← Qwen, OpenRouter, providers
│   │   ├── council/        ← Multi-LLM reasoning council
│   │   ├── reflex/         ← 8 reflex modules
│   │   ├── integrations/   ← Time, weather, system APIs
│   │   ├── cognition/      ← Intent classifier, context builder
│   │   ├── memory/         ← ChromaDB, SQLite vector store
│   │   ├── knowledge/      ← Obsidian bridge, vault indexer
│   │   ├── identity/       ← User profile, learning engine
│   │   └── mesh/           ← Device mesh, presence fusion
│   └── requirements.txt
├── docs/                   ← This directory — architecture truth
├── MARK_III_MANIFEST.md    ← Master index
└── MARK_VERSION.md         ← This file
```

---

## Claude Handoff Protocol

Any new Claude session working on MARK III must read in this order:

1. `MARK_VERSION.md` (this file)
2. `MARK_III_MANIFEST.md`
3. `docs/architecture/system_overview.md`
4. `docs/architecture/cognitive_pipeline.md`
5. Relevant subsystem docs from `docs/architecture/`
6. Relevant ADRs from `docs/adr/`
7. Current phase from `docs/roadmap/`

**Never** rely on conversation history as architectural truth.
The repository is the single source of truth.

---

[[MARK_HOME]] · [[MARK_III_MANIFEST]] · [[system_overview]] · [[cognitive_pipeline]] · [[completed_phases]] · [[future]] · [[engineering_principles]]
