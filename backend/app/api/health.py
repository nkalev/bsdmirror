"""
Health check API endpoints.
"""
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.config import settings

router = APIRouter()


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
    
    # Check PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
        health_status["services"]["postgres"] = {
            "status": "healthy",
            "host": settings.POSTGRES_HOST
        }
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["services"]["postgres"] = {
            "status": "unhealthy",
            "error": str(e)
        }
    
    # Check Redis
    try:
        await redis_client.ping()
        health_status["services"]["redis"] = {
            "status": "healthy",
            "host": settings.REDIS_HOST
        }
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["services"]["redis"] = {
            "status": "unhealthy",
            "error": str(e)
        }
    
    return health_status
