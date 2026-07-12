"""Background periodic sync task for source caches."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_periodic_sync(cache, service, interval: int) -> None:
    """Refresh ``cache`` every ``interval`` seconds until cancelled.

    The first refresh is expected to be triggered by the application lifespan
    startup; this loop performs subsequent refreshes.
    """
    while True:
        try:
            await asyncio.sleep(interval)
            await cache.refresh(service)
        except asyncio.CancelledError:
            logger.info("Periodic sync task cancelled")
            raise
        except Exception:
            logger.exception("Periodic cache refresh failed")
