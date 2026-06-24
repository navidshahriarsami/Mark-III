import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors } from '@/constants/Colors';
import type { Recommendation } from '@/services/api';

const CATEGORY_ICONS: Record<string, string> = {
  focus:  '◎',
  break:  '◌',
  career: '◈',
  health: '◉',
  admin:  '◇',
};

const PRIORITY_COLOURS: Record<number, string> = {
  2: Colors.red,
  1: Colors.amber,
  0: Colors.green,
};

interface Props {
  item: Recommendation;
}

export function RecommendationCard({ item }: Props) {
  const icon    = CATEGORY_ICONS[item.category] ?? '○';
  const colour  = PRIORITY_COLOURS[item.priority] ?? Colors.textMuted;

  return (
    <View style={[styles.card, { borderLeftColor: colour }]}>
      <Text style={[styles.icon, { color: colour }]}>{icon}</Text>
      <View style={{ flex: 1 }}>
        <Text style={styles.text}>{item.text}</Text>
        <Text style={[styles.meta, { color: colour }]}>
          {item.category.toUpperCase()}
          {item.priority === 2 ? '  ·  HIGH PRIORITY' : item.priority === 1 ? '  ·  MEDIUM' : ''}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection:   'row',
    alignItems:      'flex-start',
    gap:             12,
    backgroundColor: Colors.surface,
    borderRadius:    12,
    borderWidth:     1,
    borderColor:     Colors.border,
    borderLeftWidth: 3,
    padding:         14,
    marginBottom:    10,
  },
  icon: { fontSize: 18, marginTop: 1 },
  text: { fontSize: 13, color: Colors.textPrimary, lineHeight: 19, marginBottom: 4 },
  meta: { fontSize: 10, fontWeight: '600', letterSpacing: 0.5 },
});
