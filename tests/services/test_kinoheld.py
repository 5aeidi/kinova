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
        assert call_variables == {"limit": 1}


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
