#!/bin/bash
# MARK III — Device Client Watchdog
# Keeps device_client.py running regardless of network drops,
# Tailscale interruptions, or process crashes.
# Auto-reconnects on any available connection.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLIENT="$SCRIPT_DIR/device_client.py"
HOST="100.94.162.25"
NAME="MacBook Pro M1"
TYPE="macbook"
LOG="$HOME/Desktop/idea72/Mark III/mesh.log"
RESTART_DELAY=5    # seconds between crash restarts
MAX_DELAY=60       # max seconds between restarts after repeated crashes
crash_count=0

echo "$(date): MARK III watchdog started" >> "$LOG"

while true; do
    # Wait for any network before attempting connection
    until ping -c1 -W2 8.8.8.8 &>/dev/null || ping -c1 -W2 "$HOST" &>/dev/null; do
        echo "$(date): No network — waiting..." >> "$LOG"
        sleep 10
    done

    echo "$(date): Network available — starting MARK client (attempt $((crash_count+1)))" >> "$LOG"

    python3 "$CLIENT" \
        --host "$HOST" \
        --name "$NAME" \
        --type "$TYPE" \
        --mic >> "$LOG" 2>&1

    EXIT_CODE=$?
    crash_count=$((crash_count + 1))

    # Exponential backoff on repeated crashes (5s → 10s → 20s → 40s → 60s cap)
    DELAY=$(( RESTART_DELAY * (2 ** (crash_count - 1)) ))
    DELAY=$(( DELAY > MAX_DELAY ? MAX_DELAY : DELAY ))

    echo "$(date): Client exited (code $EXIT_CODE, crash #$crash_count) — restarting in ${DELAY}s" >> "$LOG"
    sleep "$DELAY"

    # Reset crash count after a long stable run (assume it was a network drop not a bug)
    if [ "$DELAY" -ge "$MAX_DELAY" ]; then
        crash_count=0
    fi
done
