/**
 * Polls /status every POLL_INTERVAL_MS and syncs result to Zustand store.
 * Components just call this hook — they don't need to know about polling.
 */

import { useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/services/api';
import { useMarkStore } from '@/store/useMarkStore';
import { Config } from '@/constants/Config';

export function useServerStatus() {
  const setServerStatus = useMarkStore((s) => s.setServerStatus);

  const query = useQuery({
    queryKey:      ['serverStatus'],
    queryFn:       api.getStatus,
    refetchInterval: Config.POLL_INTERVAL_MS,
    retry:         3,
    staleTime:     Config.POLL_INTERVAL_MS / 2,
  });

  useEffect(() => {
    if (query.data) {
      setServerStatus(query.data);
    }
  }, [query.data, setServerStatus]);

  return query;
}

export function useBreaches() {
  return useQuery({
    queryKey:        ['breaches'],
    queryFn:         () => api.getBreaches(50),
    refetchInterval: 30_000,
    retry:           2,
  });
}

export function usePendingCommands(deviceId: string | null) {
  return useQuery({
    queryKey:        ['pendingCommands', deviceId],
    queryFn:         () => (deviceId ? api.getPendingCommands(deviceId) : []),
    refetchInterval: 5_000,
    enabled:         !!deviceId,
  });
}

export function useCognitiveContext(deviceId: string | null) {
  return useQuery({
    queryKey:        ['cognitiveContext', deviceId],
    queryFn:         () => (deviceId ? api.getContext(deviceId) : null),
    refetchInterval: 60_000,
    enabled:         !!deviceId,
    retry:           2,
  });
}

export function useRecommendations(deviceId: string | null) {
  return useQuery({
    queryKey:        ['recommendations', deviceId],
    queryFn:         () => (deviceId ? api.getRecommendations(deviceId) : null),
    refetchInterval: 60_000,
    enabled:         !!deviceId,
    retry:           2,
  });
}

export function useDailyReport(deviceId: string | null, date?: string) {
  return useQuery({
    queryKey:        ['dailyReport', deviceId, date],
    queryFn:         () => (deviceId ? api.getDailyReport(deviceId, date) : null),
    refetchInterval: 5 * 60_000,
    enabled:         !!deviceId,
    staleTime:       3 * 60_000,
  });
}

export function useWeeklyReport(deviceId: string | null) {
  return useQuery({
    queryKey:        ['weeklyReport', deviceId],
    queryFn:         () => (deviceId ? api.getWeeklyReport(deviceId) : null),
    refetchInterval: 15 * 60_000,
    enabled:         !!deviceId,
    staleTime:       10 * 60_000,
  });
}

// ── Memory Engine ────────────────────────────────────────────────────────────

export function useProfile(deviceId: string | null) {
  return useQuery({
    queryKey: ['profile', deviceId],
    queryFn:  () => (deviceId ? api.getProfile(deviceId) : null),
    enabled:  !!deviceId,
    staleTime: 60_000,
  });
}

export function useGoals(deviceId: string | null, status?: string) {
  return useQuery({
    queryKey: ['goals', deviceId, status],
    queryFn:  () => (deviceId ? api.getGoals(deviceId, status) : []),
    enabled:  !!deviceId,
    staleTime: 30_000,
  });
}

export function useProjects(deviceId: string | null, status?: string, goalId?: number) {
  return useQuery({
    queryKey: ['projects', deviceId, status, goalId],
    queryFn:  () => (deviceId ? api.getProjects(deviceId, status, goalId) : []),
    enabled:  !!deviceId,
    staleTime: 30_000,
  });
}

export function useMemories(deviceId: string | null, opts?: {
  limit?: number; memory_type?: string; importance?: number;
  project_id?: number; goal_id?: number;
}) {
  return useQuery({
    queryKey: ['memories', deviceId, opts],
    queryFn:  () => (deviceId ? api.getMemories(deviceId, opts) : []),
    enabled:  !!deviceId,
    staleTime: 20_000,
  });
}

export function useMemorySearch(deviceId: string | null, q: string) {
  return useQuery({
    queryKey: ['memorySearch', deviceId, q],
    queryFn:  () => (deviceId && q.length >= 2 ? api.searchMemory(deviceId, q) : null),
    enabled:  !!deviceId && q.length >= 2,
    staleTime: 10_000,
  });
}

// ── AI Reasoning Engine ──────────────────────────────────────────────────────

export function useAIInsights(deviceId: string | null) {
  return useQuery({
    queryKey:        ['aiInsights', deviceId],
    queryFn:         () => (deviceId ? api.getAIInsights(deviceId) : null),
    enabled:         !!deviceId,
    staleTime:       8 * 60_000,
    refetchInterval: 10 * 60_000,
  });
}

export function useDailyBrief(deviceId: string | null) {
  return useQuery({
    queryKey:  ['dailyBrief', deviceId],
    queryFn:   () => (deviceId ? api.getDailyBrief(deviceId) : null),
    enabled:   !!deviceId,
    staleTime: 4 * 60_000,
  });
}

export function useEveningReview(deviceId: string | null) {
  return useQuery({
    queryKey:  ['eveningReview', deviceId],
    queryFn:   () => (deviceId ? api.getEveningReview(deviceId) : null),
    enabled:   !!deviceId,
    staleTime: 8 * 60_000,
  });
}

export function useAIWeeklyReview(deviceId: string | null) {
  return useQuery({
    queryKey:  ['aiWeeklyReview', deviceId],
    queryFn:   () => (deviceId ? api.getAIWeeklyReview(deviceId) : null),
    enabled:   !!deviceId,
    staleTime: 14 * 60_000,
  });
}

export function useProviderStatus() {
  return useQuery({
    queryKey:        ['providerStatus'],
    queryFn:         api.getProviderStatus,
    refetchInterval: 60_000,
    staleTime:       30_000,
  });
}

// ── Conversation Engine ──────────────────────────────────────────────────────

// ── Voice Core ───────────────────────────────────────────────────────────────

export function useVoiceCapabilities() {
  return useQuery({
    queryKey:  ['voiceCapabilities'],
    queryFn:   api.getVoiceCapabilities,
    staleTime: 60_000,
  });
}

// ── Conversation Engine ──────────────────────────────────────────────────────

export function useSessions(deviceId: string | null, limit = 20) {
  return useQuery({
    queryKey:  ['sessions', deviceId, limit],
    queryFn:   () => (deviceId ? api.getSessions(deviceId, limit) : { sessions: [] }),
    enabled:   !!deviceId,
    staleTime: 10_000,
  });
}

export function useConversationHistory(sessionId: string | null, limit = 50) {
  return useQuery({
    queryKey:  ['conversationHistory', sessionId, limit],
    queryFn:   () => (sessionId ? api.getConversationHistory(sessionId, limit) : { session_id: '', messages: [] }),
    enabled:   !!sessionId,
    staleTime: 5_000,
  });
}
