"""Unified internal routes across cached data sources."""

import contextlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.api.deps import get_cinetixx_cache, get_cinetixx_cached_service, get_kinoheld_cache
from app.core.config import settings
from app.schemas.cinema import CinemaSearchParams
from app.schemas.cinetixx import (
    CinetixxCinemaSearchParams,
    CinetixxCitySearchParams,
    CinetixxGenreSearchParams,
    CinetixxMovieSearchParams,
    CinetixxShowSearchParams,
)
from app.schemas.city import CitySearchParams
from app.schemas.movie import MovieSearchParams
from app.schemas.show import ShowSearchParams
from app.schemas.unified import UnifiedCinema, UnifiedCity, UnifiedGenre, UnifiedMovie, UnifiedShow
from app.services.cache import KinoheldCache
from app.services.cinetixx import CinetixxService
from app.services.cinetixx_cache import CinetixxCache
from app.services.unified import (
    cinetixx_cinema_to_unified,
    cinetixx_city_to_unified,
    cinetixx_genre_to_unified,
    cinetixx_movie_to_unified,
    cinetixx_show_to_unified,
    kinoheld_cinema_to_unified,
    kinoheld_city_to_unified,
    kinoheld_genre_to_unified,
    kinoheld_movie_to_unified,
    kinoheld_show_to_unified,
)

router = APIRouter(prefix="/internal/unified", tags=["internal", "unified"])

KinoheldCacheDep = Annotated[KinoheldCache, Depends(get_kinoheld_cache)]
CinetixxCacheDep = Annotated[CinetixxCache, Depends(get_cinetixx_cache)]
CinetixxServiceDep = Annotated[CinetixxService, Depends(get_cinetixx_cached_service)]

SUPPORTED_SOURCES = {"kinoheld", "cinetixx"}


def _requested_sources(source: str | None) -> set[str]:
    if source is None or source == "all":
        return set(SUPPORTED_SOURCES)
    normalized = source.casefold()
    if normalized not in SUPPORTED_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported source '{source}'",
        )
    return {normalized}


def _split_unified_id(resource_id: str) -> tuple[str | None, str]:
    if ":" not in resource_id:
        return None, resource_id
    source, source_id = resource_id.split(":", 1)
    return source.casefold(), source_id


async def _ensure_cinetixx_cached(
    cache: CinetixxCache,
    service: CinetixxService,
    sources: set[str],
    mandator_id: int | None,
) -> None:
    if "cinetixx" not in sources:
        return
    if mandator_id is not None:
        if not await cache.has_mandator(mandator_id):
            await cache.cache_mandator(service, mandator_id)
        return
    if not cache.snapshot()["mandators"] and settings.cinetixx_sync_mandator_ids:
        await cache.refresh(service)


def _sort_by_name(items):
    return sorted(
        items,
        key=lambda item: (
            getattr(item, "name", None) or getattr(item, "title", None) or ""
        ).casefold(),
    )


def _sort_shows(items: list[UnifiedShow]) -> list[UnifiedShow]:
    return sorted(
        items,
        key=lambda item: (
            item.beginning.timestamp
            if item.beginning and item.beginning.timestamp is not None
            else 2**63 - 1
        ),
    )


