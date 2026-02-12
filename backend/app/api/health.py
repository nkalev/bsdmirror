"""
Health check API endpoints.
"""
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis
import structlog

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.config import settings

logger = structlog.get_logger(__name__)
router = APIRouter()

HEALTH_CHECK_TIMEOUT = 5  # seconds


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/health/detailed")
async def detailed_health_check(
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
) -> Dict[str, Any]:
    """Detailed health check with database and Redis status."""
    health_status = {
        "status": "healthy",
        "version": settings.VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {}
    }

    # Check PostgreSQL with timeout
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=HEALTH_CHECK_TIMEOUT)
        health_status["services"]["postgres"] = {
            "status": "healthy",
        }
    except asyncio.TimeoutError:
        logger.error("PostgreSQL health check timed out")
        health_status["status"] = "degraded"
        health_status["services"]["postgres"] = {
            "status": "unhealthy",
            "error": "connection timeout"
        }
    except Exception as e:
        logger.error("PostgreSQL health check failed", error=str(e))
        health_status["status"] = "degraded"
        health_status["services"]["postgres"] = {
            "status": "unhealthy",
            "error": "connection error"
        }

    # Check Redis with timeout
    try:
        await asyncio.wait_for(redis_client.ping(), timeout=HEALTH_CHECK_TIMEOUT)
        health_status["services"]["redis"] = {
            "status": "healthy",
        }
    except asyncio.TimeoutError:
        logger.error("Redis health check timed out")
        health_status["status"] = "degraded"
        health_status["services"]["redis"] = {
            "status": "unhealthy",
            "error": "connection timeout"
        }
    except Exception as e:
        logger.error("Redis health check failed", error=str(e))
        health_status["status"] = "degraded"
        health_status["services"]["redis"] = {
            "status": "unhealthy",
            "error": "connection error"
        }

    return health_status
