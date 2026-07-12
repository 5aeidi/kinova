"""Tests for the Cinetixx service layer."""

from unittest.mock import AsyncMock

import pytest

from app.schemas.cinetixx import (
    CinetixxMandatorSearchParams,
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

SAMPLE_DISCOVERY = {
    "id": 1627459203,
    "hasShows": True,
    "mandatorId": 1627457285,
    "mandatorName": "Kaczor; Berlin",
    "name": "ACUDkino GmbH - Berlin",
    "cinemaName": "ACUDkino GmbH",
    "address": "Veteranenstr. 21, 10119 Berlin",
    "city": "Berlin",
    "postCode": "10119",
    "phone": "",
    "latitude": 52.533608,
    "longitude": 13.40086,
    "_urlProgram": "http://booking.cinetixx.de/frontend/#/program/1627459203",
    "_urlPrettyProgram": "http://booking.cinetixx.de/Kinoprogramm/acudkino+gmbh-berlin",
    "_urlGiftCards": "http://booking.cinetixx.de/frontend/?gutscheine=1627459203",
    "_urlCardBalance": "http://booking.cinetixx.de/frontend/?guthaben=1627459203",
}

LIVE_STYLE_SHOW_INFO_XML = """<?xml version="1.0" encoding="utf-8"?>
<ShowInfo>
  <Show id="3583487126">
    <SHOW_BEGINNING>2026-07-12T18:15:00+02:00</SHOW_BEGINNING>
    <SHOW_ID>3583487126</SHOW_ID>
    <TEXT>Program description</TEXT>
    <VERKAUFSSTART>2026-07-06T13:03:54+02:00</VERKAUFSSTART>
    <VERKAUFSENDE>2026-07-12T17:15:00+02:00</VERKAUFSENDE>
    <BOOKING_LINK>https://booking.cinetixx.de/frontend/index.html?showId=3583487126</BOOKING_LINK>
    <MOVIE_ID>3415771563</MOVIE_ID>
    <EVENT_ID>3454223239</EVENT_ID>
    <ARTWORK>https://images.cinetixx.com/posters/poster.jpg</ARTWORK>
    <VERANSTALTUNGSTITEL>GELBE BRIEFE D, ab 12</VERANSTALTUNGSTITEL>
    <VERANSTALTUNGSKURZTITEL>GELBE BRIEFE</VERANSTALTUNGSKURZTITEL>
    <SPRACHVERSION>D</SPRACHVERSION>
    <ALTERSFREIGABE>ab 12</ALTERSFREIGABE>
    <CITY_ID>385625355</CITY_ID>
    <STADT>Berlin</STADT>
    <CINEMA_ID>1627459203</CINEMA_ID>
    <KINO>ACUDkino GmbH</KINO>
    <AUDITORIUM_ID>1674657342</AUDITORIUM_ID>
    <SAAL>Kino 1</SAAL>
    <SPIELDAUER_EVENT>128</SPIELDAUER_EVENT>
    <MANDATOR_ID>1627457285</MANDATOR_ID>
    <FLAG_3D>false</FLAG_3D>
    <VERSIONTYPE>D</VERSIONTYPE>
    <LANGUAGE>D, Deutsch</LANGUAGE>
    <AUDIOTYPE>TBA</AUDIOTYPE>
    <SEATSELECTION>false</SEATSELECTION>
    <ARTWORK_BIG>https://images.cinetixx.com/posters/poster-big.jpg</ARTWORK_BIG>
    <EVENT_TRAILER>https://example.test/trailer</EVENT_TRAILER>
    <YEAR>2026</YEAR>
    <COUNTRY>DE</COUNTRY>
    <GENRE>Drama</GENRE>
    <ACTOR>Actor One, Actor Two</ACTOR>
    <DIRECTOR>Director One</DIRECTOR>
    <TYPE Key="SHOW_TYPE_STD">Standard</TYPE>
    <PRICE>9/7</PRICE>
    <TEXT_SHORT>Short description</TEXT_SHORT>
  </Show>
</ShowInfo>"""


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


@pytest.mark.asyncio
class TestDiscoverMandators:
    async def test_discovers_mandators_from_search_objects(self):
        client = AsyncMock()
        client.search_cinemas.return_value = {"searchList": [{"searchObject": SAMPLE_DISCOVERY}]}
        service = CinetixxService(client)

        result = await service.discover_mandators(CinetixxMandatorSearchParams(search="acud"))

        assert len(result) == 1
        assert result[0].cinema_id == "1627459203"
        assert result[0].mandator_id == 1627457285
        assert result[0].cinema_name == "ACUDkino GmbH"
        assert result[0].program_url.endswith("/#/program/1627459203")
        client.search_cinemas.assert_awaited_once_with(
            search="acud",
            lat=None,
            lon=None,
            page=None,
            page_size=100,
        )

    async def test_discovers_mandator_by_cinema_id(self):
        client = AsyncMock()
        client.get_cinema.return_value = SAMPLE_DISCOVERY
        service = CinetixxService(client)

        result = await service.discover_mandators(
            CinetixxMandatorSearchParams(cinema_id="1627459203"),
        )

        assert [item.mandator_id for item in result] == [1627457285]
        client.get_cinema.assert_awaited_once_with("1627459203")


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

    def test_derives_resources_from_live_style_uppercase_xml_tags(self):
        service = CinetixxService(AsyncMock())
        parsed = service._parse_body(LIVE_STYLE_SHOW_INFO_XML, "text/xml")
        show_info = CinetixxShowInfo(mandatorId=1627457285, data=parsed)

        dataset = service.normalize_show_info(show_info)

        assert dataset.cinemas[0].id == "1627459203"
        assert dataset.cinemas[0].name == "ACUDkino GmbH"
        assert dataset.movies[0].id == "3415771563"
        assert dataset.movies[0].title == "GELBE BRIEFE D, ab 12"
        assert dataset.movies[0].short_title == "GELBE BRIEFE"
        assert dataset.movies[0].genres == ["Drama"]
        assert dataset.movies[0].actors == ["Actor One", "Actor Two"]
        assert dataset.shows[0].id == "3583487126"
        assert dataset.shows[0].city == "Berlin"
        assert dataset.shows[0].auditorium_name == "Kino 1"
        assert dataset.shows[0].duration == 128
        assert dataset.shows[0].prices[0].category == "9/7"
        assert dataset.cities[0].mandator_ids == [1627457285]
        assert dataset.genres[0].name == "Drama"