@router.get("/cinemas", response_model=list[UnifiedCinema])
async def list_unified_cinemas(
    params: Annotated[CinemaSearchParams, Depends()],
    kinoheld_cache: KinoheldCacheDep,
    cinetixx_cache: CinetixxCacheDep,
    cinetixx_service: CinetixxServiceDep,
    source: Annotated[str | None, Query(description="Optional source tag filter")] = None,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> list[UnifiedCinema]:
    """List unified cinemas from cached providers."""
    sources = _requested_sources(source)
    await _ensure_cinetixx_cached(cinetixx_cache, cinetixx_service, sources, mandator_id)

    results: list[UnifiedCinema] = []
    if "kinoheld" in sources:
        results.extend(
            kinoheld_cinema_to_unified(item) for item in await kinoheld_cache.search_cinemas(params)
        )
    if "cinetixx" in sources:
        cinetixx = await cinetixx_cache.search_cinemas(
            CinetixxCinemaSearchParams(
                mandator_id=mandator_id,
                search=params.search or params.location,
                limit=params.limit,
            ),
        )
        results.extend(cinetixx_cinema_to_unified(item) for item in cinetixx)

    return _sort_by_name(results)[: params.limit]


@router.get("/cinemas/{cinema_id}", response_model=UnifiedCinema)
async def get_unified_cinema(
    kinoheld_cache: KinoheldCacheDep,
    cinetixx_cache: CinetixxCacheDep,
    cinetixx_service: CinetixxServiceDep,
    cinema_id: Annotated[str, Path(..., description="Unified or provider cinema ID")],
    source: Annotated[str | None, Query(description="Optional source tag filter")] = None,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> UnifiedCinema:
    """Fetch one unified cinema by unified ID or provider ID."""
    id_source, source_id = _split_unified_id(cinema_id)
    sources = _requested_sources(source or id_source)
    await _ensure_cinetixx_cached(cinetixx_cache, cinetixx_service, sources, mandator_id)

    if "kinoheld" in sources:
        with contextlib.suppress(Exception):
            return kinoheld_cinema_to_unified(await kinoheld_cache.get_cinema(source_id))
    if "cinetixx" in sources:
        with contextlib.suppress(Exception):
            return cinetixx_cinema_to_unified(
                await cinetixx_cache.get_cinema(source_id, mandator_id)
            )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unified cinema not found")


@router.get("/movies", response_model=list[UnifiedMovie])
async def list_unified_movies(
    params: Annotated[MovieSearchParams, Depends()],
    kinoheld_cache: KinoheldCacheDep,
    cinetixx_cache: CinetixxCacheDep,
    cinetixx_service: CinetixxServiceDep,
    source: Annotated[str | None, Query(description="Optional source tag filter")] = None,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> list[UnifiedMovie]:
    """List unified movies/events from cached providers."""
    sources = _requested_sources(source)
    await _ensure_cinetixx_cached(cinetixx_cache, cinetixx_service, sources, mandator_id)

    results: list[UnifiedMovie] = []
    if "kinoheld" in sources:
        results.extend(
            kinoheld_movie_to_unified(item) for item in await kinoheld_cache.search_movies(params)
        )
    if "cinetixx" in sources:
        cinetixx = await cinetixx_cache.search_movies(
            CinetixxMovieSearchParams(
                mandator_id=mandator_id,
                search=params.search or params.location,
                limit=params.limit,
            ),
        )
        results.extend(cinetixx_movie_to_unified(item) for item in cinetixx)

    return _sort_by_name(results)[: params.limit]


@router.get("/movies/{movie_id}", response_model=UnifiedMovie)
async def get_unified_movie(
    kinoheld_cache: KinoheldCacheDep,
    cinetixx_cache: CinetixxCacheDep,
    cinetixx_service: CinetixxServiceDep,
    movie_id: Annotated[str, Path(..., description="Unified or provider movie/event ID")],
    source: Annotated[str | None, Query(description="Optional source tag filter")] = None,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> UnifiedMovie:
    """Fetch one unified movie/event by unified ID or provider ID."""
    id_source, source_id = _split_unified_id(movie_id)
    sources = _requested_sources(source or id_source)
    await _ensure_cinetixx_cached(cinetixx_cache, cinetixx_service, sources, mandator_id)

    if "kinoheld" in sources:
        with contextlib.suppress(Exception):
            return kinoheld_movie_to_unified(await kinoheld_cache.get_movie(source_id))
    if "cinetixx" in sources:
        with contextlib.suppress(Exception):
            return cinetixx_movie_to_unified(await cinetixx_cache.get_movie(source_id, mandator_id))
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unified movie not found")


@router.get("/shows", response_model=list[UnifiedShow])
async def list_unified_shows(
    params: Annotated[ShowSearchParams, Depends()],
    kinoheld_cache: KinoheldCacheDep,
    cinetixx_cache: CinetixxCacheDep,
    cinetixx_service: CinetixxServiceDep,
    source: Annotated[str | None, Query(description="Optional source tag filter")] = None,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> list[UnifiedShow]:
    """List unified shows from cached providers."""
    sources = _requested_sources(source)
    await _ensure_cinetixx_cached(cinetixx_cache, cinetixx_service, sources, mandator_id)

    results: list[UnifiedShow] = []
    if "kinoheld" in sources:
        results.extend(
            kinoheld_show_to_unified(item) for item in await kinoheld_cache.search_shows(params)
        )
    if "cinetixx" in sources:
        cinetixx = await cinetixx_cache.search_shows(
            CinetixxShowSearchParams(
                mandator_id=mandator_id,
                date=params.date,
                days=params.days,
                movie_id=params.movie_id,
                cinema_id=params.cinema_id,
                limit=1000,
            ),
        )
        results.extend(cinetixx_show_to_unified(item) for item in cinetixx)

    return _sort_shows(results)


@router.get("/shows/{show_id}", response_model=UnifiedShow)
async def get_unified_show(
    kinoheld_cache: KinoheldCacheDep,
    cinetixx_cache: CinetixxCacheDep,
    cinetixx_service: CinetixxServiceDep,
    show_id: Annotated[str, Path(..., description="Unified or provider show ID")],
    source: Annotated[str | None, Query(description="Optional source tag filter")] = None,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> UnifiedShow:
    """Fetch one unified show by unified ID or provider ID."""
    id_source, source_id = _split_unified_id(show_id)
    sources = _requested_sources(source or id_source)
    await _ensure_cinetixx_cached(cinetixx_cache, cinetixx_service, sources, mandator_id)

    if "kinoheld" in sources:
        with contextlib.suppress(Exception):
            return kinoheld_show_to_unified(await kinoheld_cache.get_show(source_id))
    if "cinetixx" in sources:
        with contextlib.suppress(Exception):
            return cinetixx_show_to_unified(await cinetixx_cache.get_show(source_id, mandator_id))
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unified show not found")


@router.get("/cities", response_model=list[UnifiedCity])
async def list_unified_cities(
    params: Annotated[CitySearchParams, Depends()],
    kinoheld_cache: KinoheldCacheDep,
    cinetixx_cache: CinetixxCacheDep,
    cinetixx_service: CinetixxServiceDep,
    source: Annotated[str | None, Query(description="Optional source tag filter")] = None,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> list[UnifiedCity]:
    """List unified cities from cached providers."""
    sources = _requested_sources(source)
    await _ensure_cinetixx_cached(cinetixx_cache, cinetixx_service, sources, mandator_id)

    results: list[UnifiedCity] = []
    if "kinoheld" in sources:
        results.extend(
            kinoheld_city_to_unified(item) for item in await kinoheld_cache.search_cities(params)
        )
    if "cinetixx" in sources:
        cinetixx = await cinetixx_cache.search_cities(
            CinetixxCitySearchParams(
                mandator_id=mandator_id,
                search=params.search or params.location,
                limit=params.limit,
            ),
        )
        results.extend(cinetixx_city_to_unified(item) for item in cinetixx)

    return _sort_by_name(results)[: params.limit]


@router.get("/cities/{city_id}", response_model=UnifiedCity)
async def get_unified_city(
    kinoheld_cache: KinoheldCacheDep,
    cinetixx_cache: CinetixxCacheDep,
    cinetixx_service: CinetixxServiceDep,
    city_id: Annotated[str, Path(..., description="Unified or provider city ID")],
    source: Annotated[str | None, Query(description="Optional source tag filter")] = None,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> UnifiedCity:
    """Fetch one unified city by unified ID or provider ID."""
    id_source, source_id = _split_unified_id(city_id)
    sources = _requested_sources(source or id_source)
    await _ensure_cinetixx_cached(cinetixx_cache, cinetixx_service, sources, mandator_id)

    if "kinoheld" in sources:
        with contextlib.suppress(Exception):
            return kinoheld_city_to_unified(await kinoheld_cache.get_city(source_id))
    if "cinetixx" in sources:
        with contextlib.suppress(Exception):
            return cinetixx_city_to_unified(await cinetixx_cache.get_city(source_id, mandator_id))
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unified city not found")


@router.get("/genres", response_model=list[UnifiedGenre])
async def list_unified_genres(
    kinoheld_cache: KinoheldCacheDep,
    cinetixx_cache: CinetixxCacheDep,
    cinetixx_service: CinetixxServiceDep,
    source: Annotated[str | None, Query(description="Optional source tag filter")] = None,
    mandator_id: Annotated[int | None, Query(alias="mandatorId", gt=0)] = None,
) -> list[UnifiedGenre]:
    """List unified genres/categories from cached providers."""
    sources = _requested_sources(source)
    await _ensure_cinetixx_cached(cinetixx_cache, cinetixx_service, sources, mandator_id)

    results: list[UnifiedGenre] = []
    if "kinoheld" in sources:
        results.extend(
            kinoheld_genre_to_unified(item) for item in await kinoheld_cache.list_genres()
        )
    if "cinetixx" in sources:
        cinetixx = await cinetixx_cache.list_genres(
            CinetixxGenreSearchParams(mandator_id=mandator_id)
        )
        results.extend(cinetixx_genre_to_unified(item) for item in cinetixx)

    return _sort_by_name(results)
