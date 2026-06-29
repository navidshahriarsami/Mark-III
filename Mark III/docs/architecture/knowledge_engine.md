# MARK III — Knowledge Engine

## Purpose

Obsidian is MARK's authoritative knowledge base. It is not conversational memory. It stores structured documentation, architecture, engineering decisions, research, and specifications. MARK reads it; the owner writes to it.

## Architecture

```
app/services/knowledge/
├── obsidian_bridge.py      ← main interface, auto-detects vault
├── vault_indexer.py        ← file watcher + incremental indexer
├── markdown_parser.py      ← parses .md → title/sections/tags/chunks
├── knowledge_manager.py    ← orchestrates Obsidian + ChromaDB
├── knowledge_router.py     ← decides when to query the vault
├── knowledge_cache.py      ← LRU cache for recent docs
└── knowledge_diagnostics.py ← indexing event log
```

## Vault Indexing

1. On MARK startup → `initialize_knowledge_base()` runs in background thread
2. Walks all `.md` files in the vault
3. Parses each file: YAML frontmatter, headings, sections, tags, wikilinks
4. Splits into chunks by heading (each section = one embedding)
5. Embeds via `nomic-embed-text` → stores in ChromaDB `obsidian` collection
6. Polls for changes every 60 seconds → incremental re-index on change
7. File hash tracking prevents re-indexing unchanged files

## Supported Content

- Architecture documents
- Roadmaps and phase plans
- Engineering decision records
- Meeting notes
- Research and ideas
- Funding documentation
- Specifications
- Any `.md` file in the vault

## Knowledge Router

Queries the vault only when the intent matches knowledge patterns:
```
architecture | roadmap | spec | design | decision | phase
document | plan | requirement | research | mark iii | pipeline
```

Skips vault for: greetings, live data queries (time/weather), short conversational queries.

## Context Builder Integration

When vault results are found, they are added to the context package:
```
[MARK III — System Manifest] › Device Mesh
The Device Mesh allows MARK to exist across multiple devices...
```

This context is passed to Qwen. Qwen reasons over it — it does not search files itself.

## Current Vault

The MARK III project folder (`idea72/Mark III/`) serves as the initial vault. This means MARK indexes its own documentation and can answer architecture questions from source.

**Future:** Owner's personal Obsidian vault for personal knowledge (notes, research, decisions).

## Related Documents

- [Memory Architecture](memory_architecture.md)
- [Cognitive Pipeline](cognitive_pipeline.md)

---

[[memory_architecture]] · [[cognitive_pipeline]] · [[identity_engine]] · [[system_overview]] · [[ADR-0006-Obsidian-Knowledge-Authority]] · [[ADR-0004-Memory-Architecture]] · [[ADR-0007-Context-Builder]] · [[MARK_III_MANIFEST]]
