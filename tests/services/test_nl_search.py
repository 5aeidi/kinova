"""Tests for the natural-language search service."""

import datetime as dt
from unittest.mock import AsyncMock

import pytest

from app.schemas.cinema import Cinema, CitySummary
from app.schemas.movie import Genre, Movie, Person
from app.schemas.show import Show, ShowFlag
from app.schemas.yorck import YorckCinema, YorckDataset, YorckMovie, YorckShow
from app.services.cache import KinoheldCache
from app.services.llm_client import LLMClient, LLMError
from app.services.nl_search import (
    NaturalLanguageQuery,
    NaturalLanguageSearchService,
    ParsedIntent,
    SourceCaches,
    StructuredSearchQuery,
)
from app.services.yorck_cache import YorckCache


@pytest.fixture
def llm_client() -> LLMClient:
    return LLMClient(api_key="test-key")


@pytest.fixture
def nl_service(llm_client: LLMClient) -> NaturalLanguageSearchService:
    return NaturalLanguageSearchService(llm_client)


@pytest.fixture
def mock_live_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def empty_cache() -> KinoheldCache:
    return KinoheldCache()


@pytest.fixture
def sample_movie() -> Movie:
    return Movie(
        id="m1",
        title="A Nightmare on Elm Street",
        duration=91,
        production_year="1984",
        imdb_rating=7.4,
        genres=[{"id": "g1", "name": "Horror", "urlSlug": "horror"}],
        actors=[Person(id="a1", name="Heather Langenkamp")],
        directors=[Person(id="d1", name="Wes Craven")],
    )


@pytest.fixture
def sample_movie_long() -> Movie:
    return Movie(
        id="m2",
        title="The Godfather",
        duration=175,
        production_year="1972",
        imdb_rating=9.2,
        genres=[{"id": "g2", "name": "Drama", "urlSlug": "drama"}],
        actors=[Person(id="a2", name="Jaylen Hunter")],
    )


@pytest.fixture
def sample_cinema() -> Cinema:
    return Cinema(id="c1", name="CineStar Berlin")


@pytest.fixture
def sample_show(sample_movie: Movie, sample_cinema: Cinema) -> Show:
    return Show(
        id="s1",
        name="A Nightmare on Elm Street - OmU",
        flags=[ShowFlag(name="OmU", code="OmU")],
        movie=sample_movie,
    )


async def test_parse_prompt_uses_llm(nl_service: NaturalLanguageSearchService) -> None:
    nl_service.llm_client.chat_completion = AsyncMock(
        return_value={
            "intent": "movies",
            "genres": ["Horror"],
            "date": "tomorrow",
            "location": None,
            "flags": ["OmU"],
            "language": "English",
            "durationMax": 100,
        }
    )

    request = NaturalLanguageQuery(prompt="horror movies for tomorrow with english subtitles")
    parsed = await nl_service._parse_prompt(request)

    assert parsed.intent == "movies"
    assert parsed.genres == ["Horror"]
    assert parsed.flags == ["OmU"]
    assert parsed.duration_max == 100


async def test_parse_prompt_falls_back_to_heuristic(
    nl_service: NaturalLanguageSearchService,
) -> None:
    nl_service.llm_client.chat_completion = AsyncMock(side_effect=LLMError("down"))

    request = NaturalLanguageQuery(prompt="horror movies for tomorrow with english subtitles")
    parsed = await nl_service._parse_prompt(request)

    assert parsed.intent == "movies"
    assert parsed.genres == ["Horror"]
    assert parsed.flags == ["OmU"]
    assert parsed.date == (dt.date.today() + dt.timedelta(days=1)).isoformat()


async def test_parse_prompt_tolerates_null_list_fields(
    nl_service: NaturalLanguageSearchService,
) -> None:
    """Groq's JSON mode does not enforce the schema; null for "no items" happens."""
    nl_service.llm_client.chat_completion = AsyncMock(
        return_value={
            "intent": "movies",
            "searchQuery": "Tuner",
            "genres": None,
            "flags": None,
            "actors": None,
            "directors": None,
            "cast": None,
        }
    )

    parsed = await nl_service._parse_prompt(NaturalLanguageQuery(prompt="Tuner"))

    assert parsed.intent == "movies"
    assert parsed.search_query == "Tuner"
    assert parsed.genres == []
    assert parsed.flags == []
    assert parsed.actors == []
    assert parsed.directors == []
    assert parsed.cast == []


