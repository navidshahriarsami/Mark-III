# MARK III — Changelog

All notable changes to MARK III are documented here.
Format: `[Version] — Date — Summary`

---

## [0.20.1] — 2026-06-30 — Action System Fixes from Live Testing

**Type:** Bug fix

- Fixed LAUNCH_APP regex lazy quantifier silently truncating multi-word app names ("visual studio code" → "visual"); changed to greedy, safe because downstream stop-word filtering already handles trailing "app"/"application"/"for me"
- Added app_aliases.py: fuzzy-resolves mis-transcribed app names ("node pad", "nodepad", "note pad" → "notepad") via difflib, cutoff calibrated against real Whisper mis-transcriptions
- Fixed notification_executor.py: no Windows-native fallback existed when plyer/win10toast weren't installed — added a PowerShell System.Windows.Forms.NotifyIcon balloon-tip fallback that requires no pip dependency
- All fixes verified against the exact phrases that failed in live voice testing, not synthetic test cases

---

## [0.20.0] — 2026-06-30 — Universal Action System

**Type:** Major feature

- Discovered and absorbed dormant Phase 12A/12B/13 action/policy engine (built for an unused async FastAPI backend) into the live synchronous architecture
- action_loop.py: dedicated background thread + event loop hosts the async AsyncActionQueue; voice loop bridges in via asyncio.run_coroutine_threadsafe
- action_store.py: SQLite persistence (mirrors fact_store.py), replaces SQLAlchemy app.models.db.ActionRecord entirely
- policy_context.py: reads live mesh device registry + live identity profile, replaces dormant presence_manager.py + SQLAlchemy UserContext/DailyReport
- action_router.py wired into query_council() — "open Chrome", "delete X", "restart the computer" now execute via voice
- Tiered Approval Framework: new Capability.APPROVAL_AUTHORITY mesh capability gates CRITICAL-tier approvals — capability-based, not device-hardcoded. Desktop only today; iOS registers the same capability when it ships, zero code changes required
- Voice "yes"/"no" resolves pending approvals — intercepted before social reflex so it isn't swallowed as a generic acknowledgment
- Fixed a real cross-thread asyncio.Event race: ApprovalManager.respond() was calling Event.set() directly from the voice thread, which doesn't safely wake a coroutine owned by a different thread's event loop. Caught only because of end-to-end integration testing with a real approval flow
- app/api/v1/ and app/models/db.py marked superseded (not deleted) — explicit notices in __init__.py
- ADR-0012 documents the as-built integration; ADR-0010 marked superseded
- Phase 13 Agent System explicitly deferred — same dormant stack, not absorbed this phase

---

## [0.19.0] — 2026-06-30 — MARK III Constitution + Knowledge Governance System

**Type:** Constitutional milestone

- CLAUDE.md created — permanent Article XV engineering directive for all future Claude sessions
- Knowledge Governance System: 14-module subsystem in app/services/governance/
- Knowledge Governor: orchestrates all governance routing; starts before mesh + voice
- Knowledge Classifier: domain classification <1ms (Engineering/UserFact/Identity/Operational/Experiential/Temporary)
- Knowledge Lifecycle: Draft→Implemented→Validated→Documented→Indexed→Embedded→Committed→Stable
- Architecture Guardian: detects drift between implementation and documentation
- Repository Observer: watchdog on docs/ (30s poll) → auto re-indexes ChromaDB on change
- ADR Manager: creates/validates ADRs; ADR-0011 created for KGS
- Version Manager: programmatic MARK_VERSION.md updates
- Changelog Manager: programmatic CHANGELOG.md updates
- Repository Diagnostics: full health report at GET /governance/diagnostics
- Constitution Manager: validates CLAUDE.md on boot, reports Article XV status
- GET /governance/diagnostics: architecture + memory + recall + ADRs + version in one call
- GET /governance/constitution: reports constitutional invariants + Article XV status
- Authoritative Memory Engine: fact_store.py (SQLite), fact_extractor.py, fact_normalizer.py
- Recall engine bypasses LLM for all stored facts (structured→vector→LLM order)
- Facts stored from every voice utterance automatically
- POST /memory/fact, GET /memory/facts, GET /memory/stats endpoints live
- Architecture v3.0: Governed Knowledge — repository is the constitution

