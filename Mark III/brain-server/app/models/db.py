"""
MARK III Brain Server — SQLAlchemy ORM Models

Table layout:
  devices       — one row per registered daemon installation
  heartbeat_log — time-series of daemon heartbeats
  snapshots     — classified foreground-window events from daemons
  commands      — privileged command queue + HITL approval state
  breach_log    — rabbit-hole threshold crossings + notification receipts
"""

import time
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Float, ForeignKey,
    Integer, String, Text, JSON, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Device(Base):
    __tablename__ = "devices"

    id:               Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:        Mapped[str]   = mapped_column(String(64),  unique=True, nullable=False, index=True)
    hostname:         Mapped[str]   = mapped_column(String(128), nullable=False)
    platform:         Mapped[str]   = mapped_column(String(64),  nullable=False)
    version:          Mapped[str]   = mapped_column(Text,        nullable=False)
    registered_at:    Mapped[float] = mapped_column(Float, default=time.time)
    last_seen:        Mapped[float] = mapped_column(Float, default=time.time)
    heartbeat_count:  Mapped[int]   = mapped_column(Integer, default=0)

    expo_push_token:  Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    mobile_platform:  Mapped[Optional[str]] = mapped_column(String(32),  nullable=True)

    heartbeats: Mapped[list["HeartbeatLog"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    snapshots:  Mapped[list["Snapshot"]]     = relationship(back_populates="device", cascade="all, delete-orphan")
    commands:   Mapped[list["Command"]]      = relationship(back_populates="device", cascade="all, delete-orphan")
    breaches:   Mapped[list["BreachLog"]]    = relationship(back_populates="device", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Device {self.device_id[:8]}… host={self.hostname}>"


class HeartbeatLog(Base):
    __tablename__ = "heartbeat_log"

    id:        Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str]   = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    ts:        Mapped[float] = mapped_column(Float, nullable=False, index=True)
    uptime_s:  Mapped[float] = mapped_column(Float, nullable=False)

    device: Mapped["Device"] = relationship(back_populates="heartbeats")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id:             Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:      Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    ts:             Mapped[float]         = mapped_column(Float,   nullable=False, index=True)
    process_name:   Mapped[str]           = mapped_column(String(128), nullable=False)
    window_title:   Mapped[str]           = mapped_column(String(256), nullable=False)
    classification: Mapped[str]           = mapped_column(String(32),  nullable=False, index=True)
    is_browser:     Mapped[bool]          = mapped_column(Boolean, nullable=False)
    active_domain:  Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    ocr_text:       Mapped[Optional[str]] = mapped_column(Text,         nullable=True)

    device: Mapped["Device"] = relationship(back_populates="snapshots")


class Command(Base):
    __tablename__ = "commands"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id:  Mapped[str]           = mapped_column(String(64),  unique=True, nullable=False, index=True)
    device_id:   Mapped[str]           = mapped_column(String(64),  ForeignKey("devices.device_id"), nullable=False, index=True)
    raw:         Mapped[str]           = mapped_column(Text,        nullable=False)
    requester:   Mapped[str]           = mapped_column(String(64),  nullable=False)
    queued_at:   Mapped[float]         = mapped_column(Float,       default=time.time)
    status:      Mapped[str]           = mapped_column(String(16),  nullable=False, default="pending")  # pending|approved|denied
    stdout:      Mapped[str]           = mapped_column(Text,        nullable=False, default="")
    stderr:      Mapped[str]           = mapped_column(Text,        nullable=False, default="")
    returncode:  Mapped[Optional[int]] = mapped_column(Integer,     nullable=True)

    device: Mapped["Device"] = relationship(back_populates="commands")


class BreachLog(Base):
    """
    Written every time the rabbit-hole detector crosses the 15-minute threshold.
    Tracks what keyword triggered the breach, how long the user was on it,
    and whether the push notification was delivered successfully.
    """
    __tablename__ = "breach_log"

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:       Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    ts:              Mapped[float]         = mapped_column(Float,      nullable=False, index=True, default=time.time)
    keyword:         Mapped[str]           = mapped_column(String(128), nullable=False)
    duration_min:    Mapped[float]         = mapped_column(Float,       nullable=False)
    process_name:    Mapped[str]           = mapped_column(String(128), nullable=False)
    active_domain:   Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notif_sent:      Mapped[bool]          = mapped_column(Boolean,     nullable=False, default=False)
    notif_provider:  Mapped[Optional[str]] = mapped_column(String(32),  nullable=True)
    notif_receipt:   Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    device: Mapped["Device"] = relationship(back_populates="breaches")


# ---------------------------------------------------------------------------
# Phase 7 — Cognitive Engine tables
# ---------------------------------------------------------------------------

class UserContext(Base):
    """
    Snapshot of the derived cognitive state for a device, written every 60s
    by the background context loop.
    """
    __tablename__ = "user_contexts"

    id:                      Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:               Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    ts:                      Mapped[float]         = mapped_column(Float, nullable=False, index=True, default=time.time)
    current_task:            Mapped[str]           = mapped_column(String(128), nullable=False)
    productivity_state:      Mapped[str]           = mapped_column(String(64),  nullable=False, index=True)
    confidence:              Mapped[float]         = mapped_column(Float, default=0.0)
    suggested_action:        Mapped[str]           = mapped_column(Text, nullable=False)
    dominant_app:            Mapped[str]           = mapped_column(String(128), nullable=False, default="")
    dominant_classification: Mapped[str]           = mapped_column(String(32),  nullable=False, default="")
    window_count:            Mapped[int]           = mapped_column(Integer, default=0)
    is_work_block:           Mapped[bool]          = mapped_column(Boolean, default=False)


class DailyReport(Base):
    """
    Aggregated productivity metrics for one calendar day per device.
    Generated on-demand and cached; regenerated if snapshots arrive late.
    """
    __tablename__ = "daily_reports"

    id:                  Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:           Mapped[str]   = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    date:                Mapped[str]   = mapped_column(String(10), nullable=False, index=True)   # YYYY-MM-DD
    productive_minutes:  Mapped[float] = mapped_column(Float, default=0.0)
    distraction_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    focus_score:         Mapped[float] = mapped_column(Float, default=0.0)   # 0–100
    major_activities:    Mapped[dict]  = mapped_column(JSON,  nullable=True)
    top_apps:            Mapped[dict]  = mapped_column(JSON,  nullable=True)
    hourly_breakdown:    Mapped[dict]  = mapped_column(JSON,  nullable=True)
    recommendations:     Mapped[dict]  = mapped_column(JSON,  nullable=True)
    snapshot_count:      Mapped[int]   = mapped_column(Integer, default=0)
    generated_at:        Mapped[float] = mapped_column(Float, default=time.time)


class WeeklyReport(Base):
    """
    Aggregated productivity metrics for one ISO week per device.
    """
    __tablename__ = "weekly_reports"

    id:                            Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:                     Mapped[str]   = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    week_start:                    Mapped[str]   = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD Monday
    week_end:                      Mapped[str]   = mapped_column(String(10), nullable=False)
    focus_score:                   Mapped[float] = mapped_column(Float, default=0.0)
    productivity_trend:            Mapped[str]   = mapped_column(String(32), nullable=False, default="stable")
    avg_daily_productive_minutes:  Mapped[float] = mapped_column(Float, default=0.0)
    avg_daily_distraction_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    daily_scores:                  Mapped[dict]  = mapped_column(JSON, nullable=True)
    top_applications:              Mapped[dict]  = mapped_column(JSON, nullable=True)
    top_classifications:           Mapped[dict]  = mapped_column(JSON, nullable=True)
    improvement_suggestions:       Mapped[dict]  = mapped_column(JSON, nullable=True)
    snapshot_count:                Mapped[int]   = mapped_column(Integer, default=0)
    generated_at:                  Mapped[float] = mapped_column(Float, default=time.time)


class Recommendation(Base):
    """
    Prioritised action suggestions derived from current context + daily stats.
    """
    __tablename__ = "recommendations"

    id:             Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:      Mapped[str]  = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    ts:             Mapped[float]= mapped_column(Float, nullable=False, index=True, default=time.time)
    text:           Mapped[str]  = mapped_column(Text,        nullable=False)
    category:       Mapped[str]  = mapped_column(String(32),  nullable=False)  # focus|break|career|health|admin
    priority:       Mapped[int]  = mapped_column(Integer, default=0)            # 0=low 1=medium 2=high
    context_state:  Mapped[str]  = mapped_column(String(64),  nullable=False, default="")
    dismissed:      Mapped[bool] = mapped_column(Boolean, default=False)
    acted_on:       Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------
# Phase 8 — Memory Engine tables
# ---------------------------------------------------------------------------

class UserProfile(Base):
    """
    One row per device. Stores the human context behind the machine.
    """
    __tablename__ = "user_profiles"

    id:                   Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:            Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), unique=True, nullable=False, index=True)
    name:                 Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    career:               Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    interests:            Mapped[Optional[dict]]= mapped_column(JSON, nullable=True)       # list[str]
    goals_summary:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preferences:          Mapped[Optional[dict]]= mapped_column(JSON, nullable=True)       # dict
    work_schedule:        Mapped[Optional[dict]]= mapped_column(JSON, nullable=True)       # {timezone, start, end, days}
    learning_objectives:  Mapped[Optional[dict]]= mapped_column(JSON, nullable=True)       # list[str]
    created_at:           Mapped[float]         = mapped_column(Float, default=time.time)
    updated_at:           Mapped[float]         = mapped_column(Float, default=time.time, onupdate=time.time)