async def test_parse_prompt_falls_back_when_validation_fails_after_normalising(
    nl_service: NaturalLanguageSearchService,
) -> None:
    """A shape validation still rejects must degrade, not 500 the request."""
    nl_service.llm_client.chat_completion = AsyncMock(
        return_value={"intent": "movies", "durationMax": "not-a-number"}
    )

    parsed = await nl_service._parse_prompt(NaturalLanguageQuery(prompt="short movies"))

    assert parsed.intent == "movies"


async def test_filter_by_duration(
    sample_movie: Movie,
    sample_movie_long: Movie,
) -> None:
    movies = [sample_movie, sample_movie_long]
    result = NaturalLanguageSearchService._filter_by_duration(movies, None, 100)
    assert [m.id for m in result] == ["m1"]

    result = NaturalLanguageSearchService._filter_by_duration(movies, 120, None)
    assert [m.id for m in result] == ["m2"]


async def test_filter_by_year(
    sample_movie: Movie,
    sample_movie_long: Movie,
) -> None:
    movies = [sample_movie, sample_movie_long]
    result = NaturalLanguageSearchService._filter_by_year(movies, None, 1970, 1985)
    assert [m.id for m in result] == ["m1", "m2"]

    result = NaturalLanguageSearchService._filter_by_year(movies, 1984, None, None)
    assert [m.id for m in result] == ["m1"]


async def test_filter_by_rating(
    sample_movie: Movie,
    sample_movie_long: Movie,
) -> None:
    movies = [sample_movie, sample_movie_long]
    result = NaturalLanguageSearchService._filter_by_rating(movies, 8.0, None)
    assert [m.id for m in result] == ["m2"]


async def test_filter_by_people(
    sample_movie: Movie,
    sample_movie_long: Movie,
) -> None:
    movies = [sample_movie, sample_movie_long]
    result = NaturalLanguageSearchService._filter_by_people(
        movies,
        actors=[],
        directors=["Wes Craven"],
        cast=[],
    )
    assert [m.id for m in result] == ["m1"]

    result = NaturalLanguageSearchService._filter_by_people(
        movies,
        actors=["Jaylen Hunter"],
        directors=[],
        cast=[],
    )
    assert [m.id for m in result] == ["m2"]


async def test_search_movies_intent(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_movie: Movie,
) -> None:
    nl_service.llm_client.chat_completion = AsyncMock(
        return_value={
            "intent": "movies",
            "genres": ["Horror"],
            "searchQuery": "Nightmare",
        }
    )
    mock_live_service.search_movies = AsyncMock(return_value=[sample_movie])

    request = NaturalLanguageQuery(prompt="horror movies called nightmare")
    result = await nl_service.search(request, mock_live_service, empty_cache)

    assert result.intent == "movies"
    assert len(result.movies) == 1
    assert result.movies[0].id == "m1"


async def test_search_movies_duration_filter(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_movie: Movie,
    sample_movie_long: Movie,
) -> None:
    nl_service.llm_client.chat_completion = AsyncMock(
        return_value={
            "intent": "movies",
            "genres": ["Horror"],
            "durationMax": 100,
        }
    )
    mock_live_service.search_movies = AsyncMock(return_value=[sample_movie, sample_movie_long])

    request = NaturalLanguageQuery(prompt="horror movies below 100 minutes")
    result = await nl_service.search(request, mock_live_service, empty_cache)

    assert result.intent == "movies"
    assert [m.id for m in result.movies] == ["m1"]


async def test_search_movies_actor_filter(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_movie: Movie,
    sample_movie_long: Movie,
) -> None:
    nl_service.llm_client.chat_completion = AsyncMock(
        return_value={
            "intent": "movies",
            "genres": ["Drama"],
            "actors": ["Jaylen Hunter"],
        }
    )
    mock_live_service.search_movies = AsyncMock(return_value=[sample_movie, sample_movie_long])

    request = NaturalLanguageQuery(prompt="drama movies in which Jaylen Hunter acts")
    result = await nl_service.search(request, mock_live_service, empty_cache)

    assert result.intent == "movies"
    assert [m.id for m in result.movies] == ["m2"]


