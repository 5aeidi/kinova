"""Tests for the Cinetixx service layer."""

from unittest.mock import AsyncMock

import pytest

from app.schemas.cinetixx import (
    CinetixxMovieSearchParams,
    CinetixxShowInfo,
    CinetixxShowInfoParams,
    CinetixxShowSearchParams,
)
from app.services.cinetixx import CinetixxService

SAMPLE_ROW = {
    "id": 1,
    "showBeginning": "2026-07-13T20:15:00Z",
    "showId": 123,
    "bookingLink": "https://booking.cinetixx.de/frontend/?showId=123",
    "movieId": 456,
    "eventId": 789,
    "veranstaltungstitel": "Dune",
    "veranstaltungskurztitel": "Dune",
    "sprachversion": "OV",
    "altersfreigabe": "FSK 12",
    "cityId": 10,
    "stadt": "Cottbus",
    "cinemaId": 20,
    "kino": "Weltspiegel Cottbus",
    "auditoriumId": 30,
    "saal": "Saal 1",
    "spieldauerEvent": 166,
    "mandatorId": 42,
    "flag3D": True,
    "language": "en",
    "audiotype": "Atmos",
    "seatselection": True,
    "categories": ["Sci-Fi", "Event"],
    "genre": "Science Fiction;Action",
    "actor": "Timothee Chalamet, Zendaya",
    "director": "Denis Villeneuve",
    "prices": [{"amount": 12.5, "default": True, "categorie": "Adult", "area": "Parkett"}],
}


@pytest.mark.asyncio
class TestGetShowInfo:
    async def test_parses_json_response(self):
        client = AsyncMock()
        client.get_show_info.return_value = (
            '{"shows":[{"id":123,"title":"Dune"}]}',
            "application/json",
        )
        service = CinetixxService(client)

        result = await service.get_show_info(CinetixxShowInfoParams(mandator_id=42))

        assert result.mandator_id == 42
        assert result.content_type == "application/json"
        assert result.data == {"shows": [{"id": 123, "title": "Dune"}]}
        client.get_show_info.assert_awaited_once_with(42)

    async def test_parses_asmx_xml_wrapped_json(self):
        client = AsyncMock()
        client.get_show_info.return_value = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<string xmlns="http://tempuri.org/">{"shows":[{"id":456}]}</string>',
            "text/xml; charset=utf-8",
        )
        service = CinetixxService(client)

        result = await service.get_show_info(CinetixxShowInfoParams(mandator_id=42))

        assert result.data == {"string": {"shows": [{"id": 456}]}}

    async def test_parses_nested_xml(self):
        client = AsyncMock()
        client.get_show_info.return_value = (
            "<shows><show><id>1</id><title>Dune</title></show><show><id>2</id></show></shows>",
            "text/xml",
        )
        service = CinetixxService(client)

        result = await service.get_show_info(CinetixxShowInfoParams(mandator_id=42))

        assert result.data == {
            "shows": {
                "show": [
                    {"id": "1", "title": "Dune"},
                    {"id": "2"},
                ],
            },
        }

    async def test_preserves_plain_text_response(self):
        client = AsyncMock()
        client.get_show_info.return_value = (
            "Object reference not set to an instance of an object.",
            "text/plain",
        )
        service = CinetixxService(client)

        result = await service.get_show_info(CinetixxShowInfoParams(mandator_id=42))

        assert result.data == "Object reference not set to an instance of an object."


class TestNormalizeShowInfo:
    def test_derives_searchable_resources_from_program_rows(self):
        service = CinetixxService(AsyncMock())
        show_info = CinetixxShowInfo(
            mandatorId=42,
            contentType="application/json",
            data={"shows": [SAMPLE_ROW]},
        )

        dataset = service.normalize_show_info(show_info)

        assert dataset.cinemas[0].id == "20"
        assert dataset.cinemas[0].name == "Weltspiegel Cottbus"
        assert dataset.movies[0].id == "456"
        assert dataset.movies[0].title == "Dune"
        assert dataset.movies[0].genres == ["Science Fiction", "Action", "Sci-Fi", "Event"]
        assert dataset.shows[0].id == "123"
        assert dataset.shows[0].date.isoformat() == "2026-07-13"
        assert dataset.shows[0].prices[0].category == "Adult"
        assert dataset.cities[0].name == "Cottbus"
        assert {genre.name for genre in dataset.genres} == {
            "Science Fiction",
            "Action",
            "Sci-Fi",
            "Event",
        }

    def test_filters_normalized_movies_and_shows(self):
        service = CinetixxService(AsyncMock())
        dataset = service.normalize_show_info(
            CinetixxShowInfo(mandatorId=42, data={"shows": [SAMPLE_ROW]}),
        )

        movies = service.filter_movies(
            dataset.movies,
            CinetixxMovieSearchParams(search="dune"),
        )
        shows = service.filter_shows(
            dataset.shows,
            CinetixxShowSearchParams(movie_id="456"),
        )

        assert [movie.id for movie in movies] == ["456"]
        assert [show.id for show in shows] == ["123"]
