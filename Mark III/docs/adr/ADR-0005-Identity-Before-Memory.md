# ADR-0005 — Identity Before Memory

**Status:** Accepted
**Date:** 2026-06-28

## Decision

The owner's identity profile is injected into every Qwen call BEFORE memory context. Identity is not memory — it represents WHO the owner is, not WHAT happened.

This means Qwen always knows: name, occupation, technical level, current projects, goals, communication style, timezone. It knows this before the first word of the query is processed.

## Rationale

Memory tells MARK what happened. Identity tells MARK who they're talking to. These are fundamentally different. Conflating them causes MARK to treat user preferences as conversation history, which degrades with time.

## Consequence

`user_profile.json` is the permanent source of owner identity. It evolves slowly via the Learning Engine. It is never replaced by conversation summaries.
