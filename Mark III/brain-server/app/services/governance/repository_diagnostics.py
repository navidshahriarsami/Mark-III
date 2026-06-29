"""
MARK III — Repository Diagnostics

Single-call health report for the entire repository.
Aggregates: architecture guardian, memory stats, recall diagnostics,
vault index status, ADR coverage, and version consistency.

Called by:
  - mark_service startup (logged to console)
  - GET /governance/diagnostics (mesh API)
  - Voice: "Mark, run diagnostics" → system module routes here
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger("markiii.governance.diagnostics")
_OUTPUT_PATH = Path(__file__).parents[4] / "brain-server" / "repository_diagnostics.json"


@dataclass
class DiagnosticsReport:
    timestamp:    str              = ""
    healthy:      bool             = True
    architecture: dict             = field(default_factory=dict)
    memory:       dict             = field(default_factory=dict)
    recall:       dict             = field(default_factory=dict)
    adrs:         dict             = field(default_factory=dict)
    version:      dict             = field(default_factory=dict)
    knowledge:    dict             = field(default_factory=dict)
    latency_ms:   float            = 0.0
    summary:      str              = ""


def run_diagnostics() -> DiagnosticsReport:
    """Full repository health check. Non-blocking. Returns report and saves JSON."""
    t0     = time.monotonic()
    report = DiagnosticsReport(timestamp=datetime.now().isoformat(timespec="seconds"))

    # Architecture Guardian
    try:
        from app.services.governance.architecture_guardian import run_audit
        audit            = run_audit()
        report.architecture = audit.to_dict()
        if not audit.healthy:
            report.healthy = False
    except Exception as e:
        report.architecture = {"error": str(e)}

    # Structured Memory
    try:
        from app.services.memory.structured_memory import memory_stats
        report.memory = memory_stats()
    except Exception as e:
        report.memory = {"error": str(e)}

    # Recall Diagnostics
    try:
        from app.services.memory.recall_diagnostics import diag
        report.recall = diag.summary()
    except Exception as e:
        report.recall = {"error": str(e)}

    # ADR Coverage
    try:
        from app.services.governance.adr_manager import list_adrs
        adrs            = list_adrs()
        report.adrs     = {"count": len(adrs), "statuses": {a.status: 0 for a in adrs}}
        for a in adrs:
            report.adrs["statuses"][a.status] = report.adrs["statuses"].get(a.status, 0) + 1
    except Exception as e:
        report.adrs = {"error": str(e)}

    # Version
    try:
        from app.services.governance.version_manager import get_version
        vi              = get_version()
        report.version  = {"version": vi.version, "phase": vi.phase}
    except Exception as e:
        report.version = {"error": str(e)}

    # Knowledge / Vault Index
    try:
        from app.services.knowledge.vault_indexer import get_vault_indexer
        idx              = get_vault_indexer()
        state_path       = Path(__file__).parents[4] / "brain-server" / "vault_index_state.json"
        if state_path.exists():
            state        = json.loads(state_path.read_text())
            report.knowledge = {"indexed_files": len(state)}
        else:
            report.knowledge = {"indexed_files": 0}
    except Exception as e:
        report.knowledge = {"error": str(e)}

    report.latency_ms = round((time.monotonic() - t0) * 1000, 1)

    # Build summary line
    arch_h    = report.architecture.get("healthy", True)
    mem_total = report.memory.get("total", 0)
    adrs_n    = report.adrs.get("count", 0)
    ver       = report.version.get("version", "?")
    bypassed  = report.recall.get("llm_bypass_rate", 0)
    report.summary = (
        f"v{ver} | {'healthy' if arch_h else 'drift detected'} | "
        f"{mem_total} facts | {adrs_n} ADRs | bypass={bypassed:.0%}"
    )

    # Save
    try:
        _OUTPUT_PATH.write_text(json.dumps(
            {
                "timestamp":    report.timestamp,
                "healthy":      report.healthy,
                "summary":      report.summary,
                "architecture": report.architecture,
                "memory":       report.memory,
                "recall":       report.recall,
                "adrs":         report.adrs,
                "version":      report.version,
                "knowledge":    report.knowledge,
                "latency_ms":   report.latency_ms,
            },
            indent=2,
        ))
    except Exception:
        pass

    log.info("Diagnostics: %s (%.0fms)", report.summary, report.latency_ms)
    return report