---

## [0.18.1] — 2026-06-30 — Repository Refactor

**Type:** Structural (no runtime changes)

- Created `shared/` directory scaffold (contracts, protocols, schemas, interfaces, constants)
- Created `mobile/` placeholder for future iOS client
- Created `docs/api/` for API specifications
- Added `MARK_HOME.md` as repository entry point
- Added `CHANGELOG.md`
- No functional changes. All imports and runtime behaviour preserved.

---

## [0.18.0] — 2026-06-28 — Architecture Freeze + Identity Engine

**Type:** Major milestone

- Architecture frozen — repository is now the source of truth
- `docs/` created: architecture, ADRs (0001-0010), roadmap, knowledge
- `MARK_VERSION.md` created — Claude handoff protocol established
- Identity Engine: `UserProfile`, `IdentityManager`, `ProfileEngine`
- Continuous Learning: `LearningEngine`, `ActivityTracker`, `SessionSummarizer`
- Habit Detector: behavioral pattern recognition with confidence scoring
- Pattern Extractor: rule-based + Qwen-assisted insight extraction
- Goal Tracker: active goals + milestones wired into Qwen context
- Navid's profile seeded with real data

---

## [0.17.0] — 2026-06-28 — Cognitive Pipeline + Obsidian Bridge

**Type:** Major feature

- ChromaDB replaces SQLite as primary vector store
- Intent Classifier: social/factual/recall/reasoning/complex (<2ms)
- Context Builder: unified context package before every LLM call
- Obsidian Knowledge Bridge: vault indexer, markdown parser, 60s watch
- Knowledge Manager: Obsidian + ChromaDB + SQLite unified query
- 34 architectural memories seeded into ChromaDB
- Vector memory wired into `query_council()` pipeline

---

## [0.16.0] — 2026-06-25 — Device Mesh Complete

**Type:** Major feature

- Phase 16A: Device Mesh core (REST API port 8765, heartbeat watchdog)
- Phase 16B: Mac mic relay (device_client.py, Samantha TTS, port 8766)
- Phase 16C: Presence layer (fusion scoring, battery queries)
- Phase 16D: Brain owns state — desktop gates Piper TTS on active device
- ⌘⌥M hotkey → force Mac active via /mesh/activate
- Tailscale cross-network connectivity (100.94.162.25 ↔ 100.85.106.11)
- LaunchAgent auto-start on Mac boot
- Self-healing watchdog for Mac client

---

## [0.15.0] — 2026-06-23 — Always-On + Reflex Modules

**Type:** Major feature

- Phase 15A: Social reflex router, Gemma conversation tier, 20-word limit
- Phase 15B: Dynamic VAD — 300ms onset confirmation, pre-buffer
- Phase 15C: Qwen 2.5:3b via Ollama (local, offline)
- Phase 15D: Always-on voice (no wake word), WAIT_FOR_SPEECH state
- 8 reflex modules: system, weather, network, media, apps, device, calendar (stub), memory (stub)
- Startup greeting: time + weather + UV + system stats + recommendations
- GPU stats via LibreHardwareMonitorLib.dll (pythonnet, no WMI)
- Phase 18: Qwen 2.5:7b upgrade, integration manager, language detection

---

## [0.14.0] — 2026-06-21 — Voice Pipeline

**Type:** Foundation

- Piper TTS (en_US-lessac-medium ONNX, WASAPI 48kHz resampling)
- Faster-Whisper base STT (int8 CPU, 1.2s)
- ConversationBuffer VAD
- FOLLOWUP state (5s post-response window)
- Barge-in detection (-20 dBFS, 5 chunks)
- Per-turn diagnostics (voice_diagnostics.json)
- SAPI Zira fallback

---

## [0.1.0] — 2026-06 — Initial Architecture

**Type:** Foundation

- FastAPI brain server skeleton
- Multi-LLM Council (GPT-OSS 120B, Gemma 4, Llama 3.3, Claude fallback)
- OpenRouter provider layer
- Basic voice daemon
