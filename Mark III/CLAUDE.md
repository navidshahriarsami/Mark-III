# MARK III — Claude Engineering Directive

This file is read automatically by Claude Code at the start of every session.
It constitutes the permanent engineering protocol for all future Claude sessions working on MARK III.

---

## HANDOFF PROTOCOL

Before any engineering work, read in this order:

1. [MARK_HOME.md](MARK_HOME.md)
2. [MARK_VERSION.md](MARK_VERSION.md)
3. [MARK_III_MANIFEST.md](MARK_III_MANIFEST.md)
4. [docs/architecture/system_overview.md](docs/architecture/system_overview.md)
5. [docs/roadmap/completed_phases.md](docs/roadmap/completed_phases.md)

The repository is the source of truth. Conversation history is not architecture.

---

## ARTICLE XV — ENGINEERING DIRECTIVE

For every engineering task that permanently changes MARK:

### 1. Before writing code

- Read the relevant architecture document
- Check for an existing ADR that governs this area
- Verify the change does not contradict existing ADRs

### 2. After completing implementation

Run the governance checklist. Every permanent change must:

- [ ] Update `docs/architecture/` — the relevant subsystem doc
- [ ] Create or update the relevant `docs/adr/ADR-XXXX-*.md`
- [ ] Update `docs/roadmap/completed_phases.md` if a phase is complete
- [ ] Update `docs/roadmap/future.md` if the next phase is now defined
- [ ] Update `MARK_VERSION.md` — version bump + phase status
- [ ] Update `CHANGELOG.md` — one section per phase
- [ ] Update `MARK_III_MANIFEST.md` — reflect any new files or subsystems
- [ ] Validate cross-references — no broken wiki links
- [ ] Create a semantic git commit with the full change summary
- [ ] Trigger knowledge re-index (vault_indexer handles automatically)

### 3. Never

- Never leave implementation undocumented
- Never overwrite existing facts with LLM-generated values
- Never let documentation drift from implementation
- Never make a permanent architectural decision in conversation only
- Never skip the governance checklist for permanent changes

---

## TONE AND STYLE

Navid is a senior engineer and entrepreneur. Responses must be:

- Direct and professional
- Maximum 20 words for voice responses
- No humor, no sarcasm, no filler
- Senior engineer tone at all times

---

## ARCHITECTURE INVARIANTS

These never change without a new ADR:

1. Desktop brain owns all state — devices never manage their own state
2. LLM never invents facts that exist in structured memory
3. Facts are retrieved, never regenerated
4. Retrieval order: Structured Memory → Integration Manager → Vector → Obsidian → LLM
5. Identity is always injected before LLM context
6. Obsidian is engineering knowledge, not conversational memory
7. One owner per installation — no shared data between installations
8. Brain owns voice device state — `_active_voice_device` is authoritative

---

## CURRENT VERSION

See [MARK_VERSION.md](MARK_VERSION.md) for the current version and active phases.

---

## KNOWLEDGE GOVERNANCE

Every interaction is classified by the Knowledge Governor:

| Domain | Layer | Store |
|---|---|---|
| Engineering | Repository | docs/ + git |
| User Facts | Structured | structured_memory.db |
| User Identity | Identity | user_profile.json |
| Experience | Semantic | ChromaDB |
| Engineering Knowledge | Indexed | ChromaDB (obsidian collection) |
| Live Data | None | Never stored |

The Knowledge Governance System lives at:
`brain-server/app/services/governance/`

---

## SUBSYSTEM OWNERSHIP

| Responsibility | Owner | Never Handled By |
|---|---|---|
| Factual recall | recall_engine + fact_store | LLM |
| Live data | integration_manager | Vector memory |
| Reasoning | Qwen 7B | Integration manager |
| User profile | identity_manager | Session memory |
| Engineering knowledge | Obsidian + docs/ | LLM |
| Device state | brain-server | Any client |
