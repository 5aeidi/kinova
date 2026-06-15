"""Show / screening request/response schemas."""

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Url
from app.schemas.movie import Movie


class ShowFlag(BaseModel):
    """Show attribute flag (e.g. 3D, OV, OmU)."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    code: str | None = None
    category: str | None = None


class DateTimeFormatted(BaseModel):
    """Kinoheld DateTime wrapper."""

    model_config = ConfigDict(populate_by_name=True)

    formatted: str | None = None
    timestamp: int | None = None


class Auditorium(BaseModel):
    """Cinema auditorium / screen."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str | None = None
    seat_count: int | None = Field(default=None, alias="seatCount")


class Show(BaseModel):
    """A single screening / show."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    beginning: DateTimeFormatted | None = None
    admission: DateTimeFormatted | None = None
    duration: str | None = None
    flags: list[ShowFlag] = Field(default_factory=list)
    detail_url: Url | None = Field(default=None, alias="detailUrl")
    is_sold_out: bool | None = Field(default=None, alias="isSoldOut")
    movie: Movie | None = None
    auditorium: Auditorium | None = None


class ShowSearchParams(BaseModel):
    """Query parameters for ``GET /shows``."""

    model_config = ConfigDict(populate_by_name=True)

    cinema_id: str = Field(..., alias="cinemaId", description="Kinoheld cinema ID")
    date: dt.date | None = Field(default=None, description="Date in YYYY-MM-DD format")
    days: int | None = Field(default=None, ge=1, le=30, description="Number of days to fetch")
    movie_id: str | None = Field(default=None, alias="movieId", description="Filter by movie ID")
