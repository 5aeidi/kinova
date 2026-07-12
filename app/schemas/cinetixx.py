"""Cinetixx request/response schemas."""

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CinetixxShowInfoParams(BaseModel):
    """Query parameters for Cinetixx legacy showtime data."""

    model_config = ConfigDict(populate_by_name=True)

    mandator_id: int = Field(
        ...,
        alias="mandatorId",
        gt=0,
        description="Cinetixx mandator ID, not always the same as booking widget kino ID",
    )


class CinetixxShowInfo(BaseModel):
    """Source-specific Cinetixx showtime payload wrapper."""

    model_config = ConfigDict(populate_by_name=True)

    source: str = "cinetixx"
    endpoint: str = "GetShowInfoV6"
    mandator_id: int = Field(..., alias="mandatorId")
    content_type: str | None = Field(default=None, alias="contentType")
    data: Any = None


class CinetixxMandator(BaseModel):
    """Cinetixx mandator discovered from the public booking cinema index."""

    model_config = ConfigDict(populate_by_name=True)

    source: str = "cinetixx"
    cinema_id: str = Field(..., alias="cinemaId")
    mandator_id: int = Field(..., alias="mandatorId")
    name: str | None = None
    cinema_name: str | None = Field(default=None, alias="cinemaName")
    mandator_name: str | None = Field(default=None, alias="mandatorName")
    address: str | None = None
    city: str | None = None
    post_code: str | None = Field(default=None, alias="postCode")
    phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    has_shows: bool | None = Field(default=None, alias="hasShows")
    program_url: str | None = Field(default=None, alias="programUrl")
    pretty_program_url: str | None = Field(default=None, alias="prettyProgramUrl")
    gift_cards_url: str | None = Field(default=None, alias="giftCardsUrl")
    card_balance_url: str | None = Field(default=None, alias="cardBalanceUrl")


class CinetixxPrice(BaseModel):
    """Cinetixx show price information when present in the source payload."""

    model_config = ConfigDict(populate_by_name=True)

    amount: float | None = None
    category: str | None = None
    area: str | None = None
    is_default: bool | None = Field(default=None, alias="isDefault")


class CinetixxCinema(BaseModel):
    """Cinema derived from Cinetixx program data."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str = "cinetixx"
    mandator_id: int = Field(..., alias="mandatorId")
    cinema_id: str | None = Field(default=None, alias="cinemaId")
    name: str | None = None
    city_id: str | None = Field(default=None, alias="cityId")
    city: str | None = None
    region_id: str | None = Field(default=None, alias="regionId")
    region: str | None = None


class CinetixxCity(BaseModel):
    """City derived from Cinetixx program data."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str = "cinetixx"
    name: str
    mandator_ids: list[int] = Field(default_factory=list, alias="mandatorIds")


class CinetixxGenre(BaseModel):
    """Genre/category derived from Cinetixx program data."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str = "cinetixx"
    name: str


class CinetixxMovie(BaseModel):
    """Movie/event derived from Cinetixx program data."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str = "cinetixx"
    movie_id: str | None = Field(default=None, alias="movieId")
    event_id: str | None = Field(default=None, alias="eventId")
    title: str
    short_title: str | None = Field(default=None, alias="shortTitle")
    description: str | None = None
    short_description: str | None = Field(default=None, alias="shortDescription")
    duration: int | None = None
    genres: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    directors: list[str] = Field(default_factory=list)
    screen_writers: list[str] = Field(default_factory=list, alias="screenWriters")
    year: str | None = None
    country: str | None = None
    artwork: str | None = None
    artwork_big: str | None = Field(default=None, alias="artworkBig")
    trailer_url: str | None = Field(default=None, alias="trailerUrl")
    movie_url: str | None = Field(default=None, alias="movieUrl")


