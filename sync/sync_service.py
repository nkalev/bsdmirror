"""
BSD Mirrors Sync Service

Handles scheduled rsync synchronization of BSD mirrors.
Polls for pending sync jobs created by the admin panel.
"""
import asyncio
import os
import signal
import subprocess
from datetime import datetime, timezone
from typing import Optional

from aiohttp import web
from croniter import croniter
from sqlalchemy import select, update, text
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

# How often to poll for pending jobs (seconds)
POLL_INTERVAL = 10


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
    SYNC_TIMEOUT = int(os.getenv("SYNC_TIMEOUT", "600"))

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
        # Runtime settings (reloaded from DB)
        self.sync_schedule = config.SYNC_SCHEDULE
        self.sync_bandwidth_limit = config.SYNC_BANDWIDTH_LIMIT
        self.sync_timeout = config.SYNC_TIMEOUT

    async def reload_settings(self) -> None:
        """Reload settings from the database settings table (if it exists)."""
        try:
            async with self.session_maker() as session:
                result = await session.execute(select(Setting))
                settings_rows = result.scalars().all()

                for s in settings_rows:
                    if s.key == "sync_schedule" and s.value:
                        self.sync_schedule = s.value
                    elif s.key == "sync_bandwidth_limit" and s.value:
                        try:
                            self.sync_bandwidth_limit = int(s.value)
                        except ValueError:
                            pass
                    elif s.key == "sync_timeout" and s.value:
                        try:
                            self.sync_timeout = int(s.value)
                        except ValueError:
                            pass
        except Exception as e:
            # Settings table may not exist yet — use env defaults
            logger.debug("Could not reload settings from DB", error=str(e))

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
            f"--timeout={self.sync_timeout}",
        ]

        if self.sync_bandwidth_limit > 0:
            cmd.append(f"--bwlimit={self.sync_bandwidth_limit}")

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
                except (IndexError, ValueError) as e:
                    logger.debug("Failed to parse rsync total_files", line=line.strip(), error=str(e))
            elif "Number of regular files transferred:" in line:
                try:
                    stats["files_transferred"] = int(line.split(":")[1].strip().replace(",", ""))
                except (IndexError, ValueError) as e:
                    logger.debug("Failed to parse rsync files_transferred", line=line.strip(), error=str(e))
            elif "Total file size:" in line:
                try:
                    size_str = line.split(":")[1].strip().split()[0].replace(",", "")
                    stats["total_size"] = int(size_str)
                except (IndexError, ValueError) as e:
                    logger.debug("Failed to parse rsync total_size", line=line.strip(), error=str(e))
            elif "Total transferred file size:" in line:
                try:
                    size_str = line.split(":")[1].strip().split()[0].replace(",", "")
                    stats["bytes_transferred"] = int(size_str)
                except (IndexError, ValueError) as e:
                    logger.debug("Failed to parse rsync bytes_transferred", line=line.strip(), error=str(e))

        return stats

    async def sync_mirror_job(self, job_id: int, mirror_id: int, name: str, upstream: str, local_path: str) -> None:
        """Execute a sync for a pre-existing SyncJob record."""
        async with self.session_maker() as session:
            # Mark job as running
            await session.execute(
                update(SyncJob)
                .where(SyncJob.id == job_id)
                .values(status="running", started_at=datetime.now(timezone.utc))
            )
            # Update mirror status to syncing
            await session.execute(
                update(Mirror)
                .where(Mirror.id == mirror_id)
                .values(status="syncing", last_sync_started=datetime.now(timezone.utc))
            )
            await session.commit()

        logger.info("Executing sync job", job_id=job_id, mirror=name)

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
                    rsync_output=output[-10000:] if len(output) > 10000 else output,
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

        logger.info("Mirror sync finished", mirror=name, job_id=job_id, success=success)

    async def sync_mirror(self, mirror_id: int, name: str, upstream: str, local_path: str) -> None:
        """Create a new sync job and execute it (for scheduled syncs)."""
        async with self.session_maker() as session:
            sync_job = SyncJob(
                mirror_id=mirror_id,
                status="pending",
                triggered_by="scheduled"
            )
            session.add(sync_job)
            await session.commit()
            await session.refresh(sync_job)
            job_id = sync_job.id

        await self.sync_mirror_job(job_id, mirror_id, name, upstream, local_path)

    async def poll_pending_jobs(self) -> int:
        """Check for pending sync jobs and execute them. Returns count of jobs processed."""
        processed = 0

        async with self.session_maker() as session:
            result = await session.execute(
                select(SyncJob, Mirror)
                .join(Mirror, SyncJob.mirror_id == Mirror.id)
                .where(SyncJob.status == "pending")
                .order_by(SyncJob.id.asc())
            )
            pending_jobs = result.all()

        for sync_job, mirror in pending_jobs:
            if not self.running:
                break

            logger.info("Found pending sync job", job_id=sync_job.id, mirror=mirror.name)

            await self.sync_mirror_job(
                job_id=sync_job.id,
                mirror_id=mirror.id,
                name=mirror.name,
                upstream=mirror.upstream_url,
                local_path=mirror.local_path
            )
            processed += 1

        return processed

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
        """Main scheduler loop — polls for pending jobs every POLL_INTERVAL seconds
        and runs scheduled syncs at the configured cron schedule."""
        cron = croniter(self.sync_schedule, datetime.now())
        next_run = cron.get_next(datetime)

        logger.info("Next scheduled sync", next_run=next_run.isoformat())

        while self.running:
            try:
                # Sleep in short intervals to poll for pending jobs
                await asyncio.sleep(POLL_INTERVAL)

                if not self.running:
                    break

                # Poll for manually triggered pending jobs
                processed = await self.poll_pending_jobs()
                if processed > 0:
                    logger.info("Processed pending jobs", count=processed)

                # Check if cron schedule is due
                now = datetime.now()
                if now >= next_run:
                    logger.info("Cron schedule triggered", schedule=self.sync_schedule)

                    # Reload settings before scheduled sync
                    await self.reload_settings()

                    await self.run_scheduled_sync()

                    # Advance to next cron time
                    cron = croniter(self.sync_schedule, datetime.now())
                    next_run = cron.get_next(datetime)
                    logger.info("Next scheduled sync", next_run=next_run.isoformat())

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduler loop error", error=str(e))
                await asyncio.sleep(POLL_INTERVAL)

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

        # Load settings from database
        await self.reload_settings()

        # Process any pending jobs on startup
        pending = await self.poll_pending_jobs()
        if pending > 0:
            logger.info("Processed pending jobs on startup", count=pending)

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

class Setting(Base):
    """Settings table — mirrors backend Setting model."""
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    description = Column(Text)


if __name__ == "__main__":
    service = SyncService()
    asyncio.run(service.run())
