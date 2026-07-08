"""In-memory cache for Kinoheld data."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Iterable
from typing import Any

from app.core.config import settings
from app.core.exceptions import KinoheldNotFoundError
from app.schemas.cinema import Cinema, CinemaSearchParams
from app.schemas.city import City, CitySearchParams
from app.schemas.movie import Genre, Movie, MovieSearchParams
from app.schemas.show import Show, ShowSearchParams
from app.services.kinoheld import KinoheldService

logger = logging.getLogger(__name__)


def _matches(value: str | None, query: str | None) -> bool:
    """Case-insensitive substring match; a missing query matches everything."""
    if query is None:
        return True
    if value is None:
        return False
    return query.casefold() in value.casefold()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance between two lat/lon points in kilometres."""
    import math

    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


class KinoheldCache:
    """Atomic in-memory cache with query helpers for internal endpoints."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cinemas: list[Cinema] = []
        self._movies: list[Movie] = []
        self._shows: dict[str, list[Show]] = {}  # key: "cinemaId::date"
        self._cities: list[City] = []
        self._genres: list[Genre] = []
        self._last_refresh: dt.datetime | None = None

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    async def refresh(self, service: KinoheldService) -> None:
        """Fetch data from Kinoheld and rebuild the cache atomically."""
        logger.info("Starting Kinoheld cache refresh")

        cinemas = await service.search_cinemas(
            CinemaSearchParams(limit=settings.kinoheld_sync_cinema_limit),
        )
        movies = await service.search_movies(
            MovieSearchParams(limit=settings.kinoheld_sync_movie_limit),
        )
        cities = await service.search_cities(CitySearchParams(limit=100))
        genres = await service.list_genres()

        shows: dict[str, list[Show]] = {}
        for cinema_id in settings.kinoheld_sync_cinema_ids:
            for day_offset in range(settings.kinoheld_sync_show_days):
                date = (dt.date.today() + dt.timedelta(days=day_offset)).isoformat()
                params = ShowSearchParams(cinema_id=cinema_id, date=dt.date.fromisoformat(date))
                try:
                    day_shows = await service.search_shows(params)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Failed to fetch shows for cinema %s on %s", cinema_id, date)
                    day_shows = []
                shows[f"{cinema_id}::{date}"] = day_shows

        async with self._lock:
            self._cinemas = cinemas
            self._movies = movies
            self._shows = shows
            self._cities = cities
            self._genres = genres
            self._last_refresh = dt.datetime.now(tz=dt.timezone.utc)

        logger.info(
            "Cache refresh complete: %d cinemas, %d movies, %d show-day entries, "
            "%d cities, %d genres",
            len(cinemas),
            len(movies),
            len(shows),
            len(cities),
            len(genres),
        )

    # ------------------------------------------------------------------
    # Cinemas
    # ------------------------------------------------------------------
    async def search_cinemas(self, params: CinemaSearchParams) -> list[Cinema]:
        async with self._lock:
            cinemas = list(self._cinemas)

        query = params.search
        location = params.location
        distance = params.distance
        limit = params.limit

        if location:
            # Match Kinoheld's default 50 km radius when no explicit distance is given.
            if distance is None:
                distance = 50
            cinemas = self._filter_by_location(cinemas, location, distance)

        results = [
            cinema
            for cinema in cinemas
            if _matches(cinema.name, query)
            or _matches(cinema.city.name if cinema.city else None, query)
            or _matches(cinema.street, query)
        ]

        if params.only_bookable is not None:
            # The cache does not store bookability state; ignore this filter.
            pass
        if params.is_open_air is not None:
            results = [c for c in results if c.is_open_air_cinema is params.is_open_air]
        if params.is_drive_in is not None:
            results = [c for c in results if c.is_drive_in_cinema is params.is_drive_in]

        return results[:limit]

    async def get_cinema(self, cinema_id: str) -> Cinema:
        async with self._lock:
            for cinema in self._cinemas:
                if cinema.id == cinema_id:
                    return cinema
        raise KinoheldNotFoundError(f"Cinema {cinema_id} not found")

    async def add_cinemas(self, cinemas: list[Cinema]) -> None:
        """Merge new cinemas into the cache, avoiding duplicates by ID."""
        async with self._lock:
            existing_ids = {c.id for c in self._cinemas}
            self._cinemas.extend([c for c in cinemas if c.id not in existing_ids])

    # ------------------------------------------------------------------
    # Movies
    # ------------------------------------------------------------------
    async def search_movies(self, params: MovieSearchParams) -> list[Movie]:
        async with self._lock:
            movies = list(self._movies)

        query = params.search
        location = params.location
        distance = params.distance
        limit = params.limit

        if location and distance is not None:
            # We do not have cinema-to-movie linkage in the cache, so we approximate by
            # filtering cinemas around the location and then retaining movies that have at
            # least one cached show in those cinemas. If no shows are cached, this falls
            # back to returning an empty list for location+distance queries.
            async with self._lock:
                nearby_cinemas = self._filter_by_location(list(self._cinemas), location, distance)
            nearby_ids = {c.id for c in nearby_cinemas}
            movies = self._filter_movies_by_cinemas(movies, nearby_ids)
        elif location:
            # Same approximation, but match cinemas whose city name contains the location.
            async with self._lock:
                matching_cinemas = [
                    cinema
                    for cinema in self._cinemas
                    if _matches(cinema.city.name if cinema.city else None, location)
                ]
            matching_ids = {c.id for c in matching_cinemas}
            movies = self._filter_movies_by_cinemas(movies, matching_ids)

        if query:
            movies = [m for m in movies if _matches(m.title, query)]

        if params.playing is not None:
            # The cache stores a generic set of movies; we cannot reliably determine playing
            # status without show data. As a pragmatic fallback we keep movies that have at
            # least one cached future show when playing is NOW/FUTURE.
            movies = self._filter_movies_by_playing(movies, params.playing)

        return movies[:limit]

    async def get_movie(self, movie_id: str) -> Movie:
        async with self._lock:
            for movie in self._movies:
                if movie.id == movie_id:
                    return movie
        raise KinoheldNotFoundError(f"Movie {movie_id} not found")

    # ------------------------------------------------------------------
    # Shows
    # ------------------------------------------------------------------
    async def search_shows(self, params: ShowSearchParams) -> list[Show]:
        cinema_id = params.cinema_id
        base_date = params.date or dt.date.today()
        days = params.days or 1

        shows: list[Show] = []
        for offset in range(days):
            date = base_date + dt.timedelta(days=offset)
            key = f"{cinema_id}::{date.isoformat()}"
            async with self._lock:
                shows.extend(list(self._shows.get(key, [])))

        if params.movie_id:
            shows = [s for s in shows if s.movie is not None and s.movie.id == params.movie_id]

        return shows

    async def get_show(self, show_id: str) -> Show:
        async with self._lock:
            for shows in self._shows.values():
                for show in shows:
                    if show.id == show_id:
                        return show
        raise KinoheldNotFoundError(f"Show {show_id} not found")

    async def cache_shows_for_cinema(
        self,
        service: KinoheldService,
        cinema_id: str,
        dates: Iterable[str],
    ) -> None:
        """Fetch and cache shows for a cinema/date range on demand."""
        fetched: dict[str, list[Show]] = {}
        for date_str in dates:
            params = ShowSearchParams(cinema_id=cinema_id, date=dt.date.fromisoformat(date_str))
            fetched[f"{cinema_id}::{date_str}"] = await service.search_shows(params)

        async with self._lock:
            self._shows.update(fetched)

    async def has_any_shows(self, cinema_id: str) -> bool:
        """Return True if any shows are cached for ``cinema_id``."""
        async with self._lock:
            return any(key.startswith(f"{cinema_id}::") for key in self._shows)

    async def get_missing_show_dates(
        self,
        cinema_id: str,
        dates: Iterable[str],
    ) -> list[str]:
        """Return the subset of ``dates`` that is not yet cached for ``cinema_id``."""
        async with self._lock:
            return [date_str for date_str in dates if f"{cinema_id}::{date_str}" not in self._shows]

    # ------------------------------------------------------------------
    # Cities
    # ------------------------------------------------------------------
    async def search_cities(self, params: CitySearchParams) -> list[City]:
        async with self._lock:
            cities = list(self._cities)

        results = [c for c in cities if _matches(c.name, params.search)]
        return results[: params.limit]

    async def get_city(self, city_id: str) -> City:
        async with self._lock:
            for city in self._cities:
                if city.id == city_id or city.name == city_id or city.url_slug == city_id:
                    return city
        raise KinoheldNotFoundError(f"City {city_id} not found")

    # ------------------------------------------------------------------
    # Genres
    # ------------------------------------------------------------------
    async def list_genres(self) -> list[Genre]:
        async with self._lock:
            return list(self._genres)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _filter_by_location(
        self,
        cinemas: list[Cinema],
        location_name: str,
        max_distance: int,
    ) -> list[Cinema]:
        centre = None
        for city in self._cities:
            if _matches(city.name, location_name):
                centre = city.coordinates
                break

        if centre is None or centre.latitude is None or centre.longitude is None:
            # Fallback: try to find a cinema in/near the named location and use its coords.
            for cinema in cinemas:
                if _matches(cinema.city.name if cinema.city else None, location_name):
                    if cinema.coordinates and cinema.coordinates.latitude is not None:
                        centre = cinema.coordinates
                        break

        if centre is None or centre.latitude is None or centre.longitude is None:
            # No coordinate centre available; fall back to a city-name substring match.
            return [
                cinema
                for cinema in cinemas
                if _matches(cinema.city.name if cinema.city else None, location_name)
            ]

        return [
            cinema
            for cinema in cinemas
            if cinema.coordinates
            and cinema.coordinates.latitude is not None
            and cinema.coordinates.longitude is not None
            and _haversine_km(
                centre.latitude,
                centre.longitude,
                cinema.coordinates.latitude,
                cinema.coordinates.longitude,
            )
            <= max_distance
        ]

    def _filter_movies_by_cinemas(self, movies: list[Movie], cinema_ids: set[str]) -> list[Movie]:
        movie_ids: set[str] = set()
        for key, shows in self._shows.items():
            key_cinema_id = key.split("::", 1)[0]
            if key_cinema_id in cinema_ids:
                for show in shows:
                    if show.movie:
                        movie_ids.add(show.movie.id)
        return [m for m in movies if m.id in movie_ids]

    def _filter_movies_by_playing(self, movies: list[Movie], playing: str) -> list[Movie]:
        playing_upper = playing.upper()
        if playing_upper not in {"NOW", "FUTURE", "UPCOMING"}:
            return movies

        now = dt.datetime.now(tz=dt.timezone.utc)
        movie_ids_with_future_shows: set[str] = set()
        for shows in self._shows.values():
            for show in shows:
                ts = show.beginning.timestamp if show.beginning else None
                if ts is not None:
                    show_time = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
                    if show_time >= now:
                        if show.movie:
                            movie_ids_with_future_shows.add(show.movie.id)

        if playing_upper in {"NOW", "FUTURE"}:
            return [m for m in movies if m.id in movie_ids_with_future_shows]

        # UPCOMING: movies not yet having any cached show.
        return [m for m in movies if m.id not in movie_ids_with_future_shows]

    def snapshot(self) -> dict[str, Any]:
        """Return a debug snapshot of current cache contents."""
        return {
            "cinemas": len(self._cinemas),
            "movies": len(self._movies),
            "shows": {k: len(v) for k, v in self._shows.items()},
            "cities": len(self._cities),
            "genres": len(self._genres),
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
        }