class LongTermGoal(Base):
    """
    A persistent goal with category, measurable progress, and optional deadline.
    """
    __tablename__ = "long_term_goals"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:   Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    title:       Mapped[str]           = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category:    Mapped[str]           = mapped_column(String(32),  nullable=False, index=True)
    # career | research | health | financial | personal | learning
    status:      Mapped[str]           = mapped_column(String(16),  nullable=False, default="active", index=True)
    # active | paused | completed | abandoned
    progress:    Mapped[int]           = mapped_column(Integer, default=0)   # 0–100
    target_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    notes:       Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at:  Mapped[float]         = mapped_column(Float, default=time.time)
    updated_at:  Mapped[float]         = mapped_column(Float, default=time.time)


class Project(Base):
    """
    A bounded piece of work linked optionally to a LongTermGoal.
    """
    __tablename__ = "projects"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:   Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    goal_id:     Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("long_term_goals.id"), nullable=True)
    name:        Mapped[str]           = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status:      Mapped[str]           = mapped_column(String(16),  nullable=False, default="active", index=True)
    # planning | active | paused | completed | abandoned
    progress:    Mapped[int]           = mapped_column(Integer, default=0)   # 0–100
    deadline:    Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    notes:       Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at:  Mapped[float]         = mapped_column(Float, default=time.time)
    updated_at:  Mapped[float]         = mapped_column(Float, default=time.time)


