"""Tests for internal Cinetixx cache-backed endpoints."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.main import create_application
from app.services.cinetixx import CinetixxService
from app.services.cinetixx_cache import CinetixxCache
from tests.services.test_cinetixx_service import SAMPLE_DISCOVERY, SAMPLE_ROW


@pytest.fixture
def app_with_cinetixx_cache():
    app = create_application()
    cache = CinetixxCache()
    mock_client = AsyncMock()
    mock_client.get_show_info.return_value = (
        json.dumps({"shows": [SAMPLE_ROW]}),
        "application/json",
    )
    mock_client.search_cinemas.return_value = {
        "searchList": [{"searchObject": SAMPLE_DISCOVERY}],
    }
    service = CinetixxService(mock_client)

    async def override_cache():
        return cache

    async def override_service():
        return service

    from app.api.deps import get_cinetixx_cache, get_cinetixx_cached_service

    app.dependency_overrides[get_cinetixx_cache] = override_cache
    app.dependency_overrides[get_cinetixx_cached_service] = override_service
    yield app, mock_client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
class TestInternalCinetixx:
    async def test_shows_endpoint_populates_cache_on_demand(self, app_with_cinetixx_cache):
        app, mock_client = app_with_cinetixx_cache

        async with self._client(app) as client:
            response = await client.get("/api/v1/internal/cinetixx/shows?mandatorId=42")
            health = await client.get("/api/v1/internal/cinetixx/health")

        assert response.status_code == 200
        assert response.json()[0]["id"] == "123"
        assert health.status_code == 200
        assert health.json()["cached_mandators"] == [42]
        assert health.json()["cached_shows"] == 1
        mock_client.get_show_info.assert_awaited_once_with(42)

    async def test_movies_endpoint_uses_cached_data(self, app_with_cinetixx_cache):
        app, _ = app_with_cinetixx_cache

        async with self._client(app) as client:
            await client.get("/api/v1/internal/cinetixx/shows?mandatorId=42")
            response = await client.get("/api/v1/internal/cinetixx/movies?mandatorId=42")

        assert response.status_code == 200
        assert response.json()[0]["title"] == "Dune"

    async def test_mandators_endpoint_caches_discovery(self, app_with_cinetixx_cache):
        app, mock_client = app_with_cinetixx_cache

        async with self._client(app) as client:
            response = await client.get("/api/v1/internal/cinetixx/mandators?search=acud")
            cached = await client.get("/api/v1/internal/cinetixx/mandators?search=acud")
            health = await client.get("/api/v1/internal/cinetixx/health")

        assert response.status_code == 200
        assert response.json()[0]["mandatorId"] == 1627457285
        assert cached.json()[0]["cinemaId"] == "1627459203"
        assert health.json()["cached_discovered_mandators"] == 1
        mock_client.search_cinemas.assert_awaited_once()

    @staticmethod
    def _client(app) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://testserver")
