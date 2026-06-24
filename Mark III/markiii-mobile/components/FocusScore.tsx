import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors } from '@/constants/Colors';

interface Props {
  score:      number;   // 0–100
  label?:     string;
  sublabel?:  string;
}

function scoreColour(score: number): string {
  if (score >= 75) return Colors.green;
  if (score >= 50) return Colors.amber;
  return Colors.red;
}

export function FocusScore({ score, label = "Today's Focus", sublabel }: Props) {
  const colour = scoreColour(score);

  return (
    <View style={styles.card}>
      <View style={[styles.ring, { borderColor: colour }]}>
        <Text style={[styles.scoreText, { color: colour }]}>{Math.round(score)}</Text>
        <Text style={[styles.pct, { color: colour }]}>%</Text>
      </View>
      <Text style={styles.label}>{label}</Text>
      {sublabel ? <Text style={styles.sublabel}>{sublabel}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    alignItems:      'center',
    backgroundColor: Colors.surface,
    borderRadius:    16,
    borderWidth:     1,
    borderColor:     Colors.border,
    padding:         24,
    marginBottom:    16,
  },
  ring: {
    width:        110,
    height:       110,
    borderRadius: 55,
    borderWidth:  6,
    alignItems:   'center',
    justifyContent: 'center',
    flexDirection:  'row',
    marginBottom:   14,
  },
  scoreText: { fontSize: 38, fontWeight: '700', letterSpacing: -1 },
  pct:       { fontSize: 18, fontWeight: '600', marginTop: 10 },
  label:     { fontSize: 13, color: Colors.textMuted, textTransform: 'uppercase', letterSpacing: 1 },
  sublabel:  { fontSize: 12, color: Colors.textSecondary, marginTop: 4, textAlign: 'center' },
});
