import json
import secrets
import uuid

from redis.asyncio import Redis

from kairos.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def create_session(user_id: uuid.UUID, email: str) -> str:
    session_id = secrets.token_urlsafe(32)
    await get_redis().set(
        f"session:{session_id}",
        json.dumps({"user_id": str(user_id), "email": email}),
        ex=86400 * 30,
    )
    return session_id


async def get_session(session_id: str) -> dict | None:
    data = await get_redis().get(f"session:{session_id}")
    return json.loads(data) if data else None


async def delete_session(session_id: str) -> None:
    await get_redis().delete(f"session:{session_id}")