class Memory(Base):
    """
    An atomic memory: event, decision, instruction, achievement, or note.
    Full-text search runs over title + content + tags.
    """
    __tablename__ = "memories"

    id:           Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:    Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    project_id:   Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    goal_id:      Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("long_term_goals.id"), nullable=True, index=True)
    ts:           Mapped[float]         = mapped_column(Float, nullable=False, default=time.time, index=True)
    title:        Mapped[str]           = mapped_column(String(256), nullable=False)
    content:      Mapped[str]           = mapped_column(Text,        nullable=False)
    memory_type:  Mapped[str]           = mapped_column(String(32),  nullable=False, default="note", index=True)
    # event | decision | instruction | achievement | conversation | note
    importance:   Mapped[int]           = mapped_column(Integer, default=3)  # 1=low … 5=critical
    tags:         Mapped[Optional[dict]]= mapped_column(JSON, nullable=True)  # list[str]
    created_at:   Mapped[float]         = mapped_column(Float, default=time.time)


# ---------------------------------------------------------------------------
# Phase 9 — AI Provider Layer tables
# ---------------------------------------------------------------------------

class AIInsight(Base):
    """
    Cached output of a reasoning call — one row per (device, task_type).
    Used as a TTL cache so repeat calls don't re-invoke the LLM.
    """
    __tablename__ = "ai_insights"

    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:     Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    task_type:     Mapped[str]           = mapped_column(String(64),  nullable=False, index=True)
    text:          Mapped[str]           = mapped_column(Text,        nullable=False)
    provider:      Mapped[str]           = mapped_column(String(32),  nullable=False)
    model:         Mapped[str]           = mapped_column(String(64),  nullable=False, default="")
    input_tokens:  Mapped[int]           = mapped_column(Integer,     default=0)
    output_tokens: Mapped[int]           = mapped_column(Integer,     default=0)
    cost_usd:      Mapped[float]         = mapped_column(Float,       default=0.0)
    generated_at:  Mapped[float]         = mapped_column(Float,       default=time.time, index=True)


