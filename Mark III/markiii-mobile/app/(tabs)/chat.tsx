/**
 * MARK III — Chat Tab (Phase 10 + 11)
 *
 * Persistent multi-turn conversations with MARK III.
 * Includes push-to-talk voice input (Phase 11).
 *
 * Features:
 *   - Typewriter animation for assistant responses
 *   - Session history (modal)
 *   - Suggested questions when conversation is empty
 *   - Context reference chips below each assistant message
 *   - Provider / model / cost metadata per message
 *   - Voice button: hold to record, release to transcribe + respond
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, FlatList,
  StyleSheet, ActivityIndicator, KeyboardAvoidingView,
  Platform, Modal, ScrollView, Pressable, PanResponder, Alert,
} from 'react-native';
import { useQueryClient } from '@tanstack/react-query';
import { Colors } from '@/constants/Colors';
import { api, ConversationMessageItem, ConversationSession } from '@/services/api';
import { useMarkStore } from '@/store/useMarkStore';
import { useSessions } from '@/hooks/useServerStatus';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LocalMessage {
  id:          string;          // temp ID until server confirms
  role:        'user' | 'assistant';
  content:     string;
  displayText: string;          // typewriter progress for assistant
  provider?:   string;
  model?:      string;
  cost_usd?:   number;
  latency_ms?: number;
  context_refs?: { ref_type: string; ref_id: string; ref_title: string }[];
  done:        boolean;         // typewriter complete
  error?:      string | null;
}

const TYPEWRITER_SPEED_MS = 12;  // ms per character
const SUGGESTED_QUESTIONS = [
  'What should I focus on today?',
  'How has my productivity been this week?',
  'What are my active goals?',
  'Give me a strategy for my current projects.',
  'What distractions should I avoid today?',
  'Summarise my daily brief.',
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtCost(cost: number): string {
  if (cost === 0) return 'free';
  if (cost < 0.001) return `$${(cost * 1000).toFixed(3)}m`;
  return `$${cost.toFixed(4)}`;
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetaBadge({ label, color = Colors.textMuted }: { label: string; color?: string }) {
  return (
    <View style={[styles.metaBadge, { borderColor: color }]}>
      <Text style={[styles.metaBadgeText, { color }]}>{label}</Text>
    </View>
  );
}

function ContextRefChips({ refs }: { refs: { ref_type: string; ref_title: string }[] }) {
  if (!refs || refs.length === 0) return null;
  const color: Record<string, string> = {
    goal:    Colors.green,
    project: Colors.amber,
    memory:  Colors.blue,
  };
  return (
    <View style={styles.refChipsRow}>
      {refs.slice(0, 4).map((r, i) => (
        <View key={i} style={[styles.refChip, { borderColor: color[r.ref_type] ?? Colors.border }]}>
          <Text style={[styles.refChipText, { color: color[r.ref_type] ?? Colors.textMuted }]}>
            {r.ref_type[0].toUpperCase()} · {r.ref_title.length > 18 ? r.ref_title.slice(0, 18) + '…' : r.ref_title}
          </Text>
        </View>
      ))}
    </View>
  );
}

function UserBubble({ msg }: { msg: LocalMessage }) {
  return (
    <View style={styles.userBubbleWrap}>
      <View style={styles.userBubble}>
        <Text style={styles.userBubbleText}>{msg.content}</Text>
      </View>
    </View>
  );
}

function AssistantBubble({ msg }: { msg: LocalMessage }) {
  const isLoading    = !msg.done && msg.displayText === '';
  const isProactive  = (msg as any).source === 'agent';

  return (
    <View style={styles.assistantBubbleWrap}>
      <View style={styles.assistantHeader}>
        <Text style={[styles.assistantLabel, isProactive && { color: Colors.amber }]}>
          {isProactive ? '◉ MARK III' : 'MARK III'}
        </Text>
        {msg.error && <Text style={styles.errorBadge}> ⚠ degraded</Text>}
        {isProactive && <Text style={styles.proactiveBadge}>proactive</Text>}
      </View>

      <View style={styles.assistantBubble}>
        {isLoading ? (
          <ActivityIndicator size="small" color={Colors.green} />
        ) : (
          <Text style={styles.assistantBubbleText}>
            {msg.displayText}
            {!msg.done && <Text style={styles.cursor}>▌</Text>}
          </Text>
        )}
      </View>

      {msg.done && (
        <>
          <ContextRefChips refs={msg.context_refs ?? []} />
          <View style={styles.metaRow}>
            {msg.provider && msg.provider !== 'none' && (
              <MetaBadge label={msg.provider} color={Colors.green} />
            )}
            {msg.model && msg.model !== 'none' && (
              <MetaBadge label={msg.model.split('-').slice(-1)[0]} />
            )}
            {msg.cost_usd !== undefined && (
              <MetaBadge label={fmtCost(msg.cost_usd)} />
            )}
            {msg.latency_ms !== undefined && msg.latency_ms > 0 && (
              <MetaBadge label={fmtMs(msg.latency_ms)} />
            )}
          </View>
        </>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Approval Banner
// ---------------------------------------------------------------------------

interface PendingApproval {
  approval_id:  string;
  action_id:    string;
  prompt:       string;
  requested_at: number;
}

function ApprovalBanner({
  approval,
  onRespond,
}: {
  approval: PendingApproval;
  onRespond: (approvalId: string, verdict: 'approved' | 'denied') => void;
}) {
  return (
    <View style={styles.approvalBanner}>
      <Text style={styles.approvalTitle}>Action Required</Text>
      <Text style={styles.approvalPrompt}>{approval.prompt}</Text>
      <View style={styles.approvalBtns}>
        <TouchableOpacity
          style={[styles.approvalBtn, styles.approvalDenyBtn]}
          onPress={() => onRespond(approval.approval_id, 'denied')}
        >
          <Text style={styles.approvalBtnText}>Deny</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.approvalBtn, styles.approvalAllowBtn]}
          onPress={() => onRespond(approval.approval_id, 'approved')}
        >
          <Text style={[styles.approvalBtnText, { color: Colors.bg }]}>Allow</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

function SuggestedQuestions({ onSelect }: { onSelect: (q: string) => void }) {
  return (
    <View style={styles.suggestedWrap}>
      <Text style={styles.suggestedTitle}>Ask MARK III anything</Text>
      <Text style={styles.suggestedSub}>Start with a question, or tap one below:</Text>
      {SUGGESTED_QUESTIONS.map((q, i) => (
        <TouchableOpacity key={i} style={styles.suggestedBtn} onPress={() => onSelect(q)}>
          <Text style={styles.suggestedBtnText}>{q}</Text>
        </TouchableOpacity>
      ))}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Session History Modal
// ---------------------------------------------------------------------------

function SessionModal({
  visible,
  sessions,
  currentId,
  onSelect,
  onNew,
  onClose,
}: {
  visible:   boolean;
  sessions:  ConversationSession[];
  currentId: string | null;
  onSelect:  (s: ConversationSession) => void;
  onNew:     () => void;
  onClose:   () => void;
}) {
  function fmtDate(ts: number) {
    const d = new Date(ts * 1000);
    const now = new Date();
    const diff = (now.getTime() - d.getTime()) / 1000;
    if (diff < 60)       return 'just now';
    if (diff < 3600)     return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400)    return `${Math.floor(diff / 3600)}h ago`;
    return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' });
  }

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={styles.modalOverlay} onPress={onClose}>
        <Pressable style={styles.modalSheet} onPress={() => {}}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Conversations</Text>
            <TouchableOpacity style={styles.newSessionBtn} onPress={onNew}>
              <Text style={styles.newSessionBtnText}>+ New</Text>
            </TouchableOpacity>
          </View>
          <ScrollView style={{ flex: 1 }}>
            {sessions.length === 0 && (
              <Text style={styles.emptyText}>No conversations yet.</Text>
            )}
            {sessions.map(s => (
              <TouchableOpacity
                key={s.id}
                style={[styles.sessionRow, s.id === currentId && styles.sessionRowActive]}
                onPress={() => { onSelect(s); onClose(); }}
              >
                <Text style={styles.sessionRowTitle} numberOfLines={1}>{s.title}</Text>
                <View style={styles.sessionRowMeta}>
                  <Text style={styles.sessionRowSub}>{s.message_count} msgs</Text>
                  <Text style={styles.sessionRowSub}>{fmtDate(s.updated_at)}</Text>
                </View>
              </TouchableOpacity>
            ))}
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Voice Button (Phase 11)
// Push-to-talk: hold → record → release → STT + LLM + TTS via /voice/transcribe
// ---------------------------------------------------------------------------

type VoicePhase = 'idle' | 'recording' | 'processing';

function VoiceButton({
  deviceId,
  sessionId,
  disabled,
  onVoiceResult,
}: {
  deviceId:      string | null;
  sessionId:     string | null;
  disabled:      boolean;
  onVoiceResult: (transcript: string, responseText: string) => void;
}) {
  const [phase,           setPhase]           = useState<VoicePhase>('idle');
  const [voiceSid,        setVoiceSid]        = useState<string | null>(null);
  const [convSid,         setConvSid]         = useState<string | null>(null);
  const [errorMsg,        setErrorMsg]        = useState<string>('');
  const recordingRef                          = useRef<any>(null);  // expo-av Recording
  const pressRef                              = useRef<boolean>(false);

  // Attempt to import expo-av (optional — graceful degrade if not installed)
  const getAudio = () => {
    try {
      return require('expo-av');
    } catch {
      return null;
    }
  };

  const onPressIn = useCallback(async () => {
    if (!deviceId || disabled || phase !== 'idle') return;
    pressRef.current = true;
    setErrorMsg('');

    const av = getAudio();
    if (!av) {
      setErrorMsg('expo-av not installed');
      return;
    }

    try {
      // Request mic permission
      const { Audio } = av;
      const perm = await Audio.requestPermissionsAsync();
      if (!perm.granted) {
        setErrorMsg('Microphone permission denied');
        return;
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      // Start recording
      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      recordingRef.current = recording;
      setPhase('recording');

      // Ensure voice session exists
      if (!voiceSid) {
        try {
          const vs = await api.startVoice(deviceId, convSid ?? undefined);
          setVoiceSid(vs.voice_session_id);
          setConvSid(vs.conv_session_id);
        } catch {
          // non-fatal — transcribe endpoint will create session
        }
      }
    } catch (e: any) {
      setErrorMsg(e?.message ?? 'Recording error');
      setPhase('idle');
    }
  }, [deviceId, disabled, phase, voiceSid, convSid]);

  const onPressOut = useCallback(async () => {
    if (!pressRef.current || phase !== 'recording') return;
    pressRef.current = false;
    setPhase('processing');

    const av = getAudio();
    if (!av || !recordingRef.current || !deviceId) {
      setPhase('idle');
      return;
    }

    try {
      const { Audio } = av;

      // Stop recording and get URI
      await recordingRef.current.stopAndUnloadAsync();
      const uri = recordingRef.current.getURI();
      recordingRef.current = null;

      // Reset audio mode
      await Audio.setAudioModeAsync({ allowsRecordingIOS: false });

      // Read file as base64
      const { FileSystem } = require('expo-file-system');
      const base64 = await FileSystem.readAsStringAsync(uri, {
        encoding: FileSystem.EncodingType.Base64,
      });

      // POST to /voice/transcribe
      const result = await api.transcribeVoice(
        deviceId, base64, convSid ?? undefined, voiceSid ?? undefined,
      );

      if (result.error && !result.response_text) {
        setErrorMsg(result.error);
      } else {
        setConvSid(c => c || null);  // keep conv session

        // Play TTS audio if provided
        if (result.audio_b64) {
          try {
            const { FileSystem } = require('expo-file-system');
            const { Audio } = av;
            const wavUri = FileSystem.cacheDirectory + `mark3_response_${Date.now()}.wav`;
            await FileSystem.writeAsStringAsync(wavUri, result.audio_b64, {
              encoding: FileSystem.EncodingType.Base64,
            });
            const { sound } = await Audio.Sound.createAsync({ uri: wavUri });
            await sound.playAsync();
            // Cleanup after playback
            sound.setOnPlaybackStatusUpdate((status: any) => {
              if (status.didJustFinish) {
                sound.unloadAsync();
                FileSystem.deleteAsync(wavUri, { idempotent: true });
              }
            });
          } catch (playErr) {
            // Silent fail — text response still delivered
          }
        }

        onVoiceResult(result.transcript, result.response_text);
      }
    } catch (e: any) {
      setErrorMsg(e?.message ?? 'Processing error');
    } finally {
      setPhase('idle');
    }
  }, [phase, deviceId, voiceSid, convSid, onVoiceResult]);

  const panResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onPanResponderGrant:          () => onPressIn(),
      onPanResponderRelease:        () => onPressOut(),
      onPanResponderTerminate:      () => { pressRef.current = false; setPhase('idle'); },
    })
  ).current;

  const isRecording   = phase === 'recording';
  const isProcessing  = phase === 'processing';

  return (
    <View style={styles.voiceBtnWrap}>
      <View
        {...panResponder.panHandlers}
        style={[
          styles.voiceBtn,
          isRecording  && styles.voiceBtnActive,
          isProcessing && styles.voiceBtnProcessing,
          (disabled || phase === 'processing') && styles.voiceBtnDisabled,
        ]}
      >
        {isProcessing
          ? <ActivityIndicator size="small" color={Colors.textPrimary} />
          : <Text style={[styles.voiceBtnIcon, isRecording && { color: Colors.red }]}>
              {isRecording ? '●' : '◎'}
            </Text>
        }
      </View>
      {(isRecording || errorMsg) && (
        <Text style={[styles.voiceBtnHint, errorMsg ? { color: Colors.red } : {}]}>
          {errorMsg || 'Release to send'}
        </Text>
      )}
    </View>
  );
}


// ---------------------------------------------------------------------------
// Main screen
// ---------------------------------------------------------------------------

export default function ChatScreen() {
  const deviceId   = useMarkStore(s => s.deviceId);
  const qc         = useQueryClient();

  const [sessionId,     setSessionId]     = useState<string | null>(null);
  const [messages,      setMessages]      = useState<LocalMessage[]>([]);
  const [inputText,     setInputText]     = useState('');
  const [sending,       setSending]       = useState(false);
  const [showHistory,   setShowHistory]   = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState<PendingApproval[]>([]);

  const flatRef   = useRef<FlatList>(null);
  const typeTimers = useRef<NodeJS.Timeout[]>([]);

  const { data: sessionsData, refetch: refetchSessions } = useSessions(deviceId);
  const sessions = sessionsData?.sessions ?? [];

  // ---------------------------------------------------------------------------
  // Start a new session
  // ---------------------------------------------------------------------------

  const startNewSession = useCallback(async () => {
    if (!deviceId) return;
    try {
      const result = await api.startConversation(deviceId);
      setSessionId(result.session_id);
      setMessages([]);
      refetchSessions();
    } catch (e) {
      console.error('startConversation error', e);
    }
  }, [deviceId, refetchSessions]);

  // Auto-start session on mount
  useEffect(() => {
    if (deviceId && !sessionId) {
      startNewSession();
    }
  }, [deviceId]);

  // Poll for pending approvals every 3 seconds
  useEffect(() => {
    if (!deviceId) return;
    const poll = async () => {
      try {
        const result = await api.getPendingApprovals(deviceId);
        setPendingApprovals(result.pending ?? []);
      } catch { /* non-fatal */ }
    };
    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, [deviceId]);

  const handleApprovalResponse = useCallback(async (
    approvalId: string,
    verdict: 'approved' | 'denied',
  ) => {
    try {
      await api.respondApproval(approvalId, verdict);
      setPendingApprovals(prev => prev.filter(a => a.approval_id !== approvalId));
    } catch (e) {
      Alert.alert('Error', 'Could not record response. Please try again.');
    }
  }, []);

  // Cleanup typewriter timers on unmount
  useEffect(() => {
    return () => {
      typeTimers.current.forEach(t => clearTimeout(t));
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Typewriter animation
  // ---------------------------------------------------------------------------

  const startTypewriter = useCallback((msgId: string, fullText: string) => {
    let i = 0;
    const tick = () => {
      i++;
      setMessages(prev => prev.map(m =>
        m.id === msgId
          ? { ...m, displayText: fullText.slice(0, i), done: i >= fullText.length }
          : m
      ));
      if (i < fullText.length) {
        const t = setTimeout(tick, TYPEWRITER_SPEED_MS);
        typeTimers.current.push(t);
      }
    };
    tick();
  }, []);

  // ---------------------------------------------------------------------------
  // Send a message
  // ---------------------------------------------------------------------------

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || !deviceId || sending) return;

    let sid = sessionId;
    if (!sid) {
      const result = await api.startConversation(deviceId);
      sid = result.session_id;
      setSessionId(sid);
    }

    const userMsg: LocalMessage = {
      id:          `u-${Date.now()}`,
      role:        'user',
      content:     text.trim(),
      displayText: text.trim(),
      done:        true,
    };

    const assistantPlaceholder: LocalMessage = {
      id:          `a-${Date.now()}`,
      role:        'assistant',
      content:     '',
      displayText: '',
      done:        false,
    };

    setMessages(prev => [...prev, userMsg, assistantPlaceholder]);
    setInputText('');
    setSending(true);

    setTimeout(() => flatRef.current?.scrollToEnd({ animated: true }), 100);

    try {
      const resp = await api.sendConversationMessage(sid, deviceId, text.trim());

      const fullText = resp.text || 'MARK III had no response.';

      setMessages(prev => prev.map(m =>
        m.id === assistantPlaceholder.id
          ? {
              ...m,
              content:      fullText,
              provider:     resp.provider,
              model:        resp.model,
              cost_usd:     resp.cost_usd,
              latency_ms:   resp.latency_ms,
              context_refs: resp.context_refs,
              error:        resp.error,
            }
          : m
      ));

      startTypewriter(assistantPlaceholder.id, fullText);
      refetchSessions();

    } catch (err: any) {
      const errText = err?.response?.data?.detail ?? err?.message ?? 'Connection error.';
      setMessages(prev => prev.map(m =>
        m.id === assistantPlaceholder.id
          ? { ...m, content: errText, displayText: errText, done: true, error: errText }
          : m
      ));
    } finally {
      setSending(false);
      setTimeout(() => flatRef.current?.scrollToEnd({ animated: true }), 200);
    }
  }, [deviceId, sessionId, sending, startTypewriter, refetchSessions]);

  // ---------------------------------------------------------------------------
  // Load existing session
  // ---------------------------------------------------------------------------

  const loadSession = useCallback(async (s: ConversationSession) => {
    setSessionId(s.id);
    setMessages([]);
    try {
      const history = await api.getConversationHistory(s.id, 50);
      const loaded: LocalMessage[] = history.messages.map(m => ({
        id:          String(m.id),
        role:        m.role as 'user' | 'assistant',
        content:     m.content,
        displayText: m.content,
        provider:    m.provider,
        model:       m.model,
        cost_usd:    m.cost_usd,
        latency_ms:  m.latency_ms,
        done:        true,
      }));
      setMessages(loaded);
      setTimeout(() => flatRef.current?.scrollToEnd({ animated: false }), 100);
    } catch (e) {
      console.error('loadSession error', e);
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Current session title
  // ---------------------------------------------------------------------------

  const currentSession = sessions.find(s => s.id === sessionId);
  const sessionTitle   = currentSession?.title ?? 'MARK III';

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const showSuggested = messages.length === 0 && !sending;

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={90}
    >
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity style={styles.headerSessionBtn} onPress={() => setShowHistory(true)}>
          <Text style={styles.headerSessionTitle} numberOfLines={1}>{sessionTitle}</Text>
          <Text style={styles.headerChevron}>▾</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.newChatBtn} onPress={startNewSession}>
          <Text style={styles.newChatBtnText}>＋</Text>
        </TouchableOpacity>
      </View>

      {/* Messages */}
      {showSuggested ? (
        <ScrollView contentContainerStyle={{ flexGrow: 1 }}>
          <SuggestedQuestions onSelect={q => sendMessage(q)} />
        </ScrollView>
      ) : (
        <FlatList
          ref={flatRef}
          data={messages}
          keyExtractor={m => m.id}
          contentContainerStyle={styles.messageList}
          renderItem={({ item }) =>
            item.role === 'user'
              ? <UserBubble msg={item} />
              : <AssistantBubble msg={item} />
          }
          onContentSizeChange={() => flatRef.current?.scrollToEnd({ animated: true })}
        />
      )}

      {/* Pending action approvals */}
      {pendingApprovals.map(approval => (
        <ApprovalBanner
          key={approval.approval_id}
          approval={approval}
          onRespond={handleApprovalResponse}
        />
      ))}

      {/* Input bar */}
      <View style={styles.inputBar}>
        <TextInput
          style={styles.input}
          placeholder="Message MARK III…"
          placeholderTextColor={Colors.textMuted}
          value={inputText}
          onChangeText={setInputText}
          multiline
          returnKeyType="send"
          onSubmitEditing={() => sendMessage(inputText)}
          editable={!sending}
          blurOnSubmit={false}
        />
        <VoiceButton
          deviceId={deviceId}
          sessionId={sessionId}
          disabled={sending}
          onVoiceResult={(transcript, responseText) => {
            // Insert voice exchange into chat as if typed
            if (transcript) {
              const voiceUserMsg: LocalMessage = {
                id:          `vu-${Date.now()}`,
                role:        'user',
                content:     `🎙 ${transcript}`,
                displayText: `🎙 ${transcript}`,
                done:        true,
              };
              const voiceAsstMsg: LocalMessage = {
                id:          `va-${Date.now()}`,
                role:        'assistant',
                content:     responseText,
                displayText: '',
                done:        false,
              };
              setMessages(prev => [...prev, voiceUserMsg, voiceAsstMsg]);
              const aId = voiceAsstMsg.id;
              startTypewriter(aId, responseText);
              setTimeout(() => flatRef.current?.scrollToEnd({ animated: true }), 100);
            }
          }}
        />
        <TouchableOpacity
          style={[styles.sendBtn, (!inputText.trim() || sending) && styles.sendBtnDisabled]}
          onPress={() => sendMessage(inputText)}
          disabled={!inputText.trim() || sending}
        >
          {sending
            ? <ActivityIndicator size="small" color={Colors.bg} />
            : <Text style={styles.sendBtnText}>▶</Text>
          }
        </TouchableOpacity>
      </View>

      {/* Session history modal */}
      <SessionModal
        visible={showHistory}
        sessions={sessions}
        currentId={sessionId}
        onSelect={loadSession}
        onNew={() => { startNewSession(); setShowHistory(false); }}
        onClose={() => setShowHistory(false)}
      />
    </KeyboardAvoidingView>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  root: {
    flex:            1,
    backgroundColor: Colors.bg,
  },

  // Header
  header: {
    flexDirection:   'row',
    alignItems:      'center',
    paddingHorizontal: 16,
    paddingTop:      16,
    paddingBottom:   12,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  headerSessionBtn: {
    flex:         1,
    flexDirection: 'row',
    alignItems:   'center',
    gap:          4,
  },
  headerSessionTitle: {
    color:      Colors.textPrimary,
    fontSize:   17,
    fontWeight: '600',
    flex:       1,
  },
  headerChevron: {
    color:    Colors.textMuted,
    fontSize: 14,
  },
  newChatBtn: {
    width:           36,
    height:          36,
    borderRadius:    18,
    backgroundColor: Colors.surface,
    alignItems:      'center',
    justifyContent:  'center',
    borderWidth:     1,
    borderColor:     Colors.border,
  },
  newChatBtnText: {
    color:    Colors.green,
    fontSize: 20,
    lineHeight: 24,
  },

  // Messages
  messageList: {
    padding:     16,
    paddingBottom: 8,
    gap:         12,
  },

  // User bubble
  userBubbleWrap: {
    alignItems: 'flex-end',
    marginBottom: 4,
  },
  userBubble: {
    backgroundColor: Colors.green + '22',
    borderWidth:     1,
    borderColor:     Colors.green + '44',
    borderRadius:    16,
    borderBottomRightRadius: 4,
    paddingHorizontal: 14,
    paddingVertical:   10,
    maxWidth:        '82%',
  },
  userBubbleText: {
    color:    Colors.textPrimary,
    fontSize: 15,
    lineHeight: 22,
  },

  // Assistant bubble
  assistantBubbleWrap: {
    alignItems:  'flex-start',
    marginBottom: 4,
    maxWidth:    '90%',
  },
  assistantHeader: {
    flexDirection: 'row',
    alignItems:    'center',
    marginBottom:  4,
    gap:           6,
  },
  assistantLabel: {
    color:      Colors.green,
    fontSize:   12,
    fontWeight: '700',
    letterSpacing: 1.2,
  },
  errorBadge: {
    color:    Colors.red ?? '#ef4444',
    fontSize: 11,
  },
  assistantBubble: {
    backgroundColor: Colors.surface,
    borderWidth:     1,
    borderColor:     Colors.border,
    borderRadius:    16,
    borderBottomLeftRadius: 4,
    paddingHorizontal: 14,
    paddingVertical:   10,
    minWidth:        60,
    minHeight:       42,
    justifyContent:  'center',
  },
  assistantBubbleText: {
    color:    Colors.textPrimary,
    fontSize: 15,
    lineHeight: 23,
  },
  cursor: {
    color:    Colors.green,
    fontSize: 15,
  },

  // Meta row
  metaRow: {
    flexDirection: 'row',
    flexWrap:      'wrap',
    gap:           4,
    marginTop:     4,
  },
  metaBadge: {
    borderWidth:   1,
    borderRadius:  4,
    paddingHorizontal: 5,
    paddingVertical:   1,
  },
  metaBadgeText: {
    fontSize: 10,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },

  // Context refs
  refChipsRow: {
    flexDirection: 'row',
    flexWrap:      'wrap',
    gap:           4,
    marginTop:     6,
  },
  refChip: {
    borderWidth:       1,
    borderRadius:      10,
    paddingHorizontal: 7,
    paddingVertical:   2,
  },
  refChipText: {
    fontSize: 10,
  },

  // Voice button
  voiceBtnWrap: {
    alignItems: 'center',
    gap:        2,
  },
  voiceBtn: {
    width:           44,
    height:          44,
    borderRadius:    22,
    backgroundColor: Colors.surface,
    borderWidth:     1,
    borderColor:     Colors.border,
    alignItems:      'center',
    justifyContent:  'center',
  },
  voiceBtnActive: {
    backgroundColor: Colors.red + '22',
    borderColor:     Colors.red,
  },
  voiceBtnProcessing: {
    backgroundColor: Colors.green + '22',
    borderColor:     Colors.green,
  },
  voiceBtnDisabled: {
    opacity: 0.4,
  },
  voiceBtnIcon: {
    fontSize:   20,
    color:      Colors.textMuted,
    lineHeight: 24,
  },
  voiceBtnHint: {
    fontSize: 9,
    color:    Colors.green,
    textAlign: 'center',
    maxWidth:  50,
  },

  // Suggested questions
  suggestedWrap: {
    flex:    1,
    padding: 24,
    justifyContent: 'center',
    gap:     12,
  },
  suggestedTitle: {
    color:      Colors.textPrimary,
    fontSize:   22,
    fontWeight: '700',
    marginBottom: 4,
  },
  suggestedSub: {
    color:    Colors.textMuted,
    fontSize: 14,
    marginBottom: 8,
  },
  suggestedBtn: {
    backgroundColor: Colors.surface,
    borderWidth:     1,
    borderColor:     Colors.border,
    borderRadius:    10,
    padding:         12,
  },
  suggestedBtnText: {
    color:    Colors.textPrimary,
    fontSize: 14,
  },

  // Input bar
  inputBar: {
    flexDirection:   'row',
    alignItems:      'flex-end',
    gap:             8,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderTopWidth:  1,
    borderTopColor:  Colors.border,
    backgroundColor: Colors.bg,
  },
  input: {
    flex:            1,
    backgroundColor: Colors.surface,
    borderWidth:     1,
    borderColor:     Colors.border,
    borderRadius:    20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    color:           Colors.textPrimary,
    fontSize:        15,
    maxHeight:       120,
    lineHeight:      22,
  },
  sendBtn: {
    width:           44,
    height:          44,
    borderRadius:    22,
    backgroundColor: Colors.green,
    alignItems:      'center',
    justifyContent:  'center',
  },
  sendBtnDisabled: {
    backgroundColor: Colors.border,
  },
  sendBtnText: {
    color:    Colors.bg,
    fontSize: 16,
    fontWeight: '700',
  },

  // Modal
  modalOverlay: {
    flex:            1,
    backgroundColor: 'rgba(0,0,0,0.6)',
    justifyContent:  'flex-end',
  },
  modalSheet: {
    backgroundColor: Colors.surface,
    borderTopLeftRadius:  20,
    borderTopRightRadius: 20,
    paddingTop:      16,
    paddingBottom:   32,
    maxHeight:       '70%',
  },
  modalHeader: {
    flexDirection:   'row',
    alignItems:      'center',
    justifyContent:  'space-between',
    paddingHorizontal: 20,
    paddingBottom:   12,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
    marginBottom:    8,
  },
  modalTitle: {
    color:      Colors.textPrimary,
    fontSize:   17,
    fontWeight: '700',
  },
  newSessionBtn: {
    backgroundColor: Colors.green + '22',
    borderWidth:     1,
    borderColor:     Colors.green,
    borderRadius:    8,
    paddingHorizontal: 12,
    paddingVertical:   6,
  },
  newSessionBtnText: {
    color:      Colors.green,
    fontSize:   13,
    fontWeight: '600',
  },
  sessionRow: {
    paddingHorizontal: 20,
    paddingVertical:   12,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  sessionRowActive: {
    backgroundColor: Colors.green + '11',
  },
  sessionRowTitle: {
    color:      Colors.textPrimary,
    fontSize:   15,
    fontWeight: '500',
    marginBottom: 2,
  },
  sessionRowMeta: {
    flexDirection: 'row',
    gap:           12,
  },
  sessionRowSub: {
    color:    Colors.textMuted,
    fontSize: 12,
  },
  emptyText: {
    color:    Colors.textMuted,
    fontSize: 14,
    textAlign: 'center',
    paddingVertical: 32,
  },

  // Proactive agent badge
  proactiveBadge: {
    fontSize:      9,
    color:         Colors.amber,
    borderWidth:   1,
    borderColor:   Colors.amber,
    borderRadius:  4,
    paddingHorizontal: 4,
    paddingVertical:   1,
    marginLeft:    6,
  },

  // Approval banner
  approvalBanner: {
    backgroundColor: Colors.surface,
    borderTopWidth:  1,
    borderTopColor:  Colors.amber,
    paddingHorizontal: 16,
    paddingVertical:   12,
  },
  approvalTitle: {
    color:      Colors.amber,
    fontSize:   11,
    fontWeight: '700',
    letterSpacing: 0.5,
    marginBottom: 4,
  },
  approvalPrompt: {
    color:      Colors.textPrimary,
    fontSize:   14,
    marginBottom: 10,
    lineHeight: 20,
  },
  approvalBtns: {
    flexDirection: 'row',
    gap:           10,
    justifyContent: 'flex-end',
  },
  approvalBtn: {
    paddingHorizontal: 20,
    paddingVertical:   8,
    borderRadius:      8,
    borderWidth:       1,
  },
  approvalDenyBtn: {
    borderColor: Colors.border,
  },
  approvalAllowBtn: {
    backgroundColor: Colors.green,
    borderColor:     Colors.green,
  },
  approvalBtnText: {
    fontSize:   14,
    fontWeight: '600',
    color:      Colors.textPrimary,
  },
});
