"""
Admin API endpoints.
"""
import re
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.mirror import Mirror, MirrorType, MirrorStatus
from app.models.sync_job import SyncJob, SyncStatus
from app.models.audit_log import AuditLog
from app.models.setting import Setting
from app.api.auth import require_admin, require_operator, get_current_user, create_audit_log

logger = structlog.get_logger(__name__)
router = APIRouter()


# Pydantic models
class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: Optional[str] = None
    password: str = Field(min_length=12, max_length=128)
    role: UserRole = UserRole.READONLY


class UserUpdateRequest(BaseModel):
    email: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str]
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime]

    class Config:
        from_attributes = True


class MirrorUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    upstream_url: Optional[str] = None

    @field_validator("upstream_url")
    @classmethod
    def validate_upstream_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^(rsync|https?)://", v):
            raise ValueError("upstream_url must start with rsync://, http://, or https://")
        if len(v) > 500:
            raise ValueError("upstream_url must be 500 characters or fewer")
        return v


class TriggerSyncRequest(BaseModel):
    mirror_id: int


class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int]
    username: Optional[str]
    action: str
    resource_type: str
    resource_id: Optional[str]
    details: Optional[dict]
    ip_address: Optional[str]
    created_at: datetime


# ===========================================
# User Management
# ===========================================

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db)
) -> List[UserResponse]:
    """List all users (admin only)."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: Request,
    user_data: UserCreateRequest,
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db)
) -> User:
    """Create a new user (admin only)."""
    # Check if username exists
    existing = await db.execute(
        select(User).where(User.username == user_data.username)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )

    # Create user
    user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        role=user_data.role
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("User created", user_id=user.id, created_by=current_user.id)
    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action="user_created",
        resource_type="user",
        resource_id=str(user.id),
        details={"username": user.username, "role": user.role.value},
        request=request
    )

    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    request: Request,
    user_id: Annotated[int, Path(gt=0)],
    user_data: UserUpdateRequest,
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db)
) -> User:
    """Update a user (admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Prevent self-demotion
    if user_id == current_user.id and user_data.role and user_data.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot demote yourself"
        )

    changes = {}
    if user_data.email is not None:
        user.email = user_data.email
        changes["email"] = user_data.email
    if user_data.role is not None:
        user.role = user_data.role
        changes["role"] = user_data.role.value
    if user_data.is_active is not None:
        user.is_active = user_data.is_active
        changes["is_active"] = user_data.is_active

    await db.commit()
    await db.refresh(user)

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action="user_updated",
        resource_type="user",
        resource_id=str(user_id),
        details=changes,
        request=request
    )

    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    request: Request,
    user_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db)
) -> None:
    """Delete a user (admin only)."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself"
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    username = user.username
    await db.delete(user)
    await db.commit()

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action="user_deleted",
        resource_type="user",
        resource_id=str(user_id),
        details={"username": username},
        request=request
    )


# ===========================================
# Mirror Management
# ===========================================

@router.patch("/mirrors/{mirror_id}")
async def update_mirror(
    request: Request,
    mirror_id: Annotated[int, Path(gt=0)],
    mirror_data: MirrorUpdateRequest,
    current_user: Annotated[User, Depends(require_operator)],
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Update mirror configuration (operator+)."""
    result = await db.execute(select(Mirror).where(Mirror.id == mirror_id))
    mirror = result.scalar_one_or_none()

    if not mirror:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mirror not found"
        )

    changes = {}
    if mirror_data.enabled is not None:
        mirror.enabled = mirror_data.enabled
        changes["enabled"] = mirror_data.enabled
    if mirror_data.upstream_url is not None:
        mirror.upstream_url = mirror_data.upstream_url
        changes["upstream_url"] = mirror_data.upstream_url

    await db.commit()

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action="mirror_updated",
        resource_type="mirror",
        resource_id=str(mirror_id),
        details=changes,
        request=request
    )

    return {"message": "Mirror updated", "changes": changes}


