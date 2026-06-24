/**
 * MARK III Mobile — Brain Server API Client
 *
 * Typed wrappers around every endpoint the mobile app consumes.
 * All methods throw on network error — callers (React Query hooks) handle retry.
 */

import axios, { AxiosInstance } from 'axios';
import { Config } from '@/constants/Config';

// ---------------------------------------------------------------------------
// Response types
// ---------------------------------------------------------------------------

export interface ServerStatus {
  status:           string;
  server_ts:        number;
  uptime_s:         number;
  database:         string;
  notification:     string;
  devices_online:   number;
  snapshots_total:  number;
  commands_total:   number;
  breaches_total:   number;
  recent_snapshots: RecentSnapshot[];
}

export interface RecentSnapshot {
  device_id:      string;
  process:        string;
  classification: string;
  domain:         string | null;
  ts:             number;
}

export interface DeviceRecord {
  device_id:       string;
  hostname:        string;
  platform:        string;
  heartbeat_count: number;
  last_seen:       number;
}

export interface BreachRecord {
  id:             number;
  device_id:      string;
  ts:             number;
  keyword:        string;
  duration_min:   number;
  process_name:   string;
  active_domain:  string | null;
  notif_sent:     boolean;
  notif_provider: string;
}

export interface PendingCommand {
  id:         string;
  raw:        string;
  requester:  string;
  queued_at:  number;
}

export interface CognitiveContext {
  device_id:               string;
  ts:                      number;
  current_task:            string;
  productivity_state:      string;
  confidence:              number;
  suggested_action:        string;
  dominant_app:            string;
  dominant_classification: string;
  window_count:            number;
  is_work_block:           boolean;
}

export interface Recommendation {
  text:     string;
  category: string;
  priority: number;
}

export interface RecommendationsResponse {
  device_id:       string;
  context_state:   string;
  is_work_block:   boolean;
  recommendations: Recommendation[];
}

export interface HourlyBucket {
  hour:                    number;
  dominant_classification: string | null;
  minutes:                 number;
  colour:                  string | null;
}

export interface DailyReport {
  date:                    string;
  device_id:               string;
  productive_minutes:      number;
  distraction_minutes:     number;
  focus_score:             number;
  major_activities:        { classification: string; minutes: number; colour: string }[];
  top_apps:                { app: string; minutes: number }[];
  hourly_breakdown:        HourlyBucket[];
  recommendations:         string[];
  snapshot_count:          number;
}

// ── Memory Engine ──────────────────────────────────────────────────────────

export interface UserProfile {
  device_id:           string;
  name:                string | null;
  career:              string | null;
  interests:           string[];
  goals_summary:       string | null;
  preferences:         Record<string, unknown>;
  work_schedule:       Record<string, unknown>;
  learning_objectives: string[];
  exists:              boolean;
}

export interface LongTermGoal {
  id:          number;
  device_id:   string;
  title:       string;
  description: string | null;
  category:    string;
  status:      string;
  progress:    number;
  target_date: string | null;
  notes:       string | null;
  created_at:  number;
  updated_at:  number;
}

export interface Project {
  id:          number;
  device_id:   string;
  goal_id:     number | null;
  name:        string;
  description: string | null;
  status:      string;
  progress:    number;
  deadline:    string | null;
  notes:       string | null;
  created_at:  number;
  updated_at:  number;
}

export interface Memory {
  id:          number;
  device_id:   string;
  project_id:  number | null;
  goal_id:     number | null;
  ts:          number;
  title:       string;
  content:     string;
  memory_type: string;
  importance:  number;
  tags:        string[] | null;
  created_at:  number;
}

// ── AI Provider Layer ────────────────────────────────────────────────────────

export interface AIResponse {
  text:      string;
  cached:    boolean;
  task_type: string;
  provider:  string;
  model:     string;
  cost_usd:  number;
}

export interface ProviderInfo {
  enabled:      boolean;
  available:    boolean;
  error:        string | null;
  avg_latency:  number;
  calls_total:  number;
  calls_error:  number;
  last_check:   number;
  usage_30d: {
    cost_usd_30d:   number;
    tokens_in_30d:  number;
    tokens_out_30d: number;
    calls_30d:      number;
  };
}

