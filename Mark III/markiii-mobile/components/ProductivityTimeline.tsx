/**
 * Horizontal 24-hour timeline.
 * Each hour is one thin coloured bar segment — active hours glow their
 * dominant classification colour; inactive hours are the surface colour.
 */
import React from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { Colors } from '@/constants/Colors';
import type { HourlyBucket } from '@/services/api';

interface Props {
  hourlyBreakdown: HourlyBucket[];
}

function fmt(h: number): string {
  if (h === 0)  return '12a';
  if (h < 12)   return `${h}a`;
  if (h === 12) return '12p';
  return `${h - 12}p`;
}

export function ProductivityTimeline({ hourlyBreakdown }: Props) {
  const now         = new Date().getHours();
  const maxMinutes  = Math.max(...hourlyBreakdown.map(b => b.minutes), 1);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>TODAY'S TIMELINE</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.scroll}>
        <View style={styles.bars}>
          {hourlyBreakdown.map(bucket => {
            const height  = bucket.minutes > 0
              ? Math.max(8, (bucket.minutes / maxMinutes) * 56)
              : 4;
            const colour  = bucket.colour ?? Colors.border;
            const isPast  = bucket.hour <= now;
            const isCurrent = bucket.hour === now;

            return (
              <View key={bucket.hour} style={styles.column}>
                <View style={styles.barTrack}>
                  <View
                    style={[
                      styles.bar,
                      {
                        height,
                        backgroundColor: bucket.minutes > 0 ? colour : Colors.border,
                        opacity:         isPast ? 1.0 : 0.25,
                        borderWidth:     isCurrent ? 1 : 0,
                        borderColor:     Colors.textPrimary,
                      },
                    ]}
                  />
                </View>
                <Text style={[styles.hourLabel, isCurrent && styles.hourLabelCurrent]}>
                  {fmt(bucket.hour)}
                </Text>
              </View>
            );
          })}
        </View>
      </ScrollView>

      {/* Legend */}
      <View style={styles.legend}>
        {Object.entries(LEGEND_ITEMS).map(([cls, colour]) => (
          <View key={cls} style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: colour }]} />
            <Text style={styles.legendLabel}>{cls}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const LEGEND_ITEMS: Record<string, string> = {
  ide:           '#00C896',
  terminal:      '#888888',
  browser:       '#4A9EFF',
  distraction:   '#FF4C4C',
  communication: '#A855F7',
};

const styles = StyleSheet.create({
  container: {
    backgroundColor: Colors.surface,
    borderRadius:    12,
    borderWidth:     1,
    borderColor:     Colors.border,
    padding:         14,
    marginBottom:    16,
  },
  title: {
    fontSize:        10,
    fontWeight:      '600',
    color:           Colors.textMuted,
    letterSpacing:   1,
    textTransform:   'uppercase',
    marginBottom:    12,
  },
  scroll: { marginBottom: 10 },
  bars:   { flexDirection: 'row', alignItems: 'flex-end', gap: 3, height: 80 },
  column: { alignItems: 'center', width: 22 },
  barTrack: {
    height:          60,
    justifyContent:  'flex-end',
    marginBottom:    4,
  },
  bar: {
    width:        16,
    borderRadius: 3,
    minHeight:    4,
  },
  hourLabel: {
    fontSize:  8,
    color:     Colors.textMuted,
    textAlign: 'center',
  },
  hourLabelCurrent: { color: Colors.textPrimary, fontWeight: '700' },

  legend:     { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 4 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  legendDot:  { width: 7, height: 7, borderRadius: 4 },
  legendLabel:{ fontSize: 10, color: Colors.textMuted },
});
