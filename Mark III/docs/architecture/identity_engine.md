# MARK III — Identity Engine

## Purpose

Every MARK installation belongs to exactly one owner. MARK must know who it is talking to before any reasoning occurs. Identity is not memory — it is the permanent model of the owner.

## Architecture

```
app/services/identity/
├── identity_manager.py    ← singleton, loads/saves profile
├── profile_schema.py      ← UserProfile dataclass (all fields)
├── profile_engine.py      ← provides context string for Qwen
├── learning_engine.py     ← infers patterns every 4 hours
├── activity_tracker.py    ← records query types, active hours
├── session_summarizer.py  ← Qwen summarizes each session → ChromaDB
├── preference_manager.py  ← evolves comm style, language, app prefs
├── voice_profile.py       ← voice enrollment metadata (biometrics future)
└── identity_diagnostics.py ← health logging
```

## UserProfile Fields

**Identity:** user_id, display_name, preferred_name, email
**Context:** timezone, languages, occupation, organisation, technical_level
**Goals:** goals[], interests[], current_projects[]
**Tools:** primary_devices[], preferred_apps[], preferred_ide, preferred_browser
**Working:** work_start, work_end, focus_hours, working_days, timezone
**Communication:** response_length, explanation_depth, tone, language
**Preferences:** notifications, privacy, automation settings
**Infrastructure:** obsidian_vault path, mesh_devices[]
**Voice:** enrolled status, confidence threshold, model version
**Meta:** profile_version, created_at, updated_at, onboarded, onboarding_source

## What MARK Learns Automatically

| Signal | What it teaches |
|---|---|
| Peak active hours | Updates `work_start` |
| Ratio of complex queries | Infers `technical_level = expert` |
| Detected language | Updates `languages[]` primary |
| Mentioned apps | Updates `preferred_apps[]` |
| Session summaries | Stored in ChromaDB `conversations` collection |

## Profile Context Injection

Before every Qwen call, the profile engine injects:
```
OWNER PROFILE:
Name: Navid
Occupation: Developer & Entrepreneur
Technical level: expert
Working on: MARK III, PathwayAU
Goals: Build MARK as personal AI OS, Launch PathwayAU
Preferred style: concise responses, professional tone
Timezone: Australia/Sydney
```

## Multi-Installation Isolation

```
Desktop A (Navid)     → user_profile.json (Navid's data)
Desktop B (Uncle)     → user_profile.json (Uncle's data)
```

Zero data sharing. Same codebase, completely isolated personalities.

## Mobile Onboarding Hook

When the iOS app completes onboarding, it calls:
```python
identity_manager.from_mobile_onboarding(data)
```

No architecture change required. The profile schema already supports all mobile-provided fields.

## Voice Authentication (Future)

`voice_profile.py` contains the enrollment metadata structure. Biometric implementation (speaker verification via pyannote.audio) comes in a dedicated security phase. Currently: open access (single-user assumption).

## Related Documents

- [Memory Architecture](memory_architecture.md)
- [Knowledge Engine](knowledge_engine.md)

---

[[memory_architecture]] · [[knowledge_engine]] · [[cognitive_pipeline]] · [[system_overview]] · [[ADR-0005-Identity-Before-Memory]] · [[ADR-0001-Mark-Operating-System]] · [[future]] · [[vision]]
