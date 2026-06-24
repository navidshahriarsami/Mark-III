import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors } from '@/constants/Colors';
import type { BreachRecord } from '@/services/api';

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString('en-AU', {
    weekday: 'short', hour: '2-digit', minute: '2-digit',
  });
}

export function BreachCard({ breach }: { breach: BreachRecord }) {
  return (
    <View style={styles.card}>
      <View style={styles.topRow}>
        <View style={styles.keywordBadge}>
          <Text style={styles.keywordText}>{breach.keyword}</Text>
        </View>
        <Text style={styles.duration}>{Math.round(breach.duration_min)} min</Text>
      </View>

      <View style={styles.metaRow}>
        <Text style={styles.meta}>{breach.process_name}</Text>
        {breach.active_domain ? (
          <Text style={styles.meta}> · {breach.active_domain}</Text>
        ) : null}
      </View>

      <View style={styles.bottomRow}>
        <Text style={styles.ts}>{fmtDate(breach.ts)}</Text>
        <View style={[styles.notifDot, { backgroundColor: breach.notif_sent ? Colors.green : Colors.textMuted }]}>
          <Text style={styles.notifLabel}>
            {breach.notif_sent ? breach.notif_provider : 'no notif'}
          </Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Colors.surface,
    borderRadius:    12,
    borderWidth:     1,
    borderColor:     Colors.border,
    borderLeftWidth: 3,
    borderLeftColor: Colors.red,
    padding:         14,
    marginBottom:    10,
  },
  topRow: {
    flexDirection:  'row',
    justifyContent: 'space-between',
    alignItems:     'center',
    marginBottom:   6,
  },
  keywordBadge: {
    backgroundColor: 'rgba(255,76,76,0.15)',
    borderRadius:    6,
    paddingHorizontal: 8,
    paddingVertical:   3,
  },
  keywordText: { color: Colors.red, fontSize: 13, fontWeight: '600' },
  duration:    { color: Colors.textSecondary, fontSize: 13, fontWeight: '500' },
  metaRow:     { flexDirection: 'row', flexWrap: 'wrap', marginBottom: 8 },
  meta:        { color: Colors.textSecondary, fontSize: 12 },
  bottomRow:   { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  ts:          { color: Colors.textMuted, fontSize: 11 },
  notifDot: {
    borderRadius:    10,
    paddingHorizontal: 7,
    paddingVertical:   2,
    backgroundColor: 'rgba(0,200,150,0.12)',
  },
  notifLabel: { color: Colors.textMuted, fontSize: 10 },
});
