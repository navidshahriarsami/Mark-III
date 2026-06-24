import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors } from '@/constants/Colors';

type Variant = 'online' | 'offline' | 'syncing' | 'distraction' | 'unknown';

const CONFIG: Record<Variant, { label: string; dot: string; text: string }> = {
  online:      { label: 'Online',      dot: Colors.green,  text: Colors.green },
  offline:     { label: 'Offline',     dot: Colors.red,    text: Colors.red },
  syncing:     { label: 'Syncing',     dot: Colors.amber,  text: Colors.amber },
  distraction: { label: 'Distraction', dot: Colors.red,    text: Colors.red },
  unknown:     { label: 'Unknown',     dot: Colors.textMuted, text: Colors.textMuted },
};

export function StatusBadge({ variant }: { variant: Variant }) {
  const { label, dot, text } = CONFIG[variant];
  return (
    <View style={styles.row}>
      <View style={[styles.dot, { backgroundColor: dot }]} />
      <Text style={[styles.label, { color: text }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row:   { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot:   { width: 8, height: 8, borderRadius: 4 },
  label: { fontSize: 13, fontWeight: '500' },
});
