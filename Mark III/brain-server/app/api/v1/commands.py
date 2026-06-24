import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db import Command
from app.schemas.command import (
    PendingCommandRequest, PendingCommandResponse,
    CommandStatusResponse,
    CommandResultRequest, CommandResultResponse,
    PendingCommandsResponse,
)

logger = logging.getLogger("markiii.server.commands")
router = APIRouter(prefix="/commands", tags=["commands"])


@router.post("/pending", response_model=PendingCommandResponse)
async def queue_pending_command(
    body: PendingCommandRequest,
    db: AsyncSession = Depends(get_db),
):
    cmd = Command(
        request_id = body.request_id,
        device_id  = body.device_id,
        raw        = body.raw,
        requester  = body.requester,
    )
    db.add(cmd)
    logger.warning(
        "Privileged command queued  id=%s  device=%s  raw=%r",
        cmd.request_id, cmd.device_id[:16], cmd.raw[:80],
    )
    return PendingCommandResponse(request_id=cmd.request_id)


@router.get("/pending", response_model=PendingCommandsResponse)
async def get_pending_commands(
    device_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Command).where(
            Command.device_id == device_id,
            Command.status    == "pending",
        )
    )
    pending = result.scalars().all()
    return PendingCommandsResponse(commands=[
        {"id": r.request_id, "raw": r.raw, "requester": r.requester, "queued_at": r.queued_at}
        for r in pending
    ])


@router.get("/{request_id}/status", response_model=CommandStatusResponse)
async def get_command_status(
    request_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Command).where(Command.request_id == request_id))
    cmd = result.scalar_one_or_none()
    if cmd is None:
        raise HTTPException(status_code=404, detail="Command not found.")
    return CommandStatusResponse(request_id=request_id, status=cmd.status)


@router.patch("/{request_id}/status")
async def update_command_status(
    request_id: str,
    status: str,
    db: AsyncSession = Depends(get_db),
):
    if status not in ("approved", "denied"):
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'denied'.")
    result = await db.execute(select(Command).where(Command.request_id == request_id))
    cmd = result.scalar_one_or_none()
    if cmd is None:
        raise HTTPException(status_code=404, detail="Command not found.")
    cmd.status = status
    logger.info("Command %s → %s", request_id, status)
    return {"request_id": request_id, "status": status}


@router.post("/{request_id}/result", response_model=CommandResultResponse)
async def record_command_result(
    request_id: str,
    body: CommandResultRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Command).where(Command.request_id == request_id))
    cmd = result.scalar_one_or_none()
    if cmd is None:
        raise HTTPException(status_code=404, detail="Command not found.")
    cmd.status     = body.status
    cmd.stdout     = body.stdout
    cmd.stderr     = body.stderr
    cmd.returncode = body.returncode
    logger.info("Command result  id=%s  status=%s  rc=%s", request_id, body.status, body.returncode)
    return CommandResultResponse(request_id=request_id)
