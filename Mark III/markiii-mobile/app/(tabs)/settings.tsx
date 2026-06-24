import React from 'react';
import { View, Text, ScrollView, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Colors } from '@/constants/Colors';
import { useMarkStore } from '@/store/useMarkStore';
import { Config } from '@/constants/Config';

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue} selectable numberOfLines={1}>{value}</Text>
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.card}>{children}</View>
    </View>
  );
}

export default function SettingsScreen() {
  const pushToken    = useMarkStore((s) => s.pushToken);
  const serverStatus = useMarkStore((s) => s.serverStatus);

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Settings</Text>

        <Section title="Connection">
          <Row label="Brain URL"     value={Config.BRAIN_URL} />
          <Row label="Poll interval" value={`${Config.POLL_INTERVAL_MS / 1000}s`} />
        </Section>

        <Section title="Push Notifications">
          <Row
            label="Expo Push Token"
            value={pushToken ? `${pushToken.slice(0, 28)}…` : 'Not registered'}
          />
          <Row
            label="Backend"
            value={serverStatus?.notification ?? '—'}
          />
        </Section>

        <Section title="Brain Server">
          <Row label="Database"    value={serverStatus?.database ?? '—'} />
          <Row label="Version"     value="0.5.0" />
          <Row label="Devices"     value={String(serverStatus?.devices_online ?? '—')} />
          <Row label="Breaches"    value={String(serverStatus?.breaches_total ?? '—')} />
        </Section>

        <Section title="About">
          <Row label="App version"  value="0.6.0" />
          <Row label="Build"        value="Phase 6 — React Native" />
        </Section>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:         { flex: 1, backgroundColor: Colors.bg },
  content:      { padding: 20, paddingBottom: 48 },
  title:        { fontSize: 28, fontWeight: '700', color: Colors.textPrimary, marginBottom: 24 },
  section:      { marginBottom: 24 },
  sectionTitle: {
    fontSize: 11, fontWeight: '600', color: Colors.textMuted,
    textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10,
  },
  card: {
    backgroundColor: Colors.surface,
    borderRadius:    12,
    borderWidth:     1,
    borderColor:     Colors.border,
    overflow:        'hidden',
  },
  row: {
    flexDirection:   'row',
    justifyContent:  'space-between',
    alignItems:      'center',
    paddingHorizontal: 16,
    paddingVertical:   13,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  rowLabel: { fontSize: 14, color: Colors.textSecondary },
  rowValue: { fontSize: 13, color: Colors.textPrimary, fontWeight: '500', maxWidth: '55%', textAlign: 'right' },
});