async def test_search_cinemas_intent(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_cinema: Cinema,
) -> None:
    nl_service.llm_client.chat_completion = AsyncMock(
        return_value={"intent": "cinemas", "location": "Berlin"}
    )
    mock_live_service.search_cinemas = AsyncMock(return_value=[sample_cinema])

    request = NaturalLanguageQuery(prompt="cinemas in Berlin")
    result = await nl_service.search(request, mock_live_service, empty_cache)

    assert result.intent == "cinemas"
    assert len(result.cinemas) == 1
    assert result.cinemas[0].id == "c1"


async def test_search_shows_intent(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_cinema: Cinema,
    sample_movie: Movie,
    sample_show: Show,
) -> None:
    nl_service.llm_client.chat_completion = AsyncMock(
        return_value={
            "intent": "shows",
            "location": "Berlin",
            "genres": ["Horror"],
            "date": (dt.date.today() + dt.timedelta(days=1)).isoformat(),
            "flags": ["OmU"],
        }
    )
    mock_live_service.search_cinemas = AsyncMock(return_value=[sample_cinema])
    mock_live_service.search_movies = AsyncMock(return_value=[sample_movie])
    mock_live_service.search_shows = AsyncMock(return_value=[sample_show])

    request = NaturalLanguageQuery(prompt="horror shows in Berlin tomorrow with english subtitles")
    result = await nl_service.search(request, mock_live_service, empty_cache)

    assert result.intent == "shows"
    assert len(result.shows) == 1
    assert result.shows[0].id == "s1"


async def test_filter_by_flags() -> None:
    show_with_subs = Show(
        id="s1",
        name="Film OmU",
        flags=[ShowFlag(name="OmU", code="OmU")],
    )
    show_without = Show(
        id="s2",
        name="Film",
        flags=[],
    )

    result = NaturalLanguageSearchService._filter_by_flags([show_with_subs, show_without], ["OmU"])
    assert len(result) == 1
    assert result[0].id == "s1"


async def test_parsed_intent_date_normalisation() -> None:
    parsed = ParsedIntent(date="tomorrow")
    assert parsed.date == (dt.date.today() + dt.timedelta(days=1)).isoformat()

    parsed2 = ParsedIntent(date="2025-12-25")
    assert parsed2.date == "2025-12-25"


async def test_heuristic_extracts_duration_max() -> None:
    parsed = NaturalLanguageSearchService._heuristic_parse("horror movies under 90 minutes")
    assert parsed.duration_max == 90
    assert parsed.genres == ["Horror"]


async def test_structured_search_movies(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_movie: Movie,
    sample_movie_long: Movie,
) -> None:
    mock_live_service.search_movies = AsyncMock(return_value=[sample_movie, sample_movie_long])

    request = StructuredSearchQuery(
        intent="movies",
        genres=["Horror"],
        duration_max=100,
    )
    result = await nl_service.structured_search(request, mock_live_service, empty_cache)

    assert result.intent == "movies"
    assert [m.id for m in result.movies] == ["m1"]


async def test_structured_search_movies_by_actor(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_movie: Movie,
    sample_movie_long: Movie,
) -> None:
    mock_live_service.search_movies = AsyncMock(return_value=[sample_movie, sample_movie_long])

    request = StructuredSearchQuery(
        intent="movies",
        genres=["Drama"],
        actors=["Jaylen Hunter"],
    )
    result = await nl_service.structured_search(request, mock_live_service, empty_cache)

    assert result.intent == "movies"
    assert [m.id for m in result.movies] == ["m2"]


async def test_structured_to_parsed() -> None:
    request = StructuredSearchQuery(
        intent="movies",
        genres=["Comedy"],
        duration_min=80,
        duration_max=120,
        year_min=2020,
        rating_min=7.0,
        actors=["Jim Carrey"],
    )
    parsed = NaturalLanguageSearchService._structured_to_parsed(request)

    assert parsed.intent == "movies"
    assert parsed.genres == ["Comedy"]
    assert parsed.duration_min == 80
    assert parsed.duration_max == 120
    assert parsed.year_min == 2020
    assert parsed.rating_min == 7.0
    assert parsed.actors == ["Jim Carrey"]


