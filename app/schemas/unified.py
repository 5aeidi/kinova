"""Unified response schemas across cinema data sources."""

from pydantic import ConfigDict, Field

from app.schemas.cinema import Cinema
from app.schemas.city import City
from app.schemas.movie import Genre, Movie
from app.schemas.show import Show


class UnifiedCinema(Cinema):
    """Cinema response tagged with its source."""

    model_config = ConfigDict(populate_by_name=True)

    source: str
    source_id: str = Field(..., alias="sourceId")


class UnifiedMovie(Movie):
    """Movie response tagged with its source."""

    model_config = ConfigDict(populate_by_name=True)

    source: str
    source_id: str = Field(..., alias="sourceId")


class UnifiedShow(Show):
    """Show response tagged with its source."""

    model_config = ConfigDict(populate_by_name=True)

    source: str
    source_id: str = Field(..., alias="sourceId")


class UnifiedCity(City):
    """City response tagged with its source."""

    model_config = ConfigDict(populate_by_name=True)

    source: str
    source_id: str = Field(..., alias="sourceId")


class UnifiedGenre(Genre):
    """Genre response tagged with its source."""

    model_config = ConfigDict(populate_by_name=True)

    source: str
    source_id: str = Field(..., alias="sourceId")
