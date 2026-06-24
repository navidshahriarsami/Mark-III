/**
 * MARK III — Memory Screen (Phase 8: Memory Engine)
 *
 * Shows:
 *   • Active long-term goals with progress rings
 *   • Active/planning projects linked to goals
 *   • Recent memories (pinned high-importance first)
 *   • Search bar across all memory content
 */

import React, { useState, useCallback } from 'react';
import {
  View, Text, ScrollView, RefreshControl, TextInput,
  TouchableOpacity, StyleSheet, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useQueryClient } from '@tanstack/react-query';

import { Colors } from '@/constants/Colors';
import { useServerStatus } from '@/hooks/useServerStatus';
import {
  useGoals, useProjects, useMemories, useMemorySearch,
} from '@/hooks/useServerStatus';
import type { LongTermGoal, Project, Memory } from '@/services/api';

// ---------------------------------------------------------------------------
// Category colours
// ---------------------------------------------------------------------------

const CATEGORY_COLOUR: Record<string, string> = {
  career:    Colors.blue,
  research:  '#22D3EE',
  health:    '#4ADE80',
  financial: Colors.amber,
  learning:  '#A855F7',
  personal:  Colors.textMuted,
};

const TYPE_ICON: Record<string, string> = {
  event:        '◎',
  decision:     '◈',
  instruction:  '◉',
  achievement:  '★',
  conversation: '◌',
  note:         '◇',
};

const STATUS_COLOUR: Record<string, string> = {
  active:    Colors.green,
  planning:  Colors.amber,
  paused:    Colors.textMuted,
  completed: Colors.blue,
  abandoned: Colors.red,
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ProgressRing({ progress, colour }: { progress: number; colour: string }) {
  const size   = 36;
  const stroke = 3;
  const r      = (size - stroke) / 2;
  const circ   = 2 * Math.PI * r;
  const offset = circ - (progress / 100) * circ;

  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      {/* SVG unavailable in RN without library — use a simple border circle */}
      <View style={{
        width: size, height: size, borderRadius: size / 2,
        borderWidth: stroke, borderColor: colour,
        alignItems: 'center', justifyContent: 'center',
        backgroundColor: 'transparent',
      }}>
        <Text style={{ fontSize: 9, fontWeight: '700', color: colour }}>{progress}%</Text>
      </View>
    </View>
  );
}

function GoalCard({ goal }: { goal: LongTermGoal }) {
  const colour = CATEGORY_COLOUR[goal.category] ?? Colors.textMuted;
  const daysLeft = goal.target_date
    ? Math.ceil((new Date(goal.target_date + 'T00:00:00').getTime() - Date.now()) / 86400000)
    : null;

  return (
    <View style={[styles.card, { borderLeftWidth: 3, borderLeftColor: colour }]}>
      <View style={styles.cardRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.cardTitle} numberOfLines={2}>{goal.title}</Text>
          <View style={styles.tagRow}>
            <View style={[styles.tag, { backgroundColor: colour + '22' }]}>
              <Text style={[styles.tagText, { color: colour }]}>{goal.category}</Text>
            </View>
            {daysLeft !== null && (
              <View style={[styles.tag, { backgroundColor: daysLeft <= 7 ? Colors.red + '22' : Colors.border }]}>
                <Text style={[styles.tagText, { color: daysLeft <= 7 ? Colors.red : Colors.textMuted }]}>
                  {daysLeft > 0 ? `${daysLeft}d left` : 'overdue'}
                </Text>
              </View>
            )}
          </View>
        </View>
        <ProgressRing progress={goal.progress} colour={colour} />
      </View>
      {goal.description ? (
        <Text style={styles.cardDesc} numberOfLines={2}>{goal.description}</Text>
      ) : null}
    </View>
  );
}

