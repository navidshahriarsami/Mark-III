/**
 * MARK III — Sudo Approval Modal
 *
 * Renders over the dashboard when one or more privileged commands are pending.
 * The user must explicitly tap Approve or Deny — no accidental dismissal.
 */

import React, { useState } from 'react';
import {
  Modal, View, Text, TouchableOpacity,
  ScrollView, StyleSheet, ActivityIndicator,
} from 'react-native';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/services/api';
import { useMarkStore } from '@/store/useMarkStore';
import { Colors } from '@/constants/Colors';
import type { PendingCommand } from '@/services/api';

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' });
}

interface CommandRowProps {
  command:  PendingCommand;
  onDecide: (id: string, verdict: 'approved' | 'denied') => void;
  busy:     boolean;
}

function CommandRow({ command, onDecide, busy }: CommandRowProps) {
  return (
    <View style={styles.commandRow}>
      <View style={styles.commandHeader}>
        <Text style={styles.requester}>{command.requester}</Text>
        <Text style={styles.commandTs}>{fmtTime(command.queued_at)}</Text>
      </View>
      <View style={styles.commandBox}>
        <Text style={styles.commandRaw} selectable>{command.raw}</Text>
      </View>
      <View style={styles.actionRow}>
        <TouchableOpacity
          style={[styles.btn, styles.denyBtn]}
          onPress={() => onDecide(command.id, 'denied')}
          disabled={busy}
        >
          <Text style={styles.denyText}>Deny</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.btn, styles.approveBtn]}
          onPress={() => onDecide(command.id, 'approved')}
          disabled={busy}
        >
          {busy ? (
            <ActivityIndicator color={Colors.bg} size="small" />
          ) : (
            <Text style={styles.approveText}>Approve</Text>
          )}
        </TouchableOpacity>
      </View>
    </View>
  );
}

export function SudoApprovalModal() {
  const pendingCommands = useMarkStore((s) => s.pendingCommands);
  const removeCommand   = useMarkStore((s) => s.removeCommand);
  const queryClient     = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: ({ id, verdict }: { id: string; verdict: 'approved' | 'denied' }) =>
      api.setCommandStatus(id, verdict),
    onMutate:  ({ id }) => setBusyId(id),
    onSuccess: (_, { id }) => {
      removeCommand(id);
      queryClient.invalidateQueries({ queryKey: ['pendingCommands'] });
    },
    onSettled: () => setBusyId(null),
  });

  if (pendingCommands.length === 0) return null;

  return (
    <Modal transparent animationType="fade" visible statusBarTranslucent>
      <View style={styles.overlay}>
        <View style={styles.sheet}>
          <View style={styles.sheetHeader}>
            <View style={styles.warningBadge}>
              <Text style={styles.warningIcon}>⚠</Text>
              <Text style={styles.warningText}>Privileged Command Approval</Text>
            </View>
            <Text style={styles.subheading}>
              MARK III is requesting elevated shell access.{'\n'}
              Review each command carefully before approving.
            </Text>
          </View>

          <ScrollView style={styles.list} showsVerticalScrollIndicator={false}>
            {pendingCommands.map((cmd) => (
              <CommandRow
                key={cmd.id}
                command={cmd}
                onDecide={(id, verdict) => mutation.mutate({ id, verdict })}
                busy={busyId === cmd.id}
              />
            ))}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex:            1,
    backgroundColor: 'rgba(0,0,0,0.75)',
    justifyContent:  'flex-end',
  },
  sheet: {
    backgroundColor: Colors.surfaceRaised,
    borderTopLeftRadius:  24,
    borderTopRightRadius: 24,
    paddingTop:    24,
    paddingBottom: 40,
    maxHeight:     '85%',
  },
  sheetHeader:  { paddingHorizontal: 20, marginBottom: 16 },
  warningBadge: {
    flexDirection:  'row',
    alignItems:     'center',
    gap:            8,
    marginBottom:   10,
  },
  warningIcon: { fontSize: 18, color: Colors.amber },
  warningText: { fontSize: 16, fontWeight: '700', color: Colors.textPrimary },
  subheading:  { fontSize: 13, color: Colors.textSecondary, lineHeight: 19 },
  list:        { paddingHorizontal: 20 },
  commandRow: {
    borderWidth:   1,
    borderColor:   Colors.border,
    borderRadius:  12,
    padding:       14,
    marginBottom:  12,
  },
  commandHeader: {
    flexDirection:  'row',
    justifyContent: 'space-between',
    marginBottom:   8,
  },
  requester:  { fontSize: 12, color: Colors.textMuted, fontWeight: '500' },
  commandTs:  { fontSize: 12, color: Colors.textMuted },
  commandBox: {
    backgroundColor: Colors.bg,
    borderRadius:    8,
    padding:         10,
    marginBottom:    12,
  },
  commandRaw: { fontFamily: 'monospace', fontSize: 13, color: Colors.amber },
  actionRow:  { flexDirection: 'row', gap: 10 },
  btn:        { flex: 1, paddingVertical: 12, borderRadius: 10, alignItems: 'center' },
  denyBtn:    { backgroundColor: 'rgba(255,76,76,0.15)', borderWidth: 1, borderColor: Colors.red },
  denyText:   { color: Colors.red, fontWeight: '600', fontSize: 14 },
  approveBtn: { backgroundColor: Colors.green },
  approveText:{ color: Colors.bg, fontWeight: '700', fontSize: 14 },
});