class ReasoningLog(Base):
    """
    Full audit trail of every LLM call MARK III makes.
    Stores latency, tokens, cost, and any error.
    """
    __tablename__ = "reasoning_log"

    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:     Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    ts:            Mapped[float]         = mapped_column(Float, nullable=False, default=time.time, index=True)
    task_type:     Mapped[str]           = mapped_column(String(64),  nullable=False)
    provider:      Mapped[str]           = mapped_column(String(32),  nullable=False)
    model:         Mapped[str]           = mapped_column(String(64),  nullable=False, default="")
    latency_ms:    Mapped[float]         = mapped_column(Float,       default=0.0)
    input_tokens:  Mapped[int]           = mapped_column(Integer,     default=0)
    output_tokens: Mapped[int]           = mapped_column(Integer,     default=0)
    cost_usd:      Mapped[float]         = mapped_column(Float,       default=0.0)
    error:         Mapped[Optional[str]] = mapped_column(Text,        nullable=True)


class ProviderUsage(Base):
    """
    Rolling usage totals per provider/model for cost visibility.
    Each row is one API call.
    """
    __tablename__ = "provider_usage"

    id:            Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts:            Mapped[float] = mapped_column(Float, nullable=False, default=time.time, index=True)
    provider:      Mapped[str]   = mapped_column(String(32), nullable=False, index=True)
    model:         Mapped[str]   = mapped_column(String(64), nullable=False, default="")
    task_type:     Mapped[str]   = mapped_column(String(64), nullable=False, default="")
    input_tokens:  Mapped[int]   = mapped_column(Integer,    default=0)
    output_tokens: Mapped[int]   = mapped_column(Integer,    default=0)
    cost_usd:      Mapped[float] = mapped_column(Float,      default=0.0)


class AIConversation(Base):
    """
    Legacy Phase 9 table — kept for backwards compatibility.
    Phase 10 uses ConversationSession + ConversationMessage instead.
    """
    __tablename__ = "ai_conversations"

    id:         Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id:  Mapped[str]   = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    session_id: Mapped[str]   = mapped_column(String(64), nullable=False, index=True)
    role:       Mapped[str]   = mapped_column(String(16), nullable=False)
    content:    Mapped[str]   = mapped_column(Text,       nullable=False)
    provider:   Mapped[str]   = mapped_column(String(32), nullable=False, default="")
    model:      Mapped[str]   = mapped_column(String(64), nullable=False, default="")
    cost_usd:   Mapped[float] = mapped_column(Float,      default=0.0)
    ts:         Mapped[float] = mapped_column(Float, nullable=False, default=time.time, index=True)


# ---------------------------------------------------------------------------
# Phase 10 — Conversation Engine tables
# ---------------------------------------------------------------------------

class ConversationSession(Base):
    """
    A named conversation thread. One device may have many sessions.
    MARK III owns the session — providers are interchangeable.
    """
    __tablename__ = "conversation_sessions"

    id:             Mapped[str]           = mapped_column(String(64), primary_key=True)   # UUID
    device_id:      Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    title:          Mapped[str]           = mapped_column(String(256), nullable=False, default="New conversation")
    topic_summary:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # rolling LLM summary
    message_count:  Mapped[int]           = mapped_column(Integer, default=0)
    is_active:      Mapped[bool]          = mapped_column(Boolean, default=True)
    provider_used:  Mapped[str]           = mapped_column(String(32), nullable=False, default="")
    total_cost_usd: Mapped[float]         = mapped_column(Float, default=0.0)
    created_at:     Mapped[float]         = mapped_column(Float, default=time.time, index=True)
    updated_at:     Mapped[float]         = mapped_column(Float, default=time.time)


