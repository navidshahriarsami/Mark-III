import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db import Device
from app.schemas.device import DeviceRegisterRequest, DeviceRegisterResponse

logger = logging.getLogger("markiii.server.devices")
router = APIRouter(prefix="/devices", tags=["devices"])


# ---------------------------------------------------------------------------
# Schemas specific to this file
# ---------------------------------------------------------------------------

class PushTokenRequest(BaseModel):
    mobile_device_id: str
    expo_push_token:  str
    platform:         str


class DeviceListItem(BaseModel):
    device_id:       str
    hostname:        str
    platform:        str
    heartbeat_count: int
    last_seen:       float


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/register", response_model=DeviceRegisterResponse)
async def register_device(
    body: DeviceRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Device).where(Device.device_id == body.device_id))
    device = result.scalar_one_or_none()

    if device:
        device.hostname  = body.hostname
        device.platform  = body.platform
        device.version   = body.version
        device.last_seen = time.time()
        action = "updated"
    else:
        device = Device(
            device_id = body.device_id,
            hostname  = body.hostname,
            platform  = body.platform,
            version   = body.version,
        )
        db.add(device)
        action = "new"

    await db.flush()

    count_result = await db.execute(select(func.count()).select_from(Device))
    total = count_result.scalar_one()

    logger.info(
        "Device %s  id=%s  host=%s  total_devices=%d",
        action, device.device_id[:16], device.hostname, total,
    )

    return DeviceRegisterResponse(
        device_id = device.device_id,
        message   = f"Welcome back, {device.hostname}. MARK III online.",
    )


@router.get("", response_model=list[DeviceListItem])
async def list_devices(db: AsyncSession = Depends(get_db)):
    """Mobile app: fetch all registered devices."""
    result = await db.execute(select(Device).order_by(Device.last_seen.desc()))
    devices = result.scalars().all()
    return [
        DeviceListItem(
            device_id       = d.device_id,
            hostname        = d.hostname,
            platform        = d.platform,
            heartbeat_count = d.heartbeat_count,
            last_seen       = d.last_seen,
        )
        for d in devices
    ]


@router.post("/register-push-token")
async def register_push_token(
    body: PushTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Mobile app registers its Expo push token here after boot.
    The brain server stores this and uses it for FCM fan-out on breach alerts.
    We match on expo_push_token so re-installs update the existing row.
    """
    result = await db.execute(
        select(Device).where(Device.expo_push_token == body.expo_push_token)
    )
    device = result.scalar_one_or_none()

    if device is None:
        # First registration — create a synthetic mobile device record
        device = Device(
            device_id       = f"mobile-{body.mobile_device_id[:32]}",
            hostname        = body.mobile_device_id,
            platform        = body.platform,
            version         = "expo",
            expo_push_token = body.expo_push_token,
            mobile_platform = body.platform,
        )
        db.add(device)
        logger.info("Mobile push token registered. platform=%s", body.platform)
    else:
        device.mobile_platform = body.platform
        device.last_seen       = time.time()
        logger.info("Mobile push token refreshed. device_id=%s", device.device_id[:16])

    return {"status": "registered"}
