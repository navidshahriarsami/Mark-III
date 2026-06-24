from fastapi import APIRouter
from app.api.v1 import alerts, commands, devices, heartbeat, snapshots, cognitive, memory, ai, conversation, voice, actions, agents, council

router = APIRouter(prefix="/api/v1")
router.include_router(devices.router)
router.include_router(heartbeat.router)
router.include_router(snapshots.router)
router.include_router(commands.router)
router.include_router(alerts.router)
router.include_router(cognitive.router)
router.include_router(memory.router)
router.include_router(ai.router)
router.include_router(conversation.router)
router.include_router(voice.router)
router.include_router(actions.router)
router.include_router(agents.router)
router.include_router(council.router)
