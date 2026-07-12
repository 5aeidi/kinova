"""In-memory cache for normalized Cinetixx data."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from app.core.config import settings
from app.core.exceptions import CinetixxNotFoundError
from app.schemas.cinetixx import (
    CinetixxCinema,
    CinetixxCinemaSearchParams,
    CinetixxCity,
    CinetixxCitySearchParams,
    CinetixxDataset,
    CinetixxGenre,
    CinetixxGenreSearchParams,
    CinetixxMovie,
    CinetixxMovieSearchParams,
    CinetixxShow,
    CinetixxShowInfo,
    CinetixxShowSearchParams,
)
from app.services.cinetixx import CinetixxService

logger = logging.getLogger(__name__)


class CinetixxCache:
    """Atomic in-memory cache with query helpers for Cinetixx internal endpoints."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._payloads: dict[int, CinetixxShowInfo] = {}
        self._datasets: dict[int, CinetixxDataset] = {}
        self._last_refresh: dt.datetime | None = None

    async def refresh(self, service: CinetixxService) -> None:
        """Fetch configured Cinetixx mandators and rebuild the cache atomically."""
        logger.info("Starting Cinetixx cache refresh")

        payloads: dict[int, CinetixxShowInfo] = {}
        datasets: dict[int, CinetixxDataset] = {}
        for mandator_id in settings.cinetixx_sync_mandator_ids:
            try:
                show_info = await service.get_show_info_by_mandator(mandator_id)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to fetch Cinetixx mandator %s", mandator_id)
                continue

            payloads[mandator_id] = show_info
            datasets[mandator_id] = service.normalize_show_info(show_info)

        async with self._lock:
            self._payloads = payloads
            self._datasets = datasets
            self._last_refresh = dt.datetime.now(tz=dt.timezone.utc)

        merged = CinetixxService.merge_datasets(list(datasets.values()))
        logger.info(
            "Cinetixx cache refresh complete: %d mandators, %d cinemas, %d movies, %d shows",
            len(datasets),
            len(merged.cinemas),
            len(merged.movies),
            len(merged.shows),
        )

    async def cache_mandator(self, service: CinetixxService, mandator_id: int) -> None:
        """Fetch and cache one Cinetixx mandator on demand."""
        show_info = await service.get_show_info_by_mandator(mandator_id)
        dataset = service.normalize_show_info(show_info)

        async with self._lock:
            self._payloads[mandator_id] = show_info
            self._datasets[mandator_id] = dataset
            self._last_refresh = dt.datetime.now(tz=dt.timezone.utc)

    async def has_mandator(self, mandator_id: int) -> bool:
        """Return whether a mandator is already cached."""
        async with self._lock:
            return mandator_id in self._datasets

    async def get_show_info(self, mandator_id: int) -> CinetixxShowInfo:
        """Return cached raw show-info payload for a mandator."""
        async with self._lock:
            if payload := self._payloads.get(mandator_id):
                return payload
        raise CinetixxNotFoundError(f"Cinetixx mandator {mandator_id} not found in cache")

    async def get_dataset(self, mandator_id: int | None = None) -> CinetixxDataset:
        """Return a normalized dataset for one mandator or all cached mandators."""
        async with self._lock:
            if mandator_id is not None:
                dataset = self._datasets.get(mandator_id)
                if dataset is None:
                    return CinetixxDataset()
                return dataset.model_copy(deep=True)
            return CinetixxService.merge_datasets(
                [dataset.model_copy(deep=True) for dataset in self._datasets.values()],
            )

    async def search_cinemas(self, params: CinetixxCinemaSearchParams) -> list[CinetixxCinema]:
        """Search cached Cinetixx cinemas."""
        dataset = await self.get_dataset(params.mandator_id)
        return CinetixxService.filter_cinemas(dataset.cinemas, params)

    async def get_cinema(
        self,
        cinema_id: str,
        mandator_id: int | None = None,
    ) -> CinetixxCinema:
        """Return a cached Cinetixx cinema by ID."""
        cinemas = await self.search_cinemas(CinetixxCinemaSearchParams(mandator_id=mandator_id))
        for cinema in cinemas:
            if cinema.id == cinema_id or cinema.cinema_id == cinema_id:
                return cinema
        raise CinetixxNotFoundError(f"Cinetixx cinema {cinema_id} not found")

    async def search_movies(self, params: CinetixxMovieSearchParams) -> list[CinetixxMovie]:
        """Search cached Cinetixx movies."""
        dataset = await self.get_dataset(params.mandator_id)
        return CinetixxService.filter_movies(dataset.movies, params)

    async def get_movie(
        self,
        movie_id: str,
        mandator_id: int | None = None,
    ) -> CinetixxMovie:
        """Return a cached Cinetixx movie by ID."""
        movies = await self.search_movies(CinetixxMovieSearchParams(mandator_id=mandator_id))
        for movie in movies:
            if movie.id == movie_id or movie.movie_id == movie_id or movie.event_id == movie_id:
                return movie
        raise CinetixxNotFoundError(f"Cinetixx movie {movie_id} not found")

    async def search_shows(self, params: CinetixxShowSearchParams) -> list[CinetixxShow]:
        """Search cached Cinetixx shows."""
        dataset = await self.get_dataset(params.mandator_id)
        return CinetixxService.filter_shows(dataset.shows, params)

    async def get_show(
        self,
        show_id: str,
        mandator_id: int | None = None,
    ) -> CinetixxShow:
        """Return a cached Cinetixx show by ID."""
        shows = await self.search_shows(CinetixxShowSearchParams(mandator_id=mandator_id))
        for show in shows:
            if show.id == show_id or show.show_id == show_id:
                return show
        raise CinetixxNotFoundError(f"Cinetixx show {show_id} not found")

    async def search_cities(self, params: CinetixxCitySearchParams) -> list[CinetixxCity]:
        """Search cached Cinetixx cities."""
        dataset = await self.get_dataset(params.mandator_id)
        return CinetixxService.filter_cities(dataset.cities, params)

    async def get_city(self, city_id: str, mandator_id: int | None = None) -> CinetixxCity:
        """Return a cached Cinetixx city by ID or name."""
        cities = await self.search_cities(CinetixxCitySearchParams(mandator_id=mandator_id))
        for city in cities:
            if city.id == city_id or city.name == city_id:
                return city
        raise CinetixxNotFoundError(f"Cinetixx city {city_id} not found")

    async def list_genres(self, params: CinetixxGenreSearchParams) -> list[CinetixxGenre]:
        """List cached Cinetixx genres."""
        dataset = await self.get_dataset(params.mandator_id)
        return CinetixxService.filter_genres(dataset.genres, params)

    def snapshot(self) -> dict:
        """Return a lightweight cache status snapshot."""
        datasets = [dataset.model_copy(deep=True) for dataset in self._datasets.values()]
        merged = CinetixxService.merge_datasets(datasets)
        return {
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "mandators": sorted(self._datasets.keys()),
            "cinemas": len(merged.cinemas),
            "movies": len(merged.movies),
            "shows": len(merged.shows),
            "cities": len(merged.cities),
            "genres": len(merged.genres),
        }
