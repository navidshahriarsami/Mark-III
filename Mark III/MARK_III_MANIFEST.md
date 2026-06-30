# MARK III — System Manifest

**Version:** 0.21.0 | **Phase:** Discovery Engine | **Updated:** 2026-06-30

> This is the master index. Every subsystem is documented here.
> The authoritative version lives at the repository root.

---

## Navigation

| Section | Document |
|---|---|
| Entry point | [MARK_HOME.md](MARK_HOME.md) |
| Version + phases | [MARK_VERSION.md](MARK_VERSION.md) |
| Release history | [CHANGELOG.md](CHANGELOG.md) |
| System architecture | [docs/architecture/system_overview.md](docs/architecture/system_overview.md) |
| Cognitive pipeline | [docs/architecture/cognitive_pipeline.md](docs/architecture/cognitive_pipeline.md) |
| Device mesh | [docs/architecture/device_mesh.md](docs/architecture/device_mesh.md) |
| Memory architecture | [docs/architecture/memory_architecture.md](docs/architecture/memory_architecture.md) |
| Identity engine | [docs/architecture/identity_engine.md](docs/architecture/identity_engine.md) |
| Knowledge engine | [docs/architecture/knowledge_engine.md](docs/architecture/knowledge_engine.md) |
| Universal Action System | [docs/architecture/action_system.md](docs/architecture/action_system.md) |
| Discovery Engine | [docs/architecture/discovery_engine.md](docs/architecture/discovery_engine.md) |
| All ADRs | [docs/adr/](docs/adr/) |
| Mesh API | [docs/api/mesh_api.md](docs/api/mesh_api.md) |
| Completed phases | [docs/roadmap/completed_phases.md](docs/roadmap/completed_phases.md) |
| Future roadmap | [docs/roadmap/future.md](docs/roadmap/future.md) |
| Vision | [docs/knowledge/vision.md](docs/knowledge/vision.md) |
| Engineering principles | [docs/knowledge/engineering_principles.md](docs/knowledge/engineering_principles.md) |
| Investor summary | [docs/knowledge/investor_summary.md](docs/knowledge/investor_summary.md) |
| Shared layer | [shared/README.md](shared/README.md) |
| Mobile client | [mobile/README.md](mobile/README.md) |

---

## Repository Structure

```
Mark III/
├── MARK_HOME.md            ← Start here
├── MARK_VERSION.md         ← Version + Claude handoff protocol
├── MARK_III_MANIFEST.md    ← This file
├── CHANGELOG.md            ← Release history
├── README.md               ← GitHub summary
├── docs/
│   ├── architecture/       ← 8 architecture docs
│   ├── adr/                ← ADR-0001 through ADR-0013
│   ├── roadmap/            ← Completed phases + future
│   ├── knowledge/          ← Vision, principles, investor
│   └── api/                ← Mesh API reference
├── brain-server/           ← Desktop brain (Python 3.11)
│   ├── mark_service.py
│   ├── requirements.txt
│   ├── app/
│   │   ├── api/            ← Superseded FastAPI routes (not run by mark_service.py)
│   │   ├── models/         ← Superseded SQLAlchemy models (not run)
│   │   └── services/
│   │       ├── voice/          ← STT, TTS, always-on loop
│   │       ├── ai/             ← Qwen, OpenRouter, providers
│   │       ├── council/        ← Multi-LLM reasoning
│   │       ├── reflex/         ← 8 reflex modules
│   │       ├── integrations/   ← Time, weather, system APIs
│   │       ├── cognition/      ← Intent classifier, context builder
│   │       ├── memory/         ← ChromaDB, SQLite vector store, structured facts
│   │       ├── knowledge/      ← Obsidian bridge, vault indexer
│   │       ├── identity/       ← User profile, learning, goals
│   │       ├── governance/     ← Knowledge Governance System
│   │       ├── actions/        ← Universal Action System (live)
│   │       ├── policy/         ← Policy Engine (live)
│   │       ├── discovery/      ← Discovery Engine — self-built app + file index
│   │       ├── agents/         ← Proactive Agent System (dormant — deferred)
│   │       └── mesh/           ← Device mesh, presence fusion
│   └── user_profile.json   ← Owner identity (gitignored in production)
├── desktop-daemon/         ← Windows desktop daemon
├── shared/                 ← Cross-component scaffold (future)
└── mobile/                 ← iOS client (Phase 16B-iOS)
```

---

## Current Cognitive Pipeline

```
Voice → Whisper → Intent → Social Reflex → Integration Manager
                                                    ↓
                              Identity Manager → Context Builder
                                                    ↓
                                            Direct Recall (≥0.75)
                                                    ↓
                                              Qwen 7B (local)
                                                    ↓
                                           Council (complex only)
                                                    ↓
                                             Piper TTS → Speaker
```

---

## External Tools & Models

| Tool | Version | Purpose |
|---|---|---|
| Ollama | 0.30.9 | Local LLM inference runtime |
| qwen2.5:7b | - | Primary conversation + reasoning |
| nomic-embed-text | - | 768-dim embeddings for ChromaDB |
| faster-whisper | 1.2.1 | STT (base model, int8 CPU) |
| piper-tts | 1.4.2 | TTS (en_US-lessac-medium ONNX) |
| chromadb | 1.5.9 | Primary vector store |
| LibreHardwareMonitor | 0.9.6 | GPU/CPU temperature (DLL direct) |
| Tailscale | 1.98.x | Cross-network mesh connectivity |

---

## Installed Hardware

| Device | Role | IP |
|---|---|---|
| Desktop (i7-8700K, 34GB, GTX 980 Ti) | MARK Core | 100.94.162.25 |
| MacBook Pro M1 | Mac Client | 100.85.106.11 |
| iPhone 16 | Mobile (Phase 16B-iOS) | — |

---

## Launch Commands

```powershell
# Desktop (Windows)
cd "Mark III\brain-server"
python mark_service.py --console
```

```bash
# Mac client
python3 ~/.mark/device_client.py --host 100.94.162.25 --type macbook --mic
```
