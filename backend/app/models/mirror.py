"""
Mirror configuration model.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, BigInteger, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class MirrorType(str, Enum):
    """Types of BSD mirrors."""
    FREEBSD = "freebsd"
    NETBSD = "netbsd"
    OPENBSD = "openbsd"


class MirrorStatus(str, Enum):
    """Status of a mirror."""
    ACTIVE = "active"
    SYNCING = "syncing"
    ERROR = "error"
    DISABLED = "disabled"


class Mirror(Base):
    """Mirror configuration and status."""
    
    __tablename__ = "mirrors"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    mirror_type: Mapped[MirrorType] = mapped_column(
        SQLEnum(MirrorType, name="mirror_type"),
        nullable=False
    )
    upstream_url: Mapped[str] = mapped_column(String(500), nullable=False)
    local_path: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[MirrorStatus] = mapped_column(
        SQLEnum(MirrorStatus, name="mirror_status"),
        default=MirrorStatus.ACTIVE,
        nullable=False
    )
    
    # Sync information
    last_sync_started: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    last_sync_completed: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    last_sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Size tracking
    total_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    file_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    
    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    
    def __repr__(self) -> str:
        return f"<Mirror(id={self.id}, name={self.name}, status={self.status})>"
