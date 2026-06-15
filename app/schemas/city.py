"""City request/response schemas."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Geo, Url


class City(BaseModel):
    """City object."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str
    url_slug: str | None = Field(default=None, alias="urlSlug")
    coordinates: Geo | None = None
    detail_url: Url | None = Field(default=None, alias="detailUrl")


class CitySearchParams(BaseModel):
    """Query parameters for ``GET /cities``."""

    model_config = ConfigDict(populate_by_name=True)

    search: str | None = Field(default=None, description="Free-text city search")
    location: str | None = Field(default=None, description="City name to centre the search")
    distance: int | None = Field(default=None, ge=1, le=100)
    limit: int = Field(default=20, ge=1, le=100)