@router.post("/mirrors/{mirror_id}/sync")
async def trigger_sync(
    request: Request,
    mirror_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(require_operator)],
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Trigger a manual sync for a mirror (operator+)."""
    result = await db.execute(select(Mirror).where(Mirror.id == mirror_id))
    mirror = result.scalar_one_or_none()

    if not mirror:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mirror not found"
        )

    if not mirror.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mirror is disabled"
        )

    if mirror.status == MirrorStatus.SYNCING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mirror is already syncing"
        )

    # Create sync job
    sync_job = SyncJob(
        mirror_id=mirror_id,
        status=SyncStatus.PENDING,
        triggered_by=current_user.username
    )
    db.add(sync_job)
    await db.commit()
    await db.refresh(sync_job)

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action="sync_triggered",
        resource_type="mirror",
        resource_id=str(mirror_id),
        details={"sync_job_id": sync_job.id},
        request=request
    )

    return {"message": "Sync job created", "job_id": sync_job.id}


# ===========================================
# Sync Job Logs
# ===========================================

class SyncJobLogResponse(BaseModel):
    id: int
    mirror_id: int
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    files_transferred: Optional[int]
    bytes_transferred: Optional[int]
    rsync_output: Optional[str]
    error_message: Optional[str]
    triggered_by: Optional[str]
    created_at: datetime


@router.get("/sync-jobs/{job_id}/logs", response_model=SyncJobLogResponse)
async def get_sync_job_logs(
    job_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db)
) -> SyncJobLogResponse:
    """Get sync job details including rsync output logs."""
    result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync job not found"
        )

    return SyncJobLogResponse(
        id=job.id,
        mirror_id=job.mirror_id,
        status=job.status.value if hasattr(job.status, 'value') else str(job.status),
        started_at=job.started_at,
        completed_at=job.completed_at,
        files_transferred=job.files_transferred,
        bytes_transferred=job.bytes_transferred,
        rsync_output=job.rsync_output,
        error_message=job.error_message,
        triggered_by=job.triggered_by,
        created_at=job.created_at,
    )


# ===========================================
# Audit Logs
# ===========================================

@router.get("/audit-logs", response_model=List[AuditLogResponse])
async def get_audit_logs(
    current_user: Annotated[User, Depends(require_admin)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> List[AuditLogResponse]:
    """Get audit logs (admin only)."""
    query = select(AuditLog, User.username).outerjoin(User).order_by(AuditLog.created_at.desc())

    if action:
        query = query.where(AuditLog.action == action)

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)

    return [
        AuditLogResponse(
            id=log.id,
            user_id=log.user_id,
            username=username,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            details=log.details,
            ip_address=log.ip_address,
            created_at=log.created_at
        )
        for log, username in result.all()
    ]


# ===========================================
# Dashboard Stats
# ===========================================

@router.get("/dashboard")
async def get_dashboard(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Get admin dashboard data."""
    # Get mirror stats
    mirrors_result = await db.execute(select(Mirror))
    mirrors = mirrors_result.scalars().all()

    # Get user count
    user_count_result = await db.execute(select(func.count(User.id)))
    user_count = user_count_result.scalar()

    # Get recent sync jobs
    recent_syncs = await db.execute(
        select(SyncJob)
        .order_by(SyncJob.created_at.desc())
        .limit(5)
    )

    # Get recent audit logs
    recent_logs = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(10)
    )

    total_size = sum(m.total_size_bytes or 0 for m in mirrors)

    return {
        "mirrors": {
            "total": len(mirrors),
            "active": sum(1 for m in mirrors if m.status == MirrorStatus.ACTIVE),
            "syncing": sum(1 for m in mirrors if m.status == MirrorStatus.SYNCING),
            "error": sum(1 for m in mirrors if m.status == MirrorStatus.ERROR),
            "total_size_bytes": total_size
        },
        "users": {
            "total": user_count
        },
        "recent_syncs": [
            {
                "id": job.id,
                "mirror_id": job.mirror_id,
                "status": job.status.value,
                "created_at": job.created_at.isoformat()
            }
            for job in recent_syncs.scalars().all()
        ],
        "recent_activity": [
            {
                "id": log.id,
                "action": log.action,
                "created_at": log.created_at.isoformat()
            }
            for log in recent_logs.scalars().all()
        ]
    }


# ===========================================
# Settings
# ===========================================

class SettingResponse(BaseModel):
    id: int
    key: str
    value: Optional[str]
    description: Optional[str]
    updated_at: datetime

    class Config:
        from_attributes = True


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, str] = Field(
        ...,
        description="Key-value pairs of settings to update"
    )


@router.get("/settings", response_model=List[SettingResponse])
async def get_settings(
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db)
) -> List[SettingResponse]:
    """Get all settings (admin only)."""
    result = await db.execute(select(Setting).order_by(Setting.key))
    return result.scalars().all()


@router.patch("/settings")
async def update_settings(
    request: Request,
    data: SettingsUpdateRequest,
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Update settings (admin only)."""
    changes = {}

    for key, value in data.settings.items():
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()

        if setting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Setting '{key}' not found"
            )

        old_value = setting.value
        setting.value = value
        setting.updated_at = datetime.now(timezone.utc)
        changes[key] = {"old": old_value, "new": value}

    await db.commit()

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action="settings_updated",
        resource_type="settings",
        resource_id=None,
        details=changes,
        request=request
    )

    logger.info("Settings updated", changes=changes, updated_by=current_user.username)
    return {"message": "Settings updated", "changes": changes}
