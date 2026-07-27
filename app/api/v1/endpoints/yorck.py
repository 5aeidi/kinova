"""Yorck Kinogruppe source routes."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_yorck_service
from app.schemas.yorck import (
    YorckCinema,
    YorckCinemaSearchParams,
    YorckCity,
    YorckCitySearchParams,
    YorckGenre,
    YorckGenreSearchParams,
    YorckMovie,
    YorckMovieSearchParams,
    YorckShow,
    YorckShowSearchParams,
)
from app.services.yorck import YorckService

router = APIRouter(prefix="/yorck", tags=["yorck"])

ServiceDep = Annotated[YorckService, Depends(get_yorck_service)]


@router.get("/cinemas", response_model=list[YorckCinema])
async def list_cinemas(
    service: ServiceDep,
    search: Annotated[str | None, Query(description="Free-text cinema/district search")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[YorckCinema]:
    """List cinemas from the Yorck programme."""
    return await service.search_cinemas(YorckCinemaSearchParams(search=search, limit=limit))


@router.get("/cinemas/{cinema_id}", response_model=YorckCinema)
async def get_cinema(
    service: ServiceDep,
    cinema_id: Annotated[str, Path(..., description="Yorck cinema slug or Vista ID")],
) -> YorckCinema:
    """Fetch a Yorck cinema by slug or Vista ID."""
    return await service.get_cinema(cinema_id)


@router.get("/movies", response_model=list[YorckMovie])
async def list_movies(
    service: ServiceDep,
    search: Annotated[str | None, Query(description="Free-text movie/genre search")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[YorckMovie]:
    """List movies/specials from the Yorck programme."""
    return await service.search_movies(YorckMovieSearchParams(search=search, limit=limit))


@router.get("/movies/{movie_id}", response_model=YorckMovie)
async def get_movie(
    service: ServiceDep,
    movie_id: Annotated[str, Path(..., description="Yorck movie ID, slug, or Vista ID")],
) -> YorckMovie:
    """Fetch a Yorck movie/special by ID."""
    return await service.get_movie(movie_id)


@router.get("/shows", response_model=list[YorckShow])
async def list_shows(
    service: ServiceDep,
    date: Annotated[dt.date | None, Query(description="Start date in YYYY-MM-DD format")] = None,
    days: Annotated[int | None, Query(ge=1, le=30)] = None,
    movie_id: Annotated[str | None, Query(alias="movieId")] = None,
    cinema_id: Annotated[str | None, Query(alias="cinemaId")] = None,
    search: Annotated[str | None, Query(description="Free-text show/movie/cinema search")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[YorckShow]:
    """List shows from the Yorck programme."""
    params = YorckShowSearchParams(
        date=date,
        days=days,
        movie_id=movie_id,
        cinema_id=cinema_id,
        search=search,
        limit=limit,
    )
    return await service.search_shows(params)


@router.get("/shows/{show_id}", response_model=YorckShow)
async def get_show(
    service: ServiceDep,
    show_id: Annotated[str, Path(..., description="Yorck session ID")],
) -> YorckShow:
    """Fetch a Yorck show by session ID."""
    return await service.get_show(show_id)


@router.get("/cities", response_model=list[YorckCity])
async def list_cities(
    service: ServiceDep,
    search: Annotated[str | None, Query(description="Free-text city search")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[YorckCity]:
    """List cities derived from Yorck cinema addresses."""
    return await service.search_cities(YorckCitySearchParams(search=search, limit=limit))


@router.get("/genres", response_model=list[YorckGenre])
async def list_genres(
    service: ServiceDep,
    search: Annotated[str | None, Query(description="Free-text genre/label search")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[YorckGenre]:
    """List genres/labels derived from the Yorck programme."""
    return await service.list_genres(YorckGenreSearchParams(search=search, limit=limit))
