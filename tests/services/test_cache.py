"""Tests for the Kinoheld cache layer."""

import datetime as dt
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.core.exceptions import KinoheldNotFoundError
from app.schemas.cinema import Cinema, CinemaSearchParams, CitySummary
from app.schemas.city import City, CitySearchParams
from app.schemas.common import Geo
from app.schemas.movie import Genre, Movie, MovieSearchParams
from app.schemas.show import Show, ShowSearchParams
from app.services.cache import KinoheldCache, _intern_movies
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

    async def test_prewarms_shows_for_the_first_n_cinemas(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
        monkeypatch,
    ):
        """Without this, cached_shows silently stays 0 when no cinema IDs are set."""
        monkeypatch.setattr(settings, "kinoheld_sync_cinema_ids", [])
        monkeypatch.setattr(settings, "kinoheld_sync_cinema_count", 2)
        monkeypatch.setattr(settings, "kinoheld_sync_show_days", 1)
        mock_service.search_cinemas.return_value = [
            Cinema(id=str(i), name=f"Kino {i}") for i in range(5)
        ]
        mock_service.search_movies.return_value = []
        mock_service.search_cities.return_value = []
        mock_service.list_genres.return_value = []
        mock_service.search_shows.return_value = [Show(id="s1", name="Show")]

        await cache.refresh(mock_service)

        snapshot = cache.snapshot()
        assert sum(snapshot["shows"].values()) == 2
        assert {key.split("::")[0] for key in snapshot["shows"]} == {"0", "1"}

    async def test_priority_locations_get_the_prewarm_budget_first(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
        monkeypatch,
    ):
        """A small budget must land on the locations we actually serve."""
        monkeypatch.setattr(settings, "kinoheld_sync_cinema_ids", [])
        monkeypatch.setattr(settings, "kinoheld_sync_priority_locations", ["Berlin"])
        monkeypatch.setattr(settings, "kinoheld_sync_cinema_count", 2)
        monkeypatch.setattr(settings, "kinoheld_sync_show_days", 1)
        berlin = [Cinema(id="b1", name="Babylon"), Cinema(id="b2", name="Central")]
        catalogue = [Cinema(id=f"x{i}", name=f"Elsewhere {i}") for i in range(50)]

        async def search_cinemas(params):
            return berlin if params.location == "Berlin" else catalogue

        mock_service.search_cinemas.side_effect = search_cinemas
        mock_service.search_movies.return_value = []
        mock_service.search_cities.return_value = []
        mock_service.list_genres.return_value = []
        mock_service.search_shows.return_value = []

        await cache.refresh(mock_service)

        assert {key.split("::")[0] for key in cache.snapshot()["shows"]} == {"b1", "b2"}
        # Priority cinemas lead the cached list, and the rest of the catalogue follows.
        assert [c.id for c in cache._cinemas[:2]] == ["b1", "b2"]
        assert len(cache._cinemas) == 52

    async def test_priority_location_is_not_backfilled_again(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
        monkeypatch,
    ):
        monkeypatch.setattr(settings, "kinoheld_sync_priority_locations", ["Berlin"])
        monkeypatch.setattr(settings, "kinoheld_sync_cinema_count", 0)
        mock_service.search_cinemas.return_value = [Cinema(id="b1", name="Babylon")]
        mock_service.search_movies.return_value = []
        mock_service.search_cities.return_value = []
        mock_service.list_genres.return_value = []

        await cache.refresh(mock_service)

        assert await cache.is_location_backfilled("berlin") is True
        assert await cache.is_location_backfilled("Hamburg") is False

    async def test_failed_priority_location_is_not_marked_backfilled(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
        monkeypatch,
    ):
        monkeypatch.setattr(settings, "kinoheld_sync_priority_locations", ["Berlin"])
        monkeypatch.setattr(settings, "kinoheld_sync_cinema_count", 0)

        async def search_cinemas(params):
            if params.location == "Berlin":
                raise RuntimeError("upstream down")
            return []

        mock_service.search_cinemas.side_effect = search_cinemas
        mock_service.search_movies.return_value = []
        mock_service.search_cities.return_value = []
        mock_service.list_genres.return_value = []

        await cache.refresh(mock_service)

        assert await cache.is_location_backfilled("Berlin") is False

    async def test_explicit_cinema_ids_are_merged_with_the_auto_selection(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
        monkeypatch,
    ):
        monkeypatch.setattr(settings, "kinoheld_sync_cinema_ids", ["99"])
        monkeypatch.setattr(settings, "kinoheld_sync_cinema_count", 1)
        monkeypatch.setattr(settings, "kinoheld_sync_show_days", 1)
        mock_service.search_cinemas.return_value = [Cinema(id="0", name="Kino")]
        mock_service.search_movies.return_value = []
        mock_service.search_cities.return_value = []
        mock_service.list_genres.return_value = []
        mock_service.search_shows.return_value = []

        await cache.refresh(mock_service)

        assert {key.split("::")[0] for key in cache.snapshot()["shows"]} == {"99", "0"}


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
        berlin = Cinema(
            id="1",
            name="Berlin Kino",
            city=CitySummary(name="Berlin"),
            coordinates=Geo(latitude=52.52, longitude=13.405),
        )
        munich = Cinema(
            id="2",
            name="Munich Kino",
            city=CitySummary(name="Munich"),
            coordinates=Geo(latitude=48.135, longitude=11.582),
        )
        cache._cities = [
            City(id="1", name="Berlin", coordinates=Geo(latitude=52.52, longitude=13.405)),
        ]
        cache._cinemas = [berlin, munich]

        results = await cache.search_cinemas(
            CinemaSearchParams(location="Berlin", limit=10),
        )

        assert [c.id for c in results] == ["1"]

    async def test_filters_by_location_uses_default_radius(self, cache: KinoheldCache):
        centre = City(id="1", name="Berlin", coordinates=Geo(latitude=52.52, longitude=13.405))
        berlin_cinema = Cinema(
            id="1",
            name="Berlin Kino",
            coordinates=Geo(latitude=52.53, longitude=13.41),
        )
        nearby_cinema = Cinema(
            id="2",
            name="Potsdam Kino",
            coordinates=Geo(latitude=52.4, longitude=13.07),
        )
        far_cinema = Cinema(
            id="3",
            name="Munich Kino",
            coordinates=Geo(latitude=48.135, longitude=11.582),
        )
        cache._cities = [centre]
        cache._cinemas = [berlin_cinema, nearby_cinema, far_cinema]

        results = await cache.search_cinemas(
            CinemaSearchParams(location="Berlin", limit=10),
        )

        assert {c.id for c in results} == {"1", "2"}


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
class TestCacheHelpers:
    async def test_add_cinemas_merges_without_duplicates(self, cache: KinoheldCache):
        cache._cinemas = [Cinema(id="1", name="Kino")]
        await cache.add_cinemas([Cinema(id="1", name="Kino"), Cinema(id="2", name="Kino 2")])

        assert len(cache._cinemas) == 2
        assert {c.id for c in cache._cinemas} == {"1", "2"}

    async def test_has_any_shows(self, cache: KinoheldCache):
        cache._shows = {"c1::2024-06-15": [Show(id="s1", name="Show")]}

        assert await cache.has_any_shows("c1") is True
        assert await cache.has_any_shows("c2") is False


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

    async def test_location_filters_by_distance(self, cache: KinoheldCache):
        cache._cities = [
            City(id="1", name="Berlin", coordinates=Geo(latitude=52.52, longitude=13.405)),
            City(id="2", name="Potsdam", coordinates=Geo(latitude=52.39, longitude=13.06)),
            City(id="3", name="Munich", coordinates=Geo(latitude=48.14, longitude=11.58)),
        ]

        results = await cache.search_cities(CitySearchParams(location="Berlin", limit=10))

        assert {c.id for c in results} == {"1", "2"}

    async def test_location_falls_back_to_name_match(self, cache: KinoheldCache):
        cache._cities = [City(id="1", name="Berlin"), City(id="2", name="Munich")]

        results = await cache.search_cities(CitySearchParams(location="Berlin", limit=10))

        assert [c.id for c in results] == ["1"]


