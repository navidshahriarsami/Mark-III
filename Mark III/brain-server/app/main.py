"""
MARK III â€” Unified Brain Server (Phase 5: PostgreSQL + Push Notifications)

Boot:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Interactive API docs:
    http://localhost:8000/docs
"""

import asyncio
import logging
import logging.config
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, desc

from app.config import settings
from app.api.v1.router import router as v1_router
from app.database import create_all_tables, AsyncSessionLocal
from app.middleware.logging import RequestLogMiddleware
from app.models.db import Device, Snapshot, Command, BreachLog, UserContext, Recommendation, AIInsight, ReasoningLog, ProviderUsage, AIConversation, ConversationSession, ConversationMessage, ContextReference, VoiceSession, VoiceUtterance, ActionRecord, ActionApproval, AgentRun
from app.services.notification import build_notification_service
from app.services.context_engine import derive_context
from app.services.recommendation_engine import generate_recommendations
from app.services.report_engine import PRODUCTIVE_CLASSES, DISTRACTION_CLASSES, INTERVAL_MIN

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s  %(name)-36s  %(levelname)-8s  %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class":     "logging.StreamHandler",
            "stream":    "ext://sys.stdout",
            "formatter": "default",
        },
        "file": {
            "class":       "logging.handlers.RotatingFileHandler",
            "filename":    "logs/brain_server.log",
            "maxBytes":    5_000_000,
            "backupCount": 3,
            "formatter":   "default",
            "encoding":    "utf-8",
        },
    },
    "loggers": {
        "markiii": {
            "handlers":  ["console", "file"],
            "level":     settings.log_level,
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers":  [],
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level":    "WARNING",
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("markiii.server")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

_WORK_BLOCKS     = [{"start": 9, "end": 12}, {"start": 13, "end": 17}]
_CONTEXT_WINDOW  = 900   # seconds
_CONTEXT_INTERVAL = 60   # run every 60 s


async def _context_loop() -> None:
    """
    Background task: every 60 s, derive cognitive context for every registered
    device and persist a UserContext row + fresh Recommendations.
    """
    await asyncio.sleep(10)   # let the server finish booting first
    while True:
        try:
            async with AsyncSessionLocal() as db:
                devices_result = await db.execute(select(Device))
                devices        = devices_result.scalars().all()

                for device in devices:
                    cutoff      = time.time() - _CONTEXT_WINDOW
                    snap_result = await db.execute(
                        select(Snapshot)
                        .where(Snapshot.device_id == device.device_id)
                        .where(Snapshot.ts >= cutoff)
                        .order_by(desc(Snapshot.ts))
                        .limit(120)
                    )
                    snapshots = snap_result.scalars().all()
                    ctx       = derive_context(snapshots, _WORK_BLOCKS)

                    # Persist context snapshot
                    db.add(UserContext(
                        device_id               = device.device_id,
                        ts                      = time.time(),
                        current_task            = ctx.current_task,
                        productivity_state      = ctx.productivity_state.value,
                        confidence              = ctx.confidence,
                        suggested_action        = ctx.suggested_action,
                        dominant_app            = ctx.dominant_app,
                        dominant_classification = ctx.dominant_classification,
                        window_count            = ctx.window_count,
                        is_work_block           = ctx.is_work_block,
                    ))

                    # Today's metrics for recommendations
                    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                    today_result = await db.execute(
                        select(Snapshot)
                        .where(Snapshot.device_id == device.device_id)
                        .where(Snapshot.ts >= today_start)
                    )
                    today_rows        = today_result.scalars().all()
                    productive_today  = sum(INTERVAL_MIN for s in today_rows if (s.classification or "unknown") in PRODUCTIVE_CLASSES)
                    distraction_today = sum(INTERVAL_MIN for s in today_rows if (s.classification or "unknown") in DISTRACTION_CLASSES)

                    recs = generate_recommendations(
                        state                     = ctx.productivity_state,
                        is_work_block             = ctx.is_work_block,
                        distraction_minutes_today = distraction_today,
                        productive_minutes_today  = productive_today,
                    )
                    for item in recs:
                        db.add(Recommendation(
                            device_id     = device.device_id,
                            ts            = time.time(),
                            text          = item.text,
                            category      = item.category,
                            priority      = item.priority,
                            context_state = item.context_state,
                        ))

                    logger.info(
                        "Context  device=%s  state=%s  conf=%.2f  work_block=%s",
                        device.device_id[:16], ctx.productivity_state.value,
                        ctx.confidence, ctx.is_work_block,
                    )

                await db.commit()

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Context loop error: %s", exc)

        await asyncio.sleep(_CONTEXT_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("MARK III Brain Server starting (Phase 11 â€” Voice Core).")
    logger.info("  host     : %s:%d",   settings.host, settings.port)
    logger.info("  database : %s",      settings.database_url.split("@")[-1])
    logger.info("  notif    : %s",      settings.notification_backend)
    logger.info("=" * 60)

    await create_all_tables()
    logger.info("Database tables verified.")

    app.state.notification_service = build_notification_service()

    context_task = asyncio.create_task(_context_loop(), name="cognitive-context-loop")
    logger.info("Cognitive context loop started (interval=%ds).", _CONTEXT_INTERVAL)

    # Action Queue â€” start background worker
    from app.services.actions.action_queue import get_action_queue
    from app.database import AsyncSessionLocal as _AsyncSessionLocal
    from contextlib import asynccontextmanager as _acm

    action_queue = get_action_queue()

    @_acm
    async def _db_factory():
        async with _AsyncSessionLocal() as session:
            yield session

    action_queue.set_db_factory(_db_factory)
    await action_queue.start()
    logger.info("Action Queue started.")

    # Agent System â€” bootstrap + start scheduler
    from app.services.agents.agent_manager import bootstrap_agents
    _agent_manager, _agent_scheduler = bootstrap_agents(_db_factory)
    await _agent_scheduler.start()
    logger.info("Agent System started (%d agents).", len(_agent_manager._agents))

    # Voice Core â€” start daemon + register local desktop device
    from app.services.voice.voice_daemon import get_voice_daemon
    from app.services.voice.presence_manager import get_presence_manager
    from app.config import settings as _settings
    import socket as _socket

    voice_daemon = get_voice_daemon()
    await voice_daemon.start()
    if _settings.voice_enabled:
        hostname = _socket.gethostname()
        get_presence_manager().register_desktop(
            device_id     = hostname,
            name          = f"Desktop ({hostname})",
            mic_index     = None if _settings.default_mic_index < 0 else _settings.default_mic_index,
            speaker_index = None if _settings.default_speaker_index < 0 else _settings.default_speaker_index,
        )
        logger.info("Voice Core ready  host=%s  mode=%s", hostname, _settings.voice_mode)
    else:
        logger.info("Voice Core loaded (disabled â€” set VOICE_ENABLED=true in .env to activate)")

    yield

    context_task.cancel()
    try:
        await context_task
    except asyncio.CancelledError:
        pass

    await voice_daemon.stop()
    await action_queue.stop()
    await _agent_scheduler.stop()

    logger.info("Brain server shutting down.")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title       = "MARK III Brain Server",
    description = "Central coordinator for the MARK III AI assistant.",
    version     = "0.14.0",
    docs_url    = "/docs",
    redoc_url   = "/redoc",
    lifespan    = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = settings.cors_origins,
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)
app.add_middleware(RequestLogMiddleware)
app.include_router(v1_router)


# ---------------------------------------------------------------------------
# Status endpoint â€” live DB stats
# ---------------------------------------------------------------------------

_SERVER_START = time.time()


@app.get("/status", tags=["meta"])
async def status():
    async with AsyncSessionLocal() as db:
        device_count   = (await db.execute(select(func.count()).select_from(Device))).scalar_one()
        snapshot_count = (await db.execute(select(func.count()).select_from(Snapshot))).scalar_one()
        command_count  = (await db.execute(select(func.count()).select_from(Command))).scalar_one()
        breach_count   = (await db.execute(select(func.count()).select_from(BreachLog))).scalar_one()

        recent_result  = await db.execute(
            select(Snapshot).order_by(Snapshot.ts.desc()).limit(5)
        )
        recent = recent_result.scalars().all()

    return {
        "status":           "ok",
        "server_ts":        time.time(),
        "uptime_s":         round(time.time() - _SERVER_START, 1),
        "database":         settings.database_url.split("///")[-1],
        "notification":     settings.notification_backend,
        "devices_online":   device_count,
        "snapshots_total":  snapshot_count,
        "commands_total":   command_count,
        "breaches_total":   breach_count,
        "recent_snapshots": [
            {
                "device_id":      s.device_id[:16],
                "process":        s.process_name,
                "classification": s.classification,
                "domain":         s.active_domain,
                "ts":             s.ts,
            }
            for s in recent
        ],
    }


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "MARK III Brain Server v0.5. See /docs."}
