import json
from typing import Any

import structlog
from redis.asyncio import Redis, from_url

from src.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

_redis: Redis | None = None


async def init_redis() -> None:
    global _redis

    _redis = from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )

    # Verify connection
    await _redis.ping()
    logger.info("redis_initialized", url=settings.redis_url.split("@")[-1])


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        logger.info("redis_connection_closed")


async def check_redis_health() -> bool:
    if not _redis:
        return False
    try:
        await _redis.ping()
        return True
    except Exception as e:
        logger.error("redis_health_check_failed", error=str(e))
        return False


def get_redis() -> Redis:
    if not _redis:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _redis


async def redis_get(key: str) -> Any | None:
    client = get_redis()
    value = await client.get(key)
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


async def redis_set(key: str, value: Any, ttl: int | None = None) -> None:
    client = get_redis()
    serialized = json.dumps(value) if not isinstance(value, str) else value
    if ttl:
        await client.setex(key, ttl, serialized)
    else:
        await client.set(key, serialized)


async def redis_delete(key: str) -> int:
    client = get_redis()
    return await client.delete(key)


async def redis_exists(key: str) -> bool:
    client = get_redis()
    return bool(await client.exists(key))
