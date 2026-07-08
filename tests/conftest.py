"""Shared pytest fixtures."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.main import create_application
from app.services.graphql_client import GraphQLClient
from app.services.kinoheld import KinoheldService


@pytest.fixture(autouse=True)
def _disable_lifespan_network_calls(monkeypatch):
    """Unit tests should not depend on the real Kinoheld network."""

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    monkeypatch.setattr("app.main.lifespan", noop_lifespan)


@pytest.fixture
def mock_graphql_client() -> AsyncMock:
    """Return a mock GraphQL client whose execute method can be configured per test."""
    return AsyncMock(spec=GraphQLClient)


@pytest.fixture
def kinoheld_service(mock_graphql_client: AsyncMock) -> KinoheldService:
    """Return a KinoheldService backed by a mock GraphQL client."""
    return KinoheldService(mock_graphql_client)


@pytest.fixture
def test_app(mock_graphql_client: AsyncMock):
    """Create a FastAPI test app with the GraphQL client dependency overridden."""
    app = create_application()

    async def override_get_kinoheld_service() -> AsyncGenerator[KinoheldService, None]:
        yield KinoheldService(mock_graphql_client)

    from app.api.deps import get_kinoheld_service

    app.dependency_overrides[get_kinoheld_service] = override_get_kinoheld_service
    yield app
    app.dependency_overrides.clear()
