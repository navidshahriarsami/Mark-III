# MARK III — Mobile Client

**Status:** Phase 16B-iOS — Xcode project created, Swift files pending.

## Platform

Native Swift / SwiftUI. No React Native. No Expo.

## Target

iPhone 16 (iOS 18). Xcode 15.4+. Free Apple ID for development (7-day install cycle). $99/year Apple Developer account for distribution.

## Planned Features

- Background GPS via CoreLocation (Always permission)
- Voice relay: mic → /mesh/voice → desktop Whisper → Samantha TTS
- Mesh registration + heartbeat (battery, GPS coordinates every 15s)
- Minimal SwiftUI status UI (MARK is the brain, not the app)
- Emergency SOS via satellite (iPhone 14+, built-in)
- Shift commands: "shift to iPhone", "shift to desktop"

## Xcode Project

Location: `mobile/MarkMobile/Mark III.xcodeproj`
Bundle ID: `com.markiii.ios`
Interface: SwiftUI
Language: Swift

## Architecture

The iPhone is a PORTAL into MARK, not a brain.

```
iPhone mic → AVFoundation capture → POST /mesh/voice (Tailscale)
                                         ↓
                                  Desktop Whisper + Qwen
                                         ↓
                              Response text → AVSpeechSynthesizer
```

## Related

- [Device Mesh Architecture](../docs/architecture/device_mesh.md)
- [ADR-0003: Device Mesh](../docs/adr/ADR-0003-Device-Mesh.md)
- [Future Roadmap](../docs/roadmap/future.md)
