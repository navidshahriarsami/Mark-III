# ADR-0011 — Knowledge Governance System

**Status:** Accepted
**Date:** 2026-06-30
**Author:** Navid Shahriar Sami

## Context

MARK III had no formal system for managing its own engineering knowledge. Architecture
decisions existed in conversation, not in the repository. Documentation could drift from
implementation. Future Claude sessions had no guaranteed mechanism for reading the
constitution of the system before making changes.

The MARK III Constitution established that:
- The repository is the permanent engineering authority
- Conversation is an event; knowledge is an asset
- Every permanent engineering decision must exist in the repository
- Engineering is institutional memory

## Decision

Introduce a Knowledge Governance System (KGS) as a core subsystem of MARK III:

```
app/services/governance/
  knowledge_governor.py     ← Orchestrator; starts on service boot
  knowledge_classifier.py   ← Domain classification (<1ms)
  knowledge_lifecycle.py    ← Draft→Implemented→Stable state machine
  knowledge_validator.py    ← Implementation vs documentation sync check
  repository_observer.py    ← Watchdog for docs/ changes (30s poll)
  documentation_manager.py  ← Creates/updates markdown docs
  architecture_guardian.py  ← Detects architecture drift
  adr_manager.py            ← ADR creation and validation
  roadmap_manager.py        ← Roadmap phase tracking
  version_manager.py        ← MARK_VERSION.md management
  changelog_manager.py      ← CHANGELOG.md management
  knowledge_index_manager.py ← ChromaDB index refresh
  repository_diagnostics.py  ← Full repository health report
  constitution_manager.py   ← Loads and validates CLAUDE.md
```

The MARK III Constitution is permanently encoded in `CLAUDE.md` at the repository root.
Claude Code reads this file automatically at the start of every session. Article XV
defines the engineering directive all future sessions must follow.

## Consequences

- Every future Claude session reads `CLAUDE.md` before any engineering work
- The Architecture Guardian detects drift between code and documentation
- The Repository Observer re-indexes documentation changes automatically
- Repository diagnostics are available at `GET /governance/diagnostics`
- The Knowledge Governance System starts before mesh and voice on boot
- `CLAUDE.md` is a constitutional document — changes require explicit engineer approval

---

[[knowledge_governor]] · [[system_overview]] · [[ADR-0001-Mark-Operating-System]] · [[engineering_principles]] · [[CLAUDE]] · [[repository_diagnostics]]
