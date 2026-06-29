# MARK III — Shared Layer

Cross-component contracts, protocols, schemas, and interfaces.

This layer will eventually be shared between:
- `brain-server/` (desktop brain, Python)
- `mobile/` (iOS client, Swift)
- `desktop-daemon/` (Windows daemon)
- Future: Watch client, embedded devices

## Structure

```
shared/
├── contracts/      ← Device interaction contracts (what each device must implement)
├── protocols/      ← Mesh protocol definitions (message formats, endpoints)
├── schemas/        ← Data schemas (UserProfile, Device, Memory...)
├── interfaces/     ← Shared interfaces and abstract definitions
├── constants/      ← Shared constants (ports, timeouts, thresholds)
└── memory/         ← Memory schema contracts
```

## Status

**Scaffold only.** No implementation yet.

Contracts will be defined when MARK Mobile (iOS) is built in Phase 16B-iOS,
as that is the first client that requires a formal contract with the brain server.

## Related

- [Mesh Protocol](../docs/architecture/device_mesh.md)
- [Memory Architecture](../docs/architecture/memory_architecture.md)
- [ADR-0003: Device Mesh](../docs/adr/ADR-0003-Device-Mesh.md)
