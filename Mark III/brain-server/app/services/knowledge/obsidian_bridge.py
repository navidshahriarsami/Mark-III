"""
MARK III — Obsidian Bridge

Primary interface between MARK's cognitive pipeline and the Obsidian vault.

The vault is MARK's authoritative knowledge base — not conversational memory.
It stores architecture, roadmaps, specifications, research, decisions, and
personal knowledge. MARK reads from it; the user writes to it via Obsidian.

Auto-detects vault location. Configurable via OBSIDIAN_VAULT env var or .env.
"""
from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("markiii.knowledge.obsidian")


@dataclass
class KnowledgeResult:
    content:    str
    title:      str
    source:     str   # file path
    heading:    str   # section heading
    score:      float
    tags:       list[str]
    category:   str


# ─── Vault detection ──────────────────────────────────────────────────────────

def _detect_vault() -> Optional[Path]:
    """Auto-detect Obsidian vault location."""
    # 1. Environment variable
    env = os.getenv("OBSIDIAN_VAULT") or os.getenv("MARK_VAULT")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p

    # 2. Common locations by platform
    home = Path.home()
    system = platform.system()

    candidates = []
    if system == "Darwin":  # macOS
        candidates = [
            home / "Documents" / "Obsidian Vault",
            home / "Documents" / "vault",
            home / "Documents" / "Notes",
            home / "Desktop" / "Obsidian Vault",
            home / "iCloud Drive" / "Obsidian",
        ]
    elif system == "Windows":
        candidates = [
            home / "Documents" / "Obsidian Vault",
            home / "Documents" / "vault",
            home / "Documents" / "Notes",
            home / "Desktop" / "Obsidian Vault",
            home / "OneDrive" / "Documents" / "Obsidian Vault",
        ]
    else:  # Linux
        candidates = [
            home / "Documents" / "Obsidian Vault",
            home / "vault",
            home / "notes",
        ]

    for p in candidates:
        if p.exists() and any(p.glob("*.md")):
            log.info("Auto-detected vault: %s", p)
            return p

    return None


# ─── ObsidianBridge ───────────────────────────────────────────────────────────

class ObsidianBridge:
    """
    Connects MARK to an Obsidian vault.

    Usage:
        bridge = ObsidianBridge()
        if bridge.is_available():
            results = bridge.search("MARK III architecture")
    """

    def __init__(self, vault_path: Optional[Path] = None) -> None:
        self._vault    = vault_path or _detect_vault()
        self._indexer  = None
        self._cache    = None
        self._ready    = False

        if self._vault:
            log.info("Obsidian vault: %s", self._vault)
        else:
            log.info("No Obsidian vault found — knowledge bridge inactive")

    def is_available(self) -> bool:
        return self._vault is not None and self._vault.exists()

    def setup(self, auto_watch: bool = True) -> dict:
        """
        Initialize indexer, run initial scan, optionally start file watcher.
        Returns indexing stats.
        """
        if not self.is_available():
            return {"error": "No vault configured"}

        from app.services.memory.chroma_store   import get_chroma_store
        from app.services.knowledge.vault_indexer import VaultIndexer
        from app.services.knowledge.knowledge_cache import KnowledgeCache

        chroma          = get_chroma_store()
        self._indexer   = VaultIndexer(self._vault, chroma)
        self._cache     = KnowledgeCache()
        self._ready     = True

        # Initial index (incremental — skips unchanged files)
        stats = self._indexer.full_index()

        # Start background watcher
        if auto_watch:
            self._indexer.start_watching()

        return stats

    def search(
        self,
        query:     str,
        top_k:     int   = 5,
        min_score: float = 0.35,
    ) -> list[KnowledgeResult]:
        """Search the vault for documents relevant to the query."""
        if not self._ready:
            return []

        from app.services.memory.chroma_store import get_chroma_store
        results = get_chroma_store().search(
            query,
            top_k       = top_k,
            collections = ["obsidian"],
            min_score   = min_score,
        )

        return [
            KnowledgeResult(
                content  = r.content,
                title    = r.metadata.get("title", ""),
                source   = r.metadata.get("file", ""),
                heading  = r.metadata.get("heading", ""),
                score    = r.score,
                tags     = r.metadata.get("tags", "").split(","),
                category = r.metadata.get("category", ""),
            )
            for r in results
        ]

    def rebuild_index(self) -> dict:
        """Force full re-index of the entire vault."""
        if not self._indexer:
            return {"error": "Not initialized"}
        return self._indexer.full_index(force=True)

    def vault_stats(self) -> dict:
        from app.services.memory.chroma_store import get_chroma_store
        count = get_chroma_store().count("obsidian")
        return {
            "vault_path":    str(self._vault) if self._vault else None,
            "indexed_chunks": count,
            "ready":          self._ready,
        }

    def set_vault(self, path: str) -> bool:
        """Manually set vault path and re-initialize."""
        p = Path(path).expanduser()
        if not p.exists():
            return False
        self._vault = p
        self._ready = False
        self.setup()
        return True


# ─── Singleton ────────────────────────────────────────────────────────────────

_bridge: Optional[ObsidianBridge] = None


def get_obsidian_bridge() -> ObsidianBridge:
    global _bridge
    if _bridge is None:
        _bridge = ObsidianBridge()
    return _bridge