async def test_structured_search_cinemas(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_cinema: Cinema,
) -> None:
    mock_live_service.search_cinemas = AsyncMock(return_value=[sample_cinema])

    request = StructuredSearchQuery(intent="cinemas", location="Berlin")
    result = await nl_service.structured_search(request, mock_live_service, empty_cache)

    assert result.intent == "cinemas"
    assert [c.id for c in result.cinemas] == ["c1"]


async def test_structured_search_shows_with_location_uses_cache_filter(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_cinema: Cinema,
    sample_movie: Movie,
    sample_show: Show,
) -> None:
    # Cinemas must be filtered by location; only the Berlin cinema should be used.
    berlin_cinema = Cinema(id="c1", name="CineStar Berlin", city=CitySummary(name="Berlin"))
    munich_cinema = Cinema(id="c2", name="Mathäser München", city=CitySummary(name="Munich"))
    empty_cache._cinemas = [berlin_cinema, munich_cinema]
    empty_cache._movies = [sample_movie]
    empty_cache._shows = {
        f"c1::{dt.date.today().isoformat()}": [sample_show],
    }
    # Stamped fresh so the cached day is served rather than re-fetched.
    empty_cache._shows_fetched_at = {
        f"c1::{dt.date.today().isoformat()}": dt.datetime.now(tz=dt.timezone.utc),
    }

    mock_live_service.search_shows = AsyncMock(return_value=[])

    request = StructuredSearchQuery(
        intent="shows",
        location="Berlin",
        date=dt.date.today().isoformat(),
        use_cache=True,
    )
    result = await nl_service.structured_search(request, mock_live_service, empty_cache)

    assert result.intent == "shows"
    assert [c.id for c in result.cinemas] == ["c1"]
    assert len(result.shows) == 1
    assert result.shows[0].id == sample_show.id
    # The Munich cinema should not trigger a live shows lookup.
    mock_live_service.search_shows.assert_not_awaited()


def _movie(movie_id: str, *genres: str) -> Movie:
    return Movie(
        id=movie_id,
        title=f"Film {movie_id}",
        genres=[{"id": g, "name": g, "urlSlug": g.lower()} for g in genres],
    )


@pytest.mark.asyncio
class TestGenreGrounding:
    async def test_vocabulary_ranks_by_movie_usage_and_honours_limit(self) -> None:
        cache = KinoheldCache()
        cache._movies = [
            _movie("1", "Komödie"),
            _movie("2", "Komödie"),
            _movie("3", "Komödie"),
            _movie("4", "Drama"),
            _movie("5", "Drama"),
            _movie("6", "Horror"),
        ]
        cache._genres = [Genre(id="x", name="Nischenfilm", urlSlug="nischenfilm")]

        assert await cache.genre_vocabulary(3) == ["Komödie", "Drama", "Horror"]
        # Catalogue tags nothing is screening still appear, but only behind the rest.
        assert (await cache.genre_vocabulary(10))[-1] == "Nischenfilm"
        assert await cache.genre_vocabulary(0) == []

    async def test_vocabulary_deduplicates_case_insensitively(self) -> None:
        cache = KinoheldCache()
        cache._movies = [_movie("1", "Drama"), _movie("2", "drama"), _movie("3", "DRAMA")]
        cache._genres = []

        assert await cache.genre_vocabulary(10) == ["Drama"]

    async def test_prompt_is_grounded_in_real_tags(
        self,
        nl_service: NaturalLanguageSearchService,
    ) -> None:
        captured: dict[str, str] = {}

        async def capture(system_message: str, user_message: str, **kwargs: object) -> dict:
            captured["system"] = system_message
            return {"intent": "movies", "genres": ["Komödie"]}

        nl_service.llm_client.chat_completion = capture
        parsed = await nl_service._parse_prompt(
            NaturalLanguageQuery(prompt="something funny"),
            ["Komödie", "Drama"],
        )

        assert parsed.genres == ["Komödie"]
        assert "Available genres" in captured["system"]
        assert "Komödie, Drama" in captured["system"]
        assert "never invent a genre" in captured["system"]

    async def test_prompt_without_vocabulary_keeps_generic_hint(
        self,
        nl_service: NaturalLanguageSearchService,
    ) -> None:
        captured: dict[str, str] = {}

        async def capture(system_message: str, user_message: str, **kwargs: object) -> dict:
            captured["system"] = system_message
            return {"intent": "movies"}

        nl_service.llm_client.chat_completion = capture
        await nl_service._parse_prompt(NaturalLanguageQuery(prompt="anything"), [])

        assert "Available genres" not in captured["system"]
        assert "genre names like Horror" in captured["system"]

    async def test_vocabulary_failure_does_not_break_search(self) -> None:
        cache = KinoheldCache()
        cache.genre_vocabulary = AsyncMock(side_effect=RuntimeError("boom"))

        assert await NaturalLanguageSearchService._genre_vocabulary(cache) == []


