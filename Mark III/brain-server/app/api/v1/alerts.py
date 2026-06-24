"""
MARK III — Breach Alert Ingestion

The daemon's RabbitHoleDetector POSTs here the moment a distraction
threshold is crossed. This route:
  1. Persists the breach record to the database.
  2. Resolves the device hostname for a human-readable notification.
  3. Fires a push notification via the configured backend (Pushover / FCM / log).
  4. Returns a receipt so the daemon knows delivery succeeded.
"""

import logging
import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import desc

from app.database import get_db
from app.models.db import BreachLog, Device
from app.schemas.breach import BreachReportRequest, BreachReportResponse
from app.services.notification import BreachAlert

logger = logging.getLogger("markiii.server.alerts")
router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/breaches")
async def list_breaches(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Mobile app: fetch breach history, newest first."""
    result = await db.execute(
        select(BreachLog).order_by(desc(BreachLog.ts)).limit(limit)
    )
    breaches = result.scalars().all()
    return [
        {
            "id":            b.id,
            "device_id":     b.device_id,
            "ts":            b.ts,
            "keyword":       b.keyword,
            "duration_min":  b.duration_min,
            "process_name":  b.process_name,
            "active_domain": b.active_domain,
            "notif_sent":    b.notif_sent,
            "notif_provider":b.notif_provider,
        }
        for b in breaches
    ]


@router.post("/breach", response_model=BreachReportResponse)
async def report_breach(
    body: BreachReportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # Resolve hostname for the notification message
    result  = await db.execute(select(Device).where(Device.device_id == body.device_id))
    device  = result.scalar_one_or_none()
    hostname = device.hostname if device else body.device_id[:16]

    # Persist the breach
    breach = BreachLog(
        device_id    = body.device_id,
        ts           = time.time(),
        keyword      = body.keyword,
        duration_min = body.duration_min,
        process_name = body.process_name,
        active_domain = body.active_domain,
    )
    db.add(breach)
    await db.flush()   # get breach.id before notification

    logger.warning(
        "BREACH  device=%s  host=%s  keyword=%r  duration=%.1f min  domain=%s",
        body.device_id[:16], hostname, body.keyword,
        body.duration_min, body.active_domain or "-",
    )

    # Fire push notification via the service attached to app.state at startup
    notif_service = request.app.state.notification_service
    alert = BreachAlert(
        device_id    = body.device_id,
        hostname     = hostname,
        keyword      = body.keyword,
        duration_min = body.duration_min,
        process_name = body.process_name,
        active_domain = body.active_domain,
    )
    notif_sent, receipt = await notif_service.send_breach_alert(alert)

    # Update breach record with notification outcome
    breach.notif_sent     = notif_sent
    breach.notif_provider = notif_service.backend_name
    breach.notif_receipt  = receipt[:256] if receipt else None

    logger.info(
        "Breach #%d persisted. notif_sent=%s  provider=%s  receipt=%s",
        breach.id, notif_sent, notif_service.backend_name, receipt,
    )

    return BreachReportResponse(
        notif_sent     = notif_sent,
        notif_provider = notif_service.backend_name,
        breach_id      = breach.id,
    )