@pytest.mark.asyncio
class TestOnDemandShows:
    async def test_refresh_keeps_on_demand_shows(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
    ):
        future = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        cache._shows = {f"c9::{future}": [Show(id="s1", name="Show")]}
        mock_service.search_cinemas.return_value = []
        mock_service.search_movies.return_value = []
        mock_service.search_cities.return_value = []
        mock_service.list_genres.return_value = []

        await cache.refresh(mock_service)

        assert f"c9::{future}" in cache._shows

    async def test_refresh_prunes_past_show_dates(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
    ):
        past = (dt.date.today() - dt.timedelta(days=2)).isoformat()
        cache._shows = {f"c9::{past}": [Show(id="s1", name="Show")]}
        mock_service.search_cinemas.return_value = []
        mock_service.search_movies.return_value = []
        mock_service.search_cities.return_value = []
        mock_service.list_genres.return_value = []

        await cache.refresh(mock_service)

        assert cache._shows == {}

    async def test_cache_shows_for_cinema_survives_a_failing_date(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
    ):
        good_show = Show(id="s1", name="Show")
        mock_service.search_shows.side_effect = [RuntimeError("boom"), [good_show]]

        await cache.cache_shows_for_cinema(mock_service, "c1", ["2026-07-25", "2026-07-26"])

        assert "c1::2026-07-25" not in cache._shows
        assert cache._shows["c1::2026-07-26"] == [good_show]


