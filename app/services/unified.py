"""Mapping helpers for unified internal source responses."""

from app.schemas.cinema import Cinema, CitySummary
from app.schemas.cinetixx import (
    CinetixxCinema,
    CinetixxCity,
    CinetixxGenre,
    CinetixxMovie,
    CinetixxShow,
)
from app.schemas.city import City
from app.schemas.common import Image, Url
from app.schemas.movie import Genre, Movie, Person
from app.schemas.show import Auditorium, DateTimeFormatted, Show, ShowFlag
from app.schemas.unified import UnifiedCinema, UnifiedCity, UnifiedGenre, UnifiedMovie, UnifiedShow


def _url(value: str | None) -> Url | None:
    if value is None:
        return None
    return Url(url=value)


def _image(value: str | None) -> Image | None:
    if value is None:
        return None
    return Image(url=value)


def _movie_payload_from_cinetixx(movie: CinetixxMovie) -> dict:
    return {
        "id": movie.id,
        "title": movie.title,
        "description": movie.description or movie.short_description,
        "additionalDescription": None,
        "duration": movie.duration,
        "genres": [Genre(name=name) for name in dict.fromkeys([*movie.genres, *movie.categories])],
        "directors": [Person(name=name) for name in movie.directors if name],
        "actors": [Person(name=name) for name in movie.actors if name],
        "productionYear": movie.year,
        "thumb": _image(movie.artwork or movie.artwork_big),
        "heroImage": _image(movie.artwork_big or movie.artwork),
        "detailUrl": _url(movie.movie_url),
        "urlSlug": None,
        "imdbRating": None,
        "imdbVotes": None,
    }


def _show_payload_from_cinetixx(show: CinetixxShow) -> dict:
    beginning = None
    if show.begins_at is not None:
        beginning = DateTimeFormatted(
            formatted=show.begins_at.isoformat(),
            timestamp=int(show.begins_at.timestamp()),
        )

    movie = None
    if show.movie_id or show.event_id or show.movie_title or show.text:
        movie = Movie(
            id=show.movie_id or show.event_id or show.id,
            title=show.movie_title or show.text or show.id,
        )

    auditorium = None
    if show.auditorium_id or show.auditorium_name:
        auditorium = Auditorium(id=show.auditorium_id, name=show.auditorium_name)

    return {
        "id": show.id,
        "name": show.movie_title or show.text or show.id,
        "beginning": beginning,
        "admission": None,
        "duration": str(show.duration) if show.duration is not None else None,
        "flags": [ShowFlag(name=flag) for flag in show.flags],
        "detailUrl": _url(show.booking_url),
        "isSoldOut": None,
        "movie": movie,
        "auditorium": auditorium,
    }


def kinoheld_cinema_to_unified(cinema: Cinema) -> UnifiedCinema:
    """Map a Kinoheld cinema into the unified schema."""
    return UnifiedCinema(**cinema.model_dump(by_alias=True), source="kinoheld", sourceId=cinema.id)


def cinetixx_cinema_to_unified(cinema: CinetixxCinema) -> UnifiedCinema:
    """Map a Cinetixx cinema into the unified schema."""
    payload = Cinema(
        id=cinema.id,
        name=cinema.name or cinema.id,
        city=CitySummary(id=cinema.city_id, name=cinema.city),
    ).model_dump(by_alias=True)
    return UnifiedCinema(
        **payload,
        source="cinetixx",
        sourceId=cinema.id,
    )


def kinoheld_movie_to_unified(movie: Movie) -> UnifiedMovie:
    """Map a Kinoheld movie into the unified schema."""
    return UnifiedMovie(**movie.model_dump(by_alias=True), source="kinoheld", sourceId=movie.id)


def cinetixx_movie_to_unified(movie: CinetixxMovie) -> UnifiedMovie:
    """Map a Cinetixx movie/event into the unified schema."""
    return UnifiedMovie(**_movie_payload_from_cinetixx(movie), source="cinetixx", sourceId=movie.id)


def kinoheld_show_to_unified(show: Show) -> UnifiedShow:
    """Map a Kinoheld show into the unified schema."""
    return UnifiedShow(**show.model_dump(by_alias=True), source="kinoheld", sourceId=show.id)


def cinetixx_show_to_unified(show: CinetixxShow) -> UnifiedShow:
    """Map a Cinetixx show into the unified schema."""
    return UnifiedShow(**_show_payload_from_cinetixx(show), source="cinetixx", sourceId=show.id)


def kinoheld_city_to_unified(city: City) -> UnifiedCity:
    """Map a Kinoheld city into the unified schema."""
    return UnifiedCity(
        **city.model_dump(by_alias=True), source="kinoheld", sourceId=city.id or city.name
    )


def cinetixx_city_to_unified(city: CinetixxCity) -> UnifiedCity:
    """Map a Cinetixx city into the unified schema."""
    return UnifiedCity(
        id=city.id,
        name=city.name,
        source="cinetixx",
        sourceId=city.id,
    )


def kinoheld_genre_to_unified(genre: Genre) -> UnifiedGenre:
    """Map a Kinoheld genre into the unified schema."""
    source_id = genre.id or genre.name
    return UnifiedGenre(**genre.model_dump(by_alias=True), source="kinoheld", sourceId=source_id)


def cinetixx_genre_to_unified(genre: CinetixxGenre) -> UnifiedGenre:
    """Map a Cinetixx genre/category into the unified schema."""
    return UnifiedGenre(id=genre.id, name=genre.name, source="cinetixx", sourceId=genre.id)
