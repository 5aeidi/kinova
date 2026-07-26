"""Tests for the Kinoheld service layer."""

import datetime as dt
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import KinoheldNotFoundError
from app.schemas.cinema import CinemaSearchParams
from app.schemas.movie import MovieSearchParams
from app.schemas.show import ShowSearchParams
from app.services.kinoheld import KinoheldService


@pytest.mark.asyncio
class TestSearchCinemas:
    async def test_returns_cinemas(
        self,
        kinoheld_service: KinoheldService,
        mock_graphql_client: AsyncMock,
    ):
        mock_graphql_client.execute.return_value = {
            "cinemas": [
                {
                    "id": "1",
                    "name": "Kino Berlin",
                    "thumbnail": [{"url": "https://example.com/t.png"}],
                    "heroImage": [{"url": "https://example.com/h.jpg"}],
                },
            ],
        }

        result = await kinoheld_service.search_cinemas(CinemaSearchParams(limit=1))

        assert len(result) == 1
        assert result[0].id == "1"
        assert result[0].thumbnail is not None
        mock_graphql_client.execute.assert_awaited_once()
        call_variables = mock_graphql_client.execute.call_args.kwargs["variables"]
        assert call_variables == {"limit": 1, "onlyBookable": False}

    async def test_defaults_request_complete_cinema_dataset(
        self,
        kinoheld_service: KinoheldService,
        mock_graphql_client: AsyncMock,
    ):
        mock_graphql_client.execute.return_value = {"cinemas": []}

        await kinoheld_service.search_cinemas(CinemaSearchParams())

        call_variables = mock_graphql_client.execute.call_args.kwargs["variables"]
        assert call_variables == {"limit": 1000, "onlyBookable": False}


@pytest.mark.asyncio
class TestSearchMovies:
    async def test_returns_movies(
        self,
        kinoheld_service: KinoheldService,
        mock_graphql_client: AsyncMock,
    ):
        mock_graphql_client.execute.return_value = {
            "movies": [
                {
                    "id": "99",
                    "title": "Dune",
                    "thumb": [{"url": "https://example.com/t.jpg"}],
                    "heroImage": [{"url": "https://example.com/h.jpg"}],
                },
            ],
        }

        result = await kinoheld_service.search_movies(MovieSearchParams(search="Dune"))

        assert len(result) == 1
        assert result[0].id == "99"
        assert result[0].thumb is not None


@pytest.mark.asyncio
class TestSearchShows:
    async def test_serializes_date_to_iso_string(
        self,
        kinoheld_service: KinoheldService,
        mock_graphql_client: AsyncMock,
    ):
        mock_graphql_client.execute.return_value = {"shows": []}

        await kinoheld_service.search_shows(
            ShowSearchParams(cinema_id="123", date=dt.date(2024, 6, 15), days=3),
        )

        variables = mock_graphql_client.execute.call_args.kwargs["variables"]
        assert variables == {
            "cinemaId": "123",
            "date": "2024-06-15",
            "days": 3,
        }

    async def test_omits_none_movie_id(
        self,
        kinoheld_service: KinoheldService,
        mock_graphql_client: AsyncMock,
    ):
        mock_graphql_client.execute.return_value = {"shows": []}

        await kinoheld_service.search_shows(ShowSearchParams(cinema_id="123"))

        variables = mock_graphql_client.execute.call_args.kwargs["variables"]
        assert "movieId" not in variables
        assert variables == {"cinemaId": "123"}

    async def test_one_malformed_movie_does_not_discard_the_whole_cinema(
        self,
        kinoheld_service: KinoheldService,
        mock_graphql_client: AsyncMock,
    ):
        """Kinoheld returns shows whose embedded movie has a null id and title."""
        mock_graphql_client.execute.return_value = {
            "shows": [
                {"id": "1", "name": "Toy Story 5", "movie": {"id": "9", "title": "Toy Story 5"}},
                {"id": "2", "name": "Broken", "movie": {"id": None, "title": None}},
                {"id": "3", "name": "Vaiana", "movie": {"id": "8", "title": "Vaiana"}},
            ],
        }

        shows = await kinoheld_service.search_shows(ShowSearchParams(cinema_id="123"))

        assert [s.id for s in shows] == ["1", "2", "3"]
        # The screening survives; only its unusable movie record is dropped.
        assert shows[1].movie is None
        assert shows[1].name == "Broken"

    async def test_unsalvageable_record_is_skipped(
        self,
        kinoheld_service: KinoheldService,
        mock_graphql_client: AsyncMock,
    ):
        mock_graphql_client.execute.return_value = {
            "shows": [
                {"id": "1", "name": "Fine"},
                {"name": "No id at all"},
            ],
        }

        shows = await kinoheld_service.search_shows(ShowSearchParams(cinema_id="123"))

        assert [s.id for s in shows] == ["1"]

    async def test_malformed_cinema_record_is_skipped(
        self,
        kinoheld_service: KinoheldService,
        mock_graphql_client: AsyncMock,
    ):
        mock_graphql_client.execute.return_value = {
            "cinemas": [{"id": "1", "name": "Kino"}, {"name": "no id"}],
        }

        cinemas = await kinoheld_service.search_cinemas(CinemaSearchParams())

        assert [c.id for c in cinemas] == ["1"]


@pytest.mark.asyncio
class TestGetCinema:
    async def test_raises_when_not_found(
        self,
        kinoheld_service: KinoheldService,
        mock_graphql_client: AsyncMock,
    ):
        mock_graphql_client.execute.return_value = {"cinema": None}

        with pytest.raises(KinoheldNotFoundError):
            await kinoheld_service.get_cinema("missing")