export interface ProviderStatus {
  preferred_provider: string;
  providers: Record<string, ProviderInfo>;
  totals: {
    cost_usd_all_time: number;
    calls_all_time:    number;
  };
}

export interface SearchResult {
  query:     string;
  memories:  Memory[];
  projects:  Project[];
  goals:     LongTermGoal[];
  total:     number;
}

export interface WeeklyReport {
  week_start:                    string;
  week_end:                      string;
  device_id:                     string;
  focus_score:                   number;
  productivity_trend:            string;
  avg_daily_productive_minutes:  number;
  avg_daily_distraction_minutes: number;
  daily_scores:                  { date: string; score: number; productive_minutes: number }[];
  top_applications:              { app: string; minutes: number }[];
  top_classifications:           { classification: string; minutes: number; colour: string }[];
  improvement_suggestions:       string[];
  snapshot_count:                number;
}

// Voice Core (Phase 11)

export interface VoiceStartResponse {
  voice_session_id: string;
  conv_session_id:  string;
  mode:             string;
  device_type:      string;
}

export interface VoiceTranscribeResponse {
  transcript:       string;
  stt_confidence:   number;
  stt_latency_ms:   number;
  response_text:    string;
  audio_b64:        string;       // base64 WAV for playback
  tts_latency_ms:   number;
  total_latency_ms: number;
  provider:         string;
  model:            string;
  cost_usd:         number;
  error:            string | null;
}

export interface VoiceSpeakResponse {
  audio_b64:   string;
  engine:      string;
  duration_s:  number;
  latency_ms:  number;
  error:       string | null;
}

export interface VoiceCapabilities {
  audio:         { available: boolean; reason?: string; microphones?: number; speakers?: number };
  stt_available: boolean;
  tts_available: boolean;
  wake_word:     Record<string, { installed: boolean }>;
}

export interface ConversationSessionStart {
  session_id: string;
  title:      string;
  created_at: number;
}

export interface ConversationSession {
  id:             string;
  device_id:      string;
  title:          string;
  topic_summary:  string | null;
  message_count:  number;
  is_active:      boolean;
  provider_used:  string;
  total_cost_usd: number;
  created_at:     number;
  updated_at:     number;
}

export interface ConversationMessageItem {
  id:           number;
  session_id:   string;
  role:         'user' | 'assistant' | 'system';
  content:      string;
  provider:     string;
  model:        string;
  input_tokens: number;
  output_tokens: number;
  cost_usd:     number;
  latency_ms:   number;
  context_hash: string | null;
  ts:           number;
}

export interface ConversationResponse {
  session_id:    string;
  message_id:    number;
  text:          string;
  provider:      string;
  model:         string;
  input_tokens:  number;
  output_tokens: number;
  cost_usd:      number;
  latency_ms:    number;
  context_refs:  { ref_type: string; ref_id: string; ref_title: string }[];
  error?:        string | null;
}

export interface ConversationSearchResult {
  session_id: string;
  title:      string;
  message:    string;
  role:       string;
  ts:         number;
  updated_at: number;
}

// ---------------------------------------------------------------------------
// Client factory
// ---------------------------------------------------------------------------

function buildClient(): AxiosInstance {
  return axios.create({
    baseURL: Config.BRAIN_URL,
    timeout: Config.REQUEST_TIMEOUT_MS,
    headers: {
      'Content-Type': 'application/json',
      'X-Agent':      'MarkIII-Mobile/0.6',
    },
  });
}

const client = buildClient();

// ---------------------------------------------------------------------------
// API methods
// ---------------------------------------------------------------------------

