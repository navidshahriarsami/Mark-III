/**
 * MARK III Mobile — Runtime Configuration
 *
 * BRAIN_URL: point this at your brain server.
 * For local dev with Expo Go on your phone, use your PC's LAN IP, not localhost.
 * Example: "http://192.168.1.42:8000"
 */
export const Config = {
  BRAIN_URL: 'http://192.168.4.85:8000',
  POLL_INTERVAL_MS:   15_000,   // dashboard refresh interval
  REQUEST_TIMEOUT_MS: 8_000,
} as const;
