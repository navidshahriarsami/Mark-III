import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db import Snapshot
from app.schemas.snapshot import SnapshotRequest, SnapshotResponse

logger = logging.getLogger("markiii.server.snapshots")
router = APIRouter(prefix="/snapshot", tags=["snapshots"])

_NOTABLE = {"distraction", "unknown"}


@router.post("", response_model=SnapshotResponse)
async def ingest_snapshot(
    body: SnapshotRequest,
    db: AsyncSession = Depends(get_db),
):
    snap = Snapshot(
        device_id      = body.device_id,
        ts             = body.ts,
        process_name   = body.process_name,
        window_title   = body.window_title,
        classification = body.classification,
        is_browser     = body.is_browser,
        active_domain  = body.active_domain,
        ocr_text       = body.ocr_text,
    )
    db.add(snap)

    log = logger.warning if body.classification in _NOTABLE else logger.info
    log(
        "Snapshot  device=%-16s  class=%-14s  process=%-22s  domain=%s",
        body.device_id[:16],
        body.classification,
        body.process_name,
        body.active_domain or "-",
    )

    return SnapshotResponse(device_id=body.device_id)
