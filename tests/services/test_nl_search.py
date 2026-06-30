"""Tests for the natural-language search service."""

import datetime as dt
from unittest.mock import AsyncMock

import pytest

from app.schemas.cinema import Cinema
from app.schemas.movie import Movie
from app.schemas.show import Show, ShowFlag
from app.services.cache import KinoheldCache
from app.services.llm_client import LLMClient, LLMError
from app.services.nl_search import (
    NaturalLanguageQuery,
    NaturalLanguageSearchService,
    ParsedIntent,
)


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
        genres=[{"id": "g1", "name": "Horror", "urlSlug": "horror"}],
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
        }
    )

    request = NaturalLanguageQuery(prompt="horror movies for tomorrow with english subtitles")
    parsed = await nl_service._parse_prompt(request)

    assert parsed.intent == "movies"
    assert parsed.genres == ["Horror"]
    assert parsed.flags == ["OmU"]


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
