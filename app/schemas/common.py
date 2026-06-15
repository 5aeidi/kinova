"""Shared response models and base types."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Url(BaseModel):
    """Kinoheld URL wrapper."""

    model_config = ConfigDict(populate_by_name=True)

    url: HttpUrl | None = None


class Image(BaseModel):
    """Kinoheld image asset."""

    model_config = ConfigDict(populate_by_name=True)

    url: HttpUrl | None = None
    alt: str | None = None


class Geo(BaseModel):
    """Geographic coordinates."""

    model_config = ConfigDict(populate_by_name=True)

    latitude: float | None = None
    longitude: float | None = None


class PaginationParams(BaseModel):
    """Reusable pagination / limit parameters."""

    model_config = ConfigDict(populate_by_name=True)

    limit: int = Field(default=20, ge=1, le=100)


def first_image(value: Any) -> Any:
    """Normalize Kinoheld image fields that are sometimes a list.

    The upstream GraphQL API returns either a single image object or a list of
    image objects for the same field depending on the query. Take the first
    item when a list is returned so the model stays a single ``Image``.
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return value
