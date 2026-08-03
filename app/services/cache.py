"""In-memory cache for Kinoheld data."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
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


_TRAILING_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _normalize_title(title: str) -> str:
    """Normalize a movie title for cross-record matching.

    Show-embedded movies carry version suffixes ("Die Odyssee (OmU)") that the
    catalog record ("Die Odyssee") lacks; strip trailing parentheticals.
    """
    normalized = title.strip()
    while True:
        stripped = _TRAILING_PARENS_RE.sub("", normalized)
        if stripped == normalized:
            break
        normalized = stripped
    return normalized.casefold()


def _titles_with_genres(movies: Iterable[Movie]) -> dict[str, list[Genre]]:
    """Index real (non-placeholder) genres by normalized title."""
    return {
        _normalize_title(movie.title): movie.genres
        for movie in movies
        if movie.title and movie.genres and any(g.name for g in movie.genres)
    }


def _enrich_show_genres(shows: Iterable[Show], genres_by_title: dict[str, list[Genre]]) -> None:
    """Backfill empty show-embedded genres from a title -> genres index.

    Kinoheld's show query returns placeholder genres ({"id": null, "name": ""})
    for the per-version movie records embedded in shows, while the catalog query
    has real genre data for the same films.
    """
    for show in shows:
        movie = show.movie
        if movie is None:
            continue
        genres = [g for g in (movie.genres or []) if g.name]
        if not genres and movie.title:
            genres = genres_by_title.get(_normalize_title(movie.title), [])
        movie.genres = list(genres)


def _intern_movies(
    show_groups: Iterable[list[Show]],
    canonical: dict[str, Movie] | None = None,
) -> int:
    """Collapse duplicate embedded movies onto one instance per movie ID.

    Kinoheld embeds a full movie record — description, cast, directors, genres — in
    every single show, so a film screened 26 times arrives as 26 identical ``Movie``
    objects. Those embedded records dominate the show cache, and sharing one instance
    per ID reclaims most of it without touching the read path.

    Sharing is safe because the only mutation applied to an embedded movie is genre
    backfill, which is a property of the film rather than of one screening; doing it
    once now serves every show of that film.

    Pass a shared ``canonical`` registry to collapse each response as it arrives, so
    the duplicates never pile up in the first place; collapsing only at the end still
    leaves every copy alive at once, and that peak is what the process keeps.

    Returns the number of duplicate instances dropped.
    """
    canonical = {} if canonical is None else canonical
    collapsed = 0
    for shows in show_groups:
        for show in shows:
            movie = show.movie
            if movie is None or not movie.id:
                continue
            existing = canonical.setdefault(movie.id, movie)
            if existing is not movie:
                show.movie = existing
                collapsed += 1
    return collapsed


def _titles_missing_genres(shows: Iterable[Show]) -> set[str]:
    """Return normalized titles of shows still left without any genre."""
    return {
        _normalize_title(show.movie.title)
        for show in shows
        if show.movie is not None and show.movie.title and not show.movie.genres
    }


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
        # Locations whose full live cinema list has been merged in since the last
        # refresh. The periodic refresh only fetches a globally capped slice, so a
        # location query can be served a partial list without this backfill.
        self._backfilled_locations: set[str] = set()
        # Normalized title -> genres, accumulated across refreshes. Show-embedded
        # movies carry placeholder genres, and the cached catalog is a capped slice,
        # so titles outside it are resolved live once and remembered here.
        self._genres_by_title: dict[str, list[Genre]] = {}
        # Titles a live lookup could not resolve; retried once per refresh cycle
        # rather than on every request.
        self._unresolved_titles: set[str] = set()

    # ------------------------------------------------------------------
    # Genre enrichment
    # ------------------------------------------------------------------
    def _genre_index(self) -> dict[str, list[Genre]]:
        """Title -> genres from the cached catalog, plus anything resolved since.

        Callers must hold ``self._lock``.
        """
        return _titles_with_genres(self._movies) | self._genres_by_title

    async def _apply_genres(self, service: KinoheldService, shows: list[Show]) -> None:
        """Fill in show-embedded genres, resolving unknown titles from the catalog.

        The cached catalog is a globally capped slice, so films playing outside it —
        typically arthouse and one-off event screenings — have no local record to match
        against. Look those up live, once per title, and remember the answer.
        """
        async with self._lock:
            index = self._genre_index()
        _enrich_show_genres(shows, index)

        async with self._lock:
            unknown = _titles_missing_genres(shows) - self._unresolved_titles
        if not unknown:
            return

        semaphore = asyncio.Semaphore(settings.kinoheld_sync_concurrency)

        async def resolve(title: str) -> tuple[str, list[Genre], bool]:
            """Return (title, genres, failed). A failed lookup is retried later."""
            async with semaphore:
                try:
                    matches = await service.search_movies(
                        MovieSearchParams(search=title, limit=5),
                    )
                except Exception:
                    logger.exception("Failed to resolve genres for %r", title)
                    return title, [], True
            return title, _titles_with_genres(matches).get(title) or [], False

        lookups = await asyncio.gather(
            *(resolve(t) for t in sorted(unknown)[: settings.kinoheld_genre_lookup_limit]),
        )
        resolved = {title: genres for title, genres, _ in lookups if genres}
        # Only titles the catalog genuinely has nothing for are remembered as
        # unresolved; a transient lookup failure must not poison the title.
        unresolved = {title for title, genres, failed in lookups if not genres and not failed}

        if not resolved and not unresolved:
            return
        async with self._lock:
            self._genres_by_title.update(resolved)
            self._unresolved_titles |= unresolved
            index = self._genre_index()
        _enrich_show_genres(shows, index)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    async def _priority_cinemas(
        self,
        service: KinoheldService,
    ) -> tuple[list[Cinema], set[str]]:
        """Fetch the full cinema list for each priority location, in order.

        The global refresh slice is not ordered by relevance, so without this the
        pre-warm budget lands on whichever cinemas the catalogue happens to list
        first — rarely the ones anybody is querying.

        Returns the cinemas and the locations that were fetched successfully; a
        location whose fetch failed must not be recorded as backfilled.
        """
        found: list[Cinema] = []
        seen: set[str] = set()
        fetched: set[str] = set()
        for location in settings.kinoheld_sync_priority_locations:
            try:
                cinemas = await service.search_cinemas(
                    CinemaSearchParams(location=location, limit=1000),
                )
            except Exception:
                logger.exception("Failed to fetch priority location %r", location)
                continue
            fetched.add(location.casefold())
            for cinema in cinemas:
                if cinema.id not in seen:
                    seen.add(cinema.id)
                    found.append(cinema)
        return found, fetched

    def _cinemas_to_prefetch(self, cinemas: list[Cinema]) -> list[str]:
        """Cinema IDs to pre-fetch shows for: explicit IDs, then the first N cinemas.

        ``cinemas`` must already be ordered with priority locations first. Relying on
        ``kinoheld_sync_cinema_ids`` alone means an unset list silently leaves the show
        cache empty, which is invisible until someone notices ``cached_shows`` at 0.
        """
        selected = list(settings.kinoheld_sync_cinema_ids)
        seen = set(selected)
        for cinema in cinemas[: settings.kinoheld_sync_cinema_count]:
            if cinema.id not in seen:
                seen.add(cinema.id)
                selected.append(cinema.id)
        return selected

    async def _prefetch_shows(
        self,
        service: KinoheldService,
        cinemas: list[Cinema],
    ) -> dict[str, list[Show]]:
        """Fetch shows for the pre-warm set concurrently, one entry per cinema/date."""
        cinema_ids = self._cinemas_to_prefetch(cinemas)
        if not cinema_ids:
            return {}

        dates = [
            (dt.date.today() + dt.timedelta(days=offset)).isoformat()
            for offset in range(settings.kinoheld_sync_show_days)
        ]
        shows = await self._fetch_shows(service, cinema_ids, dates)
        logger.info(
            "Pre-fetched shows for %d cinemas over %d days",
            len(cinema_ids),
            len(dates),
        )
        return shows

    async def _fetch_shows(
        self,
        service: KinoheldService,
        cinema_ids: Iterable[str],
        dates: Iterable[str],
    ) -> dict[str, list[Show]]:
        """Fetch every cinema/date combination concurrently.

        Serial fetching is the difference between a fast response and a timeout once a
        location resolves to dozens of cinemas.
        """
        semaphore = asyncio.Semaphore(settings.kinoheld_sync_concurrency)
        dates = list(dates)
        # Shared across the batch so each response's embedded movies collapse onto the
        # copies already seen. Deferring this to the end would hold every duplicate at
        # once, and that peak is what the process never gives back.
        canonical: dict[str, Movie] = {}

        async def fetch(cinema_id: str, date: str) -> tuple[str, list[Show] | None]:
            params = ShowSearchParams(cinema_id=cinema_id, date=dt.date.fromisoformat(date))
            async with semaphore:
                try:
                    shows = await service.search_shows(params)
                except Exception:
                    logger.exception("Failed to fetch shows for cinema %s on %s", cinema_id, date)
                    # Leave the entry absent rather than caching an empty day, so the
                    # date is retried instead of reading as "no shows" until refresh.
                    return f"{cinema_id}::{date}", None
            _intern_movies([shows], canonical)
            return f"{cinema_id}::{date}", shows

        results = await asyncio.gather(
            *(fetch(cinema_id, date) for cinema_id in cinema_ids for date in dates),
        )
        return {key: shows for key, shows in results if shows is not None}

    async def refresh(self, service: KinoheldService) -> None:
        """Fetch data from Kinoheld and rebuild the cache atomically."""
        logger.info("Starting Kinoheld cache refresh")

        catalogue = await service.search_cinemas(
            CinemaSearchParams(limit=settings.kinoheld_sync_cinema_limit),
        )
        # Priority locations lead the list so the pre-warm budget reaches them first,
        # and their cinemas are merged in even if the global slice omitted them.
        priority, priority_locations = await self._priority_cinemas(service)
        priority_ids = {cinema.id for cinema in priority}
        cinemas = priority + [c for c in catalogue if c.id not in priority_ids]

        movies = await service.search_movies(
            MovieSearchParams(limit=settings.kinoheld_sync_movie_limit),
        )
        cities = await service.search_cities(CitySearchParams(limit=100))
        genres = await service.list_genres()

        shows = await self._prefetch_shows(service, cinemas)

        async with self._lock:
            self._genres_by_title.update(_titles_with_genres(movies))
            # Give previously unresolvable titles another chance each cycle.
            self._unresolved_titles.clear()

        for day_shows in shows.values():
            await self._apply_genres(service, day_shows)

        async with self._lock:
            self._cinemas = cinemas
            # Priority locations were just fetched in full, so they need no backfill.
            self._backfilled_locations = set(priority_locations)
            self._movies = movies
            # Merge so on-demand entries cached via cache_shows_for_cinema survive
            # periodic refreshes (which only cover the configured sync cinemas).
            self._shows.update(shows)
            self._prune_stale_shows()
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
            async with self._lock:
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

    async def add_cinemas(self, cinemas: list[Cinema], location: str | None = None) -> None:
        """Merge new cinemas into the cache, avoiding duplicates by ID.

        Passing ``location`` records that this location's live list has been merged in,
        so subsequent queries for it are served from the cache alone.
        """
        async with self._lock:
            existing_ids = {c.id for c in self._cinemas}
            self._cinemas.extend([c for c in cinemas if c.id not in existing_ids])
            if location:
                self._backfilled_locations.add(location.casefold())

    async def is_location_backfilled(self, location: str) -> bool:
        """Return whether this location's full live cinema list is already cached."""
        async with self._lock:
            return location.casefold() in self._backfilled_locations

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
            async with self._lock:
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

    async def list_all_shows(self) -> list[Show]:
        """Return all cached shows across cinemas and dates."""
        async with self._lock:
            return [show for shows in self._shows.values() for show in shows]

    async def cache_shows_for_cinema(
        self,
        service: KinoheldService,
        cinema_id: str,
        dates: Iterable[str],
    ) -> None:
        """Fetch and cache shows for a cinema/date range on demand."""
        await self.cache_shows_for_cinemas(service, [cinema_id], dates)

    async def cache_shows_for_cinemas(
        self,
        service: KinoheldService,
        cinema_ids: Iterable[str],
        dates: Iterable[str],
    ) -> None:
        """Fetch and cache shows for several cinemas at once, concurrently."""
        cinema_ids = list(cinema_ids)
        if not cinema_ids:
            return
        fetched = await self._fetch_shows(service, cinema_ids, dates)

        # Enrich the whole batch in one pass. Per-day passes repeat the same titles
        # across cinemas and dates, multiplying the live lookups by the batch size.
        await self._apply_genres(service, [s for day in fetched.values() for s in day])

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

        if params.location:
            centre = next(
                (
                    c.coordinates
                    for c in cities
                    if _matches(c.name, params.location)
                    and c.coordinates
                    and c.coordinates.latitude is not None
                    and c.coordinates.longitude is not None
                ),
                None,
            )
            if centre is not None:
                max_distance = params.distance if params.distance is not None else 50
                results = [
                    c
                    for c in results
                    if c.coordinates
                    and c.coordinates.latitude is not None
                    and c.coordinates.longitude is not None
                    and _haversine_km(
                        centre.latitude,
                        centre.longitude,
                        c.coordinates.latitude,
                        c.coordinates.longitude,
                    )
                    <= max_distance
                ]
            else:
                results = [c for c in results if _matches(c.name, params.location)]

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

    async def genre_vocabulary(self, limit: int) -> list[str]:
        """Return the most-used genre tags, most common first.

        The catalogue carries hundreds of near-duplicate labels
        (``Komödie``/``Actionkomödie``/``Familienkomödie``), far too many to put in
        front of an LLM. Ranking by how many cached movies actually carry each tag
        keeps the list short enough to be cheap while still covering real queries.
        """
        if limit <= 0:
            return []
        async with self._lock:
            movies = list(self._movies)
            catalogue = [genre.name for genre in self._genres]

        counts: dict[str, int] = {}
        seen: dict[str, str] = {}
        for movie in movies:
            for genre in movie.genres:
                name = (genre.name or "").strip()
                if not name:
                    continue
                key = name.casefold()
                seen.setdefault(key, name)
                counts[key] = counts.get(key, 0) + 1

        # Catalogue tags nobody is currently screening still belong in the vocabulary,
        # just behind everything that has movies attached to it.
        for name in catalogue:
            cleaned = (name or "").strip()
            if cleaned:
                seen.setdefault(cleaned.casefold(), cleaned)

        ranked = sorted(seen, key=lambda key: (-counts.get(key, 0), key))
        return [seen[key] for key in ranked[:limit]]

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

    def _prune_stale_shows(self) -> None:
        """Drop cached show entries for past dates. Caller must hold the lock."""
        today = dt.date.today().isoformat()
        stale = [key for key in self._shows if key.split("::", 1)[-1] < today]
        for key in stale:
            del self._shows[key]

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
