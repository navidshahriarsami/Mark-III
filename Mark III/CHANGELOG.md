# MARK III — Changelog

All notable changes to MARK III are documented here.
Format: `[Version] — Date — Summary`

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
