/**
 * MARK III — Insights Screen (Phase 7: Cognitive Engine)
 *
 * Shows:
 *   • Today's focus score
 *   • Current cognitive context (task + state + suggestion)
 *   • Prioritised recommendations
 *   • 24-hour productivity timeline
 *   • Weekly focus trend
 */

import React, { useState } from 'react';
import {
  View, Text, ScrollView, RefreshControl,
  TouchableOpacity, StyleSheet,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useQueryClient } from '@tanstack/react-query';

import { Colors } from '@/constants/Colors';
import {
  useCognitiveContext, useRecommendations,
  useDailyReport, useWeeklyReport,
} from '@/hooks/useServerStatus';
import { useServerStatus } from '@/hooks/useServerStatus';
import { FocusScore } from '@/components/FocusScore';
import { RecommendationCard } from '@/components/RecommendationCard';
import { ProductivityTimeline } from '@/components/ProductivityTimeline';

const STATE_COLOURS: Record<string, string> = {
  software_development: Colors.green,
  career_development:   Colors.blue,
  research:             Colors.blue,
  communication:        '#A855F7',
  administrative:       Colors.amber,
  distraction:          Colors.red,
  entertainment:        Colors.red,
  break:                Colors.textMuted,
  idle:                 Colors.textMuted,
  unknown:              Colors.textMuted,
};

const TREND_ICON: Record<string, string> = {
  improving:          '↑',
  declining:          '↓',
  stable:             '→',
  insufficient_data:  '–',
};

const TREND_COLOUR: Record<string, string> = {
  improving:         Colors.green,
  declining:         Colors.red,
  stable:            Colors.amber,
  insufficient_data: Colors.textMuted,
};

