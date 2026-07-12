"""Tests for Cinetixx API endpoints."""

import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import httpx
import pytest

from app.main import create_application
from app.services.cinetixx import CinetixxService
from tests.services.test_cinetixx_service import SAMPLE_ROW


@pytest.fixture
def app_with_cinetixx_mock():
    mock_cinetixx_client = AsyncMock()
    mock_cinetixx_client.get_show_info.return_value = (
        json.dumps({"shows": [SAMPLE_ROW]}),
        "application/json",
    )
    app = create_application()

    async def override_get_cinetixx_service() -> AsyncGenerator[CinetixxService, None]:
        yield CinetixxService(mock_cinetixx_client)

    from app.api.deps import get_cinetixx_service

    app.dependency_overrides[get_cinetixx_service] = override_get_cinetixx_service
    yield app, mock_cinetixx_client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
class TestGetCinetixxShowInfo:
    async def test_returns_show_info(self, app_with_cinetixx_mock):
        app, mock_cinetixx_client = app_with_cinetixx_mock

        async with self._client(app) as client:
            response = await client.get("/api/v1/cinetixx/show-info?mandatorId=42")

        assert response.status_code == 200
        assert response.json() == {
            "source": "cinetixx",
            "endpoint": "GetShowInfoV6",
            "mandatorId": 42,
            "contentType": "application/json",
            "data": {"shows": [SAMPLE_ROW]},
        }
        mock_cinetixx_client.get_show_info.assert_awaited_once_with(42)

    async def test_missing_mandator_id_returns_validation_error(self, app_with_cinetixx_mock):
        app, _ = app_with_cinetixx_mock

        async with self._client(app) as client:
            response = await client.get("/api/v1/cinetixx/show-info")

        assert response.status_code == 422

    async def test_returns_normalized_shows(self, app_with_cinetixx_mock):
        app, _ = app_with_cinetixx_mock

        async with self._client(app) as client:
            response = await client.get("/api/v1/cinetixx/shows?mandatorId=42&movieId=456")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "123"
        assert data[0]["movieTitle"] == "Dune"
        assert data[0]["cinemaName"] == "Weltspiegel Cottbus"

    async def test_returns_normalized_movies(self, app_with_cinetixx_mock):
        app, _ = app_with_cinetixx_mock

        async with self._client(app) as client:
            response = await client.get("/api/v1/cinetixx/movies?mandatorId=42&search=dune")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "456"
        assert data[0]["title"] == "Dune"

    async def test_non_positive_mandator_id_returns_validation_error(self, app_with_cinetixx_mock):
        app, _ = app_with_cinetixx_mock

        async with self._client(app) as client:
            response = await client.get("/api/v1/cinetixx/show-info?mandatorId=0")

        assert response.status_code == 422

    @staticmethod
    def _client(app) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://testserver")
