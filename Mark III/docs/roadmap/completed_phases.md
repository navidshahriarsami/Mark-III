# MARK III — Completed Phases

## Phase 14 — Voice Pipeline
**Completed:** 2026-06-21
- Piper TTS (en_US-lessac-medium ONNX, 50-120ms synthesis, WASAPI 48kHz)
- SAPI Zira fallback
- Barge-in detection (-20 dBFS, 5 chunks, 150ms sustained)
- FOLLOWUP state (5s post-response window)
- Per-turn diagnostics (voice_diagnostics.json)
- ConversationBuffer VAD

## Phase 15A — Reflex + Conversation Tier
**Completed:** 2026-06-22
- Social reflex router (hello, thanks, yes/no, wake word patterns)
- Gemma 4 31B conversation tier (replaced GPT-OSS as primary)
- 20-word voice response limit enforced
- Silence detection fix (onset confirmation 300ms)

## Phase 15B — Dynamic VAD
**Completed:** 2026-06-22
- ConversationBuffer completely rewritten
- 300ms onset confirmation (rejects keyboard clicks, fan noise, desk bumps)
- Pre-buffer (450ms) preserves speech onset
- `on_speech_start` callback for WAIT_FOR_SPEECH state
- Silence timeout: 2.0s

## Phase 15C — Qwen Local LLM
**Completed:** 2026-06-22
- Qwen 2.5:3b via Ollama (replaced Gemma as primary)
- Conversation history (6 turns, rolling)
- `nomic-embed-text` warmup at startup
- `_THINK_RE` regex strips Qwen3 thinking blocks

## Phase 15D — Always-On + 8 Reflex Modules
**Completed:** 2026-06-23
- Always-listening mode (no wake word)
- WAIT_FOR_SPEECH state
- 8 reflex modules: system, weather, network, media, apps, device, calendar (stub), memory (stub)
- GPU stats via LibreHardwareMonitorLib.dll (pythonnet)
- Weather via Open-Meteo (UV index, 30-min cache)
- Startup greeting (time + weather + UV + system + recommendations)

## Phase 16A — Device Mesh Core
**Completed:** 2026-06-24
- mesh_manager.py (REST API port 8765, heartbeat watchdog)
- device_registry.py (thread-safe, mesh_devices.json persistence)
- mesh_protocol.py (Device, DeviceType, DeviceState, Capability)
- mesh_diagnostics.py (500-event rolling log)
- presence_fusion.py (multi-signal active device scoring)

## Phase 16B — Mac Mic Relay + Samantha
**Completed:** 2026-06-24
- device_client.py (Mac heartbeat + inbound listener port 8766)
- Samantha TTS via macOS `say -v Samantha`
- macOS system notifications via osascript
- Mic relay: VAD capture → POST /mesh/voice → desktop Whisper → response
- Conversation handoff (/mark/conversation endpoint)
- LaunchAgent for auto-start on Mac boot

## Phase 16C — Presence Layer
**Completed:** 2026-06-24
- Presence queries: "where am I?", "which devices are online?", "all batteries?"
- Presence fusion scoring (active flag + state + recency + device type)
- Battery status across all mesh devices

## Phase 16D — Brain Owns State
**Completed:** 2026-06-25
- Removed all device-side state management
- `_active_voice_device` owned exclusively by desktop brain
- Desktop Piper TTS gated on `is_desktop_active()`
- Mac always sends audio, desktop decides whether to respond
- `⌘⌥M` hotkey → POST /mesh/activate → force Mac active
- "Shift to Mac / shift to desktop" voice commands
- Remote desktop commands: "on the desktop, [command]"

## Phase 18 — Cognitive Pipeline Upgrade
**Completed:** 2026-06-28
- Qwen 2.5:7b upgrade (from 3b)
- Integration Manager (time/weather/system route before LLM)
- Language detection from Whisper (no language="en" lock)
- Language-aware Qwen responses (12 languages)
- World clock with tzdata (20+ cities)
- ChromaDB (replaces SQLite as primary vector store)
- Intent Classifier (social/factual/recall/reasoning/complex, <2ms)
- Context Builder (unified context package before Qwen)
- Obsidian Knowledge Bridge (vault indexer, markdown parser, 60s watch)
- User Profile + Identity Engine (learning, activity tracking, session summarizer)

## Phase 17 — Universal Action System
**Completed:** 2026-06-30
- Discovered dormant Phase 12A/12B/13 action/policy/agent engine, built for an async FastAPI backend `mark_service.py` never ran
- Absorbed action engine into live sync architecture via dedicated background asyncio thread (`action_loop.py`)
- SQLite persistence (`action_store.py`) replaces SQLAlchemy entirely
- Live mesh + identity context replaces dormant `presence_manager.py` + SQLAlchemy queries
- Voice-triggered actions: "open X", "delete Y", "restart the computer"
- Tiered Approval Framework — capability-based (`Capability.APPROVAL_AUTHORITY`), not device-hardcoded
- Fixed cross-thread `asyncio.Event` race in approval resolution
- `app/api/v1/` and `app/models/db.py` marked superseded, not deleted
- Phase 13 Agent System deferred — out of scope this phase

---

[[future]] · [[system_overview]] · [[cognitive_pipeline]] · [[device_mesh]] · [[memory_architecture]] · [[identity_engine]] · [[MARK_VERSION]] · [[CHANGELOG]]