function ProjectCard({ project, goals }: { project: Project; goals: LongTermGoal[] }) {
  const statusColour = STATUS_COLOUR[project.status] ?? Colors.textMuted;
  const linkedGoal   = goals.find(g => g.id === project.goal_id);
  const daysLeft     = project.deadline
    ? Math.ceil((new Date(project.deadline + 'T00:00:00').getTime() - Date.now()) / 86400000)
    : null;

  return (
    <View style={[styles.card, { paddingVertical: 10 }]}>
      <View style={styles.cardRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.cardTitle} numberOfLines={1}>{project.name}</Text>
          <View style={styles.tagRow}>
            <View style={[styles.dot, { backgroundColor: statusColour }]} />
            <Text style={[styles.tagText, { color: statusColour }]}>{project.status}</Text>
            {linkedGoal ? (
              <Text style={styles.linkedGoalText} numberOfLines={1}>  ↳ {linkedGoal.title}</Text>
            ) : null}
          </View>
        </View>
        <View style={{ alignItems: 'flex-end', gap: 4 }}>
          <Text style={styles.progressText}>{project.progress}%</Text>
          {daysLeft !== null && (
            <Text style={[styles.tagText, { color: daysLeft <= 3 ? Colors.red : Colors.textMuted }]}>
              {daysLeft > 0 ? `${daysLeft}d` : 'due'}
            </Text>
          )}
        </View>
      </View>
    </View>
  );
}

function MemoryCard({ memory }: { memory: Memory }) {
  const [expanded, setExpanded] = useState(false);
  const typeIcon = TYPE_ICON[memory.memory_type] ?? '◇';
  const impColour = memory.importance >= 4 ? Colors.red
    : memory.importance >= 3 ? Colors.amber
    : Colors.textMuted;

  return (
    <TouchableOpacity
      style={[styles.card, { paddingVertical: 10 }]}
      onPress={() => setExpanded(e => !e)}
      activeOpacity={0.75}
    >
      <View style={styles.cardRow}>
        <Text style={[styles.typeIcon, { color: impColour }]}>{typeIcon}</Text>
        <View style={{ flex: 1 }}>
          <Text style={styles.memTitle} numberOfLines={1}>{memory.title}</Text>
          <Text style={styles.memMeta}>{memory.memory_type} · imp {memory.importance}/5</Text>
        </View>
        <Text style={styles.memTime}>{fmtTs(memory.ts)}</Text>
      </View>
      {expanded && (
        <Text style={styles.memContent}>{memory.content}</Text>
      )}
      {memory.tags && memory.tags.length > 0 && (
        <View style={styles.tagRow}>
          {memory.tags.slice(0, 4).map((t, i) => (
            <View key={i} style={styles.tag}>
              <Text style={styles.tagText}>#{t}</Text>
            </View>
          ))}
        </View>
      )}
    </TouchableOpacity>
  );
}

function fmtTs(ts: number): string {
  const d = new Date(ts * 1000);
  const now = new Date();
  const diffH = (now.getTime() - d.getTime()) / 3600000;
  if (diffH < 1)   return `${Math.round(diffH * 60)}m ago`;
  if (diffH < 24)  return `${Math.round(diffH)}h ago`;
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' });
}

// ---------------------------------------------------------------------------
// Main screen
// ---------------------------------------------------------------------------

