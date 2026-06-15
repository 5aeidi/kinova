"""Movie request/response schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import Image, Url, first_image


class Genre(BaseModel):
    """Movie genre."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str
    url_slug: str | None = Field(default=None, alias="urlSlug")


class Person(BaseModel):
    """Actor, director, etc."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str | None = None


class Movie(BaseModel):
    """Movie object."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    description: str | None = None
    additional_description: str | None = Field(default=None, alias="additionalDescription")
    duration: int | None = None
    genres: list[Genre] = Field(default_factory=list)
    directors: list[Person] = Field(default_factory=list)
    actors: list[Person] = Field(default_factory=list)
    production_year: str | None = Field(default=None, alias="productionYear")
    thumb: Image | None = None
    hero_image: Image | None = Field(default=None, alias="heroImage")
    detail_url: Url | None = Field(default=None, alias="detailUrl")
    url_slug: str | None = Field(default=None, alias="urlSlug")
    imdb_rating: float | None = Field(default=None, alias="imdbRating")
    imdb_votes: int | None = Field(default=None, alias="imdbVotes")

    @field_validator("thumb", "hero_image", mode="before")
    @classmethod
    def _normalize_image(cls, value: Any) -> Any:
        return first_image(value)


class MovieSearchParams(BaseModel):
    """Query parameters for ``GET /movies``."""

    model_config = ConfigDict(populate_by_name=True)

    search: str | None = Field(default=None, description="Free-text movie title search")
    location: str | None = Field(default=None, description="City name to restrict results")
    distance: int | None = Field(default=None, ge=1, le=100)
    limit: int = Field(default=20, ge=1, le=100)
    playing: str | None = Field(
        default=None,
        description="Filter by playing status (e.g. NOW, SOON)",
    )
