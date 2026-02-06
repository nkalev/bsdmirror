"""
BSD Mirrors Sync Service

Handles scheduled rsync synchronization of BSD mirrors.
"""
import asyncio
import os
import signal
import subprocess
from datetime import datetime, timezone
from typing import Optional

from aiohttp import web
from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import structlog

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class SyncConfig:
    """Configuration from environment variables."""
    
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB = os.getenv("POSTGRES_DB", "bsdmirrors")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "bsdmirrors")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
    
    REDIS_HOST = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    
    SYNC_SCHEDULE = os.getenv("SYNC_SCHEDULE", "0 4 * * *")
    SYNC_BANDWIDTH_LIMIT = int(os.getenv("SYNC_BANDWIDTH_LIMIT", "0"))
    
    FREEBSD_ENABLED = os.getenv("FREEBSD_ENABLED", "true").lower() == "true"
    FREEBSD_UPSTREAM = os.getenv("FREEBSD_UPSTREAM", "rsync://ftp.freebsd.org/FreeBSD/")
    
    NETBSD_ENABLED = os.getenv("NETBSD_ENABLED", "true").lower() == "true"
    NETBSD_UPSTREAM = os.getenv("NETBSD_UPSTREAM", "rsync://ftp.netbsd.org/pub/NetBSD/")
    
    OPENBSD_ENABLED = os.getenv("OPENBSD_ENABLED", "true").lower() == "true"
    OPENBSD_UPSTREAM = os.getenv("OPENBSD_UPSTREAM", "rsync://ftp.openbsd.org/pub/OpenBSD/")
    
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


config = SyncConfig()


