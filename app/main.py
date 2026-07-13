"""FastAPI application entrypoint."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import KinovaError, generic_exception_handler, kinova_exception_handler
from app.services.cache import KinoheldCache
from app.services.cinetixx import CinetixxService
from app.services.cinetixx_cache import CinetixxCache
from app.services.cinetixx_client import CinetixxClient
from app.services.graphql_client import GraphQLClient
from app.services.kinoheld import KinoheldService
from app.services.sync import run_periodic_sync

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage the Kinoheld cache and background sync task."""
    cache = KinoheldCache()
    app.state.kinoheld_cache = cache
    cinetixx_cache = CinetixxCache()
    app.state.cinetixx_cache = cinetixx_cache

    sync_task: asyncio.Task[None] | None = None
    cinetixx_sync_task: asyncio.Task[None] | None = None
    cinetixx_initial_refresh_task: asyncio.Task[None] | None = None
    client: GraphQLClient | None = None
    cinetixx_client: CinetixxClient | None = None

    try:
        client = GraphQLClient()
        service = KinoheldService(client)
        app.state.kinoheld_service = service
        cinetixx_client = CinetixxClient()
        cinetixx_service = CinetixxService(cinetixx_client)
        app.state.cinetixx_service = cinetixx_service

        logger.info("Performing initial Kinoheld cache refresh")
        with contextlib.suppress(Exception):
            await cache.refresh(service)
        logger.info("Scheduling initial Cinetixx cache refresh in the background")
        cinetixx_initial_refresh_task = asyncio.create_task(
            cinetixx_cache.refresh(cinetixx_service),
            name="cinetixx-initial-cache-refresh",
        )

        sync_task = asyncio.create_task(
            run_periodic_sync(cache, service, settings.kinoheld_sync_interval_seconds),
        )
        cinetixx_sync_task = asyncio.create_task(
            run_periodic_sync(
                cinetixx_cache,
                cinetixx_service,
                settings.cinetixx_sync_interval_seconds,
            ),
        )
        yield
    finally:
        if sync_task is not None:
            sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sync_task
        if cinetixx_sync_task is not None:
            cinetixx_sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cinetixx_sync_task
        if cinetixx_initial_refresh_task is not None:
            cinetixx_initial_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cinetixx_initial_refresh_task
        if client is not None:
            await client.close()
        if cinetixx_client is not None:
            await cinetixx_client.close()


def create_application() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title=settings.app_name,
        description="Kinova — a RESTful wrapper around the Kinoheld GraphQL API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    app.add_exception_handler(KinovaError, kinova_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    return app


app = create_application()