class ConversationMessage(Base):
    """
    One turn in a conversation — either a user message or MARK III response.
    Stores the full provider metadata for cost tracking and auditability.
    """
    __tablename__ = "conversation_messages"

    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id:    Mapped[str]           = mapped_column(String(64), ForeignKey("conversation_sessions.id"), nullable=False, index=True)
    device_id:     Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    role:          Mapped[str]           = mapped_column(String(16), nullable=False, index=True)  # user | assistant | system
    content:       Mapped[str]           = mapped_column(Text, nullable=False)
    provider:      Mapped[str]           = mapped_column(String(32), nullable=False, default="")
    model:         Mapped[str]           = mapped_column(String(64), nullable=False, default="")
    input_tokens:  Mapped[int]           = mapped_column(Integer, default=0)
    output_tokens: Mapped[int]           = mapped_column(Integer, default=0)
    cost_usd:      Mapped[float]         = mapped_column(Float, default=0.0)
    latency_ms:    Mapped[float]         = mapped_column(Float, default=0.0)
    context_hash:  Mapped[Optional[str]] = mapped_column(String(32), nullable=True)   # hash of injected context
    ts:            Mapped[float]         = mapped_column(Float, nullable=False, default=time.time, index=True)


class ContextReference(Base):
    """
    Records which MARK III entities (goal, project, memory, report)
    were injected into the context of a specific conversation message.
    Enables "why did MARK III say that?" auditability.
    """
    __tablename__ = "context_references"

    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int]           = mapped_column(Integer, ForeignKey("conversation_messages.id"), nullable=False, index=True)
    session_id: Mapped[str]           = mapped_column(String(64), ForeignKey("conversation_sessions.id"), nullable=False, index=True)
    ref_type:   Mapped[str]           = mapped_column(String(32), nullable=False)  # goal|project|memory|daily_report|weekly_report|context
    ref_id:     Mapped[Optional[str]] = mapped_column(String(64), nullable=True)   # FK id as string
    ref_title:  Mapped[str]           = mapped_column(String(256), nullable=False)
    ts:         Mapped[float]         = mapped_column(Float, nullable=False, default=time.time)


# ---------------------------------------------------------------------------
# Phase 11 — Voice Core tables
# ---------------------------------------------------------------------------

class VoiceSession(Base):
    """
    One continuous voice interaction session.
    Links to a ConversationSession so voice turns appear in chat history.
    A VoiceSession may span many utterances.
    """
    __tablename__ = "voice_sessions"

    id:              Mapped[str]           = mapped_column(String(64), primary_key=True)          # UUID
    device_id:       Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)             # FK → conversation_sessions
    mode:            Mapped[str]           = mapped_column(String(32), nullable=False, default="push_to_talk")  # push_to_talk | always_listening
    wake_engine:     Mapped[str]           = mapped_column(String(32), nullable=False, default="")
    stt_engine:      Mapped[str]           = mapped_column(String(32), nullable=False, default="faster_whisper")
    tts_engine:      Mapped[str]           = mapped_column(String(32), nullable=False, default="piper")
    mic_name:        Mapped[str]           = mapped_column(String(128), nullable=False, default="")
    speaker_name:    Mapped[str]           = mapped_column(String(128), nullable=False, default="")
    utterance_count: Mapped[int]           = mapped_column(Integer, default=0)
    is_active:       Mapped[bool]          = mapped_column(Boolean, default=True)
    started_at:      Mapped[float]         = mapped_column(Float, nullable=False, default=time.time, index=True)
    ended_at:        Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class VoiceUtterance(Base):
    """
    One spoken exchange: user speech → MARK III response.
    Stores both raw transcript and synthesized response text.
    """
    __tablename__ = "voice_utterances"

    id:                Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    voice_session_id:  Mapped[str]           = mapped_column(String(64), ForeignKey("voice_sessions.id"), nullable=False, index=True)
    conversation_msg_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)            # FK → conversation_messages (assistant turn)
    device_id:         Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    trigger:           Mapped[str]           = mapped_column(String(32), nullable=False, default="wake_word")  # wake_word | push_to_talk | api
    user_transcript:   Mapped[str]           = mapped_column(Text, nullable=False)
    stt_confidence:    Mapped[float]         = mapped_column(Float, default=0.0)
    stt_latency_ms:    Mapped[float]         = mapped_column(Float, default=0.0)
    response_text:     Mapped[str]           = mapped_column(Text, nullable=False, default="")
    tts_latency_ms:    Mapped[float]         = mapped_column(Float, default=0.0)
    total_latency_ms:  Mapped[float]         = mapped_column(Float, default=0.0)   # wake word → audio out
    audio_duration_s:  Mapped[float]         = mapped_column(Float, default=0.0)   # duration of user speech
    ts:                Mapped[float]         = mapped_column(Float, nullable=False, default=time.time, index=True)