class SyncService:
    """Main sync service class."""
    
    def __init__(self):
        self.running = True
        self.engine = create_async_engine(config.database_url, pool_size=5)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.current_sync: Optional[asyncio.subprocess.Process] = None
    
    async def run_rsync(
        self,
        source: str,
        destination: str,
        mirror_name: str
    ) -> tuple[bool, str, dict]:
        """Run rsync command and capture output."""
        
        # Build rsync command
        cmd = [
            "rsync",
            "-avHz",
            "--delete",
            "--delete-delay",
            "--delay-updates",
            "--stats",
            "--timeout=600",
        ]
        
        if config.SYNC_BANDWIDTH_LIMIT > 0:
            cmd.append(f"--bwlimit={config.SYNC_BANDWIDTH_LIMIT}")
        
        cmd.extend([source, destination])
        
        logger.info("Starting rsync", mirror=mirror_name, source=source, destination=destination)
        
        try:
            # Ensure destination exists
            os.makedirs(destination, exist_ok=True)
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            self.current_sync = process
            
            stdout, _ = await process.communicate()
            output = stdout.decode("utf-8", errors="replace")
            
            self.current_sync = None
            
            # Parse statistics from output
            stats = self._parse_rsync_stats(output)
            
            if process.returncode == 0:
                logger.info("Rsync completed successfully", mirror=mirror_name, stats=stats)
                return True, output, stats
            else:
                logger.error("Rsync failed", mirror=mirror_name, returncode=process.returncode)
                return False, output, stats
                
        except Exception as e:
            logger.error("Rsync error", mirror=mirror_name, error=str(e))
            return False, str(e), {}
    
    def _parse_rsync_stats(self, output: str) -> dict:
        """Parse rsync statistics from output."""
        stats = {}
        
        for line in output.split("\n"):
            if "Number of files:" in line:
                try:
                    stats["total_files"] = int(line.split(":")[1].strip().split()[0].replace(",", ""))
                except (IndexError, ValueError):
                    pass
            elif "Number of regular files transferred:" in line:
                try:
                    stats["files_transferred"] = int(line.split(":")[1].strip().replace(",", ""))
                except (IndexError, ValueError):
                    pass
            elif "Total file size:" in line:
                try:
                    size_str = line.split(":")[1].strip().split()[0].replace(",", "")
                    stats["total_size"] = int(size_str)
                except (IndexError, ValueError):
                    pass
            elif "Total transferred file size:" in line:
                try:
                    size_str = line.split(":")[1].strip().split()[0].replace(",", "")
                    stats["bytes_transferred"] = int(size_str)
                except (IndexError, ValueError):
                    pass
        
        return stats
    
    async def sync_mirror(self, mirror_id: int, name: str, upstream: str, local_path: str) -> None:
        """Sync a single mirror."""
        async with self.session_maker() as session:
            # Update mirror status to syncing
            await session.execute(
                update(Mirror)
                .where(Mirror.id == mirror_id)
                .values(status="syncing", last_sync_started=datetime.now(timezone.utc))
            )
            
            # Create sync job
            sync_job = SyncJob(
                mirror_id=mirror_id,
                status="running",
                started_at=datetime.now(timezone.utc),
                triggered_by="scheduled"
            )
            session.add(sync_job)
            await session.commit()
            await session.refresh(sync_job)
            job_id = sync_job.id
        
        # Run rsync
        success, output, stats = await self.run_rsync(upstream, local_path, name)
        
        # Update job and mirror status
        async with self.session_maker() as session:
            now = datetime.now(timezone.utc)
            
            # Update sync job
            await session.execute(
                update(SyncJob)
                .where(SyncJob.id == job_id)
                .values(
                    status="completed" if success else "failed",
                    completed_at=now,
                    files_transferred=stats.get("files_transferred"),
                    bytes_transferred=stats.get("bytes_transferred"),
                    rsync_output=output[-10000:] if len(output) > 10000 else output,  # Limit output size
                    error_message=None if success else output[-1000:]
                )
            )
            
            # Update mirror status
            mirror_update = {
                "status": "active" if success else "error",
                "last_sync_completed": now if success else None,
                "last_sync_error": None if success else output[-500:]
            }
            
            if success and stats.get("total_size"):
                mirror_update["total_size_bytes"] = stats["total_size"]
            if success and stats.get("total_files"):
                mirror_update["file_count"] = stats["total_files"]
            
            await session.execute(
                update(Mirror)
                .where(Mirror.id == mirror_id)
                .values(**mirror_update)
            )
            await session.commit()
        
        logger.info("Mirror sync finished", mirror=name, success=success)
    
    async def run_scheduled_sync(self) -> None:
        """Run sync for all enabled mirrors."""
        logger.info("Starting scheduled sync for all mirrors")
        
        async with self.session_maker() as session:
            result = await session.execute(
                select(Mirror).where(Mirror.enabled == True)
            )
            mirrors = result.scalars().all()
        
        for mirror in mirrors:
            if not self.running:
                break
            
            await self.sync_mirror(
                mirror_id=mirror.id,
                name=mirror.name,
                upstream=mirror.upstream_url,
                local_path=mirror.local_path
            )
    
    async def scheduler_loop(self) -> None:
        """Main scheduler loop."""
        cron = croniter(config.SYNC_SCHEDULE, datetime.now())
        
        while self.running:
            next_run = cron.get_next(datetime)
            wait_seconds = (next_run - datetime.now()).total_seconds()
            
            logger.info("Next sync scheduled", next_run=next_run.isoformat(), wait_seconds=wait_seconds)
            
            try:
                await asyncio.sleep(max(0, wait_seconds))
                
                if self.running:
                    await self.run_scheduled_sync()
                    
            except asyncio.CancelledError:
                break
    
    async def health_handler(self, request: web.Request) -> web.Response:
        """Health check endpoint handler."""
        return web.json_response({
            "status": "healthy",
            "running": self.running,
            "syncing": self.current_sync is not None
        })
    
    async def start_health_server(self) -> None:
        """Start the health check HTTP server."""
        app = web.Application()
        app.router.add_get("/health", self.health_handler)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 8001)
        await site.start()
        logger.info("Health server started on port 8001")
    
    def handle_signal(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        logger.info("Received signal, shutting down", signal=signum)
        self.running = False
        
        if self.current_sync:
            self.current_sync.terminate()
    
    async def run(self) -> None:
        """Main entry point."""
        logger.info("Starting BSD Mirrors Sync Service")
        
        # Set up signal handlers
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)
        
        # Start health server
        await self.start_health_server()
        
        # Wait for database to be ready
        for i in range(30):
            try:
                async with self.engine.connect() as conn:
                    await conn.execute(select(1))
                    break
            except Exception:
                logger.info("Waiting for database...", attempt=i+1)
                await asyncio.sleep(2)
        
        # Run initial sync on startup (optional)
        if os.getenv("SYNC_ON_STARTUP", "false").lower() == "true":
            await self.run_scheduled_sync()
        
        # Start scheduler
        await self.scheduler_loop()
        
        await self.engine.dispose()
        logger.info("Sync service stopped")


# Import models (for SQLAlchemy metadata)
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, BigInteger, Enum, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Mirror(Base):
    __tablename__ = "mirrors"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True)
    mirror_type = Column(String(20))
    upstream_url = Column(String(500))
    local_path = Column(String(500))
    enabled = Column(Boolean, default=True)
    status = Column(String(20), default="active")
    last_sync_started = Column(DateTime(timezone=True))
    last_sync_completed = Column(DateTime(timezone=True))
    last_sync_error = Column(Text)
    total_size_bytes = Column(BigInteger)
    file_count = Column(BigInteger)

class SyncJob(Base):
    __tablename__ = "sync_jobs"
    id = Column(Integer, primary_key=True)
    mirror_id = Column(Integer, ForeignKey("mirrors.id"))
    status = Column(String(20), default="pending")
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    files_transferred = Column(BigInteger)
    bytes_transferred = Column(BigInteger)
    files_deleted = Column(BigInteger)
    rsync_output = Column(Text)
    error_message = Column(Text)
    triggered_by = Column(String(50))


if __name__ == "__main__":
    service = SyncService()
    asyncio.run(service.run())
