"""
Sync job model for tracking synchronization history.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import String, DateTime, BigInteger, Text, Integer, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class SyncStatus(str, Enum):
    """Status of a sync job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SyncJob(Base):
    """Sync job history and status tracking."""
    
    __tablename__ = "sync_jobs"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mirror_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mirrors.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    status: Mapped[SyncStatus] = mapped_column(
        SQLEnum(SyncStatus, name="sync_status"),
        default=SyncStatus.PENDING,
        nullable=False
    )
    
    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Statistics
    files_transferred: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    bytes_transferred: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    files_deleted: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    
    # Output
    rsync_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Trigger
    triggered_by: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="scheduled, manual, or username"
    )
    
    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Relationship
    mirror = relationship("Mirror", backref="sync_jobs")
    
    def __repr__(self) -> str:
        return f"<SyncJob(id={self.id}, mirror_id={self.mirror_id}, status={self.status})>"