export const api = {
  /** Health check + live stats — drives the dashboard */
  getStatus(): Promise<ServerStatus> {
    return client.get<ServerStatus>('/status').then(r => r.data);
  },

  /** All devices registered with the brain server */
  getDevices(): Promise<DeviceRecord[]> {
    return client.get<DeviceRecord[]>('/api/v1/devices').then(r => r.data);
  },

  /** Breach history — used by the breach log tab */
  getBreaches(limit = 50): Promise<BreachRecord[]> {
    return client
      .get<BreachRecord[]>('/api/v1/alerts/breaches', { params: { limit } })
      .then(r => r.data);
  },

  /** Pending sudo commands awaiting mobile approval */
  getPendingCommands(deviceId: string): Promise<PendingCommand[]> {
    return client
      .get<{ commands: PendingCommand[] }>('/api/v1/commands/pending', {
        params: { device_id: deviceId },
      })
      .then(r => r.data.commands);
  },

  /** Approve or deny a pending sudo command */
  setCommandStatus(requestId: string, status: 'approved' | 'denied'): Promise<void> {
    return client
      .patch(`/api/v1/commands/${requestId}/status`, null, { params: { status } })
      .then(() => undefined);
  },

  /** Register this mobile device's Expo push token with the brain server */
  registerPushToken(payload: {
    mobile_device_id: string;
    expo_push_token:  string;
    platform:         string;
  }): Promise<void> {
    return client.post('/api/v1/devices/register-push-token', payload).then(() => undefined);
  },

  // ── Cognitive Engine ───────────────────────────────────────────────────────

  getContext(deviceId: string): Promise<CognitiveContext> {
    return client.get<CognitiveContext>('/api/v1/cognitive/context', { params: { device_id: deviceId } }).then(r => r.data);
  },

  getRecommendations(deviceId: string): Promise<RecommendationsResponse> {
    return client.get<RecommendationsResponse>('/api/v1/cognitive/recommendations', { params: { device_id: deviceId } }).then(r => r.data);
  },

  getDailyReport(deviceId: string, date?: string): Promise<DailyReport> {
    return client.get<DailyReport>('/api/v1/cognitive/daily-report', {
      params: { device_id: deviceId, ...(date ? { date } : {}) },
    }).then(r => r.data);
  },

  getWeeklyReport(deviceId: string, weekStart?: string): Promise<WeeklyReport> {
    return client.get<WeeklyReport>('/api/v1/cognitive/weekly-report', {
      params: { device_id: deviceId, ...(weekStart ? { week_start: weekStart } : {}) },
    }).then(r => r.data);
  },

  // ── Memory Engine ────────────────────────────────────────────────────────

  getProfile(deviceId: string): Promise<UserProfile> {
    return client.get<UserProfile>('/api/v1/memory/profile', { params: { device_id: deviceId } }).then(r => r.data);
  },

  upsertProfile(deviceId: string, body: Partial<UserProfile>): Promise<void> {
    return client.put('/api/v1/memory/profile', body, { params: { device_id: deviceId } }).then(() => undefined);
  },

  getGoals(deviceId: string, status?: string): Promise<LongTermGoal[]> {
    return client.get<LongTermGoal[]>('/api/v1/memory/goals', {
      params: { device_id: deviceId, ...(status ? { status } : {}) },
    }).then(r => r.data);
  },

  createGoal(payload: {
    device_id: string; title: string; description?: string;
    category?: string; target_date?: string; notes?: string;
  }): Promise<LongTermGoal> {
    return client.post<LongTermGoal>('/api/v1/memory/goals', payload).then(r => r.data);
  },

  updateGoal(id: number, body: Partial<LongTermGoal>): Promise<LongTermGoal> {
    return client.put<LongTermGoal>(`/api/v1/memory/goals/${id}`, body).then(r => r.data);
  },

  deleteGoal(id: number): Promise<void> {
    return client.delete(`/api/v1/memory/goals/${id}`).then(() => undefined);
  },

  getProjects(deviceId: string, status?: string, goalId?: number): Promise<Project[]> {
    return client.get<Project[]>('/api/v1/memory/projects', {
      params: { device_id: deviceId, ...(status ? { status } : {}), ...(goalId ? { goal_id: goalId } : {}) },
    }).then(r => r.data);
  },

  createProject(payload: {
    device_id: string; name: string; description?: string;
    goal_id?: number; deadline?: string; notes?: string;
  }): Promise<Project> {
    return client.post<Project>('/api/v1/memory/projects', payload).then(r => r.data);
  },

  updateProject(id: number, body: Partial<Project>): Promise<Project> {
    return client.put<Project>(`/api/v1/memory/projects/${id}`, body).then(r => r.data);
  },

  deleteProject(id: number): Promise<void> {
    return client.delete(`/api/v1/memory/projects/${id}`).then(() => undefined);
  },

  getMemories(deviceId: string, opts?: {
    limit?: number; memory_type?: string; importance?: number;
    project_id?: number; goal_id?: number;
  }): Promise<Memory[]> {
    return client.get<Memory[]>('/api/v1/memory/memories', {
      params: { device_id: deviceId, ...opts },
    }).then(r => r.data);
  },

  createMemory(payload: {
    device_id: string; title: string; content: string;
    memory_type?: string; importance?: number;
    tags?: string[]; project_id?: number; goal_id?: number;
  }): Promise<Memory> {
    return client.post<Memory>('/api/v1/memory/memories', payload).then(r => r.data);
  },

  deleteMemory(id: number): Promise<void> {
    return client.delete(`/api/v1/memory/memories/${id}`).then(() => undefined);
  },

  searchMemory(deviceId: string, q: string, limit = 20): Promise<SearchResult> {
    return client.get<SearchResult>('/api/v1/memory/search', {
      params: { device_id: deviceId, q, limit },
    }).then(r => r.data);
  },

  // ── AI Reasoning Engine ──────────────────────────────────────────────────

  askMark(deviceId: string, question: string, sessionId?: string): Promise<AIResponse> {
    return client.post<AIResponse>('/api/v1/ai/ask', {
      device_id:  deviceId,
      question,
      session_id: sessionId ?? '',
    }).then(r => r.data);
  },

  getAIInsights(deviceId: string, force = false): Promise<AIResponse> {
    return client.get<AIResponse>('/api/v1/ai/insights', {
      params: { device_id: deviceId, force },
    }).then(r => r.data);
  },

  getDailyBrief(deviceId: string, force = false): Promise<AIResponse> {
    return client.get<AIResponse>('/api/v1/ai/daily-brief', {
      params: { device_id: deviceId, force },
    }).then(r => r.data);
  },

  getEveningReview(deviceId: string, force = false): Promise<AIResponse> {
    return client.get<AIResponse>('/api/v1/ai/evening-review', {
      params: { device_id: deviceId, force },
    }).then(r => r.data);
  },

  getAIWeeklyReview(deviceId: string, force = false): Promise<AIResponse> {
    return client.get<AIResponse>('/api/v1/ai/weekly-review', {
      params: { device_id: deviceId, force },
    }).then(r => r.data);
  },

  getProviderStatus(): Promise<ProviderStatus> {
    return client.get<ProviderStatus>('/api/v1/ai/provider-status').then(r => r.data);
  },

  // ── Conversation Engine ──────────────────────────────────────────────────

  startConversation(deviceId: string, title?: string): Promise<ConversationSessionStart> {
    return client.post<ConversationSessionStart>('/api/v1/conversation/start', {
      device_id: deviceId,
      title: title ?? 'New conversation',
    }).then(r => r.data);
  },

  sendConversationMessage(sessionId: string, deviceId: string, message: string): Promise<ConversationResponse> {
    return client.post<ConversationResponse>('/api/v1/conversation/message', {
      session_id: sessionId,
      device_id:  deviceId,
      message,
    }).then(r => r.data);
  },

  getConversationHistory(sessionId: string, limit = 50): Promise<{ session_id: string; messages: ConversationMessageItem[] }> {
    return client.get('/api/v1/conversation/history', {
      params: { session_id: sessionId, limit },
    }).then(r => r.data);
  },

  getSessions(deviceId: string, limit = 20): Promise<{ sessions: ConversationSession[] }> {
    return client.get('/api/v1/conversation/sessions', {
      params: { device_id: deviceId, limit },
    }).then(r => r.data);
  },

  searchConversations(deviceId: string, q: string): Promise<{ query: string; results: ConversationSearchResult[] }> {
    return client.get('/api/v1/conversation/search', {
      params: { device_id: deviceId, q },
    }).then(r => r.data);
  },

  // ── Voice Core ───────────────────────────────────────────────────────────

  startVoice(deviceId: string, convSessionId?: string): Promise<VoiceStartResponse> {
    return client.post<VoiceStartResponse>('/api/v1/voice/start', {
      device_id:       deviceId,
      mode:            'push_to_talk',
      device_type:     'mobile',
      conv_session_id: convSessionId,
    }).then(r => r.data);
  },

  stopVoice(deviceId: string): Promise<void> {
    return client.post('/api/v1/voice/stop', { device_id: deviceId }).then(() => undefined);
  },

  transcribeVoice(
    deviceId:       string,
    audioB64:       string,
    convSessionId?: string,
    voiceSessionId?: string,
  ): Promise<VoiceTranscribeResponse> {
    return client.post<VoiceTranscribeResponse>('/api/v1/voice/transcribe', {
      device_id:        deviceId,
      audio_b64:        audioB64,
      conv_session_id:  convSessionId,
      voice_session_id: voiceSessionId,
    }).then(r => r.data);
  },

  speakText(deviceId: string, text: string): Promise<VoiceSpeakResponse> {
    return client.post<VoiceSpeakResponse>('/api/v1/voice/speak', {
      device_id: deviceId,
      text,
    }).then(r => r.data);
  },

  interruptVoice(deviceId: string, interruptType = 'stop_speaking'): Promise<void> {
    return client.post('/api/v1/voice/interrupt', {
      device_id:      deviceId,
      interrupt_type: interruptType,
    }).then(() => undefined);
  },

  getVoiceCapabilities(): Promise<VoiceCapabilities> {
    return client.get<VoiceCapabilities>('/api/v1/voice/capabilities').then(r => r.data);
  },

  registerVoiceDevice(deviceId: string, deviceType: string, name: string): Promise<void> {
    return client.post('/api/v1/voice/device', {
      device_id:   deviceId,
      device_type: deviceType,
      name,
    }).then(() => undefined);
  },

  // --- Actions ---

  getPendingApprovals(deviceId: string): Promise<{ pending: Array<{
    approval_id:  string;
    action_id:    string;
    prompt:       string;
    requested_at: number;
  }>; count: number }> {
    return client.get(`/api/v1/actions/pending/approvals`, {
      params: { device_id: deviceId },
    }).then(r => r.data);
  },

  respondApproval(
    approvalId: string,
    verdict: 'approved' | 'denied',
  ): Promise<{ recorded: boolean; verdict: string }> {
    return client.post('/api/v1/actions/approve', {
      approval_id:  approvalId,
      verdict,
      responded_by: 'mobile',
    }).then(r => r.data);
  },

  submitAction(
    actionType: string,
    parameters: Record<string, unknown>,
    deviceId: string,
    source = 'api',
    sessionId?: string,
  ): Promise<{ action_id: string; state: string; safety_level: string }> {
    return client.post('/api/v1/actions/submit', {
      action_type: actionType,
      parameters,
      source,
      device_id:   deviceId,
      session_id:  sessionId,
    }).then(r => r.data);
  },

  getActionStatus(actionId: string): Promise<Record<string, unknown>> {
    return client.get(`/api/v1/actions/${actionId}`).then(r => r.data);
  },

  // --- Agents ---

  getAgents(): Promise<{ agents: Array<{
    agent_id: string;
    name: string;
    description: string;
    min_interval_hours: number;
  }> }> {
    return client.get('/api/v1/agents/').then(r => r.data);
  },

  getAgentHistory(deviceId: string, limit = 20): Promise<{ history: Array<{
    id:           number;
    agent_id:     string;
    ran_at:       number;
    success:      boolean;
    title:        string;
    text_snippet: string;
    delivery:     string[];
    priority:     string;
    latency_ms:   number;
    error?:       string;
  }>; count: number }> {
    return client.get('/api/v1/agents/history', {
      params: { device_id: deviceId, limit },
    }).then(r => r.data);
  },

  triggerAgent(agentId: string, deviceId: string): Promise<{
    triggered: boolean;
    title: string;
    text: string;
    success: boolean;
    error?: string;
  }> {
    return client.post(`/api/v1/agents/${agentId}/trigger`, null, {
      params: { device_id: deviceId },
    }).then(r => r.data);
  },
};
