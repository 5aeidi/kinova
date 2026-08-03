"""Tests for Yorck cache-backed internal and unified endpoints."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.main import create_application
from app.services.cache import KinoheldCache
from app.services.cinetixx import CinetixxService
from app.services.cinetixx_cache import CinetixxCache
from app.services.yorck_cache import YorckCache
from tests.services.test_yorck_service import make_service


@pytest.fixture
def app_with_yorck_cache():
    app = create_application()
    cache = YorckCache()
    service = make_service()
    kinoheld_cache = KinoheldCache()
    cinetixx_cache = CinetixxCache()
    cinetixx_service = CinetixxService(AsyncMock())

    async def override_cache():
        return cache

    async def override_service():
        return service

    async def override_kinoheld_cache():
        return kinoheld_cache

    async def override_cinetixx_cache():
        return cinetixx_cache

    async def override_cinetixx_service():
        return cinetixx_service

    from app.api.deps import (
        get_cinetixx_cache,
        get_cinetixx_cached_service,
        get_kinoheld_cache,
        get_yorck_cache,
        get_yorck_cached_service,
    )

    app.dependency_overrides[get_yorck_cache] = override_cache
    app.dependency_overrides[get_yorck_cached_service] = override_service
    app.dependency_overrides[get_kinoheld_cache] = override_kinoheld_cache
    app.dependency_overrides[get_cinetixx_cache] = override_cinetixx_cache
    app.dependency_overrides[get_cinetixx_cached_service] = override_cinetixx_service
    yield app
    app.dependency_overrides.clear()


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
class TestInternalYorck:
    async def test_cinemas_populate_on_demand(self, app_with_yorck_cache):
        async with _client(app_with_yorck_cache) as client:
            response = await client.get("/api/v1/internal/yorck/cinemas")

        assert response.status_code == 200
        data = response.json()
        assert [item["id"] for item in data] == ["babylon-kreuzberg"]
        assert data[0]["source"] == "yorck"

    async def test_get_movie_by_slug(self, app_with_yorck_cache):
        async with _client(app_with_yorck_cache) as client:
            response = await client.get("/api/v1/internal/yorck/movies/dreams")

        assert response.status_code == 200
        assert response.json()["id"] == "HO00005912"
        assert response.json()["directors"] == ["Michel Franco"]

    async def test_shows_filter_by_cinema(self, app_with_yorck_cache):
        async with _client(app_with_yorck_cache) as client:
            response = await client.get(
                "/api/v1/internal/yorck/shows?cinemaId=babylon-kreuzberg",
            )

        assert response.status_code == 200
        data = response.json()
        assert [item["id"] for item in data] == ["1002-15565"]

    async def test_missing_movie_returns_404(self, app_with_yorck_cache):
        async with _client(app_with_yorck_cache) as client:
            response = await client.get("/api/v1/internal/yorck/movies/missing")

        assert response.status_code == 404

    async def test_health_reports_cache_counts(self, app_with_yorck_cache):
        async with _client(app_with_yorck_cache) as client:
            await client.get("/api/v1/internal/yorck/cinemas")
            response = await client.get("/api/v1/internal/yorck/health")

        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "yorck-cache"
        assert body["cached_cinemas"] == 1
        assert body["cached_shows"] == 1

    async def test_unified_movies_include_yorck(self, app_with_yorck_cache):
        async with _client(app_with_yorck_cache) as client:
            response = await client.get("/api/v1/internal/unified/movies?source=yorck")

        assert response.status_code == 200
        data = response.json()
        assert {item["source"] for item in data} == {"yorck"}
        assert {item["id"] for item in data} >= {"HO00005912"}

    async def test_unified_get_by_prefixed_id(self, app_with_yorck_cache):
        async with _client(app_with_yorck_cache) as client:
            response = await client.get("/api/v1/internal/unified/movies/yorck:dreams")

        assert response.status_code == 200
        assert response.json()["source"] == "yorck"
        assert response.json()["sourceId"] == "HO00005912"

    async def test_unified_shows_include_yorck(self, app_with_yorck_cache):
        async with _client(app_with_yorck_cache) as client:
            response = await client.get(
                "/api/v1/internal/unified/shows?source=yorck&cinemaId=babylon-kreuzberg",
            )

        assert response.status_code == 200
        data = response.json()
        assert [item["id"] for item in data] == ["1002-15565"]
        assert data[0]["movie"]["title"] == "Dreams"
        assert data[0]["detailUrl"]["url"] == (
            "https://www.yorck.de/en/checkout/seats?sessionid=1002-15565"
        )