class TestGenreMatching:
    def test_compound_tags_match_the_base_concept(self) -> None:
        movies = [
            _movie("1", "Actionkomödie"),
            _movie("2", "Familienkomödie"),
            _movie("3", "Drama"),
        ]

        matched = NaturalLanguageSearchService._filter_by_genres(movies, ["Komödie"])

        assert [m.id for m in matched] == ["1", "2"]

    def test_exact_and_case_insensitive_matches_still_work(self) -> None:
        movies = [_movie("1", "Horror"), _movie("2", "Drama")]

        matched = NaturalLanguageSearchService._filter_by_genres(movies, ["horror"])

        assert [m.id for m in matched] == ["1"]

    def test_unrelated_genre_matches_nothing(self) -> None:
        movies = [_movie("1", "Horror"), _movie("2", "Drama")]

        assert NaturalLanguageSearchService._filter_by_genres(movies, ["Western"]) == []

    def test_empty_genre_list_is_a_no_op(self) -> None:
        movies = [_movie("1", "Horror")]

        assert NaturalLanguageSearchService._filter_by_genres(movies, []) == movies


# ----------------------------------------------------------------------
# Multi-source search, unknown-intent guard, and fallback title search
# ----------------------------------------------------------------------
@pytest.fixture
def yorck_cache_with_odyssey() -> YorckCache:
    """A Yorck cache holding the English-titled film Kinoheld lists in German."""
    cache = YorckCache()
    cache._dataset = YorckDataset(
        cinemas=[
            YorckCinema(
                id="babylon-kreuzberg",
                slug="babylon-kreuzberg",
                name="Babylon Kreuzberg",
                city="Berlin",
                district="Kreuzberg",
            ),
        ],
        movies=[
            YorckMovie(id="HO1", slug="the-odyssey", title="The Odyssey", runtime=172),
        ],
        shows=[
            YorckShow(
                id="1002-1",
                movieId="HO1",
                movieTitle="The Odyssey",
                cinemaId="babylon-kreuzberg",
                cinemaName="Babylon Kreuzberg",
                city="Berlin",
                beginsAt=dt.datetime.now(tz=dt.timezone.utc),
                date=dt.date.today(),
            ),
        ],
    )
    cache._last_refresh = dt.datetime.now(tz=dt.timezone.utc)
    return cache


async def test_yorck_movies_appear_in_search_results(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    yorck_cache_with_odyssey: YorckCache,
) -> None:
    """Kinoheld lists this film under its German title, so only Yorck can match it."""
    mock_live_service.search_movies = AsyncMock(return_value=[])

    result = await nl_service.structured_search(
        StructuredSearchQuery(
            intent="movies", search_query="The Odyssey", location="Berlin", limit=20
        ),
        mock_live_service,
        empty_cache,
        SourceCaches(yorck=yorck_cache_with_odyssey),
    )

    assert [m.title for m in result.movies] == ["The Odyssey"]
    assert result.movies[0].source == "yorck"
    assert result.movies[0].source_id == "HO1"


