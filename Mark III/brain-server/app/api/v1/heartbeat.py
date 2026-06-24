import logging
import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db import Device, HeartbeatLog
from app.schemas.heartbeat import HeartbeatRequest, HeartbeatResponse

logger = logging.getLogger("markiii.server.heartbeat")
router = APIRouter(prefix="/heartbeat", tags=["heartbeat"])


@router.post("", response_model=HeartbeatResponse)
async def receive_heartbeat(
    body: HeartbeatRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Device).where(Device.device_id == body.device_id)
    )
    device = result.scalar_one_or_none()

    if device is None:
        logger.warning("Heartbeat from unregistered device %s — auto-registering.", body.device_id[:16])
        device = Device(
            device_id = body.device_id,
            hostname  = "unknown",
            platform  = "unknown",
            version   = "unknown",
        )
        db.add(device)
        await db.flush()

    device.last_seen       = time.time()
    device.heartbeat_count += 1

    db.add(HeartbeatLog(
        device_id = body.device_id,
        ts        = body.ts,
        uptime_s  = body.uptime_s,
    ))

    logger.debug(
        "Heartbeat  device=%s  uptime=%.0f s  count=%d",
        body.device_id[:16], body.uptime_s, device.heartbeat_count,
    )

    return HeartbeatResponse(server_ts=time.time())
