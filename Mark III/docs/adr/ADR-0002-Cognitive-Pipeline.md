# ADR-0002 — Retrieval-First Cognitive Pipeline

**Status:** Accepted
**Date:** 2026-06-28

## Context

When MARK routes every query through the LLM first, it halluccinates factual information (time, weather, battery), produces slow responses, and uses expensive API credits even for simple questions like "what time is it?"

## Decision

Implement a retrieval-first pipeline where the LLM is always the last resort.

Priority order:
1. Social Reflex (<1ms) — deterministic responses
2. Integration Manager (<10ms) — live system data
3. Intent Classification (<2ms) — routing decision
4. Context Builder (<500ms) — assemble knowledge
5. Direct Recall — high-confidence memory bypass
6. Qwen 7B — conversation + reasoning
7. Council — complex multi-step only

## Decision Rule

**The LLM never retrieves. It reasons over information already retrieved.**

## Alternatives Considered

1. **LLM-first** — Rejected: hallucination, slow, expensive
2. **Keyword routing** — Rejected: too brittle, misses intent variations
3. **Separate models per task** — Rejected: too complex, multiple inference servers

## Consequences

- Requires building integration modules for each data source
- Intent classifier adds <2ms overhead (acceptable)
- Response quality dramatically higher for factual queries
- LLM only engages when genuinely needed

## Future Impact

This pipeline is extensible: new data sources become Integration Manager modules. New query types become Intent Classifier patterns. The LLM role remains constant: reasoning, not retrieval.
