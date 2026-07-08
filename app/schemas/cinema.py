"""Cinema request/response schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import Geo, Image, Url, first_image


class Cinema(BaseModel):
    """Cinema / theatre object."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    street: str | None = None
    city: "CitySummary | None" = None
    distance: float | None = None
    coordinates: Geo | None = None
    postcode: str | None = None
    phonenumber: str | None = None
    detail_url: Url | None = Field(default=None, alias="detailUrl")
    thumbnail: Image | None = None
    hero_image: Image | None = Field(default=None, alias="heroImage")
    url_slug: str | None = Field(default=None, alias="urlSlug")
    is_drive_in_cinema: bool | None = Field(default=None, alias="isDriveInCinema")
    is_open_air_cinema: bool | None = Field(default=None, alias="isOpenAirCinema")
    is_stationary_cinema: bool | None = Field(default=None, alias="isStationaryCinema")

    @field_validator("postcode", mode="before")
    @classmethod
    def _extract_postcode(cls, value: Any) -> str | None:
        """Accept both a plain string and the Kinoheld Postcode object."""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("postcode")
        return None

    @field_validator("thumbnail", "hero_image", mode="before")
    @classmethod
    def _normalize_image(cls, value: Any) -> Any:
        return first_image(value)


class CitySummary(BaseModel):
    """Minimal city representation embedded in cinemas."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str | None = None
    url_slug: str | None = Field(default=None, alias="urlSlug")


# Resolve forward reference
Cinema.model_rebuild()


class CinemaSearchParams(BaseModel):
    """Query parameters for ``GET /cinemas``."""

    model_config = ConfigDict(populate_by_name=True)

    search: str | None = Field(default=None, description="Free-text cinema/city search")
    location: str | None = Field(default=None, description="City name to centre the search")
    distance: int | None = Field(default=None, ge=1, le=100, description="Search radius in km")
    limit: int = Field(default=1000, ge=1, le=1000)
    only_bookable: bool = Field(default=False, alias="onlyBookable")
    is_open_air: bool | None = Field(default=None, alias="isOpenAir")
    is_drive_in: bool | None = Field(default=None, alias="isDriveIn")
