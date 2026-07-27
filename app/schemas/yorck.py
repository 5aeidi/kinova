"""Yorck Kinogruppe request/response schemas."""

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class YorckCinema(BaseModel):
    """Cinema from the Yorck Next.js data endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str = "yorck"
    slug: str
    vista_id: str | None = Field(default=None, alias="vistaId")
    name: str
    short_name: str | None = Field(default=None, alias="shortName")
    address: str | None = None
    post_code: str | None = Field(default=None, alias="postCode")
    city: str | None = None
    district: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    phone: str | None = None
    email: str | None = None
    number_of_auditoriums: int | None = Field(default=None, alias="numberOfAuditoriums")
    accessibility: str | None = None
    short_description: str | None = Field(default=None, alias="shortDescription")
    hero_image_url: str | None = Field(default=None, alias="heroImageUrl")
    detail_url: str | None = Field(default=None, alias="detailUrl")


class YorckMovie(BaseModel):
    """Film or special event from the Yorck programme."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str = "yorck"
    slug: str | None = None
    vista_id: str | None = Field(default=None, alias="vistaId")
    title: str
    original_title: str | None = Field(default=None, alias="originalTitle")
    original_language: str | None = Field(default=None, alias="originalLanguage")
    tagline: str | None = None
    description: str | None = None
    runtime: int | None = None
    genres: list[str] = Field(default_factory=list)
    fsk: int | None = None
    descriptors: list[str] = Field(default_factory=list)
    release_date: dt.date | None = Field(default=None, alias="releaseDate")
    year: int | None = None
    directors: list[str] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    writers: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    distributor: str | None = None
    tmdb_id: int | None = Field(default=None, alias="tmdbId")
    trailer_url: str | None = Field(default=None, alias="trailerUrl")
    poster_url: str | None = Field(default=None, alias="posterUrl")
    hero_image_url: str | None = Field(default=None, alias="heroImageUrl")
    detail_url: str | None = Field(default=None, alias="detailUrl")
    is_special: bool = Field(default=False, alias="isSpecial")
    is_presale: bool = Field(default=False, alias="isPresale")
    yorck_pick: bool | None = Field(default=None, alias="yorckPick")


class YorckShow(BaseModel):
    """Screening session from the Yorck programme."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str = "yorck"
    movie_id: str | None = Field(default=None, alias="movieId")
    movie_title: str | None = Field(default=None, alias="movieTitle")
    cinema_id: str | None = Field(default=None, alias="cinemaId")
    cinema_vista_id: str | None = Field(default=None, alias="cinemaVistaId")
    cinema_name: str | None = Field(default=None, alias="cinemaName")
    city: str | None = None
    begins_at: dt.datetime | None = Field(default=None, alias="beginsAt")
    date: dt.date | None = None
    formats: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    accessibility: str | None = None
    runtime: int | None = None
    booking_url: str | None = Field(default=None, alias="bookingUrl")


class YorckCity(BaseModel):
    """City derived from Yorck cinema addresses."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str = "yorck"
    name: str
    cinema_ids: list[str] = Field(default_factory=list, alias="cinemaIds")


class YorckGenre(BaseModel):
    """Genre/label derived from the Yorck programme."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str = "yorck"
    name: str


class YorckDataset(BaseModel):
    """Normalized Yorck data extracted from the public Next.js endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    cinemas: list[YorckCinema] = Field(default_factory=list)
    movies: list[YorckMovie] = Field(default_factory=list)
    shows: list[YorckShow] = Field(default_factory=list)
    cities: list[YorckCity] = Field(default_factory=list)
    genres: list[YorckGenre] = Field(default_factory=list)


class YorckCinemaSearchParams(BaseModel):
    """Query parameters for Yorck cinema search."""

    model_config = ConfigDict(populate_by_name=True)

    search: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class YorckMovieSearchParams(BaseModel):
    """Query parameters for Yorck movie search."""

    model_config = ConfigDict(populate_by_name=True)

    search: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class YorckShowSearchParams(BaseModel):
    """Query parameters for Yorck show search."""

    model_config = ConfigDict(populate_by_name=True)

    date: dt.date | None = None
    days: int | None = Field(default=None, ge=1, le=30)
    movie_id: str | None = Field(default=None, alias="movieId")
    cinema_id: str | None = Field(default=None, alias="cinemaId")
    search: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class YorckCitySearchParams(BaseModel):
    """Query parameters for Yorck city search."""

    model_config = ConfigDict(populate_by_name=True)

    search: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class YorckGenreSearchParams(BaseModel):
    """Query parameters for Yorck genre search."""

    model_config = ConfigDict(populate_by_name=True)

    search: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
