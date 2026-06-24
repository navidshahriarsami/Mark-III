/**
 * MARK III — AI Tab (Phase 9: AI Provider Layer)
 *
 * Sections:
 *   • Ask MARK   — free-form question input
 *   • Daily Brief — morning context briefing
 *   • Evening Review — end-of-day reflection
 *   • Weekly Review — AI performance synthesis
 *   • AI Insights — proactive pattern detection
 *   • Provider Status — health + cost visibility
 */

import React, { useState, useRef } from 'react';
import {
  View, Text, ScrollView, TextInput, TouchableOpacity,
  StyleSheet, ActivityIndicator, KeyboardAvoidingView,
  Platform, RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useQueryClient } from '@tanstack/react-query';

import { Colors } from '@/constants/Colors';
import { useServerStatus } from '@/hooks/useServerStatus';
import {
  useAIInsights, useDailyBrief, useEveningReview,
  useAIWeeklyReview, useProviderStatus,
} from '@/hooks/useServerStatus';
import { api } from '@/services/api';
import type { AIResponse } from '@/services/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Section = 'ask' | 'brief' | 'evening' | 'weekly' | 'insights' | 'status';

const SECTIONS: { key: Section; label: string; icon: string }[] = [
  { key: 'ask',      label: 'Ask MARK',  icon: '◎' },
  { key: 'brief',    label: 'Brief',     icon: '◈' },
  { key: 'evening',  label: 'Evening',   icon: '◉' },
  { key: 'weekly',   label: 'Weekly',    icon: '◇' },
  { key: 'insights', label: 'Insights',  icon: '⬡' },
  { key: 'status',   label: 'Providers', icon: '⚑' },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ProviderDot({ available, enabled }: { available: boolean; enabled: boolean }) {
  const colour = !enabled ? Colors.border
    : available ? Colors.green : Colors.red;
  return <View style={[styles.provDot, { backgroundColor: colour }]} />;
}

function AICard({
  result,
  loading,
  onRefresh,
  label,
}: {
  result: AIResponse | null | undefined;
  loading: boolean;
  onRefresh: () => void;
  label: string;
}) {
  if (loading) {
    return (
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{label}</Text>
        <View style={styles.loadingRow}>
          <ActivityIndicator color={Colors.green} size="small" />
          <Text style={styles.loadingText}>MARK III is reasoning…</Text>
        </View>
      </View>
    );
  }

  if (!result) {
    return (
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{label}</Text>
        <Text style={styles.emptyText}>No data. Tap refresh to generate.</Text>
        <TouchableOpacity style={styles.refreshBtn} onPress={onRefresh}>
          <Text style={styles.refreshBtnText}>Generate</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const isError = result.text.startsWith('All providers failed') || result.provider === 'local' && result.model === 'rule-engine';

  return (
    <View style={styles.card}>
      <View style={styles.cardHeader}>
        <Text style={styles.sectionTitle}>{label}</Text>
        <TouchableOpacity onPress={onRefresh}>
          <Text style={styles.refreshIcon}>↺</Text>
        </TouchableOpacity>
      </View>

      {isError ? (
        <View style={styles.errorBox}>
          <Text style={styles.errorTitle}>No AI provider configured</Text>
          <Text style={styles.errorText}>
            Add ANTHROPIC_API_KEY or OPENAI_API_KEY to brain-server/.env and restart the server.
          </Text>
        </View>
      ) : (
        <Text style={styles.aiText}>{result.text}</Text>
      )}

      <View style={styles.metaRow}>
        {result.cached && <MetaBadge label="cached" colour={Colors.amber} />}
        {result.provider !== 'local' && (
          <MetaBadge label={result.provider} colour={Colors.blue} />
        )}
        {result.model && result.model !== 'rule-engine' && result.model !== 'none' && (
          <MetaBadge label={result.model.split('-').slice(0, 2).join('-')} colour={Colors.textMuted} />
        )}
        {result.cost_usd > 0 && (
          <MetaBadge label={`$${result.cost_usd.toFixed(5)}`} colour={Colors.textMuted} />
        )}
      </View>
    </View>
  );
}

function MetaBadge({ label, colour }: { label: string; colour: string }) {
  return (
    <View style={[styles.badge, { borderColor: colour + '55' }]}>
      <Text style={[styles.badgeText, { color: colour }]}>{label}</Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Ask MARK section
// ---------------------------------------------------------------------------

function AskMark({ deviceId }: { deviceId: string | null }) {
  const [question, setQuestion]     = useState('');
  const [loading, setLoading]       = useState(false);
  const [response, setResponse]     = useState<AIResponse | null>(null);
  const [history, setHistory]       = useState<{ q: string; r: AIResponse }[]>([]);

  const handleAsk = async () => {
    if (!deviceId || !question.trim() || loading) return;
    const q = question.trim();
    setLoading(true);
    setQuestion('');
    try {
      const resp = await api.askMark(deviceId, q);
      setResponse(resp);
      setHistory(h => [{ q, r: resp }, ...h].slice(0, 10));
    } catch (e: any) {
      setResponse({
        text:      `Error: ${e?.message ?? 'Network error'}`,
        cached:    false,
        task_type: 'error',
        provider:  'none',
        model:     '',
        cost_usd:  0,
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.sectionTitle}>ASK MARK</Text>
      <Text style={styles.askSubtitle}>Ask MARK III anything about your productivity, goals, or work.</Text>

      <View style={styles.inputRow}>
        <TextInput
          style={styles.askInput}
          placeholder="How was my week? What should I focus on?"
          placeholderTextColor={Colors.textMuted}
          value={question}
          onChangeText={setQuestion}
          onSubmitEditing={handleAsk}
          returnKeyType="send"
          multiline={false}
          editable={!loading}
        />
        <TouchableOpacity
          style={[styles.sendBtn, (!question.trim() || loading) && styles.sendBtnDisabled]}
          onPress={handleAsk}
          disabled={!question.trim() || loading || !deviceId}
        >
          {loading
            ? <ActivityIndicator size="small" color={Colors.bg} />
            : <Text style={styles.sendIcon}>↑</Text>
          }
        </TouchableOpacity>
      </View>

      {response && (
        <View style={styles.responseBox}>
          <Text style={styles.aiText}>{response.text}</Text>
          <View style={styles.metaRow}>
            {response.cached && <MetaBadge label="cached" colour={Colors.amber} />}
            <MetaBadge label={response.task_type.replace('_', ' ')} colour={Colors.blue} />
            {response.provider !== 'local' && response.provider !== 'none' && (
              <MetaBadge label={response.provider} colour={Colors.textMuted} />
            )}
          </View>
        </View>
      )}

      {/* Suggested questions */}
      {!response && !loading && (
        <View style={styles.suggestions}>
          {SUGGESTED_QUESTIONS.map((q, i) => (
            <TouchableOpacity
              key={i}
              style={styles.suggestion}
              onPress={() => setQuestion(q)}
            >
              <Text style={styles.suggestionText}>{q}</Text>
            </TouchableOpacity>
          ))}
        </View>
      )}
    </View>
  );
}

const SUGGESTED_QUESTIONS = [
  "What should I focus on today?",
  "How is my career goal progressing?",
  "What's my biggest productivity blocker?",
  "Give me a weekly summary.",
];

// ---------------------------------------------------------------------------
// Provider Status section
// ---------------------------------------------------------------------------

function ProviderStatusSection() {
  const { data: status, isLoading } = useProviderStatus();

  if (isLoading || !status) {
    return (
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>PROVIDER STATUS</Text>
        <ActivityIndicator color={Colors.green} />
      </View>
    );
  }

  return (
    <View style={styles.card}>
      <Text style={styles.sectionTitle}>PROVIDER STATUS</Text>

      {Object.entries(status.providers).map(([name, info]) => (
        <View key={name} style={styles.provRow}>
          <ProviderDot available={info.available} enabled={info.enabled} />
          <View style={{ flex: 1 }}>
            <Text style={styles.provName}>{name.toUpperCase()}</Text>
            {info.error && (
              <Text style={styles.provError} numberOfLines={1}>{info.error}</Text>
            )}
          </View>
          <View style={styles.provStats}>
            <Text style={styles.provStat}>{info.usage_30d.calls_30d} calls</Text>
            <Text style={styles.provStat}>${info.usage_30d.cost_usd_30d.toFixed(4)}</Text>
          </View>
        </View>
      ))}

      <View style={styles.divider} />
      <View style={styles.totalRow}>
        <Text style={styles.totalLabel}>All-time total</Text>
        <Text style={styles.totalValue}>
          ${status.totals.cost_usd_all_time.toFixed(4)}  ·  {status.totals.calls_all_time} calls
        </Text>
      </View>

      <Text style={styles.provHint}>
        Set ANTHROPIC_API_KEY or OPENAI_API_KEY in brain-server/.env to enable AI features.
        Preferred provider: {status.preferred_provider}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Main screen
// ---------------------------------------------------------------------------

export default function AIScreen() {
  const queryClient = useQueryClient();
  const [activeSection, setActiveSection] = useState<Section>('ask');
  const [refreshing, setRefreshing]       = useState(false);

  const { data: serverStatus } = useServerStatus();
  const deviceId = serverStatus?.recent_snapshots[0]?.device_id ?? null;

  const { data: insights,  isLoading: insightsLoading  } = useAIInsights(deviceId);
  const { data: brief,     isLoading: briefLoading      } = useDailyBrief(deviceId);
  const { data: evening,   isLoading: eveningLoading    } = useEveningReview(deviceId);
  const { data: weeklyAI,  isLoading: weeklyLoading     } = useAIWeeklyReview(deviceId);

  const invalidate = (key: string) => queryClient.invalidateQueries({ queryKey: [key] });

  const onRefresh = async () => {
    setRefreshing(true);
    await queryClient.invalidateQueries({ queryKey: ['aiInsights'] });
    await queryClient.invalidateQueries({ queryKey: ['dailyBrief'] });
    await queryClient.invalidateQueries({ queryKey: ['eveningReview'] });
    await queryClient.invalidateQueries({ queryKey: ['aiWeeklyReview'] });
    setRefreshing(false);
  };

  return (
    <SafeAreaView style={styles.safe}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.title}>MARK III</Text>
        <Text style={styles.subtitle}>AI Reasoning Core</Text>
      </View>

      {/* Section tabs */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.tabBar}
        contentContainerStyle={styles.tabBarContent}
      >
        {SECTIONS.map(s => (
          <TouchableOpacity
            key={s.key}
            style={[styles.tab, activeSection === s.key && styles.tabActive]}
            onPress={() => setActiveSection(s.key)}
          >
            <Text style={[styles.tabIcon, activeSection === s.key && styles.tabIconActive]}>
              {s.icon}
            </Text>
            <Text style={[styles.tabLabel, activeSection === s.key && styles.tabLabelActive]}>
              {s.label}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Content */}
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.content}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.green} />
          }
        >
          {activeSection === 'ask' && (
            <AskMark deviceId={deviceId} />
          )}

          {activeSection === 'brief' && (
            <AICard
              result={brief}
              loading={briefLoading}
              onRefresh={() => { invalidate('dailyBrief'); }}
              label="DAILY BRIEF"
            />
          )}

          {activeSection === 'evening' && (
            <AICard
              result={evening}
              loading={eveningLoading}
              onRefresh={() => { invalidate('eveningReview'); }}
              label="EVENING REVIEW"
            />
          )}

          {activeSection === 'weekly' && (
            <AICard
              result={weeklyAI}
              loading={weeklyLoading}
              onRefresh={() => { invalidate('aiWeeklyReview'); }}
              label="AI WEEKLY REVIEW"
            />
          )}

          {activeSection === 'insights' && (
            <AICard
              result={insights}
              loading={insightsLoading}
              onRefresh={() => { invalidate('aiInsights'); }}
              label="AI INSIGHTS"
            />
          )}

          {activeSection === 'status' && (
            <ProviderStatusSection />
          )}

          {!deviceId && (
            <View style={styles.noDevice}>
              <Text style={styles.noDeviceText}>No device connected.</Text>
              <Text style={styles.noDeviceSub}>Open Dashboard to bring DESKTOP-OMJ0BL5 online.</Text>
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:    { flex: 1, backgroundColor: Colors.bg },
  scroll:  { flex: 1 },
  content: { padding: 16, paddingBottom: 48 },

  header: {
    paddingHorizontal: 20,
    paddingTop:        12,
    paddingBottom:     8,
  },
  title:    { fontSize: 22, fontWeight: '700', color: Colors.textPrimary, letterSpacing: -0.3 },
  subtitle: { fontSize: 12, color: Colors.textMuted, marginTop: 2 },

  tabBar:        { flexGrow: 0, paddingBottom: 8 },
  tabBarContent: { paddingHorizontal: 16, gap: 8 },
  tab: {
    alignItems:      'center',
    paddingHorizontal: 14,
    paddingVertical:  6,
    borderRadius:    8,
    borderWidth:     1,
    borderColor:     Colors.border,
    backgroundColor: Colors.surface,
    flexDirection:   'row',
    gap:             6,
  },
  tabActive:      { borderColor: Colors.green, backgroundColor: Colors.green + '15' },
  tabIcon:        { fontSize: 14, color: Colors.textMuted },
  tabIconActive:  { color: Colors.green },
  tabLabel:       { fontSize: 12, color: Colors.textMuted, fontWeight: '500' },
  tabLabelActive: { color: Colors.green, fontWeight: '600' },

  card: {
    backgroundColor: Colors.surface,
    borderRadius:    12,
    borderWidth:     1,
    borderColor:     Colors.border,
    padding:         16,
    marginBottom:    16,
    gap:             12,
  },
  cardHeader: {
    flexDirection:  'row',
    justifyContent: 'space-between',
    alignItems:     'center',
  },
  sectionTitle: {
    fontSize:      10,
    fontWeight:    '700',
    color:         Colors.textMuted,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
  },
  refreshIcon: { fontSize: 18, color: Colors.textMuted },

  aiText: {
    fontSize:   14,
    color:      Colors.textPrimary,
    lineHeight: 22,
  },

  metaRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  badge: {
    borderWidth:     1,
    borderRadius:    4,
    paddingHorizontal: 6,
    paddingVertical:   2,
  },
  badgeText: { fontSize: 10, fontWeight: '500' },

  loadingRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  loadingText:{ fontSize: 13, color: Colors.textSecondary },

  emptyText:  { fontSize: 13, color: Colors.textSecondary },
  refreshBtn: {
    alignSelf:       'flex-start',
    backgroundColor: Colors.green + '22',
    borderRadius:    6,
    paddingHorizontal: 12,
    paddingVertical:   6,
    borderWidth:     1,
    borderColor:     Colors.green + '44',
  },
  refreshBtnText: { fontSize: 12, color: Colors.green, fontWeight: '600' },

  errorBox: {
    backgroundColor: Colors.red + '11',
    borderRadius:    8,
    borderWidth:     1,
    borderColor:     Colors.red + '33',
    padding:         12,
    gap:             4,
  },
  errorTitle: { fontSize: 13, fontWeight: '600', color: Colors.red },
  errorText:  { fontSize: 12, color: Colors.textSecondary, lineHeight: 18 },

  // Ask MARK
  askSubtitle: { fontSize: 12, color: Colors.textMuted },
  inputRow:    { flexDirection: 'row', gap: 8, alignItems: 'center' },
  askInput: {
    flex:            1,
    backgroundColor: Colors.bg,
    borderRadius:    10,
    borderWidth:     1,
    borderColor:     Colors.border,
    paddingHorizontal: 12,
    paddingVertical:   10,
    fontSize:        14,
    color:           Colors.textPrimary,
  },
  sendBtn: {
    width:           40,
    height:          40,
    borderRadius:    20,
    backgroundColor: Colors.green,
    alignItems:      'center',
    justifyContent:  'center',
  },
  sendBtnDisabled: { backgroundColor: Colors.border },
  sendIcon:        { fontSize: 18, color: Colors.bg, fontWeight: '700' },
  responseBox: {
    backgroundColor: Colors.bg,
    borderRadius:    8,
    borderWidth:     1,
    borderColor:     Colors.border,
    padding:         12,
    gap:             8,
  },
  suggestions:    { gap: 6 },
  suggestion: {
    backgroundColor: Colors.bg,
    borderRadius:    8,
    borderWidth:     1,
    borderColor:     Colors.border,
    paddingHorizontal: 12,
    paddingVertical:   8,
  },
  suggestionText: { fontSize: 13, color: Colors.textSecondary },

  // Provider Status
  provRow: {
    flexDirection: 'row',
    alignItems:    'center',
    gap:           10,
    paddingVertical: 6,
  },
  provDot:   { width: 9, height: 9, borderRadius: 5 },
  provName:  { fontSize: 12, fontWeight: '700', color: Colors.textPrimary, letterSpacing: 0.5 },
  provError: { fontSize: 10, color: Colors.textMuted },
  provStats: { alignItems: 'flex-end', gap: 1 },
  provStat:  { fontSize: 10, color: Colors.textMuted },
  divider:   { height: 1, backgroundColor: Colors.border, marginVertical: 4 },
  totalRow:  { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  totalLabel:{ fontSize: 11, color: Colors.textMuted },
  totalValue:{ fontSize: 11, color: Colors.textPrimary, fontWeight: '600' },
  provHint: {
    fontSize:   11,
    color:      Colors.textMuted,
    lineHeight: 16,
    marginTop:  4,
  },

  noDevice: { alignItems: 'center', marginTop: 60 },
  noDeviceText: { fontSize: 15, color: Colors.textSecondary, fontWeight: '500' },
  noDeviceSub:  { fontSize: 12, color: Colors.textMuted, marginTop: 6, textAlign: 'center' },
});
