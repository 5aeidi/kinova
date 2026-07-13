"""Tests for unified internal cache-backed endpoints."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.main import create_application
from app.schemas.cinema import Cinema, CitySummary
from app.schemas.cinetixx import CinetixxCinema
from app.schemas.city import City
from app.schemas.movie import Genre, Movie
from app.schemas.show import DateTimeFormatted, Show
from app.services.cache import KinoheldCache
from app.services.cinetixx import CinetixxService
from app.services.cinetixx_cache import CinetixxCache
from app.services.unified import cinetixx_cinema_to_unified
from tests.services.test_cinetixx_service import SAMPLE_ROW


@pytest.fixture
def app_with_unified_caches():
    app = create_application()
    kinoheld_cache = KinoheldCache()
    kinoheld_movie = Movie(
        id="kh-m1",
        title="Kinoheld Dune",
        genres=[Genre(id="sci-fi", name="Science Fiction")],
    )
    kinoheld_cache._cinemas = [
        Cinema(id="kh-c1", name="Kinoheld Cinema", city=CitySummary(id="berlin", name="Berlin")),
    ]
    kinoheld_cache._movies = [kinoheld_movie]
    kinoheld_cache._cities = [City(id="berlin", name="Berlin")]
    kinoheld_cache._genres = [Genre(id="sci-fi", name="Science Fiction")]
    kinoheld_cache._shows = {
        "kh-c1::2026-07-13": [
            Show(
                id="kh-s1",
                name="Kinoheld Dune 20:00",
                beginning=DateTimeFormatted(formatted="20:00", timestamp=1783972800),
                movie=kinoheld_movie,
            ),
        ],
    }

    cinetixx_cache = CinetixxCache()
    mock_cinetixx_client = AsyncMock()
    mock_cinetixx_client.get_show_info.return_value = (
        json.dumps({"shows": [SAMPLE_ROW]}),
        "application/json",
    )
    cinetixx_service = CinetixxService(mock_cinetixx_client)

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
    )

    app.dependency_overrides[get_kinoheld_cache] = override_kinoheld_cache
    app.dependency_overrides[get_cinetixx_cache] = override_cinetixx_cache
    app.dependency_overrides[get_cinetixx_cached_service] = override_cinetixx_service
    yield app, mock_cinetixx_client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
class TestInternalUnified:
    def test_cinetixx_cinema_includes_discovered_location(self):
        cinema = cinetixx_cinema_to_unified(
            CinetixxCinema(
                id="c1",
                mandatorId=42,
                name="Cinema",
                address="Example Street 1",
                postCode="10119",
                latitude=52.5,
                longitude=13.4,
            ),
        )

        assert cinema.coordinates.model_dump() == {"latitude": 52.5, "longitude": 13.4}
        assert cinema.street == "Example Street 1"

    async def test_movies_include_source_tags(self, app_with_unified_caches):
        app, _ = app_with_unified_caches

        async with self._client(app) as client:
            response = await client.get("/api/v1/internal/unified/movies?mandatorId=42")

        assert response.status_code == 200
        data = response.json()
        assert {item["source"] for item in data} == {"kinoheld", "cinetixx"}
        assert {item["id"] for item in data} == {"kh-m1", "456"}
        assert {item["sourceId"] for item in data} == {"kh-m1", "456"}

    async def test_source_filter_returns_single_provider(self, app_with_unified_caches):
        app, _ = app_with_unified_caches

        async with self._client(app) as client:
            response = await client.get(
                "/api/v1/internal/unified/shows?source=cinetixx&mandatorId=42&cinemaId=20",
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["source"] == "cinetixx"
        assert data[0]["id"] == "123"
        assert data[0]["sourceId"] == "123"

    async def test_get_by_prefixed_id(self, app_with_unified_caches):
        app, _ = app_with_unified_caches

        async with self._client(app) as client:
            response = await client.get(
                "/api/v1/internal/unified/movies/cinetixx:456?mandatorId=42"
            )

        assert response.status_code == 200
        assert response.json()["source"] == "cinetixx"
        assert response.json()["id"] == "456"
        assert response.json()["sourceId"] == "456"

    async def test_invalid_source_returns_error(self, app_with_unified_caches):
        app, _ = app_with_unified_caches

        async with self._client(app) as client:
            response = await client.get("/api/v1/internal/unified/movies?source=unknown")

        assert response.status_code == 400

    @staticmethod
    def _client(app) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://testserver")
