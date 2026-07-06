"""Tests for internal API endpoints backed by the cache."""

import datetime as dt
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_application
from app.schemas.cinema import Cinema, CitySummary
from app.schemas.city import City
from app.schemas.movie import Movie
from app.schemas.show import Show
from app.services.cache import KinoheldCache
from app.services.kinoheld import KinoheldService


@pytest.fixture
def internal_client(mock_graphql_client: AsyncMock):
    app = create_application()
    cache = KinoheldCache()
    cache._cinemas = [Cinema(id="1", name="Cached Kino")]
    cache._movies = [Movie(id="99", title="Cached Movie")]
    cache._cities = [City(id="7", name="Cached City")]
    cache._genres = []

    async def override_service():
        yield KinoheldService(mock_graphql_client)

    async def override_cache():
        # Yield whatever cache object is currently on app.state so tests can
        # swap it after lifespan startup has completed.
        yield app.state.kinoheld_cache

    from app.api.deps import get_kinoheld_cache, get_kinoheld_cached_service, get_kinoheld_service

    app.dependency_overrides[get_kinoheld_service] = override_service
    app.dependency_overrides[get_kinoheld_cache] = override_cache
    app.dependency_overrides[get_kinoheld_cached_service] = override_service

    with TestClient(app) as test_client:
        # Lifespan startup creates its own cache instance; replace it with the
        # fixture cache so dependency overrides and direct state access line up.
        app.state.kinoheld_cache = cache
        app.state.kinoheld_service = KinoheldService(mock_graphql_client)
        yield test_client

    app.dependency_overrides.clear()


class TestInternalMovies:
    def test_list_movies_returns_cached_data(self, internal_client: TestClient):
        response = internal_client.get("/api/v1/internal/movies")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "99"
        assert data[0]["title"] == "Cached Movie"

    def test_list_movies_filters_by_location(self, internal_client: TestClient):
        cache = internal_client.app.state.kinoheld_cache
        berlin_movie = Movie(id="99", title="Berlin Movie")
        munich_movie = Movie(id="88", title="Munich Movie")
        cache._movies = [berlin_movie, munich_movie]
        cache._cinemas = [
            Cinema(id="c1", name="Berlin Kino", city=CitySummary(name="Berlin")),
            Cinema(id="c2", name="Munich Kino", city=CitySummary(name="Munich")),
        ]
        cache._shows = {
            "c1::2024-06-15": [Show(id="s1", name="Show", movie=berlin_movie)],
            "c2::2024-06-15": [Show(id="s2", name="Show", movie=munich_movie)],
        }

        response = internal_client.get("/api/v1/internal/movies?location=Berlin")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "99"

    def test_get_movie_returns_cached_movie(self, internal_client: TestClient):
        response = internal_client.get("/api/v1/internal/movies/99")

        assert response.status_code == 200
        assert response.json()["title"] == "Cached Movie"

    def test_get_movie_not_found(self, internal_client: TestClient):
        response = internal_client.get("/api/v1/internal/movies/missing")

        assert response.status_code == 404


class TestInternalCinemas:
    def test_list_cinemas_returns_cached_data(self, internal_client: TestClient):
        response = internal_client.get("/api/v1/internal/cinemas")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "1"

    def test_get_cinema_returns_cached_cinema(self, internal_client: TestClient):
        response = internal_client.get("/api/v1/internal/cinemas/1")

        assert response.status_code == 200
        assert response.json()["name"] == "Cached Kino"

    def test_list_cinemas_filters_by_location(self, internal_client: TestClient):
        cache = internal_client.app.state.kinoheld_cache
        cache._cinemas = [
            Cinema(id="1", name="Berlin Kino", city=CitySummary(name="Berlin")),
            Cinema(id="2", name="Munich Kino", city=CitySummary(name="Munich")),
        ]

        response = internal_client.get("/api/v1/internal/cinemas?location=Berlin")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "1"


class TestInternalCities:
    def test_list_cities_returns_cached_data(self, internal_client: TestClient):
        response = internal_client.get("/api/v1/internal/cities")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Cached City"


class TestInternalShows:
    def test_list_shows_on_demand_fetch(
        self,
        internal_client: TestClient,
        mock_graphql_client: AsyncMock,
    ):
        mock_graphql_client.execute.return_value = {
            "shows": [
                {
                    "id": "s1",
                    "name": "Show 20:00",
                    "beginning": {"formatted": "20:00", "timestamp": 1718452800},
                    "flags": [],
                    "movie": {"id": "99", "title": "Cached Movie", "genres": []},
                    "auditorium": {"id": "a1", "name": "Saal 1"},
                },
            ],
        }

        response = internal_client.get("/api/v1/internal/shows?cinemaId=123&movieId=99")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "s1"

    def test_list_shows_fetches_missing_dates(
        self,
        internal_client: TestClient,
        mock_graphql_client: AsyncMock,
    ):
        cache = internal_client.app.state.kinoheld_cache
        today = dt.date.today()
        cache._shows = {
            f"123::{today.isoformat()}": [Show(id="s1", name="Cached Show")],
        }

        mock_graphql_client.execute.return_value = {
            "shows": [
                {
                    "id": "s2",
                    "name": "Show Tomorrow",
                    "beginning": {"formatted": "20:00", "timestamp": 1718452800},
                    "flags": [],
                    "movie": {"id": "99", "title": "Cached Movie", "genres": []},
                    "auditorium": {"id": "a1", "name": "Saal 1"},
                },
            ],
        }

        response = internal_client.get(
            f"/api/v1/internal/shows?cinemaId=123&date={today.isoformat()}&days=2",
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert {s["id"] for s in data} == {"s1", "s2"}

    def test_get_show_returns_cached_show(self, internal_client: TestClient):
        cache = internal_client.app.state.kinoheld_cache
        cache._shows = {
            f"123::{dt.date.today().isoformat()}": [Show(id="s1", name="Cached Show")],
        }

        response = internal_client.get("/api/v1/internal/shows/s1")

        assert response.status_code == 200
        assert response.json()["name"] == "Cached Show"


class TestInternalHealth:
    def test_reports_cache_status(self, internal_client: TestClient):
        response = internal_client.get("/api/v1/internal/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["source"] == "cache"
        assert data["cached_movies"] == 1

    def test_reports_cached_shows(self, internal_client: TestClient):
        cache = internal_client.app.state.kinoheld_cache
        cache._shows = {
            f"123::{dt.date.today().isoformat()}": [Show(id="s1", name="Show")],
        }

        response = internal_client.get("/api/v1/internal/health")

        assert response.status_code == 200
        data = response.json()
        assert data["cached_shows"] == 1
