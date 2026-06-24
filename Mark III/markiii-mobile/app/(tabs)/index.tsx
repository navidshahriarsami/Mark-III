/**
 * MARK III Mobile — Dashboard Screen
 *
 * Primary view. Polls /status every 15 s, shows the DESKTOP-OMJ0BL5 card,
 * server stats, recent activity feed, foreground notification banner,
 * and the SudoApprovalModal when commands are pending.
 */

import React, { useEffect } from 'react';
import {
  View, Text, ScrollView, RefreshControl,
  TouchableOpacity, StyleSheet, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useQueryClient } from '@tanstack/react-query';

import { Colors } from '@/constants/Colors';
import { useServerStatus, usePendingCommands } from '@/hooks/useServerStatus';
import { useMarkStore } from '@/store/useMarkStore';
import { DeviceCard } from '@/components/DeviceCard';
import { SudoApprovalModal } from '@/components/SudoApprovalModal';

function fmtTs(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export default function DashboardScreen() {
  const queryClient        = useQueryClient();
  const { data: status, isLoading, isError, dataUpdatedAt } = useServerStatus();
  const lastNotification   = useMarkStore((s) => s.lastNotification);
  const clearNotification  = useMarkStore((s) => s.clearNotification);
  const setPendingCommands = useMarkStore((s) => s.setPendingCommands);

  // Poll pending commands for the active device
  const activeDeviceId = status?.recent_snapshots[0]?.device_id ?? null;
  const { data: pendingCmds } = usePendingCommands(activeDeviceId);

  useEffect(() => {
    if (pendingCmds) setPendingCommands(pendingCmds);
  }, [pendingCmds]);

  const onRefresh = () => queryClient.invalidateQueries({ queryKey: ['serverStatus'] });

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={isLoading}
            onRefresh={onRefresh}
            tintColor={Colors.green}
          />
        }
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.title}>MARK III</Text>
          {dataUpdatedAt ? (
            <Text style={styles.lastUpdated}>Updated {fmtTs(dataUpdatedAt / 1000)}</Text>
          ) : null}
        </View>

        {/* Foreground notification banner */}
        {lastNotification && (
          <TouchableOpacity style={styles.notifBanner} onPress={clearNotification} activeOpacity={0.8}>
            <Text style={styles.notifTitle}>{lastNotification.title}</Text>
            <Text style={styles.notifBody}>{lastNotification.body}</Text>
            <Text style={styles.notifDismiss}>Tap to dismiss</Text>
          </TouchableOpacity>
        )}

        {/* Error state */}
        {isError && (
          <View style={styles.errorCard}>
            <Text style={styles.errorTitle}>Brain server unreachable</Text>
            <Text style={styles.errorBody}>
              Check that uvicorn is running at the configured BRAIN_URL.
              Pull down to retry.
            </Text>
          </View>
        )}

        {/* Device card */}
        {status && <DeviceCard status={status} />}

        {/* Server stat strip */}
        {status && (
          <View style={styles.statStrip}>
            <MiniStat label="Notification" value={status.notification} />
            <MiniStat label="Database"     value={status.database.split('/').pop() ?? '-'} />
            <MiniStat label="Uptime"       value={`${Math.floor(status.uptime_s / 60)}m`} />
          </View>
        )}

        {/* Recent activity */}
        {status && status.recent_snapshots.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Recent Activity</Text>
            {status.recent_snapshots.map((snap, i) => (
              <ActivityRow key={i} snap={snap} />
            ))}
          </View>
        )}

        {/* Empty state */}
        {status && status.recent_snapshots.length === 0 && !isError && (
          <View style={styles.emptyState}>
            <Text style={styles.emptyText}>No activity yet.</Text>
            <Text style={styles.emptySubtext}>
              Open any app on DESKTOP-OMJ0BL5 and it will appear here within 10 seconds.
            </Text>
          </View>
        )}
      </ScrollView>

      {/* Sudo approval modal — renders on top when commands are pending */}
      <SudoApprovalModal />
    </SafeAreaView>
  );
}

function ActivityRow({ snap }: { snap: { process: string; classification: string; domain: string | null; ts: number } }) {
  const colour = (Colors.classColours as Record<string, string>)[snap.classification] ?? Colors.textMuted;
  return (
    <View style={styles.activityRow}>
      <View style={[styles.activityDot, { backgroundColor: colour }]} />
      <View style={{ flex: 1 }}>
        <Text style={styles.activityProcess} numberOfLines={1}>{snap.process}</Text>
        {snap.domain ? <Text style={styles.activityDomain} numberOfLines={1}>{snap.domain}</Text> : null}
      </View>
      <Text style={styles.activityClass}>{snap.classification}</Text>
    </View>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.miniStat}>
      <Text style={styles.miniStatLabel}>{label}</Text>
      <Text style={styles.miniStatValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe:    { flex: 1, backgroundColor: Colors.bg },
  scroll:  { flex: 1 },
  content: { padding: 20, paddingBottom: 40 },

  header:      { marginBottom: 20 },
  title:       { fontSize: 28, fontWeight: '700', color: Colors.textPrimary, letterSpacing: -0.5 },
  lastUpdated: { fontSize: 12, color: Colors.textMuted, marginTop: 2 },

  notifBanner: {
    backgroundColor: 'rgba(255,165,0,0.12)',
    borderWidth:     1,
    borderColor:     Colors.amber,
    borderRadius:    12,
    padding:         14,
    marginBottom:    16,
  },
  notifTitle:   { fontSize: 14, fontWeight: '700', color: Colors.amber, marginBottom: 4 },
  notifBody:    { fontSize: 13, color: Colors.textPrimary, lineHeight: 18 },
  notifDismiss: { fontSize: 11, color: Colors.textMuted, marginTop: 6 },

  errorCard: {
    backgroundColor: 'rgba(255,76,76,0.1)',
    borderWidth:     1,
    borderColor:     Colors.red,
    borderRadius:    12,
    padding:         16,
    marginBottom:    16,
  },
  errorTitle: { fontSize: 14, fontWeight: '700', color: Colors.red, marginBottom: 4 },
  errorBody:  { fontSize: 13, color: Colors.textSecondary, lineHeight: 18 },

  statStrip: {
    flexDirection:  'row',
    backgroundColor: Colors.surface,
    borderRadius:    12,
    borderWidth:     1,
    borderColor:     Colors.border,
    padding:         14,
    marginBottom:    16,
    gap:             8,
  },
  miniStat:      { flex: 1, alignItems: 'center' },
  miniStatLabel: { fontSize: 10, color: Colors.textMuted, marginBottom: 3, textTransform: 'uppercase' },
  miniStatValue: { fontSize: 13, fontWeight: '600', color: Colors.textPrimary },

  section:      { marginTop: 8 },
  sectionTitle: {
    fontSize: 11, fontWeight: '600', color: Colors.textMuted,
    textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12,
  },

  activityRow:     { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 12 },
  activityDot:     { width: 9, height: 9, borderRadius: 5 },
  activityProcess: { fontSize: 14, color: Colors.textPrimary, fontWeight: '500' },
  activityDomain:  { fontSize: 12, color: Colors.textSecondary },
  activityClass:   { fontSize: 11, color: Colors.textMuted },

  emptyState:   { alignItems: 'center', marginTop: 48 },
  emptyText:    { fontSize: 16, color: Colors.textSecondary, fontWeight: '500' },
  emptySubtext: { fontSize: 13, color: Colors.textMuted, textAlign: 'center', marginTop: 8, lineHeight: 18 },
});
