"""Sync service module entry point."""
from sync_service import SyncService
import asyncio

if __name__ == "__main__":
    service = SyncService()
    asyncio.run(service.run())