export default function MemoryScreen() {
  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);
  const [searchQ, setSearchQ]       = useState('');
  const [activeTab, setActiveTab]   = useState<'goals' | 'projects' | 'memories'>('goals');

  const { data: status } = useServerStatus();
  const deviceId = status?.recent_snapshots[0]?.device_id ?? null;

  const { data: goals,    isLoading: goalsLoading }    = useGoals(deviceId, 'active');
  const { data: projects, isLoading: projLoading }     = useProjects(deviceId);
  const { data: memories, isLoading: memLoading }      = useMemories(deviceId, { limit: 50 });
  const { data: searchResult, isLoading: searchLoading } = useMemorySearch(deviceId, searchQ);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await queryClient.invalidateQueries({ queryKey: ['goals'] });
    await queryClient.invalidateQueries({ queryKey: ['projects'] });
    await queryClient.invalidateQueries({ queryKey: ['memories'] });
    setRefreshing(false);
  }, [queryClient]);

  const isSearching = searchQ.length >= 2;

  return (
    <SafeAreaView style={styles.safe}>
      {/* Search bar */}
      <View style={styles.searchBar}>
        <Text style={styles.searchIcon}>⌕</Text>
        <TextInput
          style={styles.searchInput}
          placeholder="Search goals, projects, memories…"
          placeholderTextColor={Colors.textMuted}
          value={searchQ}
          onChangeText={setSearchQ}
          returnKeyType="search"
          clearButtonMode="while-editing"
        />
      </View>

      {isSearching ? (
        /* ── Search results ── */
        <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
          <Text style={styles.sectionTitle}>
            {searchLoading ? 'Searching…' : `${searchResult?.total ?? 0} results for "${searchQ}"`}
          </Text>
          {searchLoading && <ActivityIndicator color={Colors.green} />}
          {(searchResult?.goals ?? []).map(g => <GoalCard key={`g${g.id}`} goal={g} />)}
          {(searchResult?.projects ?? []).map(p => (
            <ProjectCard key={`p${p.id}`} project={p} goals={searchResult?.goals ?? []} />
          ))}
          {(searchResult?.memories ?? []).map(m => <MemoryCard key={`m${m.id}`} memory={m} />)}
        </ScrollView>
      ) : (
        /* ── Tab view ── */
        <>
          {/* Tab selector */}
          <View style={styles.tabs}>
            {(['goals', 'projects', 'memories'] as const).map(tab => (
              <TouchableOpacity
                key={tab}
                style={[styles.tabBtn, activeTab === tab && styles.tabBtnActive]}
                onPress={() => setActiveTab(tab)}
              >
                <Text style={[styles.tabLabel, activeTab === tab && styles.tabLabelActive]}>
                  {tab.charAt(0).toUpperCase() + tab.slice(1)}
                  {tab === 'goals'    && goals    ? ` (${goals.length})`    : ''}
                  {tab === 'projects' && projects ? ` (${projects.length})` : ''}
                  {tab === 'memories' && memories ? ` (${memories.length})` : ''}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <ScrollView
            style={styles.scroll}
            contentContainerStyle={styles.content}
            refreshControl={
              <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.green} />
            }
          >
            {activeTab === 'goals' && (
              <>
                <Text style={styles.sectionTitle}>ACTIVE GOALS</Text>
                {goalsLoading && <ActivityIndicator color={Colors.green} style={{ marginTop: 20 }} />}
                {!goalsLoading && (goals ?? []).length === 0 && (
                  <EmptyState label="No active goals" sub="Add a goal to start tracking your long-term progress." />
                )}
                {(goals ?? []).map(g => <GoalCard key={g.id} goal={g} />)}
              </>
            )}

            {activeTab === 'projects' && (
              <>
                <Text style={styles.sectionTitle}>PROJECTS</Text>
                {projLoading && <ActivityIndicator color={Colors.green} style={{ marginTop: 20 }} />}
                {!projLoading && (projects ?? []).length === 0 && (
                  <EmptyState label="No active projects" sub="Create a project to track bounded work." />
                )}
                {(projects ?? [])
                  .filter(p => ['active', 'planning'].includes(p.status))
                  .map(p => <ProjectCard key={p.id} project={p} goals={goals ?? []} />)
                }
              </>
            )}

            {activeTab === 'memories' && (
              <>
                <Text style={styles.sectionTitle}>RECENT MEMORIES</Text>
                {memLoading && <ActivityIndicator color={Colors.green} style={{ marginTop: 20 }} />}
                {!memLoading && (memories ?? []).length === 0 && (
                  <EmptyState label="No memories yet" sub="Memories capture decisions, events, and notes for future recall." />
                )}
                {(memories ?? []).map(m => <MemoryCard key={m.id} memory={m} />)}
              </>
            )}

            {!deviceId && (
              <View style={styles.emptyState}>
                <Text style={styles.emptyText}>No device connected.</Text>
                <Text style={styles.emptySub}>Open the Dashboard tab to confirm your desktop is online.</Text>
              </View>
            )}
          </ScrollView>
        </>
      )}
    </SafeAreaView>
  );
}

function EmptyState({ label, sub }: { label: string; sub: string }) {
  return (
    <View style={styles.emptyState}>
      <Text style={styles.emptyText}>{label}</Text>
      <Text style={styles.emptySub}>{sub}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe:  { flex: 1, backgroundColor: Colors.bg },
  scroll:{ flex: 1 },
  content:{ padding: 16, paddingBottom: 48 },

  searchBar: {
    flexDirection:   'row',
    alignItems:      'center',
    margin:          16,
    marginBottom:    8,
    backgroundColor: Colors.surface,
    borderRadius:    10,
    borderWidth:     1,
    borderColor:     Colors.border,
    paddingHorizontal: 12,
    height:          42,
  },
  searchIcon:  { fontSize: 18, color: Colors.textMuted, marginRight: 8 },
  searchInput: { flex: 1, fontSize: 14, color: Colors.textPrimary },

  tabs: {
    flexDirection:    'row',
    marginHorizontal: 16,
    marginBottom:     8,
    backgroundColor:  Colors.surface,
    borderRadius:     8,
    borderWidth:      1,
    borderColor:      Colors.border,
    padding:          2,
  },
  tabBtn: {
    flex:          1,
    paddingVertical: 6,
    alignItems:    'center',
    borderRadius:  6,
  },
  tabBtnActive: { backgroundColor: Colors.bg },
  tabLabel:     { fontSize: 12, color: Colors.textMuted, fontWeight: '500' },
  tabLabelActive:{ color: Colors.textPrimary, fontWeight: '600' },

  sectionTitle: {
    fontSize:      10,
    fontWeight:    '600',
    color:         Colors.textMuted,
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginBottom:  12,
  },

  card: {
    backgroundColor: Colors.surface,
    borderRadius:    10,
    borderWidth:     1,
    borderColor:     Colors.border,
    padding:         14,
    marginBottom:    10,
    gap:             8,
  },
  cardRow:  { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  cardTitle:{ fontSize: 14, fontWeight: '600', color: Colors.textPrimary, flex: 1 },
  cardDesc: { fontSize: 12, color: Colors.textSecondary, lineHeight: 16 },

  tagRow:   { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 4, alignItems: 'center' },
  tag:      { backgroundColor: Colors.border, borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2 },
  tagText:  { fontSize: 10, color: Colors.textMuted },
  dot:      { width: 7, height: 7, borderRadius: 4 },

  linkedGoalText:{ fontSize: 10, color: Colors.textMuted, flex: 1 },
  progressText:  { fontSize: 13, fontWeight: '700', color: Colors.textPrimary },

  typeIcon:   { fontSize: 16, marginRight: 2, lineHeight: 20 },
  memTitle:   { fontSize: 13, fontWeight: '600', color: Colors.textPrimary },
  memMeta:    { fontSize: 10, color: Colors.textMuted, marginTop: 2 },
  memTime:    { fontSize: 10, color: Colors.textMuted },
  memContent: { fontSize: 12, color: Colors.textSecondary, lineHeight: 18, marginTop: 8 },

  emptyState: { alignItems: 'center', marginTop: 48, paddingHorizontal: 32 },
  emptyText:  { fontSize: 15, color: Colors.textSecondary, fontWeight: '500' },
  emptySub:   { fontSize: 12, color: Colors.textMuted, textAlign: 'center', marginTop: 6, lineHeight: 16 },
});
