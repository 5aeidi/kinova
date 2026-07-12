"""FastAPI dependencies."""

from collections.abc import AsyncGenerator

from fastapi import Request

from app.core.config import settings
from app.services.cache import KinoheldCache
from app.services.cinetixx import CinetixxService
from app.services.cinetixx_cache import CinetixxCache
from app.services.cinetixx_client import CinetixxClient
from app.services.graphql_client import GraphQLClient
from app.services.kinoheld import KinoheldService
from app.services.llm_client import LLMClient


async def get_kinoheld_service(request: Request) -> AsyncGenerator[KinoheldService, None]:
    """Yield a KinoheldService backed by a request-scoped GraphQL client."""
    async with GraphQLClient() as client:
        yield KinoheldService(client)


async def get_kinoheld_cache(request: Request) -> KinoheldCache:
    """Return the shared in-memory Kinoheld cache."""
    return request.app.state.kinoheld_cache


async def get_kinoheld_cached_service(request: Request) -> KinoheldService:
    """Return the shared Kinoheld service used by the background sync task."""
    return request.app.state.kinoheld_service


async def get_cinetixx_service() -> AsyncGenerator[CinetixxService, None]:
    """Yield a CinetixxService backed by a request-scoped HTTP client."""
    async with CinetixxClient() as client:
        yield CinetixxService(client)


async def get_cinetixx_cache(request: Request) -> CinetixxCache:
    """Return the shared in-memory Cinetixx cache."""
    return request.app.state.cinetixx_cache


async def get_cinetixx_cached_service(request: Request) -> CinetixxService:
    """Return the shared Cinetixx service used by the background sync task."""
    return request.app.state.cinetixx_service


async def get_llm_client() -> AsyncGenerator[LLMClient, None]:
    """Yield an LLM client for natural-language search."""
    async with LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    ) as client:
        yield client