export default function InsightsScreen() {
  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);

  // Get device ID from live server status
  const { data: status } = useServerStatus();
  const deviceId = status?.recent_snapshots[0]?.device_id ?? null;

  const { data: ctx,    isLoading: ctxLoading }    = useCognitiveContext(deviceId);
  const { data: recs,   isLoading: recsLoading }   = useRecommendations(deviceId);
  const { data: daily,  isLoading: dailyLoading }  = useDailyReport(deviceId);
  const { data: weekly, isLoading: weeklyLoading } = useWeeklyReport(deviceId);

  const isLoading = ctxLoading || recsLoading || dailyLoading || weeklyLoading;

  const onRefresh = async () => {
    setRefreshing(true);
    await queryClient.invalidateQueries({ queryKey: ['cognitiveContext'] });
    await queryClient.invalidateQueries({ queryKey: ['recommendations'] });
    await queryClient.invalidateQueries({ queryKey: ['dailyReport'] });
    await queryClient.invalidateQueries({ queryKey: ['weeklyReport'] });
    setRefreshing(false);
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.green} />
        }
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.title}>Insights</Text>
          <Text style={styles.subtitle}>{new Date().toLocaleDateString('en-AU', { weekday: 'long', day: 'numeric', month: 'long' })}</Text>
        </View>

        {/* Focus Score */}
        {daily ? (
          <FocusScore
            score={daily.focus_score}
            sublabel={`${Math.round(daily.productive_minutes)}m productive · ${Math.round(daily.distraction_minutes)}m distracted`}
          />
        ) : (
          <View style={styles.placeholder}>
            <Text style={styles.placeholderText}>{dailyLoading ? 'Calculating focus score…' : 'No data yet today.'}</Text>
          </View>
        )}

        {/* Current Context */}
        {ctx && (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>CURRENT CONTEXT</Text>
            <View style={styles.contextRow}>
              <View style={[styles.stateDot, { backgroundColor: STATE_COLOURS[ctx.productivity_state] ?? Colors.textMuted }]} />
              <Text style={styles.taskText}>{ctx.current_task}</Text>
              <Text style={styles.confidenceText}>{Math.round(ctx.confidence * 100)}%</Text>
            </View>
            <Text style={styles.suggestionText}>{ctx.suggested_action}</Text>
            <View style={styles.metaRow}>
              <MetaChip label="App"    value={ctx.dominant_app} />
              <MetaChip label="Class"  value={ctx.dominant_classification} />
              <MetaChip label="Block"  value={ctx.is_work_block ? 'Work' : 'Free'} highlight={ctx.is_work_block} />
            </View>
          </View>
        )}

        {/* Recommendations */}
        {recs && recs.recommendations.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>RECOMMENDATIONS</Text>
            {recs.recommendations.map((item, i) => (
              <RecommendationCard key={i} item={item} />
            ))}
          </View>
        )}

        {/* Productivity Timeline */}
        {daily && daily.hourly_breakdown && (
          <ProductivityTimeline hourlyBreakdown={daily.hourly_breakdown} />
        )}

        {/* Top Activities Today */}
        {daily && daily.major_activities.length > 0 && (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>TODAY'S ACTIVITIES</Text>
            {daily.major_activities.map((a, i) => (
              <View key={i} style={styles.activityRow}>
                <View style={[styles.activityDot, { backgroundColor: a.colour ?? Colors.textMuted }]} />
                <Text style={styles.activityLabel}>{a.classification}</Text>
                <Text style={styles.activityMins}>{Math.round(a.minutes)}m</Text>
              </View>
            ))}
          </View>
        )}

        {/* Weekly Review */}
        {weekly && (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>THIS WEEK</Text>

            {/* Week score + trend */}
            <View style={styles.weekHeader}>
              <View>
                <Text style={styles.weekScore}>{weekly.focus_score}%</Text>
                <Text style={styles.weekScoreLabel}>avg focus score</Text>
              </View>
              <View style={styles.trendBadge}>
                <Text style={[styles.trendIcon, { color: TREND_COLOUR[weekly.productivity_trend] ?? Colors.textMuted }]}>
                  {TREND_ICON[weekly.productivity_trend] ?? '–'}
                </Text>
                <Text style={[styles.trendLabel, { color: TREND_COLOUR[weekly.productivity_trend] ?? Colors.textMuted }]}>
                  {weekly.productivity_trend.replace('_', ' ')}
                </Text>
              </View>
            </View>

            {/* Daily bar mini-chart */}
            <View style={styles.weekBars}>
              {weekly.daily_scores.map((day, i) => {
                const h = Math.max(3, (day.score / 100) * 48);
                const colour = day.score >= 70 ? Colors.green : day.score >= 45 ? Colors.amber : Colors.red;
                const label  = new Date(day.date + 'T12:00:00').toLocaleDateString('en-AU', { weekday: 'narrow' });
                return (
                  <View key={i} style={styles.weekBarCol}>
                    <View style={styles.weekBarTrack}>
                      <View style={[styles.weekBar, { height: h, backgroundColor: day.productive_minutes > 0 ? colour : Colors.border }]} />
                    </View>
                    <Text style={styles.weekBarLabel}>{label}</Text>
                  </View>
                );
              })}
            </View>

            {/* Suggestions */}
            {weekly.improvement_suggestions.map((s, i) => (
              <Text key={i} style={styles.suggestion}>· {s}</Text>
            ))}
          </View>
        )}

        {/* No device connected */}
        {!deviceId && !isLoading && (
          <View style={styles.emptyState}>
            <Text style={styles.emptyText}>No device connected.</Text>
            <Text style={styles.emptySubtext}>Open the Dashboard tab to confirm DESKTOP-OMJ0BL5 is online.</Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function MetaChip({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <View style={[styles.chip, highlight && styles.chipHighlight]}>
      <Text style={styles.chipLabel}>{label}</Text>
      <Text style={[styles.chipValue, highlight && { color: Colors.green }]} numberOfLines={1}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe:    { flex: 1, backgroundColor: Colors.bg },
  scroll:  { flex: 1 },
  content: { padding: 20, paddingBottom: 48 },

  header:   { marginBottom: 20 },
  title:    { fontSize: 28, fontWeight: '700', color: Colors.textPrimary, letterSpacing: -0.5 },
  subtitle: { fontSize: 13, color: Colors.textMuted, marginTop: 2 },

  sectionTitle: {
    fontSize:      10,
    fontWeight:    '600',
    color:         Colors.textMuted,
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginBottom:  12,
  },

  placeholder: {
    backgroundColor: Colors.surface,
    borderRadius:    12,
    borderWidth:     1,
    borderColor:     Colors.border,
    padding:         24,
    alignItems:      'center',
    marginBottom:    16,
  },
  placeholderText: { color: Colors.textSecondary, fontSize: 14 },

  card: {
    backgroundColor: Colors.surface,
    borderRadius:    12,
    borderWidth:     1,
    borderColor:     Colors.border,
    padding:         14,
    marginBottom:    16,
  },

  section: { marginBottom: 6 },

  contextRow:     { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 },
  stateDot:       { width: 10, height: 10, borderRadius: 5 },
  taskText:       { flex: 1, fontSize: 15, fontWeight: '600', color: Colors.textPrimary },
  confidenceText: { fontSize: 12, color: Colors.textMuted },
  suggestionText: { fontSize: 13, color: Colors.textSecondary, lineHeight: 18, marginBottom: 12 },

  metaRow: { flexDirection: 'row', gap: 8 },
  chip: {
    flex:            1,
    backgroundColor: Colors.bg,
    borderRadius:    8,
    borderWidth:     1,
    borderColor:     Colors.border,
    padding:         8,
    alignItems:      'center',
  },
  chipHighlight: { borderColor: Colors.green },
  chipLabel: { fontSize: 9, color: Colors.textMuted, textTransform: 'uppercase', letterSpacing: 0.5 },
  chipValue: { fontSize: 11, color: Colors.textPrimary, fontWeight: '500', marginTop: 2 },

  activityRow:  { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 },
  activityDot:  { width: 9, height: 9, borderRadius: 5 },
  activityLabel:{ flex: 1, fontSize: 13, color: Colors.textPrimary },
  activityMins: { fontSize: 12, color: Colors.textMuted },

  weekHeader:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 },
  weekScore:       { fontSize: 32, fontWeight: '700', color: Colors.textPrimary },
  weekScoreLabel:  { fontSize: 11, color: Colors.textMuted },
  trendBadge:      { alignItems: 'center' },
  trendIcon:       { fontSize: 24, fontWeight: '700' },
  trendLabel:      { fontSize: 10, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.5 },

  weekBars:    { flexDirection: 'row', gap: 6, marginBottom: 16, height: 64, alignItems: 'flex-end' },
  weekBarCol:  { flex: 1, alignItems: 'center' },
  weekBarTrack:{ height: 50, justifyContent: 'flex-end', marginBottom: 4 },
  weekBar:     { width: '100%', borderRadius: 3, minHeight: 3 },
  weekBarLabel:{ fontSize: 9, color: Colors.textMuted },

  suggestion: { fontSize: 12, color: Colors.textSecondary, lineHeight: 18, marginBottom: 4 },

  emptyState:   { alignItems: 'center', marginTop: 60 },
  emptyText:    { fontSize: 16, color: Colors.textSecondary, fontWeight: '500' },
  emptySubtext: { fontSize: 13, color: Colors.textMuted, textAlign: 'center', marginTop: 8, lineHeight: 18 },
});
