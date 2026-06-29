# ADR-0008 — Qwen as Reasoning Engine, Not Knowledge Base

**Status:** Accepted
**Date:** 2026-06-28

## Decision

Qwen 7B's role is conversation and reasoning ONLY. It never answers factual questions from its training data.

- Time → Integration Manager
- Weather → Integration Manager  
- System stats → Reflex modules
- Architecture → Obsidian vault + vector memory
- Personal history → vector memory

## Why Qwen 7B Not 14B for Voice?

Hardware: GTX 980 Ti has 6GB VRAM. Qwen 14B is 8GB — runs CPU-only at 5-8 tokens/second. A 20-word voice response would take 12-20 seconds. Unacceptable.

Qwen 7B: fits in VRAM partially → 2-3s responses → acceptable for voice.
Qwen 14B: for Council-tier deep reasoning where 5-30s latency is expected.

## Consequence

Qwen is fast and accurate because it doesn't hallucinate facts — it reasons over facts already retrieved. The 20-word voice limit enforces concise, direct responses.
