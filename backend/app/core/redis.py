"""
Redis connection management.
"""
from typing import Optional

import redis.asyncio as redis
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Global Redis client
redis_client: Optional[redis.Redis] = None


async def init_redis() -> None:
    """Initialize Redis connection."""
    global redis_client
    redis_client = redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    # Test connection
    await redis_client.ping()
    logger.info("Redis connection established")


async def close_redis() -> None:
    """Close Redis connection."""
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None
    logger.info("Redis connection closed")


async def get_redis() -> redis.Redis:
    """Dependency for getting Redis client."""
    if redis_client is None:
        raise RuntimeError("Redis client not initialized")
    return redis_client
