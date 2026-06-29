# MARK III

> One Brain. Multiple Bodies. One Owner.

A personal AI operating system that runs on your own hardware. Always on. Always private. Always learning.

---

## What Is MARK III?

MARK III is not a chatbot. It is a persistent AI that:

- Runs **locally** on your desktop — no cloud required
- Listens **always** via voice — no wake word
- Knows **you** specifically — identity, goals, habits, preferences
- Lives across **all your devices** — desktop, Mac, iPhone, Watch
- Learns **continuously** from your behaviour

## Current Status

**Phase 18 — Identity & Knowledge Engine** ✅

- Always-on voice interface (Whisper STT → Qwen 7B → Piper TTS)
- MacBook Pro connected via Device Mesh
- 8 live reflex modules (time, weather, system, apps, media, network...)
- ChromaDB semantic memory + Obsidian vault indexing
- User identity engine with continuous learning

## Quick Start

**Desktop (Windows):**
```powershell
cd "brain-server"
pip install -r requirements.txt
python mark_service.py --console
```

**Mac client:**
```bash
pip3 install requests psutil
python3 device_client.py --host <desktop-ip> --type macbook --mic
```

## Architecture

```
User Voice → Whisper STT → Intent → Reflex/Integration/Memory/Qwen → Piper TTS
```

Full architecture: [docs/architecture/system_overview.md](docs/architecture/system_overview.md)

## Documentation

| Document | Purpose |
|---|---|
| [MARK_HOME.md](MARK_HOME.md) | Repository entry point |
| [MARK_VERSION.md](MARK_VERSION.md) | Current version + Claude handoff |
| [docs/architecture/](docs/architecture/) | System architecture |
| [docs/adr/](docs/adr/) | Engineering decisions |
| [docs/roadmap/](docs/roadmap/) | Past + future phases |
| [docs/knowledge/vision.md](docs/knowledge/vision.md) | Product vision |

## Cost

**$99/year** (Apple Developer account). Everything else is open source or free tier.

## License

Private — Navid Shahriar Sami © 2026
