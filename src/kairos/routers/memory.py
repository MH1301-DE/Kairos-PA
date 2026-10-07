from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.repositories.memory import SqlMemoryRepository

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryCreateRequest(BaseModel):
    content: str


class MemoryUpdateRequest(BaseModel):
    content: str


def _memory_to_dict(entry: Any) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "content": entry.content,
        "source": entry.source,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
        "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
    }


@router.get("")
async def list_memory(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlMemoryRepository(session=session)
    entries = await repo.list_for_user(user_id=user_id)
    return {"entries": [_memory_to_dict(e) for e in entries]}


@router.post("", status_code=201)
async def create_memory(
    req: MemoryCreateRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="content must not be empty")
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlMemoryRepository(session=session)
    # source is always "user" here -- an agent-written entry is created internally
    # by the future agent tool layer via SqlMemoryRepository directly, never through
    # this client-facing endpoint, so a client can't spoof the "agent" badge
    entry = await repo.create(user_id=user_id, content=content, source="user")
    await session.commit()
    return _memory_to_dict(entry)


@router.patch("/{memory_id}")
async def update_memory(
    memory_id: UUID,
    req: MemoryUpdateRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="content must not be empty")
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlMemoryRepository(session=session)
    entry = await repo.update(user_id=user_id, memory_id=memory_id, content=content)
    if entry is None:
        raise HTTPException(status_code=404, detail="memory entry not found")
    await session.commit()
    return _memory_to_dict(entry)


@router.delete("/{memory_id}", status_code=204, response_model=None)
async def delete_memory(
    memory_id: UUID,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlMemoryRepository(session=session)
    deleted = await repo.delete(user_id=user_id, memory_id=memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="memory entry not found")
    await session.commit()
