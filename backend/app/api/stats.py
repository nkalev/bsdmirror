"""
Statistics API endpoints.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import humanize

from app.core.database import get_db
from app.models.mirror import Mirror
from app.models.sync_job import SyncJob, SyncStatus

router = APIRouter()


@router.get("/overview")
async def get_stats_overview(
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Get public statistics overview."""
    # Get mirrors
    result = await db.execute(select(Mirror).where(Mirror.enabled == True))
    mirrors = result.scalars().all()
    
    total_size = sum(m.total_size_bytes or 0 for m in mirrors)
    total_files = sum(m.file_count or 0 for m in mirrors)
    
    return {
        "mirrors": {
            name: {
                "status": m.status.value,
                "last_updated": m.last_sync_completed.isoformat() if m.last_sync_completed else None,
                "size": humanize.naturalsize(m.total_size_bytes) if m.total_size_bytes else "Unknown",
                "files": humanize.intcomma(m.file_count) if m.file_count else "Unknown"
            }
            for m in mirrors
            for name in [m.name]
        },
        "totals": {
            "size": humanize.naturalsize(total_size),
            "size_bytes": total_size,
            "files": humanize.intcomma(total_files),
            "files_count": total_files
        },
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


@router.get("/sync-activity")
async def get_sync_activity(
    days: int = 7,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Get sync activity for the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    result = await db.execute(
        select(SyncJob)
        .where(SyncJob.created_at >= cutoff)
        .order_by(SyncJob.created_at.desc())
    )
    jobs = result.scalars().all()
    
    # Aggregate by status
    by_status = {}
    for job in jobs:
        status = job.status.value
        by_status[status] = by_status.get(status, 0) + 1
    
    # Calculate totals
    total_bytes = sum(j.bytes_transferred or 0 for j in jobs if j.status == SyncStatus.COMPLETED)
    total_files = sum(j.files_transferred or 0 for j in jobs if j.status == SyncStatus.COMPLETED)
    
    return {
        "period_days": days,
        "total_syncs": len(jobs),
        "by_status": by_status,
        "data_transferred": humanize.naturalsize(total_bytes),
        "files_transferred": humanize.intcomma(total_files),
        "recent_syncs": [
            {
                "id": job.id,
                "mirror_id": job.mirror_id,
                "status": job.status.value,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "bytes_transferred": humanize.naturalsize(job.bytes_transferred) if job.bytes_transferred else None
            }
            for job in jobs[:10]
        ]
    }


@router.get("/health")
async def get_system_health(
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Get system health status for public display."""
    result = await db.execute(select(Mirror).where(Mirror.enabled == True))
    mirrors = result.scalars().all()
    
    # Check overall health
    all_healthy = all(m.status.value in ["active", "syncing"] for m in mirrors)
    any_syncing = any(m.status.value == "syncing" for m in mirrors)
    any_error = any(m.status.value == "error" for m in mirrors)
    
    if any_error:
        overall_status = "degraded"
    elif any_syncing:
        overall_status = "updating"
    elif all_healthy:
        overall_status = "healthy"
    else:
        overall_status = "unknown"
    
    return {
        "status": overall_status,
        "mirrors": {
            m.name: {
                "status": m.status.value,
                "last_sync": m.last_sync_completed.isoformat() if m.last_sync_completed else None
            }
            for m in mirrors
        },
        "checked_at": datetime.now(timezone.utc).isoformat()
    }
