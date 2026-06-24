"""
MARK III — Memory Engine API  (Phase 8)

Endpoints:
  GET  /api/v1/memory/profile?device_id=
  PUT  /api/v1/memory/profile?device_id=          (upsert)

  GET  /api/v1/memory/goals?device_id=&status=
  POST /api/v1/memory/goals
  PUT  /api/v1/memory/goals/{id}
  DELETE /api/v1/memory/goals/{id}

  GET  /api/v1/memory/projects?device_id=&status=
  POST /api/v1/memory/projects
  PUT  /api/v1/memory/projects/{id}
  DELETE /api/v1/memory/projects/{id}

  GET  /api/v1/memory/memories?device_id=&limit=&type=&importance=&project_id=&goal_id=
  POST /api/v1/memory/memories
  DELETE /api/v1/memory/memories/{id}

  GET  /api/v1/memory/search?device_id=&q=&limit=
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db import UserProfile, LongTermGoal, Project, Memory

logger = logging.getLogger("markiii.memory.api")
router = APIRouter(prefix="/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ProfileUpsert(BaseModel):
    name:                Optional[str]       = None
    career:              Optional[str]       = None
    interests:           Optional[list[str]] = None
    goals_summary:       Optional[str]       = None
    preferences:         Optional[dict]      = None
    work_schedule:       Optional[dict]      = None
    learning_objectives: Optional[list[str]] = None


class GoalCreate(BaseModel):
    device_id:   str
    title:       str
    description: Optional[str] = None
    category:    str = "personal"   # career|research|health|financial|personal|learning
    target_date: Optional[str] = None
    notes:       Optional[str] = None


class GoalUpdate(BaseModel):
    title:       Optional[str] = None
    description: Optional[str] = None
    category:    Optional[str] = None
    status:      Optional[str] = None
    progress:    Optional[int] = None
    target_date: Optional[str] = None
    notes:       Optional[str] = None


class ProjectCreate(BaseModel):
    device_id:   str
    goal_id:     Optional[int] = None
    name:        str
    description: Optional[str] = None
    deadline:    Optional[str] = None
    notes:       Optional[str] = None


class ProjectUpdate(BaseModel):
    goal_id:     Optional[int] = None
    name:        Optional[str] = None
    description: Optional[str] = None
    status:      Optional[str] = None
    progress:    Optional[int] = None
    deadline:    Optional[str] = None
    notes:       Optional[str] = None


class MemoryCreate(BaseModel):
    device_id:   str
    title:       str
    content:     str
    memory_type: str = "note"      # event|decision|instruction|achievement|conversation|note
    importance:  int = 3           # 1–5
    tags:        Optional[list[str]] = None
    project_id:  Optional[int] = None
    goal_id:     Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _goal_dict(g: LongTermGoal) -> dict:
    return {
        "id": g.id, "device_id": g.device_id, "title": g.title,
        "description": g.description, "category": g.category,
        "status": g.status, "progress": g.progress,
        "target_date": g.target_date, "notes": g.notes,
        "created_at": g.created_at, "updated_at": g.updated_at,
    }


def _project_dict(p: Project) -> dict:
    return {
        "id": p.id, "device_id": p.device_id, "goal_id": p.goal_id,
        "name": p.name, "description": p.description,
        "status": p.status, "progress": p.progress,
        "deadline": p.deadline, "notes": p.notes,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


def _memory_dict(m: Memory) -> dict:
    return {
        "id": m.id, "device_id": m.device_id,
        "project_id": m.project_id, "goal_id": m.goal_id,
        "ts": m.ts, "title": m.title, "content": m.content,
        "memory_type": m.memory_type, "importance": m.importance,
        "tags": m.tags, "created_at": m.created_at,
    }


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/profile")
async def get_profile(
    device_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserProfile).where(UserProfile.device_id == device_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return {
            "device_id": device_id, "name": None, "career": None,
            "interests": [], "goals_summary": None, "preferences": {},
            "work_schedule": {"start": 9, "end": 17, "days": ["Mon","Tue","Wed","Thu","Fri"]},
            "learning_objectives": [], "exists": False,
        }
    return {
        "device_id": row.device_id, "name": row.name, "career": row.career,
        "interests": row.interests or [], "goals_summary": row.goals_summary,
        "preferences": row.preferences or {},
        "work_schedule": row.work_schedule or {},
        "learning_objectives": row.learning_objectives or [],
        "created_at": row.created_at, "updated_at": row.updated_at,
        "exists": True,
    }


@router.put("/profile")
async def upsert_profile(
    device_id: str = Query(...),
    body: ProfileUpsert = ...,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserProfile).where(UserProfile.device_id == device_id)
    )
    row = result.scalar_one_or_none()

    if row:
        if body.name                is not None: row.name                = body.name
        if body.career              is not None: row.career              = body.career
        if body.interests           is not None: row.interests           = body.interests
        if body.goals_summary       is not None: row.goals_summary       = body.goals_summary
        if body.preferences         is not None: row.preferences         = body.preferences
        if body.work_schedule       is not None: row.work_schedule       = body.work_schedule
        if body.learning_objectives is not None: row.learning_objectives = body.learning_objectives
        row.updated_at = time.time()
    else:
        row = UserProfile(
            device_id           = device_id,
            name                = body.name,
            career              = body.career,
            interests           = body.interests,
            goals_summary       = body.goals_summary,
            preferences         = body.preferences,
            work_schedule       = body.work_schedule,
            learning_objectives = body.learning_objectives,
        )
        db.add(row)

    await db.commit()
    logger.info("Profile upserted  device=%s  name=%s", device_id[:16], row.name)
    return {"ok": True, "device_id": device_id}


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------

@router.get("/goals")
async def list_goals(
    device_id: str = Query(...),
    status:    Optional[str] = Query(default=None),
    category:  Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    q = select(LongTermGoal).where(LongTermGoal.device_id == device_id)
    if status:
        q = q.where(LongTermGoal.status == status)
    if category:
        q = q.where(LongTermGoal.category == category)
    q = q.order_by(desc(LongTermGoal.updated_at))
    result = await db.execute(q)
    return [_goal_dict(g) for g in result.scalars().all()]


@router.post("/goals", status_code=201)
async def create_goal(body: GoalCreate, db: AsyncSession = Depends(get_db)):
    goal = LongTermGoal(
        device_id   = body.device_id,
        title       = body.title,
        description = body.description,
        category    = body.category,
        target_date = body.target_date,
        notes       = body.notes,
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    logger.info("Goal created  id=%d  title=%s", goal.id, goal.title[:40])
    return _goal_dict(goal)


@router.put("/goals/{goal_id}")
async def update_goal(
    goal_id: int,
    body: GoalUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(LongTermGoal).where(LongTermGoal.id == goal_id))
    goal   = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(goal, field, value)
    goal.updated_at = time.time()

    await db.commit()
    return _goal_dict(goal)


@router.delete("/goals/{goal_id}", status_code=204)
async def delete_goal(goal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LongTermGoal).where(LongTermGoal.id == goal_id))
    goal   = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    await db.delete(goal)
    await db.commit()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@router.get("/projects")
async def list_projects(
    device_id: str = Query(...),
    status:    Optional[str] = Query(default=None),
    goal_id:   Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Project).where(Project.device_id == device_id)
    if status:
        q = q.where(Project.status == status)
    if goal_id:
        q = q.where(Project.goal_id == goal_id)
    q = q.order_by(desc(Project.updated_at))
    result = await db.execute(q)
    return [_project_dict(p) for p in result.scalars().all()]


@router.post("/projects", status_code=201)
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = Project(
        device_id   = body.device_id,
        goal_id     = body.goal_id,
        name        = body.name,
        description = body.description,
        deadline    = body.deadline,
        notes       = body.notes,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    logger.info("Project created  id=%d  name=%s", project.id, project.name[:40])
    return _project_dict(project)


@router.put("/projects/{project_id}")
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    result  = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    project.updated_at = time.time()

    await db.commit()
    return _project_dict(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)):
    result  = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(project)
    await db.commit()


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------

@router.get("/memories")
async def list_memories(
    device_id:   str           = Query(...),
    limit:       int           = Query(default=50, le=200),
    memory_type: Optional[str] = Query(default=None),
    importance:  Optional[int] = Query(default=None),
    project_id:  Optional[int] = Query(default=None),
    goal_id:     Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Memory).where(Memory.device_id == device_id)
    if memory_type: q = q.where(Memory.memory_type == memory_type)
    if importance:  q = q.where(Memory.importance  >= importance)
    if project_id:  q = q.where(Memory.project_id  == project_id)
    if goal_id:     q = q.where(Memory.goal_id      == goal_id)
    q = q.order_by(desc(Memory.ts)).limit(limit)
    result = await db.execute(q)
    return [_memory_dict(m) for m in result.scalars().all()]


@router.post("/memories", status_code=201)
async def create_memory(body: MemoryCreate, db: AsyncSession = Depends(get_db)):
    memory = Memory(
        device_id   = body.device_id,
        title       = body.title,
        content     = body.content,
        memory_type = body.memory_type,
        importance  = max(1, min(5, body.importance)),
        tags        = body.tags,
        project_id  = body.project_id,
        goal_id     = body.goal_id,
        ts          = time.time(),
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    logger.info("Memory created  id=%d  type=%s  title=%s", memory.id, memory.memory_type, memory.title[:40])
    return _memory_dict(memory)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.delete(memory)
    await db.commit()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_memories(
    device_id: str = Query(...),
    q:         str = Query(..., min_length=2),
    limit:     int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Full-text search across Memory.title, Memory.content, and Project.name.
    Uses SQL LIKE — no vector DB required at this phase.
    """
    pattern = f"%{q}%"

    mem_result = await db.execute(
        select(Memory)
        .where(Memory.device_id == device_id)
        .where(or_(
            Memory.title.ilike(pattern),
            Memory.content.ilike(pattern),
        ))
        .order_by(desc(Memory.importance), desc(Memory.ts))
        .limit(limit)
    )
    memories = [_memory_dict(m) for m in mem_result.scalars().all()]

    proj_result = await db.execute(
        select(Project)
        .where(Project.device_id == device_id)
        .where(or_(
            Project.name.ilike(pattern),
            Project.description.ilike(pattern),
            Project.notes.ilike(pattern),
        ))
        .order_by(desc(Project.updated_at))
        .limit(10)
    )
    projects = [_project_dict(p) for p in proj_result.scalars().all()]

    goal_result = await db.execute(
        select(LongTermGoal)
        .where(LongTermGoal.device_id == device_id)
        .where(or_(
            LongTermGoal.title.ilike(pattern),
            LongTermGoal.description.ilike(pattern),
        ))
        .order_by(desc(LongTermGoal.updated_at))
        .limit(10)
    )
    goals = [_goal_dict(g) for g in goal_result.scalars().all()]

    return {
        "query":    q,
        "memories": memories,
        "projects": projects,
        "goals":    goals,
        "total":    len(memories) + len(projects) + len(goals),
    }
