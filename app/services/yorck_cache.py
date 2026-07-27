"""In-memory cache for normalized Yorck data."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from app.schemas.yorck import (
    YorckCinema,
    YorckCinemaSearchParams,
    YorckCity,
    YorckCitySearchParams,
    YorckDataset,
    YorckGenre,
    YorckGenreSearchParams,
    YorckMovie,
    YorckMovieSearchParams,
    YorckShow,
    YorckShowSearchParams,
)
from app.services.yorck import YorckService

logger = logging.getLogger(__name__)


class YorckCache:
    """Atomic in-memory cache with query helpers for Yorck internal endpoints."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._dataset = YorckDataset()
        self._last_refresh: dt.datetime | None = None

    async def refresh(self, service: YorckService) -> None:
        """Refresh the full Yorck programme, keeping stale data on failure."""
        logger.info("Starting Yorck cache refresh")
        try:
            dataset = await service.get_dataset()
        except Exception:
            logger.exception("Yorck cache refresh failed; keeping previous data")
            return

        async with self._lock:
            self._dataset = dataset
            self._last_refresh = dt.datetime.now(tz=dt.timezone.utc)

        logger.info(
            "Yorck cache refresh complete: %d cinemas, %d movies, %d shows",
            len(dataset.cinemas),
            len(dataset.movies),
            len(dataset.shows),
        )

    async def is_populated(self) -> bool:
        """Return whether the cache holds any refreshed data."""
        async with self._lock:
            return self._last_refresh is not None

    async def get_dataset(self) -> YorckDataset:
        """Return the cached dataset. Shared cache state; callers must not mutate it."""
        async with self._lock:
            return self._dataset

    async def search_cinemas(self, params: YorckCinemaSearchParams) -> list[YorckCinema]:
        """Search cached Yorck cinemas."""
        dataset = await self.get_dataset()
        return YorckService.filter_cinemas(dataset.cinemas, params)

    async def get_cinema(self, cinema_id: str) -> YorckCinema:
        """Return a cached Yorck cinema by slug or Vista ID."""
        dataset = await self.get_dataset()
        return YorckService.find_cinema(dataset.cinemas, cinema_id)

    async def search_movies(self, params: YorckMovieSearchParams) -> list[YorckMovie]:
        """Search cached Yorck movies."""
        dataset = await self.get_dataset()
        return YorckService.filter_movies(dataset.movies, params)

    async def get_movie(self, movie_id: str) -> YorckMovie:
        """Return a cached Yorck movie by ID, slug, or Vista ID."""
        dataset = await self.get_dataset()
        return YorckService.find_movie(dataset.movies, movie_id)

    async def search_shows(self, params: YorckShowSearchParams) -> list[YorckShow]:
        """Search cached Yorck shows."""
        dataset = await self.get_dataset()
        return YorckService.filter_shows(dataset.shows, params)

    async def get_show(self, show_id: str) -> YorckShow:
        """Return a cached Yorck show by session ID."""
        dataset = await self.get_dataset()
        return YorckService.find_show(dataset.shows, show_id)

    async def search_cities(self, params: YorckCitySearchParams) -> list[YorckCity]:
        """Search cached Yorck cities."""
        dataset = await self.get_dataset()
        return YorckService.filter_cities(dataset.cities, params)

    async def get_city(self, city_id: str) -> YorckCity:
        """Return a cached Yorck city by ID or name."""
        dataset = await self.get_dataset()
        return YorckService.find_city(dataset.cities, city_id)

    async def list_genres(self, params: YorckGenreSearchParams) -> list[YorckGenre]:
        """List cached Yorck genres."""
        dataset = await self.get_dataset()
        return YorckService.filter_genres(dataset.genres, params)

    def snapshot(self) -> dict:
        """Return a lightweight cache status snapshot."""
        return {
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "cinemas": len(self._dataset.cinemas),
            "movies": len(self._dataset.movies),
            "shows": len(self._dataset.shows),
            "cities": len(self._dataset.cities),
            "genres": len(self._dataset.genres),
        }