async def test_yorck_cinemas_appear_in_cinema_search(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    yorck_cache_with_odyssey: YorckCache,
) -> None:
    mock_live_service.search_cinemas = AsyncMock(return_value=[])

    result = await nl_service.structured_search(
        StructuredSearchQuery(intent="cinemas", location="Berlin", limit=20),
        mock_live_service,
        empty_cache,
        SourceCaches(yorck=yorck_cache_with_odyssey),
    )

    assert [c.name for c in result.cinemas] == ["Babylon Kreuzberg"]
    assert result.cinemas[0].source == "yorck"


async def test_yorck_excluded_for_a_location_it_does_not_serve(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    yorck_cache_with_odyssey: YorckCache,
) -> None:
    """Yorck is Berlin-only; a Munich query must not pull its catalogue in."""
    mock_live_service.search_movies = AsyncMock(return_value=[])

    result = await nl_service.structured_search(
        StructuredSearchQuery(
            intent="movies", search_query="The Odyssey", location="Munich", limit=20
        ),
        mock_live_service,
        empty_cache,
        SourceCaches(yorck=yorck_cache_with_odyssey),
    )

    assert result.movies == []


async def test_unparseable_prompt_returns_no_results(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_movie: Movie,
) -> None:
    """An unparsed prompt must not fall through to an unfiltered catalogue browse."""
    mock_live_service.search_movies = AsyncMock(return_value=[sample_movie])

    result = await nl_service.structured_search(
        StructuredSearchQuery(intent="unknown", search_query=None, location="Berlin", limit=100),
        mock_live_service,
        empty_cache,
    )

    assert result.movies == []
    assert result.total_results == 0
    mock_live_service.search_movies.assert_not_called()


async def test_unknown_intent_with_a_search_term_still_searches(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_movie: Movie,
) -> None:
    """The guard keys on having no filters at all, not on the intent alone."""
    mock_live_service.search_movies = AsyncMock(return_value=[sample_movie])

    result = await nl_service.structured_search(
        StructuredSearchQuery(intent="unknown", search_query="Nightmare", limit=20),
        mock_live_service,
        empty_cache,
    )

    assert [m.title for m in result.movies] == ["A Nightmare on Elm Street"]


async def test_browse_intent_still_returns_the_catalogue(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_movie: Movie,
) -> None:
    """ "What's playing in Berlin" parses as movies and must keep working."""
    mock_live_service.search_movies = AsyncMock(return_value=[sample_movie])

    result = await nl_service.structured_search(
        StructuredSearchQuery(intent="movies", search_query=None, location="Berlin", limit=100),
        mock_live_service,
        empty_cache,
    )

    assert [m.title for m in result.movies] == ["A Nightmare on Elm Street"]


async def test_fallback_title_search_matches_when_upstream_returns_nothing(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    sample_movie: Movie,
) -> None:
    """Upstream misses the partial title; the local fallback must still find it.

    The fallback previously searched an always-empty list and could never match.
    """
    calls: list[str | None] = []

    async def search_movies(params):
        calls.append(params.search)
        return [] if params.search else [sample_movie]

    mock_live_service.search_movies = AsyncMock(side_effect=search_movies)

    result = await nl_service.structured_search(
        StructuredSearchQuery(intent="movies", search_query="Nightmare", limit=20),
        mock_live_service,
        empty_cache,
    )

    assert [m.title for m in result.movies] == ["A Nightmare on Elm Street"]
    assert calls == ["Nightmare", None]


async def test_show_search_reports_the_yorck_venues_its_shows_come_from(
    nl_service: NaturalLanguageSearchService,
    mock_live_service: AsyncMock,
    empty_cache: KinoheldCache,
    yorck_cache_with_odyssey: YorckCache,
) -> None:
    """A Show carries no cinema reference, so its venue must reach the client."""
    mock_live_service.search_cinemas = AsyncMock(return_value=[])
    mock_live_service.search_movies = AsyncMock(return_value=[])

    result = await nl_service.structured_search(
        StructuredSearchQuery(intent="shows", location="Berlin", limit=100),
        mock_live_service,
        empty_cache,
        SourceCaches(yorck=yorck_cache_with_odyssey),
    )

    assert [s.source for s in result.shows] == ["yorck"]
    assert [c.name for c in result.cinemas] == ["Babylon Kreuzberg"]
    assert result.cinemas[0].source == "yorck"