@pytest.mark.asyncio
class TestGenreEnrichment:
    async def test_show_embedded_genres_backfilled_from_catalog(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
    ):
        cache._movies = [
            Movie(id="99", title="Die Odyssee", genres=[Genre(id="5", name="Drama")]),
        ]
        show = Show(
            id="s1",
            name="Die Odyssee (OmU)",
            movie=Movie(id="426501", title="Die Odyssee (OmU)", genres=[Genre(name="")]),
        )
        mock_service.search_shows.return_value = [show]

        await cache.cache_shows_for_cinema(mock_service, "c1", ["2026-07-26"])

        cached = cache._shows["c1::2026-07-26"][0]
        assert [g.name for g in cached.movie.genres] == ["Drama"]

    async def test_genres_resolved_live_for_titles_outside_cached_catalog(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
    ):
        """Arthouse/event films fall outside the capped catalog slice; look them up."""
        cache._movies = []
        show = Show(
            id="s1",
            name="Unearthing Time: Joan of Arc (OmeU)",
            movie=Movie(id="424933", title="Unearthing Time: Joan of Arc (OmeU)", genres=[]),
        )
        mock_service.search_shows.return_value = [show]
        mock_service.search_movies.return_value = [
            Movie(
                id="7",
                title="Unearthing Time: Joan of Arc",
                genres=[Genre(id="9", name="Dokumentarfilm")],
            ),
        ]

        await cache.cache_shows_for_cinema(mock_service, "c1", ["2026-07-26"])

        cached = cache._shows["c1::2026-07-26"][0]
        assert [g.name for g in cached.movie.genres] == ["Dokumentarfilm"]

    async def test_resolved_genres_are_remembered_across_batches(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
    ):
        cache._movies = []
        mock_service.search_movies.return_value = [
            Movie(id="7", title="Rose", genres=[Genre(name="Drama")]),
        ]

        def make_show():
            return Show(id="s1", name="Rose (OmU)", movie=Movie(id="1", title="Rose (OmU)"))

        mock_service.search_shows.return_value = [make_show()]
        await cache.cache_shows_for_cinema(mock_service, "c1", ["2026-07-26"])
        lookups = mock_service.search_movies.await_count

        mock_service.search_shows.return_value = [make_show()]
        await cache.cache_shows_for_cinema(mock_service, "c2", ["2026-07-26"])

        assert mock_service.search_movies.await_count == lookups
        cached = cache._shows["c2::2026-07-26"][0]
        assert [g.name for g in cached.movie.genres] == ["Drama"]

    async def test_unresolvable_title_is_not_retried_every_request(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
    ):
        cache._movies = []
        mock_service.search_movies.return_value = []
        mock_service.search_shows.return_value = [
            Show(id="s1", name="Obscure", movie=Movie(id="1", title="Obscure")),
        ]

        await cache.cache_shows_for_cinema(mock_service, "c1", ["2026-07-26"])
        lookups = mock_service.search_movies.await_count
        mock_service.search_shows.return_value = [
            Show(id="s2", name="Obscure", movie=Movie(id="1", title="Obscure")),
        ]
        await cache.cache_shows_for_cinema(mock_service, "c2", ["2026-07-26"])

        assert mock_service.search_movies.await_count == lookups

    async def test_live_genre_lookups_are_bounded(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
        monkeypatch,
    ):
        monkeypatch.setattr(settings, "kinoheld_genre_lookup_limit", 3)
        cache._movies = []
        mock_service.search_movies.return_value = []
        mock_service.search_shows.return_value = [
            Show(id=f"s{i}", name=f"Film {i}", movie=Movie(id=str(i), title=f"Film {i}"))
            for i in range(20)
        ]

        await cache.cache_shows_for_cinema(mock_service, "c1", ["2026-07-26"])

        assert mock_service.search_movies.await_count == 3

    async def test_show_lookup_failure_does_not_break_enrichment(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
    ):
        cache._movies = []
        mock_service.search_movies.side_effect = RuntimeError("upstream down")
        mock_service.search_shows.return_value = [
            Show(id="s1", name="Rose", movie=Movie(id="1", title="Rose")),
        ]

        await cache.cache_shows_for_cinema(mock_service, "c1", ["2026-07-26"])

        assert cache._shows["c1::2026-07-26"][0].movie.genres == []

    async def test_real_genres_kept_and_blanks_dropped(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
    ):
        show = Show(
            id="s1",
            name="Obsession (OmU)",
            movie=Movie(
                id="1",
                title="Obsession (OmU)",
                genres=[Genre(name="Horrorfilm"), Genre(name="")],
            ),
        )
        mock_service.search_shows.return_value = [show]

        await cache.cache_shows_for_cinema(mock_service, "c1", ["2026-07-26"])

        cached = cache._shows["c1::2026-07-26"][0]
        assert [g.name for g in cached.movie.genres] == ["Horrorfilm"]


