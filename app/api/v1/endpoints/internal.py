"""Internal routes backed by the local Kinoheld cache."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import get_kinoheld_cache, get_kinoheld_cached_service, get_kinoheld_service
from app.core.config import settings
from app.schemas.cinema import Cinema, CinemaSearchParams
from app.schemas.city import City, CitySearchParams
from app.schemas.movie import Genre, Movie, MovieSearchParams
from app.schemas.show import Show, ShowSearchParams
from app.services.cache import KinoheldCache
from app.services.kinoheld import KinoheldService

router = APIRouter(prefix="/internal", tags=["internal"])

CacheDep = Annotated[KinoheldCache, Depends(get_kinoheld_cache)]
CachedServiceDep = Annotated[KinoheldService, Depends(get_kinoheld_cached_service)]
LiveServiceDep = Annotated[KinoheldService, Depends(get_kinoheld_service)]


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------
@router.get("/health")
async def internal_health_check(cache: CacheDep) -> dict[str, str | int | list[str] | None]:
    """Health probe that also reports cache status."""
    snapshot = cache.snapshot()
    return {
        "status": "ok",
        "source": "cache",
        "last_refresh": snapshot["last_refresh"],
        "cached_cinemas": snapshot["cinemas"],
        "cached_movies": snapshot["movies"],
        "cached_cities": snapshot["cities"],
        "cached_genres": snapshot["genres"],
    }


# ------------------------------------------------------------------
# Cinemas
# ------------------------------------------------------------------
@router.get("/cinemas", response_model=list[Cinema])
async def list_cinemas_internal(
    params: Annotated[CinemaSearchParams, Depends()],
    cache: CacheDep,
) -> list[Cinema]:
    """Search cached cinemas."""
    return await cache.search_cinemas(params)


@router.get("/cinemas/{cinema_id}", response_model=Cinema)
async def get_cinema_internal(
    cinema_id: Annotated[str, Path(..., description="Kinoheld cinema ID")],
    cache: CacheDep,
) -> Cinema:
    """Fetch a single cached cinema by ID."""
    return await cache.get_cinema(cinema_id)


# ------------------------------------------------------------------
# Movies
# ------------------------------------------------------------------
@router.get("/movies", response_model=list[Movie])
async def list_movies_internal(
    params: Annotated[MovieSearchParams, Depends()],
    cache: CacheDep,
) -> list[Movie]:
    """Search cached movies."""
    return await cache.search_movies(params)


@router.get("/movies/{movie_id}", response_model=Movie)
async def get_movie_internal(
    movie_id: Annotated[str, Path(..., description="Kinoheld movie ID")],
    cache: CacheDep,
) -> Movie:
    """Fetch a single cached movie by ID."""
    return await cache.get_movie(movie_id)


# ------------------------------------------------------------------
# Shows
# ------------------------------------------------------------------
@router.get("/shows", response_model=list[Show])
async def list_shows_internal(
    params: Annotated[ShowSearchParams, Depends()],
    cache: CacheDep,
    service: CachedServiceDep,
) -> list[Show]:
    """List cached shows for a cinema, optionally filtered by date and movie.

    If shows for the requested cinema/date are not in the cache, they are
    fetched on demand and stored for subsequent requests.
    """
    shows = await cache.search_shows(params)
    if shows:
        return shows

    # On-demand fetch for cinemas/dates outside the pre-configured sync list.
    cinema_id = params.cinema_id
    base_date = params.date or dt.date.today()
    dates = [
        (base_date + dt.timedelta(days=offset)).isoformat()
        for offset in range(settings.kinoheld_sync_show_days)
    ]
    await cache.cache_shows_for_cinema(service, cinema_id, dates)
    # Re-run the search now that the cache is populated for the requested date.
    return await cache.search_shows(params)


@router.get("/shows/{show_id}", response_model=Show)
async def get_show_internal(
    show_id: Annotated[str, Path(..., description="Kinoheld show ID")],
    cache: CacheDep,
) -> Show:
    """Fetch a single cached show by ID."""
    return await cache.get_show(show_id)


# ------------------------------------------------------------------
# Cities
# ------------------------------------------------------------------
@router.get("/cities", response_model=list[City])
async def list_cities_internal(
    params: Annotated[CitySearchParams, Depends()],
    cache: CacheDep,
) -> list[City]:
    """Search cached cities."""
    return await cache.search_cities(params)


@router.get("/cities/me", response_model=City)
async def city_by_ip_internal(service: LiveServiceDep) -> City:
    """Return the city inferred from the request IP.

    This is IP-specific and cannot be cached, so it calls Kinoheld directly.
    """
    return await service.city_by_ip()


@router.get("/cities/{city_id}", response_model=City)
async def get_city_internal(
    city_id: Annotated[str, Path(..., description="Kinoheld city ID or name")],
    cache: CacheDep,
) -> City:
    """Fetch a single cached city by ID, name, or slug."""
    return await cache.get_city(city_id)


# ------------------------------------------------------------------
# Genres
# ------------------------------------------------------------------
@router.get("/genres", response_model=list[Genre])
async def list_genres_internal(cache: CacheDep) -> list[Genre]:
    """List all cached movie genres."""
    return await cache.list_genres()
