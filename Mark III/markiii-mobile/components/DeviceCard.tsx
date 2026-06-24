import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors } from '@/constants/Colors';
import { StatusBadge } from './StatusBadge';
import type { ServerStatus, RecentSnapshot } from '@/services/api';

function classificationColour(c: string): string {
  return (Colors.classColours as Record<string, string>)[c] ?? Colors.textMuted;
}

function fmtUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function fmtTs(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('en-AU', {
    hour:   '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

interface Props {
  status: ServerStatus;
}

export function DeviceCard({ status }: Props) {
  const isOnline   = status.devices_online > 0;
  const lastSnap   = status.recent_snapshots[0] ?? null;

  return (
    <View style={styles.card}>
      {/* Header row */}
      <View style={styles.headerRow}>
        <View>
          <Text style={styles.hostname}>DESKTOP-OMJ0BL5</Text>
          <Text style={styles.sub}>Windows 10 · MARK III Daemon</Text>
        </View>
        <StatusBadge variant={isOnline ? 'online' : 'offline'} />
      </View>

      <View style={styles.divider} />

      {/* Stat grid */}
      <View style={styles.grid}>
        <Stat label="Uptime"     value={fmtUptime(status.uptime_s)} />
        <Stat label="Snapshots"  value={String(status.snapshots_total)} />
        <Stat label="Breaches"   value={String(status.breaches_total)} colour={status.breaches_total > 0 ? Colors.red : undefined} />
        <Stat label="Commands"   value={String(status.commands_total)} />
      </View>

      {/* Active window */}
      {lastSnap && (
        <>
          <View style={styles.divider} />
          <Text style={styles.sectionLabel}>Active window</Text>
          <View style={styles.windowRow}>
            <View style={[styles.classDot, { backgroundColor: classificationColour(lastSnap.classification) }]} />
            <View style={{ flex: 1 }}>
              <Text style={styles.processName} numberOfLines={1}>{lastSnap.process}</Text>
              {lastSnap.domain ? (
                <Text style={styles.domain} numberOfLines={1}>{lastSnap.domain}</Text>
              ) : null}
            </View>
            <Text style={styles.ts}>{fmtTs(lastSnap.ts)}</Text>
          </View>
        </>
      )}
    </View>
  );
}

function Stat({ label, value, colour }: { label: string; value: string; colour?: string }) {
  return (
    <View style={styles.stat}>
      <Text style={[styles.statValue, colour ? { color: colour } : {}]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Colors.surface,
    borderRadius:    16,
    borderWidth:     1,
    borderColor:     Colors.border,
    padding:         20,
    marginBottom:    16,
  },
  headerRow: {
    flexDirection:  'row',
    justifyContent: 'space-between',
    alignItems:     'flex-start',
  },
  hostname: { fontSize: 17, fontWeight: '600', color: Colors.textPrimary },
  sub:      { fontSize: 12, color: Colors.textSecondary, marginTop: 2 },
  divider:  { height: 1, backgroundColor: Colors.border, marginVertical: 16 },
  grid: {
    flexDirection:  'row',
    justifyContent: 'space-between',
  },
  stat:      { alignItems: 'center' },
  statValue: { fontSize: 22, fontWeight: '600', color: Colors.textPrimary },
  statLabel: { fontSize: 11, color: Colors.textSecondary, marginTop: 2 },
  sectionLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: Colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 10,
  },
  windowRow: {
    flexDirection: 'row',
    alignItems:    'center',
    gap:           10,
  },
  classDot:    { width: 10, height: 10, borderRadius: 5 },
  processName: { fontSize: 14, color: Colors.textPrimary, fontWeight: '500' },
  domain:      { fontSize: 12, color: Colors.textSecondary, marginTop: 1 },
  ts:          { fontSize: 11, color: Colors.textMuted },
});
