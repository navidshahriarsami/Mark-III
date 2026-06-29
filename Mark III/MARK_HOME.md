# MARK III — Home

Welcome to the MARK III repository. This is the starting point for every developer, contributor, and future Claude session.

---

## What Is MARK III?

A personal AI operating system. One brain (desktop). Multiple bodies (Mac, iPhone, Watch). Always on. Always private. Always yours.

→ [Vision](docs/knowledge/vision.md)
→ [Engineering Principles](docs/knowledge/engineering_principles.md)

---

## Where to Start

| Goal | Start Here |
|---|---|
| Understand the system | [System Overview](docs/architecture/system_overview.md) |
| Understand the pipeline | [Cognitive Pipeline](docs/architecture/cognitive_pipeline.md) |
| See all design decisions | [ADR Index](docs/adr/) |
| See the current version | [MARK_VERSION.md](MARK_VERSION.md) |
| Understand the roadmap | [Future Roadmap](docs/roadmap/future.md) |
| Investor overview | [Investor Summary](docs/knowledge/investor_summary.md) |
| For Claude sessions | [Claude Handoff Protocol](MARK_VERSION.md#claude-handoff-protocol) |

---

## Repository Structure

```
Mark III/
├── MARK_HOME.md            ← You are here
├── MARK_VERSION.md         ← Current version, phases, Claude handoff
├── MARK_III_MANIFEST.md    ← Master index of all components
├── CHANGELOG.md            ← Release history
├── README.md               ← GitHub-facing summary
│
├── docs/                   ← All documentation
│   ├── architecture/       ← Subsystem architecture docs
│   ├── adr/                ← Architecture Decision Records (0001-0010)
│   ├── roadmap/            ← Phase history + future plans
│   ├── knowledge/          ← Vision, principles, investor docs
│   └── api/                ← API specifications
│
├── brain-server/           ← Desktop brain (Python 3.11)
│   ├── mark_service.py     ← Entry point
│   ├── app/services/       ← All services
│   └── requirements.txt
│
├── desktop-daemon/         ← Windows desktop daemon
│
├── shared/                 ← Cross-component contracts (scaffold)
│   ├── contracts/          ← Device interaction contracts
│   ├── protocols/          ← Mesh protocol definitions
│   ├── schemas/            ← Shared data schemas
│   ├── interfaces/         ← Shared interfaces
│   └── constants/          ← Shared constants
│
└── mobile/                 ← Future mobile clients
    └── (iOS app coming — Phase 16B-iOS)
```

---

## Quick Commands

```powershell
# Start MARK III (Windows desktop)
cd brain-server
python mark_service.py --console
```

```bash
# Start Mac client (macOS)
python3 ~/.mark/device_client.py --host 100.94.162.25 --type macbook --mic
```

---

## Current Status

See [MARK_VERSION.md](MARK_VERSION.md) for the full phase status, breaking changes, and Claude handoff protocol.
