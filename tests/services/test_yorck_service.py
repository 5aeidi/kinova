"""Tests for the Yorck service normalization layer."""

import datetime as dt
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import YorckNotFoundError
from app.schemas.yorck import (
    YorckCinemaSearchParams,
    YorckMovieSearchParams,
    YorckShowSearchParams,
)
from app.services.yorck import YorckService

CINEMAS_PAGE = {
    "cinemas": [
        {
            "sys": {"id": "1002"},
            "fields": {
                "name": "Babylon Kreuzberg",
                "shortName": "BAB",
                "slug": "babylon-kreuzberg",
                "vistaId": "1002",
                "address": "Dresdener Straße 126, 10999 Berlin",
                "coordinates": {"lon": 13.41694, "lat": 52.50066},
                "district": "Kreuzberg",
                "telephone": "030 322 931 322",
                "numberOfAuditoriums": 2,
                "accessibility": "Fully accessible",
            },
        },
        {"sys": {"id": "bad"}, "fields": {}},
    ],
}

FILMS_PAGE = {
    "films": [
        {
            "sys": {"id": "HO00005912"},
            "fields": {
                "title": "Dreams",
                "vistaId": "HO00005912",
                "slug": "dreams",
                "runtime": 98,
                "mainLabel": "Thriller",
                "fsk": 16,
                "releaseDate": "2026-07-23",
                "sessions": [
                    {
                        "sys": {"id": "1002-15565"},
                        "fields": {
                            "startTime": "2026-07-26T21:00:00+01:00",
                            "formats": ["OmU"],
                            "cinema": {
                                "fields": {
                                    "name": "Babylon Kreuzberg",
                                    "accessibility": "Fully accessible",
                                },
                            },
                        },
                    },
                ],
            },
        },
    ],
    "specials": [
        {
            "sys": {"id": "sp1"},
            "fields": {
                "title": "Mongay",
                "slug": "mongay",
                "category": "Series",
                "sessions": [],
            },
        },
    ],
    "comingSoon": [
        {
            "sys": {"id": "HO00006000"},
            "fields": {
                "title": "Future Film",
                "vistaId": "HO00006000",
                "slug": "future-film",
                "mainLabel": "Drama",
                "sessions": [],
            },
        },
    ],
}

FILM_DETAIL_PAGE = {
    "film": {
        "fields": {
            "title": "Dreams",
            "slug": "dreams",
            "vistaId": "HO00005912",
            "director": "Michel Franco",
            "cast": "Jessica Chastain, Isaac Hernández",
            "writer": "Michel Franco",
            "countries": ["Mexico", "USA"],
            "year": 2026,
            "originalTitle": "Dreams: Sueños",
            "about": "An erotic thriller.",
            "additionalLabels": ["Drama"],
            "tmdbId": 1134463,
            "trailer1YouTubeId": "abc123",
        },
    },
}


def make_service() -> YorckService:
    client = AsyncMock()
    client.base_url = "https://www.yorck.de"
    client.locale = "en"

    async def get_page_data(path: str) -> dict:
        if path == "cinemas":
            return CINEMAS_PAGE
        if path == "films":
            return FILMS_PAGE
        if path.startswith("films/"):
            return FILM_DETAIL_PAGE if path == "films/dreams" else {"film": None}
        raise AssertionError(f"unexpected path {path}")

    client.get_page_data.side_effect = get_page_data
    return YorckService(client)


@pytest.mark.asyncio
class TestYorckService:
    async def test_dataset_normalizes_cinemas(self):
        dataset = await make_service().get_dataset()

        assert len(dataset.cinemas) == 1
        cinema = dataset.cinemas[0]
        assert cinema.id == "babylon-kreuzberg"
        assert cinema.vista_id == "1002"
        assert cinema.post_code == "10999"
        assert cinema.city == "Berlin"
        assert cinema.latitude == 52.50066
        assert cinema.detail_url == "https://www.yorck.de/en/cinemas/babylon-kreuzberg"

    async def test_dataset_merges_film_detail_fields(self):
        dataset = await make_service().get_dataset()

        movie = YorckService.find_movie(dataset.movies, "dreams")
        assert movie.id == "HO00005912"
        assert movie.directors == ["Michel Franco"]
        assert movie.actors == ["Jessica Chastain", "Isaac Hernández"]
        assert movie.description == "An erotic thriller."
        assert movie.genres == ["Thriller", "Drama"]
        assert movie.tmdb_id == 1134463
        assert movie.trailer_url == "https://www.youtube.com/watch?v=abc123"
        assert movie.release_date == dt.date(2026, 7, 23)

    async def test_dataset_includes_specials_and_presales(self):
        dataset = await make_service().get_dataset()

        special = YorckService.find_movie(dataset.movies, "special-mongay")
        assert special.is_special
        presale = YorckService.find_movie(dataset.movies, "HO00006000")
        assert presale.is_presale

    async def test_sessions_resolve_cinema_from_vista_prefix(self):
        dataset = await make_service().get_dataset()

        assert len(dataset.shows) == 1
        show = dataset.shows[0]
        assert show.id == "1002-15565"
        assert show.cinema_id == "babylon-kreuzberg"
        assert show.cinema_vista_id == "1002"
        assert show.movie_id == "HO00005912"
        assert show.flags == ["OmU"]
        assert show.date == dt.date(2026, 7, 26)

    async def test_filter_shows_by_date_and_cinema(self):
        dataset = await make_service().get_dataset()

        params = YorckShowSearchParams(date=dt.date(2026, 7, 26), cinema_id="babylon-kreuzberg")
        assert len(YorckService.filter_shows(dataset.shows, params)) == 1

        params = YorckShowSearchParams(date=dt.date(2026, 8, 10))
        assert YorckService.filter_shows(dataset.shows, params) == []

    async def test_filter_cinemas_and_movies(self):
        dataset = await make_service().get_dataset()

        assert YorckService.filter_cinemas(
            dataset.cinemas,
            YorckCinemaSearchParams(search="kreuzberg"),
        )
        assert YorckService.filter_movies(
            dataset.movies,
            YorckMovieSearchParams(search="thriller"),
        )

    async def test_find_missing_resources_raise(self):
        dataset = await make_service().get_dataset()

        with pytest.raises(YorckNotFoundError):
            YorckService.find_cinema(dataset.cinemas, "missing")
        with pytest.raises(YorckNotFoundError):
            YorckService.find_movie(dataset.movies, "missing")

    async def test_derived_cities_and_genres(self):
        dataset = await make_service().get_dataset()

        assert [city.name for city in dataset.cities] == ["Berlin"]
        assert {genre.name for genre in dataset.genres} == {"Thriller", "Drama", "Series"}
