# ADR-0001 — MARK III as a Personal AI Operating System

**Status:** Accepted
**Date:** 2026-06-21
**Author:** Navid Shahriar Sami

## Context

Most AI assistants are cloud-dependent, stateless, and generic. They reset between conversations, know nothing about the user, and depend entirely on internet connectivity.

The goal was to build something fundamentally different: a personal AI that runs on the user's own hardware, maintains persistent identity, knows its owner deeply, and operates across all the user's devices as a single unified intelligence.

## Decision

MARK III is architected as a personal AI operating system, not a chatbot or assistant.

Key properties:
- **Local-first:** Primary intelligence (Qwen 7B) runs on the user's hardware via Ollama
- **Always-on:** No wake word, no button, always listening
- **Persistent:** Identity, memory, and knowledge survive restarts
- **Multi-device:** One brain (desktop), multiple interfaces (Mac, iPhone, Watch)
- **Owned:** Data stays on the user's hardware. No cloud storage.

## Alternatives Considered

1. **Cloud-based assistant** — Rejected: subscription dependency, no offline capability, privacy concerns
2. **Simple voice command interface** — Rejected: too limited, no personality, no memory
3. **Plugin for existing AI** — Rejected: tied to third-party constraints, no ownership

## Consequences

- Requires dedicated desktop hardware (Windows/Linux)
- Python 3.11+ runtime
- Ollama for local LLM inference
- More complex than a simple chatbot but far more capable

## Future Impact

This decision enables: commercial deployment as MARK Box hardware, multi-user installations, MARK Connect relay infrastructure, and the full device ecosystem.
