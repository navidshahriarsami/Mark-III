# MARK III — System Manifest
**Snapshot: 2026-06-23 | Phase 15D**

A personal AI operating system for Windows. Always-on voice assistant.
No mandatory paid APIs. OpenRouter free tier + Ollama local LLM.

---

## Quick Start

```powershell
# 1. Python 3.11 required
python -m pip install -r requirements.txt

# 2. Ollama (local LLM)
winget install Ollama.Ollama
ollama pull qwen2.5:3b

# 3. Ollama auto-start at login (run from elevated terminal)
$action = New-ScheduledTaskAction -Execute "ollama" -Argument "serve"
$trigger = New-ScheduledTaskTrigger -AtLogon
Register-ScheduledTask -TaskName "OllamaServe" -Action $action -Trigger $trigger -RunLevel Highest -Force

# 4. LibreHardwareMonitor — CPU temperature (run from elevated terminal)
#    Download: https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip
#    Installed at: C:\Users\Celluloid Solutions\Downloads\LibreHardwareMonitor.exe
$lhmPath = "C:\Users\Celluloid Solutions\Downloads\LibreHardwareMonitor.exe"
$action  = New-ScheduledTaskAction -Execute $lhmPath
$trigger = New-ScheduledTaskTrigger -AtLogon
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "LibreHardwareMonitor" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force
# NOTE: Must run as admin to expose root\LibreHardwareMonitor WMI namespace

# 5. Run MARK III
python mark_service.py --console
```

---

## Voice Commands

| Say | Effect |
|---|---|
| Anything | MARK responds |
| "stop" / "pause" | MARK goes silent (sleeping) |
| "Mark" | Wake from sleeping state |
| "wait" / "hold on" | Skip this turn, keep listening |
| "sleep" / "goodnight" | Sleep mode |

---

## Architecture

```
Mic (K66, idx=1)
↓
WakeEngine (energy gate, -39 dBFS)
↓  [special commands: sleep, mute, restart]
AlwaysListeningLoop
↓
ConversationBuffer (VAD, onset=300ms, silence=2s, max=20s)
↓
Whisper base (CPU int8, faster-whisper)
↓
┌─────────────────────────────────────────────────┐
│             REFLEX LAYER (0-100ms)              │
│  Social phrases → voice/reflex_router.py        │
│  System queries → reflex/ (8 modules)           │
└─────────────────────────────────────────────────┘
↓ miss
┌─────────────────────────────────────────────────┐
│          CONVERSATION TIER (0.8-2s)             │
│  Qwen2.5:3b via Ollama (local, offline)         │
│  Conversation history: last 6 turns             │
│  Fallback: Gemma 4 31B → Llama 3.3 70B         │
└─────────────────────────────────────────────────┘
↓ complexity=high
┌─────────────────────────────────────────────────┐
│           COUNCIL / EXECUTIVE (5-30s)           │
│  Specialists: Coding, Research, Planning, etc.  │
│  Executive: GPT-OSS 120B → Llama 3.3            │
│  "Give me a second, boss." at 2s threshold      │
└─────────────────────────────────────────────────┘
↓
Piper TTS (en_US-lessac-medium, 22050Hz → 48000Hz)
SAPI Zira fallback
↓
Speaker (Realtek, idx=4)
```

---

## File Map

```
brain-server/
├── mark_service.py                    Entry point, system tray, HKCU startup
├── requirements.txt                   Python 3.11 deps (this file's companion)
├── MARK_III_MANIFEST.md              This file
├── markiii_service.log               Runtime log
├── voice_diagnostics.json            Per-turn latency rolling log (last 500)
│
├── app/
│   ├── config.py                      Pydantic settings (.env loader)
│   │
│   ├── services/
│   │   ├── voice/
│   │   │   ├── always_listening_loop.py   Phase 15+: always-on state machine
│   │   │   ├── wake_engine.py             Energy-gate wake detection
│   │   │   ├── conversation_buffer.py     VAD: onset confirm + silence timeout
│   │   │   ├── reflex_router.py           Social phrases (hello, thanks, yes/no)
│   │   │   ├── xtts_provider.py           Piper TTS → SAPI fallback
│   │   │   ├── voice_diagnostics.py       Per-turn timing dataclass + JSON log
│   │   │   ├── personality_engine.py      Context hint builder
│   │   │   └── models/
│   │   │       ├── en_US-lessac-medium.onnx
│   │   │       └── en_US-lessac-medium.onnx.json
│   │   │
│   │   ├── reflex/                        Phase 15D: system knowledge modules
│   │   │   ├── base.py                    ReflexResponse dataclass
│   │   │   ├── reflex_router.py           Priority router → 8 modules
│   │   │   ├── system_module.py           time, date, CPU, RAM, GPU, disk, temp
│   │   │   ├── weather_module.py          Open-Meteo API, 30min cache
│   │   │   ├── network_module.py          internet, IP, WiFi, ping
│   │   │   ├── media_module.py            now playing, pause/play/skip
│   │   │   ├── application_module.py      active window, running apps
│   │   │   ├── device_module.py           battery, Bluetooth devices
│   │   │   ├── calendar_module.py         stub (Google/Outlook planned)
│   │   │   └── memory_module.py           stub (memory system recall)
│   │   │
│   │   ├── ai/
│   │   │   ├── base_provider.py           BaseProvider ABC, ProviderName enum
│   │   │   ├── provider_manager.py        Registry, failover, defensive imports
│   │   │   ├── local_qwen_provider.py     Qwen2.5:3b via Ollama + conv history
│   │   │   ├── openrouter_provider.py     OpenRouter (OpenAI-compat API)
│   │   │   ├── claude_provider.py         Anthropic (lazy import, optional)
│   │   │   ├── openai_provider.py         OpenAI direct (optional)
│   │   │   └── local_provider.py          Ollama generic (config-driven)
│   │   │
│   │   └── council/
│   │       ├── council_manager.py         CognitiveCouncil: route→specialists→exec
│   │       ├── model_router.py            Local keyword routing (0ms, 0 API calls)
│   │       ├── specialist_registry.py     Specialist definitions + system prompts
│   │       ├── consensus_engine.py        Executive synthesis + fallback chain
│   │       └── voting_engine.py           Quality filter before Executive
```

