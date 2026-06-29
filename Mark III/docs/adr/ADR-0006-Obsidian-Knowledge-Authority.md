# ADR-0006 — Obsidian as Knowledge Authority

**Status:** Accepted
**Date:** 2026-06-28

## Decision

Obsidian is MARK's authoritative knowledge base. It is NOT conversational memory. It stores structured documentation that the owner writes and MARK reads.

Architecture questions → Obsidian first, then vector memory, then Qwen.
Personal history → vector memory, then session memory, then Qwen.
Live data → Integration APIs only.

## Why Not Just Vector Memory?

Vector memory is experiential — it learns from conversations. Obsidian is authoritative — the owner explicitly writes knowledge into it. These serve different purposes. Mixing them would degrade both.

## Consequence

The MARK III project folder (`idea72/Mark III/`) is the initial vault. Every markdown file in it is indexed and searchable. This document you're reading is part of that index.
