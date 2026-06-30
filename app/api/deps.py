"""FastAPI dependencies."""

from collections.abc import AsyncGenerator

from fastapi import Request

from app.services.cache import KinoheldCache
from app.services.graphql_client import GraphQLClient
from app.services.kinoheld import KinoheldService


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
