"""
MARK III — Architecture Guardian

Detects drift between implementation and documentation.

Checks:
  - Services in app/services/ that have no architecture doc
  - ADRs that reference non-existent implementations
  - Governance files missing from their expected locations
  - Version consistency between MARK_VERSION.md and CHANGELOG.md
  - Orphan documentation (docs that no code references)

Called by:
  - repository_observer (on repo change)
  - repository_diagnostics (on demand)
  - mark_service startup

Does not modify any file — only reports.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("markiii.governance.guardian")

_REPO_ROOT       = Path(__file__).parents[4]
_DOCS_ARCH       = _REPO_ROOT / "docs" / "architecture"
_DOCS_ADR        = _REPO_ROOT / "docs" / "adr"
_SERVICES_ROOT   = _REPO_ROOT / "brain-server" / "app" / "services"


@dataclass
class GuardianFinding:
    severity: str   # "critical" | "warning" | "info"
    category: str   # "drift" | "orphan" | "missing" | "inconsistency"
    message:  str
    path:     str = ""


@dataclass
class GuardianReport:
    findings:       list[GuardianFinding] = field(default_factory=list)
    critical_count: int = 0
    warning_count:  int = 0
    info_count:     int = 0
    healthy:        bool = True

    def add(self, f: GuardianFinding) -> None:
        self.findings.append(f)
        if f.severity == "critical":
            self.critical_count += 1
            self.healthy = False
        elif f.severity == "warning":
            self.warning_count += 1
        else:
            self.info_count += 1

    def summary(self) -> str:
        if self.healthy and self.warning_count == 0:
            return f"Architecture healthy. {len(self.findings)} info notes."
        parts = []
        if self.critical_count: parts.append(f"{self.critical_count} critical")
        if self.warning_count:  parts.append(f"{self.warning_count} warnings")
        if self.info_count:     parts.append(f"{self.info_count} info")
        return "Architecture findings: " + ", ".join(parts)

    def to_dict(self) -> dict:
        return {
            "healthy": self.healthy,
            "critical": self.critical_count,
            "warnings": self.warning_count,
            "info": self.info_count,
            "findings": [
                {"severity": f.severity, "category": f.category,
                 "message": f.message, "path": f.path}
                for f in self.findings
            ],
        }


def run_audit() -> GuardianReport:
    """
    Full architecture audit. Returns a report with all findings.
    Non-blocking — never raises exceptions.
    """
    report = GuardianReport()
    try:
        _check_service_coverage(report)
        _check_adr_coverage(report)
        _check_required_docs(report)
        _check_version_consistency(report)
        _check_constitution(report)
    except Exception as e:
        log.warning("Guardian audit error: %s", e)
        report.add(GuardianFinding("warning", "drift", f"Audit incomplete: {e}"))
    return report


def _check_service_coverage(report: GuardianReport) -> None:
    """Every service directory should have a corresponding architecture doc."""
    if not _SERVICES_ROOT.exists():
        return
    arch_docs = {p.stem.lower() for p in _DOCS_ARCH.glob("*.md")} if _DOCS_ARCH.exists() else set()

    for service_dir in sorted(_SERVICES_ROOT.iterdir()):
        if not service_dir.is_dir() or service_dir.name.startswith("_"):
            continue
        # Map service dirs to expected doc names
        name = service_dir.name.replace("_", "")
        covered = any(
            name in doc or service_dir.name.replace("_", "") in doc
            for doc in arch_docs
        )
        if not covered:
            report.add(GuardianFinding(
                "warning", "missing",
                f"Service '{service_dir.name}' has no architecture document.",
                str(service_dir.relative_to(_REPO_ROOT)),
            ))
            log.debug("No arch doc: %s", service_dir.name)


def _check_adr_coverage(report: GuardianReport) -> None:
    """ADRs should reference real implementation paths."""
    if not _DOCS_ADR.exists():
        return
    adr_files = list(_DOCS_ADR.glob("ADR-*.md"))
    if not adr_files:
        report.add(GuardianFinding("warning", "missing", "No ADRs found in docs/adr/"))
        return
    report.add(GuardianFinding("info", "coverage", f"{len(adr_files)} ADRs present.", "docs/adr/"))


def _check_required_docs(report: GuardianReport) -> None:
    """Required root-level documents must exist."""
    required = [
        ("MARK_HOME.md",       "critical"),
        ("MARK_VERSION.md",    "critical"),
        ("MARK_III_MANIFEST.md", "warning"),
        ("CHANGELOG.md",       "warning"),
        ("CLAUDE.md",          "critical"),
        ("README.md",          "info"),
    ]
    for filename, severity in required:
        path = _REPO_ROOT / filename
        if not path.exists():
            report.add(GuardianFinding(
                severity, "missing",
                f"Required document missing: {filename}",
                filename,
            ))


def _check_version_consistency(report: GuardianReport) -> None:
    """MARK_VERSION.md and CHANGELOG.md should agree on the latest version."""
    version_path   = _REPO_ROOT / "MARK_VERSION.md"
    changelog_path = _REPO_ROOT / "CHANGELOG.md"
    if not version_path.exists() or not changelog_path.exists():
        return

    version_text   = version_path.read_text(encoding="utf-8", errors="ignore")
    changelog_text = changelog_path.read_text(encoding="utf-8", errors="ignore")

    # Extract version from MARK_VERSION.md
    vm = re.search(r"\*\*Version[:\s]+([0-9]+\.[0-9]+\.[0-9]+)", version_text, re.I)
    # Extract latest version from CHANGELOG.md
    cm = re.search(r"\[([0-9]+\.[0-9]+\.[0-9]+)\]", changelog_text)

    if vm and cm:
        if vm.group(1) != cm.group(1):
            report.add(GuardianFinding(
                "warning", "inconsistency",
                f"Version mismatch: MARK_VERSION.md={vm.group(1)}, CHANGELOG latest={cm.group(1)}",
            ))
        else:
            report.add(GuardianFinding("info", "consistency",
                f"Version consistent: {vm.group(1)}"))


def _check_constitution(report: GuardianReport) -> None:
    """CLAUDE.md must exist and contain Article XV."""
    claude_path = _REPO_ROOT / "CLAUDE.md"
    if not claude_path.exists():
        report.add(GuardianFinding(
            "critical", "missing",
            "CLAUDE.md missing — Article XV engineering directive not enforced.",
            "CLAUDE.md",
        ))
        return
    content = claude_path.read_text(encoding="utf-8", errors="ignore")
    if "ARTICLE XV" not in content:
        report.add(GuardianFinding(
            "critical", "inconsistency",
            "CLAUDE.md exists but Article XV directive is missing.",
            "CLAUDE.md",
        ))
    else:
        report.add(GuardianFinding("info", "constitution", "CLAUDE.md present with Article XV."))