def _show_with_movie(show_id: str, movie_id: str, title: str = "Dune") -> Show:
    """A show carrying its own embedded copy of a movie, as Kinoheld returns them."""
    return Show(id=show_id, name=title, movie=Movie(id=movie_id, title=title))


class TestInternMovies:
    def test_duplicate_movies_collapse_to_one_shared_instance(self) -> None:
        groups = [
            [_show_with_movie("s1", "m1"), _show_with_movie("s2", "m1")],
            [_show_with_movie("s3", "m1"), _show_with_movie("s4", "m2", "Arrival")],
        ]

        collapsed = _intern_movies(groups)

        shows = [s for g in groups for s in g]
        assert collapsed == 2
        # Every show of the same film now points at one object, not just an equal one.
        assert shows[0].movie is shows[1].movie is shows[2].movie
        assert shows[3].movie is not shows[0].movie
        assert len({id(s.movie) for s in shows}) == 2

    def test_values_are_preserved(self) -> None:
        groups = [[_show_with_movie("s1", "m1"), _show_with_movie("s2", "m1")]]

        _intern_movies(groups)

        for show in groups[0]:
            assert show.movie is not None
            assert show.movie.id == "m1"
            assert show.movie.title == "Dune"

    def test_genre_backfill_reaches_every_show_of_the_film(self) -> None:
        groups = [[_show_with_movie("s1", "m1"), _show_with_movie("s2", "m1")]]
        _intern_movies(groups)

        # Enrichment mutates the movie; sharing must not lose it for the other show.
        groups[0][0].movie.genres = [Genre(id="g1", name="Sci-Fi", urlSlug="sci-fi")]

        assert [g.name for g in groups[0][1].movie.genres] == ["Sci-Fi"]

    def test_shows_without_a_movie_or_id_are_left_alone(self) -> None:
        no_movie = Show(id="s1", name="TBA")
        no_id = Show(id="s2", name="Mystery", movie=Movie(id="", title="Unknown"))
        groups = [[no_movie, no_id]]

        assert _intern_movies(groups) == 0
        assert no_movie.movie is None
        assert no_id.movie is not None

    def test_nothing_to_collapse_is_a_no_op(self) -> None:
        groups = [[_show_with_movie("s1", "m1"), _show_with_movie("s2", "m2", "Arrival")]]

        assert _intern_movies(groups) == 0


@pytest.mark.asyncio
class TestFetchSharesMovies:
    async def test_prefetched_shows_share_movie_instances_across_cinemas(
        self,
        cache: KinoheldCache,
        mock_service: AsyncMock,
    ) -> None:
        mock_service.search_cinemas.return_value = [
            Cinema(id="1", name="Kino A"),
            Cinema(id="2", name="Kino B"),
        ]
        mock_service.search_movies.return_value = []
        mock_service.search_cities.return_value = []
        mock_service.list_genres.return_value = []
        # Every call returns a fresh copy, exactly like separate HTTP responses do.
        mock_service.search_shows.side_effect = lambda params: [
            _show_with_movie(f"{params.cinema_id}-{params.date}", "m1"),
        ]

        monkey = settings.kinoheld_sync_cinema_count
        settings.kinoheld_sync_cinema_count = 2
        try:
            await cache.refresh(mock_service)
        finally:
            settings.kinoheld_sync_cinema_count = monkey

        cached = [s for day in cache._shows.values() for s in day]
        assert len(cached) > 1
        assert len({id(s.movie) for s in cached}) == 1


class TestInternRegistry:
    def test_shared_registry_collapses_across_separate_calls(self) -> None:
        """Each response must collapse onto movies already seen, not just within itself."""
        canonical: dict = {}
        first = [_show_with_movie("s1", "m1")]
        second = [_show_with_movie("s2", "m1")]

        assert _intern_movies([first], canonical) == 0
        assert _intern_movies([second], canonical) == 1
        assert second[0].movie is first[0].movie

    def test_registry_is_optional(self) -> None:
        groups = [[_show_with_movie("s1", "m1"), _show_with_movie("s2", "m1")]]

        assert _intern_movies(groups) == 1
