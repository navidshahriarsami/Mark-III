# MARK III — Future Roadmap

## Phase 16B-iOS — MARK Mobile (Next)

**Objective:** Native Swift iOS app. MARK on iPhone.

**Features:**
- Background GPS via CoreLocation (Always permission)
- Voice relay (AVFoundation mic → /mesh/voice → Samantha)
- Mesh registration + heartbeat (battery, GPS coordinates)
- Minimal SwiftUI status UI
- Emergency SOS via satellite (iPhone 14+)

**Technical:**
- Bundle ID: com.markiii.ios
- Xcode project exists at: `idea72/Mark III/MarkMobile/`
- Free Apple ID allows device testing (app expires every 7 days)
- Production requires $99/year Apple Developer account

## Phase 17 — Universal Actions

**Objective:** MARK can DO things, not just talk.

**Features:**
- Open/close applications by voice
- Take screenshots
- Set system reminders
- File operations (search, open)
- Browser control (URL, tabs)

**Technical:**
- `app/services/actions/` scaffolding already exists
- SudoApprovalModal in future iOS app for high-stakes actions
- All actions logged as learned patterns in vector memory

## Phase 17A — MARK Connect (Commercial Relay)

**Objective:** Replace Tailscale with self-hosted WireGuard relay.

**Why:** Tailscale is $6/user/month for commercial use. MARK Connect runs on a $6/month VPS and is fully owned.

**Features:**
- WireGuard-based encrypted relay
- Device token registration
- Auto-connect on MARK install
- Zero third-party dependency
- `curl markos.ai/install | bash` one-line setup

## Phase 18 — MARK Box Hardware

**Objective:** Dedicated hardware product.

**Target hardware:** Intel NUC N100 (~$150)
- 8-16GB RAM
- NVMe SSD (model storage)
- Pre-flashed MARK OS image

**Revenue:** Hardware sale + MARK Connect subscription

## Phase 19 — AR Glasses

**Objective:** MARK in augmented reality.

**Features:**
- AR overlay on what you see
- Object identification
- Live translation
- HUD status readout

## Phase 20 — Vision AI

**Objective:** MARK sees the world.

**Features:**
- Camera input processing
- Screen context reading
- Document analysis
- Object identification

## Phase 21 — Robot Interface

**Objective:** Physical actuation.

**Features:**
- MARK directs physical robotic arms
- Home automation execution
- Environmental interaction

## Emergency/Wellness Layer (Cross-Phase)

**Prerequisite:** iPhone mesh + background GPS

**Features:**
- Presence monitoring (2h no signal → check-in, 6h → alert, 24h → escalate)
- Last known location on signal loss
- Pre-trip registration ("I'm hiking X, back by Y")
- Emergency contact notification (email + SMS)
- Note: police calls require human intermediary (legal)

## Voice Authentication (Cross-Phase)

**Features:**
- Voice print enrollment during mobile onboarding
- Speaker diarization (owner vs. guest)
- Owner mode vs. guest mode
- `voice_profile.py` architecture already in place
- Biometric implementation: pyannote.audio
