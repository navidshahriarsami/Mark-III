"""
MARK III — Knowledge Seeder

Seeds the vector store with all architectural decisions, phase completions,
user preferences, and technical constraints accumulated across this project.

Run once after install:
    python -m app.services.memory.mark_knowledge

Or import and call seed() programmatically.
"""
from __future__ import annotations

import logging
from app.services.memory.vector_store import get_memory_store

log = logging.getLogger("markiii.memory.knowledge")

# ─── Seed data — everything we know about MARK III ───────────────────────────

_SEEDS = [

    # ── Architecture ──────────────────────────────────────────────────────────
    ("MARK III is a personal AI operating system. Desktop is the permanent brain. All devices are interfaces.",
     "architecture", ["core", "vision"], "all"),

    ("Voice pipeline: K66 mic (idx=1) → energy gate VAD → Whisper base STT → Reflex → Qwen 7B → Piper TTS → Realtek speaker (idx=4)",
     "architecture", ["voice", "pipeline"], "all"),

    ("LLM stack: Qwen2.5:7b via Ollama (primary, local, offline). OpenRouter fallback: Gemma 4 31B → Llama 3.3 70B → GPT-OSS 120B Executive",
     "architecture", ["llm", "qwen", "council"], "all"),

    ("Routing tiers: Reflex (<10ms) → Integration Manager (time/weather/system) → Qwen 7B local (1-3s) → Council Executive (5-30s)",
     "architecture", ["routing", "reflex"], "all"),

    ("Device Mesh: REST API on port 8765. Desktop=MARK Core. MacBook connected via device_client.py + Tailscale 100.94.162.25",
     "architecture", ["mesh", "devices"], "16"),

    ("Active voice device state is owned by the desktop brain only. Devices never manage their own state — they always send audio, brain decides who speaks.",
     "architecture", ["voice", "mesh", "state"], "16"),

    # ── Hardware ──────────────────────────────────────────────────────────────
    ("Desktop: Intel Core i7-8700K, 34GB RAM, NVIDIA GTX 980 Ti 6GB VRAM, Windows 10 Pro",
     "architecture", ["hardware", "desktop"], "all"),

    ("Microphone: K66 at device index 1. Speaker: Realtek at device index 4. Mac: nomic-embed-text MacBook Pro M1 via Tailscale 100.85.106.11",
     "architecture", ["hardware", "audio"], "all"),

    # ── Models installed ──────────────────────────────────────────────────────
    ("Ollama models installed: qwen2.5:7b (primary LLM), qwen2.5:3b (legacy), qwen3:4b (unused - thinking mode issue), nomic-embed-text (embeddings)",
     "architecture", ["models", "ollama"], "all"),

    ("Piper TTS: en_US-lessac-medium.onnx at 22050Hz, resampled to 48000Hz for WASAPI. Init ~3.5s, synthesis 50-120ms.",
     "architecture", ["tts", "piper"], "14"),

    # ── User preferences ──────────────────────────────────────────────────────
    ("User wants: zero humor, zero sarcasm, direct professional responses. Senior engineer tone. Max 20 words per voice response.",
     "preference", ["tone", "style"], "15"),

    ("User insists on native iOS — not Expo, not React Native, not any wrapper. MARK Mobile must be Swift/SwiftUI standalone app.",
     "preference", ["ios", "mobile"], "16B"),

    ("User philosophy: Mark and I are one. MARK lives in devices, shifts between them, performs automations, converses according to need.",
     "preference", ["vision", "philosophy"], "all"),

    ("Do not build radar/wave presence detection yet — waiting for TI IWR6843ISK sensor hardware.",
     "preference", ["presence", "radar"], "future"),

    ("MARK Connect (Phase 17): self-hosted WireGuard relay to replace Tailscale for commercial deployment. Zero third-party dependency.",
     "architecture", ["relay", "infrastructure", "commercial"], "17"),

    # ── Phase completions ─────────────────────────────────────────────────────
    ("Phase 14: Full voice pipeline — Piper TTS, barge-in, FOLLOWUP state, diagnostics, conversation buffer VAD.",
     "phase", ["14"], "14"),

    ("Phase 15A: Reflex router (social phrases), Gemma conversation tier, 20-word limit, VAD silence detection fix.",
     "phase", ["15A"], "15A"),

    ("Phase 15B: Dynamic VAD with 300ms onset confirmation (rejects keyboard clicks, fan noise). ConversationBuffer rewritten.",
     "phase", ["15B"], "15B"),

    ("Phase 15C: Ollama + Qwen2.5:3b local LLM. Conversation history (6 turns). Council stays for complex queries.",
     "phase", ["15C"], "15C"),

    ("Phase 15D: Always-on voice (no wake word). 8 reflex modules. GPU stats via LibreHardwareMonitorLib.dll. Weather+UV via Open-Meteo.",
     "phase", ["15D"], "15D"),

    ("Phase 16A: Device Mesh core — mesh_manager.py, device_registry.py, mesh_protocol.py, mesh_diagnostics.py. Desktop self-registers.",
     "phase", ["16A"], "16A"),

    ("Phase 16B+C: Mac mic relay (device_client.py), Samantha TTS on Mac, conversation handoff, presence fusion. MacBook live on Tailscale.",
     "phase", ["16B", "16C"], "16B"),

    ("Phase 16D: Standby mode, keyboard shortcut ⌘⌥M, remote desktop commands, brain-owns-state refactor. Desktop gates Piper TTS based on active device.",
     "phase", ["16D"], "16D"),

    ("Phase 18: Qwen 7B upgrade, integration manager, time service with world clock, language detection from Whisper. LLM is never source of truth for facts.",
     "phase", ["18"], "18"),

    # ── Key files ─────────────────────────────────────────────────────────────
    ("Entry point: mark_service.py. Main voice loop: app/services/voice/always_listening_loop.py. Mesh: app/services/mesh/mesh_manager.py",
     "architecture", ["files", "entry"], "all"),

    ("Reflex modules in app/services/reflex/. Integration services in app/services/integrations/. Memory in app/services/memory/.",
     "architecture", ["files", "structure"], "all"),

    ("Launch command: cd brain-server && python mark_service.py --console",
     "architecture", ["launch", "commands"], "all"),

    # ── Key decisions ─────────────────────────────────────────────────────────
    ("Qwen3:4b thinking mode cannot be disabled in Ollama 0.30.9 — generates 100-150 token thinking chain adding 5-8s latency. Switched to qwen2.5:7b.",
     "decision", ["qwen", "thinking"], "15C"),

    ("LibreHardwareMonitorLib.dll accessed via pythonnet directly — no WMI service needed. GPU temp works without admin. CPU temp needs admin for MSR access.",
     "decision", ["hardware", "temperature"], "15D"),

    ("Barge-in threshold: -20 dBFS, 5 chunks (150ms). Was -32 dBFS — too sensitive, picked up speaker bleed at -24 to -30 dBFS.",
     "decision", ["barge-in", "audio"], "15"),

    ("Silence timeout: 2.0s for main utterance. Was 4.0s, then halved. Dynamic VAD means silence timer only starts after speech confirmed.",
     "decision", ["vad", "silence"], "15B"),

    # ── Commercial vision ──────────────────────────────────────────────────────
    ("Total dev cost: $99/year (Apple Developer account). Everything else is $0 open source (Ollama, Piper, OpenRouter free tier, Open-Meteo).",
     "architecture", ["cost", "commercial", "pitch"], "all"),

    ("Future: MARK Box hardware (~$150 Intel NUC N100), MARK Connect relay ($6/month VPS). These are Phase 17-18 commercial infrastructure.",
     "architecture", ["hardware", "commercial", "future"], "future"),

    ("MARK Mobile (Phase 16B iOS): Native Swift/SwiftUI app. No Expo, no React Native. Background GPS, voice relay, Tailscale connection.",
     "phase", ["16B", "ios", "mobile"], "16B"),
]


def seed(force: bool = False) -> int:
    """
    Seed the vector store with MARK III knowledge.
    Skips if already seeded unless force=True.
    Returns number of memories added.
    """
    store = get_memory_store()

    if not force:
        stats = store.stats()
        if stats["total"] >= len(_SEEDS):
            log.info("Knowledge already seeded (%d memories) — skipping", stats["total"])
            return 0

    added = 0
    for content, category, tags, phase in _SEEDS:
        store.remember(content, category=category, tags=tags, phase=phase)
        added += 1
        log.info("Seeded [%s]: %s", category, content[:60])

    log.info("Knowledge base seeded: %d memories", added)
    return added


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    n = seed(force=True)
    print(f"\nSeeded {n} memories into mark_memory.db")

    # Quick recall test
    store = get_memory_store()
    print("\nTest recall: 'which LLM does MARK use?'")
    for m in store.recall("which LLM does MARK use?", top_k=3):
        print(f"  [{m.score:.2f}] {m.content[:80]}")