class CinetixxShow(BaseModel):
    """Show/screening derived from Cinetixx program data."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str = "cinetixx"
    mandator_id: int = Field(..., alias="mandatorId")
    show_id: str | None = Field(default=None, alias="showId")
    movie_id: str | None = Field(default=None, alias="movieId")
    event_id: str | None = Field(default=None, alias="eventId")
    movie_title: str | None = Field(default=None, alias="movieTitle")
    text: str | None = None
    begins_at: dt.datetime | None = Field(default=None, alias="beginsAt")
    date: dt.date | None = None
    booking_url: str | None = Field(default=None, alias="bookingUrl")
    cinema_id: str | None = Field(default=None, alias="cinemaId")
    cinema_name: str | None = Field(default=None, alias="cinemaName")
    city_id: str | None = Field(default=None, alias="cityId")
    city: str | None = None
    auditorium_id: str | None = Field(default=None, alias="auditoriumId")
    auditorium_name: str | None = Field(default=None, alias="auditoriumName")
    language: str | None = None
    version: str | None = None
    audio_type: str | None = Field(default=None, alias="audioType")
    age_rating: str | None = Field(default=None, alias="ageRating")
    duration: int | None = None
    is_3d: bool | None = Field(default=None, alias="is3d")
    has_seat_selection: bool | None = Field(default=None, alias="hasSeatSelection")
    sales_start: dt.datetime | None = Field(default=None, alias="salesStart")
    sales_end: dt.datetime | None = Field(default=None, alias="salesEnd")
    reservation_start: dt.datetime | None = Field(default=None, alias="reservationStart")
    reservation_end: dt.datetime | None = Field(default=None, alias="reservationEnd")
    flags: list[str] = Field(default_factory=list)
    prices: list[CinetixxPrice] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CinetixxDataset(BaseModel):
    """Normalized Cinetixx data extracted from one or more mandator payloads."""

    model_config = ConfigDict(populate_by_name=True)

    cinemas: list[CinetixxCinema] = Field(default_factory=list)
    movies: list[CinetixxMovie] = Field(default_factory=list)
    shows: list[CinetixxShow] = Field(default_factory=list)
    cities: list[CinetixxCity] = Field(default_factory=list)
    genres: list[CinetixxGenre] = Field(default_factory=list)


class CinetixxCinemaSearchParams(BaseModel):
    """Query parameters for Cinetixx cinema search."""

    model_config = ConfigDict(populate_by_name=True)

    mandator_id: int | None = Field(default=None, alias="mandatorId", gt=0)
    search: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class CinetixxMandatorSearchParams(BaseModel):
    """Query parameters for Cinetixx mandator discovery."""

    model_config = ConfigDict(populate_by_name=True)

    search: str | None = None
    cinema_id: str | None = Field(default=None, alias="cinemaId")
    lat: float | None = None
    lon: float | None = None
    page: int | None = Field(default=None, ge=1)
    limit: int = Field(default=100, ge=1, le=1000)


class CinetixxMovieSearchParams(BaseModel):
    """Query parameters for Cinetixx movie search."""

    model_config = ConfigDict(populate_by_name=True)

    mandator_id: int | None = Field(default=None, alias="mandatorId", gt=0)
    search: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class CinetixxShowSearchParams(BaseModel):
    """Query parameters for Cinetixx show search."""

    model_config = ConfigDict(populate_by_name=True)

    mandator_id: int | None = Field(default=None, alias="mandatorId", gt=0)
    date: dt.date | None = None
    days: int | None = Field(default=None, ge=1, le=30)
    movie_id: str | None = Field(default=None, alias="movieId")
    cinema_id: str | None = Field(default=None, alias="cinemaId")
    search: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class CinetixxCitySearchParams(BaseModel):
    """Query parameters for Cinetixx city search."""

    model_config = ConfigDict(populate_by_name=True)

    mandator_id: int | None = Field(default=None, alias="mandatorId", gt=0)
    search: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class CinetixxGenreSearchParams(BaseModel):
    """Query parameters for Cinetixx genre search."""

    model_config = ConfigDict(populate_by_name=True)

    mandator_id: int | None = Field(default=None, alias="mandatorId", gt=0)
    search: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