# ---------------------------------------------------------------------------
# Phase 12B — Action Engine tables
# ---------------------------------------------------------------------------

class ActionRecord(Base):
    """
    Persistent record for every action submitted to the ActionQueue.
    The in-memory Action object is persisted here on every state transition.
    """
    __tablename__ = "actions"

    id:              Mapped[str]           = mapped_column(String(64), primary_key=True)          # UUID
    action_type:     Mapped[str]           = mapped_column(String(64), nullable=False, index=True)
    safety_level:    Mapped[str]           = mapped_column(String(16), nullable=False)            # safe|caution|dangerous|critical
    parameters_json: Mapped[str]           = mapped_column(Text, nullable=False, default="{}")
    state:           Mapped[str]           = mapped_column(String(32), nullable=False, index=True) # ActionState values
    source:          Mapped[str]           = mapped_column(String(32), nullable=False, default="api")  # conversation|voice|api|schedule
    device_id:       Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    session_id:      Mapped[Optional[str]] = mapped_column(String(64), nullable=True)             # conversation or voice session
    context_hint:    Mapped[str]           = mapped_column(String(256), nullable=False, default="")
    result_json:     Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message:   Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count:     Mapped[int]           = mapped_column(Integer, default=0)
    max_retries:     Mapped[int]           = mapped_column(Integer, default=0)
    timeout_seconds: Mapped[float]         = mapped_column(Float, default=30.0)
    approval_id:     Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    deferred_until:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at:      Mapped[float]         = mapped_column(Float, default=time.time, index=True)
    updated_at:      Mapped[float]         = mapped_column(Float, default=time.time)
    started_at:      Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    completed_at:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class ActionApproval(Base):
    """
    Approval record for DANGEROUS / CRITICAL actions requiring human consent.
    Created by ApprovalManager, presented to user via mobile UI or voice prompt.
    """
    __tablename__ = "action_approvals"

    id:            Mapped[str]           = mapped_column(String(64), primary_key=True)  # UUID
    action_id:     Mapped[str]           = mapped_column(String(64), ForeignKey("actions.id"), nullable=False, index=True)
    device_id:     Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    prompt:        Mapped[str]           = mapped_column(Text, nullable=False)           # "MARK wants to delete X. Allow?"
    verdict:       Mapped[str]           = mapped_column(String(16), nullable=False, default="pending")  # pending|approved|denied
    responded_by:  Mapped[Optional[str]] = mapped_column(String(16), nullable=True)     # mobile|voice|api
    requested_at:  Mapped[float]         = mapped_column(Float, nullable=False, default=time.time, index=True)
    responded_at:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)


# ---------------------------------------------------------------------------
# Phase 13 — Agent System tables
# ---------------------------------------------------------------------------

class AgentRun(Base):
    """
    Audit log of every agent execution.
    Used by scheduler for min_interval enforcement and by the API for history.
    """
    __tablename__ = "agent_runs"

    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id:      Mapped[str]           = mapped_column(String(64), nullable=False, index=True)
    device_id:     Mapped[str]           = mapped_column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    ran_at:        Mapped[float]         = mapped_column(Float, nullable=False, default=time.time, index=True)
    success:       Mapped[bool]          = mapped_column(Boolean, default=True)
    title:         Mapped[str]           = mapped_column(String(128), nullable=False, default="")
    text_snippet:  Mapped[str]           = mapped_column(String(512), nullable=False, default="")
    delivery:      Mapped[str]           = mapped_column(String(128), nullable=False, default="[]")   # JSON list
    priority:      Mapped[str]           = mapped_column(String(16), nullable=False, default="medium")
    latency_ms:    Mapped[float]         = mapped_column(Float, default=0.0)
    error:         Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str]           = mapped_column(Text, nullable=False, default="{}")
