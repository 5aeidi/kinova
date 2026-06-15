"""FastAPI dependencies."""

from collections.abc import AsyncGenerator

from fastapi import Request

from app.services.graphql_client import GraphQLClient
from app.services.kinoheld import KinoheldService


async def get_kinoheld_service(request: Request) -> AsyncGenerator[KinoheldService, None]:
    """Yield a KinoheldService backed by a request-scoped GraphQL client."""
    async with GraphQLClient() as client:
        yield KinoheldService(client)
