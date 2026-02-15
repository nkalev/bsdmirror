"""
BSD Mirrors Backend API

FastAPI application for managing BSD mirror website.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from sqlalchemy import select

from app.core.config import settings
from app.core.database import init_db, close_db, async_session_maker
from app.core.redis import init_redis, close_redis
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.mirror import Mirror, MirrorType, MirrorStatus
from app.models.setting import Setting
from app.api import health, auth, mirrors, admin, stats

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup/shutdown."""
    # Startup
    logger.info("Starting BSD Mirrors API", version=settings.VERSION)
    await init_db()
    await init_redis()
    logger.info("Database and Redis connections established")

    # Seed admin user and default mirrors if they don't exist
    async with async_session_maker() as session:
        # Admin user
        result = await session.execute(
            select(User).where(User.username == settings.ADMIN_USERNAME)
        )
        admin_user = result.scalar_one_or_none()
        if admin_user is None:
            admin_user = User(
                username=settings.ADMIN_USERNAME,
                password_hash=hash_password(settings.ADMIN_PASSWORD),
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(admin_user)
            logger.info("Admin user created", username=settings.ADMIN_USERNAME)
        else:
            logger.info("Admin user already exists", username=settings.ADMIN_USERNAME)

        # Default mirrors
        default_mirrors = [
            {
                "name": "FreeBSD",
                "mirror_type": MirrorType.FREEBSD,
                "upstream_url": "rsync://ftp.freebsd.org/FreeBSD/",
                "local_path": "/data/mirrors/freebsd/pub/FreeBSD",
            },
            {
                "name": "NetBSD",
                "mirror_type": MirrorType.NETBSD,
                "upstream_url": "rsync://ftp.netbsd.org/pub/NetBSD/",
                "local_path": "/data/mirrors/netbsd/pub/NetBSD",
            },
            {
                "name": "OpenBSD",
                "mirror_type": MirrorType.OPENBSD,
                "upstream_url": "rsync://ftp.openbsd.org/pub/OpenBSD/",
                "local_path": "/data/mirrors/openbsd/pub/OpenBSD",
            },
        ]
        for mirror_data in default_mirrors:
            result = await session.execute(
                select(Mirror).where(Mirror.name == mirror_data["name"])
            )
            if result.scalar_one_or_none() is None:
                session.add(Mirror(
                    **mirror_data,
                    enabled=True,
                    status=MirrorStatus.ACTIVE,
                ))
                logger.info("Default mirror created", name=mirror_data["name"])

        # Default settings
        default_settings = [
            {
                "key": "sync_schedule",
                "value": "0 4 * * *",
                "description": "Cron schedule for automatic mirror synchronization",
            },
            {
                "key": "sync_bandwidth_limit",
                "value": "0",
                "description": "Rsync bandwidth limit in KB/s (0 = unlimited)",
            },
            {
                "key": "sync_timeout",
                "value": "600",
                "description": "Rsync timeout in seconds",
            },
            {
                "key": "sync_on_startup",
                "value": "false",
                "description": "Run full sync when sync service starts",
            },
        ]
        for setting_data in default_settings:
            result = await session.execute(
                select(Setting).where(Setting.key == setting_data["key"])
            )
            if result.scalar_one_or_none() is None:
                session.add(Setting(**setting_data))
                logger.info("Default setting created", key=setting_data["key"])

        await session.commit()

    yield
    
    # Shutdown
    logger.info("Shutting down BSD Mirrors API")
    await close_db()
    await close_redis()
    logger.info("Connections closed")


# Create FastAPI application
app = FastAPI(
    title="BSD Mirrors API",
    description="API for managing FreeBSD, NetBSD, and OpenBSD mirror website",
    version=settings.VERSION,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle uncaught exceptions."""
    logger.error(
        "Unhandled exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# Include API routers
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(mirrors.router, prefix="/api/mirrors", tags=["Mirrors"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(stats.router, prefix="/api/stats", tags=["Statistics"])


@app.get("/")
async def root() -> dict:
    """Root endpoint - redirect info."""
    return {
        "name": "BSD Mirrors",
        "version": settings.VERSION,
        "mirrors": {
            "FreeBSD": "/FreeBSD/",
            "NetBSD": "/NetBSD/",
            "OpenBSD": "/OpenBSD/"
        },
        "api": "/api/docs" if settings.DEBUG else None
    }