---

## Provider Chain

```
TIER 1 — REFLEX (local, 0-100ms, 0 tokens)
  Social:  voice/reflex_router.py     "hello", "thanks", "Mark", time/date queries
  System:  reflex/reflex_router.py    CPU/RAM/GPU/weather/network/apps/media

TIER 2 — CONVERSATION (local, 0.8-2s)
  Primary: Qwen2.5:3b via Ollama      offline capable
  Fallback 1: google/gemma-4-31b-it:free  (OpenRouter)
  Fallback 2: meta-llama/llama-3.3-70b-instruct:free  (OpenRouter)

TIER 3 — COUNCIL (remote, 5-30s)
  Routing:  local keyword classifier  0ms, 0 API
  Specialists: openrouter (Gemma/Llama/Qwen-Coder)
  Executive: openai/gpt-oss-120b:free → llama-3.3-70b → claude-sonnet-4-6
```

---

## Key Constants (always_listening_loop.py)

| Constant | Value | Purpose |
|---|---|---|
| `MIC_INDEX` | 1 | K66 microphone |
| `SPEAKER_INDEX` | 4 | Realtek speaker |
| `CONV_SPEECH_DB` | -35.0 dBFS | Speech onset threshold |
| `CONV_ONSET_CHUNKS` | 10 | 300ms sustained audio to confirm speech |
| `CONV_SILENCE_S` | 2.0s | Silence → end utterance |
| `CONV_MAX_S` | 20.0s | Hard recording ceiling |
| `WAIT_FOR_SPEECH_TIMEOUT_S` | 8.0s | Used for barge-in re-listen only |
| `BARGE_IN_DB` | -20.0 dBFS | (unused in always-on mode) |

---

## Models

| Model | Size | Purpose | Source |
|---|---|---|---|
| `en_US-lessac-medium.onnx` | ~65 MB | Piper TTS voice | HuggingFace auto-download |
| `Whisper base` | ~145 MB | STT | HuggingFace auto-download |
| `qwen2.5:3b` | ~1.9 GB | Local conversation LLM | `ollama pull qwen2.5:3b` |
| `qwen3:4b` | ~2.5 GB | Pulled but unused (thinking mode uncontrollable) | kept for future |
| LibreHardwareMonitor v0.9.6 | — | CPU/GPU temp via DLL (pythonnet) | `C:\Users\Celluloid Solutions\AppData\Local\LibreHardwareMonitor\` |

---

## Environment Variables (.env)

```env
OPENROUTER_API_KEY=sk-or-v1-...    # Required for Council/fallback
ANTHROPIC_API_KEY=                  # Optional, Claude Executive
OPENAI_API_KEY=                     # Optional, direct OpenAI
VOICE_ENABLED=true
```

---

## Hardware (current setup)

| Device | Index | Note |
|---|---|---|
| Microphone | 1 (K66) | USB mic |
| Speaker | 4 (Realtek) | |
| GPU | NVIDIA GTX 980 Ti | 6GB VRAM, GPUtil works |

---

## Phase History

| Phase | What was built |
|---|---|
| 13.7 | Initial service: wake word, SAPI TTS, basic STT |
| 14 | FOLLOWUP state, barge-in, diagnostics, Piper TTS |
| 15A | Reflex router, Gemma conversation tier, word limit, silence detection fix |
| 15B | Dynamic VAD (onset confirmation 300ms), Phase 15B ConversationBuffer |
| 15C | Ollama + Qwen2.5:3b local LLM, conversation history |
| 15D | Always-on (no wake word), 8 reflex modules, GPU stats, weather, apps |

---

## Planned / Stubs

- Calendar: Google Calendar / Outlook OAuth
- Spotify: full OAuth + track control
- Device Mesh: cross-device presence
- CPU temperature: requires LibreHardwareMonitor service
- Memory module: structured goal/reminder storage
- Phase 15E+: personality layer, humor re-enable, context memory
