"""Cinetixx source routes."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_cinetixx_service
from app.schemas.cinetixx import (
    CinetixxCinema,
    CinetixxCinemaSearchParams,
    CinetixxCity,
    CinetixxCitySearchParams,
    CinetixxGenre,
    CinetixxGenreSearchParams,
    CinetixxMovie,
    CinetixxMovieSearchParams,
    CinetixxShow,
    CinetixxShowInfo,
    CinetixxShowSearchParams,
)
from app.services.cinetixx import CinetixxService

router = APIRouter(prefix="/cinetixx", tags=["cinetixx"])

ServiceDep = Annotated[CinetixxService, Depends(get_cinetixx_service)]


@router.get("/show-info", response_model=CinetixxShowInfo)
async def get_show_info(
    mandator_id: Annotated[
        int,
        Query(
            ...,
            alias="mandatorId",
            gt=0,
            description="Cinetixx mandator ID, not always the booking widget kino ID",
        ),
    ],
    service: ServiceDep,
) -> CinetixxShowInfo:
    """Fetch Cinetixx legacy showtime data by mandator ID."""
    return await service.get_show_info_by_mandator(mandator_id)


@router.get("/cinemas", response_model=list[CinetixxCinema])
async def list_cinemas(
    service: ServiceDep,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
    search: Annotated[str | None, Query(description="Free-text cinema/city search")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[CinetixxCinema]:
    """List cinemas derived from Cinetixx program data."""
    params = CinetixxCinemaSearchParams(mandator_id=mandator_id, search=search, limit=limit)
    return await service.search_cinemas(params)


@router.get("/cinemas/{cinema_id}", response_model=CinetixxCinema)
async def get_cinema(
    service: ServiceDep,
    cinema_id: Annotated[str, Path(..., description="Cinetixx cinema ID")],
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> CinetixxCinema:
    """Fetch a derived Cinetixx cinema by ID."""
    return await service.get_cinema(cinema_id, mandator_id)


@router.get("/movies", response_model=list[CinetixxMovie])
async def list_movies(
    service: ServiceDep,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
    search: Annotated[str | None, Query(description="Free-text movie/event search")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[CinetixxMovie]:
    """List movies/events derived from Cinetixx program data."""
    params = CinetixxMovieSearchParams(mandator_id=mandator_id, search=search, limit=limit)
    return await service.search_movies(params)


@router.get("/movies/{movie_id}", response_model=CinetixxMovie)
async def get_movie(
    service: ServiceDep,
    movie_id: Annotated[str, Path(..., description="Cinetixx movie or event ID")],
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> CinetixxMovie:
    """Fetch a derived Cinetixx movie/event by ID."""
    return await service.get_movie(movie_id, mandator_id)


@router.get("/shows", response_model=list[CinetixxShow])
async def list_shows(
    service: ServiceDep,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
    date: Annotated[dt.date | None, Query(description="Start date in YYYY-MM-DD format")] = None,
    days: Annotated[int | None, Query(ge=1, le=30)] = None,
    movie_id: Annotated[str | None, Query(alias="movieId")] = None,
    cinema_id: Annotated[str | None, Query(alias="cinemaId")] = None,
    search: Annotated[str | None, Query(description="Free-text show/movie/cinema search")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[CinetixxShow]:
    """List shows derived from Cinetixx program data."""
    params = CinetixxShowSearchParams(
        mandator_id=mandator_id,
        date=date,
        days=days,
        movie_id=movie_id,
        cinema_id=cinema_id,
        search=search,
        limit=limit,
    )
    return await service.search_shows(params)


@router.get("/shows/{show_id}", response_model=CinetixxShow)
async def get_show(
    service: ServiceDep,
    show_id: Annotated[str, Path(..., description="Cinetixx show ID")],
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> CinetixxShow:
    """Fetch a derived Cinetixx show by ID."""
    return await service.get_show(show_id, mandator_id)


@router.get("/cities", response_model=list[CinetixxCity])
async def list_cities(
    service: ServiceDep,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
    search: Annotated[str | None, Query(description="Free-text city search")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[CinetixxCity]:
    """List cities derived from Cinetixx program data."""
    params = CinetixxCitySearchParams(mandator_id=mandator_id, search=search, limit=limit)
    return await service.search_cities(params)


@router.get("/genres", response_model=list[CinetixxGenre])
async def list_genres(
    service: ServiceDep,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
    search: Annotated[str | None, Query(description="Free-text genre/category search")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[CinetixxGenre]:
    """List genres/categories derived from Cinetixx program data."""
    params = CinetixxGenreSearchParams(mandator_id=mandator_id, search=search, limit=limit)
    return await service.list_genres(params)
