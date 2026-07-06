"""Tests for the Kinoheld cache layer."""

import datetime as dt
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import KinoheldNotFoundError
from app.schemas.cinema import Cinema, CinemaSearchParams, CitySummary
from app.schemas.city import City, CitySearchParams
from app.schemas.common import Geo
from app.schemas.movie import Movie, MovieSearchParams
from app.schemas.show import Show, ShowSearchParams
from app.services.cache import KinoheldCache
from app.services.kinoheld import KinoheldService


@pytest.fixture
def mock_service() -> AsyncMock:
    return AsyncMock(spec=KinoheldService)


@pytest.fixture
def cache() -> KinoheldCache:
    return KinoheldCache()


@pytest.mark.asyncio
class TestRefresh:
    async def test_populates_cache_from_service(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
    ):
        mock_service.search_cinemas.return_value = [Cinema(id="1", name="Kino")]
        mock_service.search_movies.return_value = [Movie(id="99", title="Dune")]
        mock_service.search_cities.return_value = [City(id="7", name="Berlin")]
        mock_service.list_genres.return_value = []

        await cache.refresh(mock_service)

        assert (await cache.get_cinema("1")).name == "Kino"
        assert (await cache.get_movie("99")).title == "Dune"
        assert (await cache.get_city("7")).name == "Berlin"


@pytest.mark.asyncio
class TestSearchCinemas:
    async def test_filters_by_name(self, cache: KinoheldCache):
        cache._cinemas = [Cinema(id="1", name="Kino Berlin"), Cinema(id="2", name="Zoo Palast")]

        results = await cache.search_cinemas(CinemaSearchParams(search="berlin", limit=10))

        assert [c.id for c in results] == ["1"]

    async def test_filters_by_location_distance(self, cache: KinoheldCache):
        berlin = Cinema(
            id="1",
            name="Berlin Kino",
            coordinates=Geo(latitude=52.52, longitude=13.405),
        )
        munich = Cinema(
            id="2",
            name="Munich Kino",
            coordinates=Geo(latitude=48.135, longitude=11.582),
        )
        cache._cities = [
            City(id="1", name="Berlin", coordinates=Geo(latitude=52.52, longitude=13.405)),
        ]
        cache._cinemas = [berlin, munich]

        results = await cache.search_cinemas(
            CinemaSearchParams(location="Berlin", distance=10, limit=10),
        )

        assert [c.id for c in results] == ["1"]

    async def test_filters_by_location_without_distance(self, cache: KinoheldCache):
        berlin = Cinema(id="1", name="Berlin Kino", city=CitySummary(name="Berlin"))
        munich = Cinema(id="2", name="Munich Kino", city=CitySummary(name="Munich"))
        cache._cinemas = [berlin, munich]

        results = await cache.search_cinemas(
            CinemaSearchParams(location="Berlin", limit=10),
        )

        assert [c.id for c in results] == ["1"]


@pytest.mark.asyncio
class TestSearchMovies:
    async def test_filters_by_title(self, cache: KinoheldCache):
        cache._movies = [Movie(id="1", title="Dune"), Movie(id="2", title="Oppenheimer")]

        results = await cache.search_movies(MovieSearchParams(search="dune", limit=10))

        assert [m.id for m in results] == ["1"]

    async def test_filters_by_location_without_distance(self, cache: KinoheldCache):
        berlin_cinema = Cinema(id="c1", name="Berlin Kino", city=CitySummary(name="Berlin"))
        munich_cinema = Cinema(id="c2", name="Munich Kino", city=CitySummary(name="Munich"))
        berlin_movie = Movie(id="m1", title="Berlin Movie")
        munich_movie = Movie(id="m2", title="Munich Movie")

        cache._cinemas = [berlin_cinema, munich_cinema]
        cache._movies = [berlin_movie, munich_movie]
        cache._shows = {
            "c1::2024-06-15": [Show(id="s1", name="Show", movie=berlin_movie)],
            "c2::2024-06-15": [Show(id="s2", name="Show", movie=munich_movie)],
        }

        results = await cache.search_movies(MovieSearchParams(location="Berlin", limit=10))

        assert [m.id for m in results] == ["m1"]


@pytest.mark.asyncio
class TestSearchShows:
    async def test_filters_by_cinema_and_movie(self, cache: KinoheldCache):
        show = Show(
            id="s1",
            name="Dune 20:00",
            movie=Movie(id="1", title="Dune"),
        )
        cache._shows = {"123::2024-06-15": [show]}

        results = await cache.search_shows(
            ShowSearchParams(cinema_id="123", date=dt.date(2024, 6, 15), movie_id="1"),
        )

        assert len(results) == 1
        assert results[0].id == "s1"

    async def test_filters_by_days_range(self, cache: KinoheldCache):
        show_today = Show(id="s1", name="Today")
        show_tomorrow = Show(id="s2", name="Tomorrow")
        cache._shows = {
            "123::2024-06-15": [show_today],
            "123::2024-06-16": [show_tomorrow],
        }

        results = await cache.search_shows(
            ShowSearchParams(cinema_id="123", date=dt.date(2024, 6, 15), days=2),
        )

        assert len(results) == 2
        assert {s.id for s in results} == {"s1", "s2"}


@pytest.mark.asyncio
class TestGetShow:
    async def test_raises_when_not_found(self, cache: KinoheldCache):
        with pytest.raises(KinoheldNotFoundError):
            await cache.get_show("missing")


@pytest.mark.asyncio
class TestSearchCities:
    async def test_filters_by_name(self, cache: KinoheldCache):
        cache._cities = [City(id="1", name="Berlin"), City(id="2", name="Munich")]

        results = await cache.search_cities(CitySearchParams(search="ber", limit=10))

        assert [c.id for c in results] == ["1"]
