"""
Mirrors API endpoints.
"""
from datetime import datetime, timezone
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import humanize

from app.core.database import get_db
from app.core.config import settings
from app.models.mirror import Mirror, MirrorType, MirrorStatus
from app.models.sync_job import SyncJob, SyncStatus

router = APIRouter()


# Pydantic models
class MirrorResponse(BaseModel):
    id: int
    name: str
    mirror_type: MirrorType
    enabled: bool
    status: MirrorStatus
    last_sync_completed: Optional[datetime]
    total_size_bytes: Optional[int]
    total_size_human: Optional[str]
    file_count: Optional[int]
    url_path: str

    class Config:
        from_attributes = True


class MirrorDetailResponse(MirrorResponse):
    upstream_url: str
    local_path: str
    last_sync_started: Optional[datetime]
    last_sync_error: Optional[str]
    created_at: datetime
    updated_at: datetime


class DirectoryEntry(BaseModel):
    name: str
    is_directory: bool
    size: Optional[int]
    size_human: Optional[str]
    modified: Optional[datetime]


class DirectoryListing(BaseModel):
    path: str
    entries: List[DirectoryEntry]
    parent_path: Optional[str]


def get_url_path(mirror_type: MirrorType) -> str:
    """Get the URL path for a mirror type."""
    paths = {
        MirrorType.FREEBSD: "/FreeBSD/",
        MirrorType.NETBSD: "/NetBSD/",
        MirrorType.OPENBSD: "/OpenBSD/"
    }
    return paths.get(mirror_type, "/")


@router.get("/", response_model=List[MirrorResponse])
async def list_mirrors(
    db: AsyncSession = Depends(get_db)
) -> List[MirrorResponse]:
    """List all configured mirrors and their status."""
    result = await db.execute(
        select(Mirror).where(Mirror.enabled == True).order_by(Mirror.name)
    )
    mirrors = result.scalars().all()
    
    response = []
    for mirror in mirrors:
        response.append(MirrorResponse(
            id=mirror.id,
            name=mirror.name,
            mirror_type=mirror.mirror_type,
            enabled=mirror.enabled,
            status=mirror.status,
            last_sync_completed=mirror.last_sync_completed,
            total_size_bytes=mirror.total_size_bytes,
            total_size_human=humanize.naturalsize(mirror.total_size_bytes) if mirror.total_size_bytes else None,
            file_count=mirror.file_count,
            url_path=get_url_path(mirror.mirror_type)
        ))
    
    return response


@router.get("/{mirror_id}", response_model=MirrorDetailResponse)
async def get_mirror(
    mirror_id: int,
    db: AsyncSession = Depends(get_db)
) -> MirrorDetailResponse:
    """Get detailed information about a specific mirror."""
    result = await db.execute(
        select(Mirror).where(Mirror.id == mirror_id)
    )
    mirror = result.scalar_one_or_none()
    
    if not mirror:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mirror not found"
        )
    
    return MirrorDetailResponse(
        id=mirror.id,
        name=mirror.name,
        mirror_type=mirror.mirror_type,
        enabled=mirror.enabled,
        status=mirror.status,
        upstream_url=mirror.upstream_url,
        local_path=mirror.local_path,
        last_sync_started=mirror.last_sync_started,
        last_sync_completed=mirror.last_sync_completed,
        last_sync_error=mirror.last_sync_error,
        total_size_bytes=mirror.total_size_bytes,
        total_size_human=humanize.naturalsize(mirror.total_size_bytes) if mirror.total_size_bytes else None,
        file_count=mirror.file_count,
        url_path=get_url_path(mirror.mirror_type),
        created_at=mirror.created_at,
        updated_at=mirror.updated_at
    )


@router.get("/{mirror_id}/sync-history")
async def get_sync_history(
    mirror_id: int,
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
) -> List[dict]:
    """Get sync job history for a mirror."""
    result = await db.execute(
        select(SyncJob)
        .where(SyncJob.mirror_id == mirror_id)
        .order_by(SyncJob.created_at.desc())
        .limit(limit)
    )
    jobs = result.scalars().all()
    
    return [
        {
            "id": job.id,
            "status": job.status,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "files_transferred": job.files_transferred,
            "bytes_transferred": job.bytes_transferred,
            "bytes_transferred_human": humanize.naturalsize(job.bytes_transferred) if job.bytes_transferred else None,
            "triggered_by": job.triggered_by,
            "error_message": job.error_message,
            "created_at": job.created_at
        }
        for job in jobs
    ]


@router.get("/status/summary")
async def get_mirrors_summary(
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Get summary status of all mirrors."""
    result = await db.execute(select(Mirror))
    mirrors = result.scalars().all()
    
    total_size = sum(m.total_size_bytes or 0 for m in mirrors)
    total_files = sum(m.file_count or 0 for m in mirrors)
    
    return {
        "total_mirrors": len(mirrors),
        "enabled_mirrors": sum(1 for m in mirrors if m.enabled),
        "total_size_bytes": total_size,
        "total_size_human": humanize.naturalsize(total_size),
        "total_files": total_files,
        "mirrors": {
            m.name: {
                "status": m.status.value,
                "enabled": m.enabled,
                "last_sync": m.last_sync_completed.isoformat() if m.last_sync_completed else None,
                "size_human": humanize.naturalsize(m.total_size_bytes) if m.total_size_bytes else None
            }
            for m in mirrors
        }
    }
