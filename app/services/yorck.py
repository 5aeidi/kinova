"""High-level service for Yorck Kinogruppe source data."""

import asyncio
import datetime as dt
import logging
import re
from typing import Any

from app.core.config import settings
from app.core.exceptions import YorckNotFoundError
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
from app.services.yorck_client import YorckClient

logger = logging.getLogger(__name__)

_ADDRESS_TAIL_RE = re.compile(r"(\d{5})\s+([^\d,]+?)\s*$")


def _matches(value: str | None, query: str | None) -> bool:
    """Case-insensitive substring match; a missing query matches everything."""
    if query is None:
        return True
    if value is None:
        return False
    return query.casefold() in value.casefold()


def _fields(entry: Any) -> dict[str, Any]:
    """Return the Contentful ``fields`` dict of an entry, tolerating bad records."""
    if isinstance(entry, dict) and isinstance(entry.get("fields"), dict):
        return entry["fields"]
    return {}


def _entry_id(entry: Any) -> str | None:
    if isinstance(entry, dict):
        sys = entry.get("sys")
        if isinstance(sys, dict):
            value = sys.get("id")
            if value is not None:
                return str(value)
    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> dt.date | None:
    text = _as_str(value)
    if text is None:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _as_datetime(value: Any) -> dt.datetime | None:
    text = _as_str(value)
    if text is None:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [text for item in value if (text := _as_str(item))]
    text = _as_str(value)
    return [text] if text else []


def _split_people(value: Any) -> list[str]:
    text = _as_str(value)
    if text is None:
        return []
    return [part.strip() for part in re.split(r"[,;/|]", text) if part.strip()]


def _asset_url(value: Any, depth: int = 0) -> str | None:
    """Extract an image URL from a (possibly wrapped) Contentful asset."""
    if not isinstance(value, dict) or depth > 6:
        return None
    file_info = value.get("file")
    if isinstance(file_info, dict):
        url = _as_str(file_info.get("url"))
        if url is None:
            return None
        return f"https:{url}" if url.startswith("//") else url
    for key in ("fields", "image", "heroImage", "poster"):
        nested = value.get(key)
        if nested is not None:
            url = _asset_url(nested, depth + 1)
            if url:
                return url
    return None


def _rich_text(value: Any, depth: int = 0) -> str | None:
    """Flatten a Contentful rich-text document (or plain string) into text."""
    if isinstance(value, str):
        return _as_str(value)
    if not isinstance(value, dict) or depth > 10:
        return None
    parts: list[str] = []
    text = _as_str(value.get("value"))
    if text:
        parts.append(text)
    content = value.get("content")
    if isinstance(content, list):
        for node in content:
            nested = _rich_text(node, depth + 1)
            if nested:
                parts.append(nested)
    joined = " ".join(parts).strip()
    return joined or None


class YorckService:
    """Business logic layer for Yorck source-specific endpoints."""

    def __init__(self, client: YorckClient) -> None:
        self.client = client

    async def get_dataset(self) -> YorckDataset:
        """Fetch and normalize the full Yorck programme."""
        cinemas_page, films_page = await asyncio.gather(
            self.client.get_page_data("cinemas"),
            self.client.get_page_data("films"),
        )

        cinemas = self._normalize_cinemas(cinemas_page.get("cinemas"))

        films = [entry for entry in films_page.get("films") or [] if _fields(entry)]
        specials = [entry for entry in films_page.get("specials") or [] if _fields(entry)]
        coming_soon = [entry for entry in films_page.get("comingSoon") or [] if _fields(entry)]

        details = await self._fetch_film_details(
            [*films, *coming_soon] if settings.yorck_fetch_film_details else [],
        )

        movies: dict[str, YorckMovie] = {}
        shows: dict[str, YorckShow] = {}
        vista_to_cinema = {c.vista_id: c for c in cinemas if c.vista_id}
        name_to_cinema = {c.name.casefold(): c for c in cinemas}

        def add(entry: dict[str, Any], is_special: bool, is_presale: bool) -> None:
            movie = self._entry_to_movie(entry, details, is_special, is_presale)
            if movie is None:
                return
            movies.setdefault(movie.id, movie)
            for session in _fields(entry).get("sessions") or []:
                show = self._session_to_show(session, movie, vista_to_cinema, name_to_cinema)
                if show is not None:
                    shows.setdefault(show.id, show)

        for entry in films:
            add(entry, is_special=False, is_presale=False)
        for entry in coming_soon:
            add(entry, is_special=False, is_presale=True)
        for entry in specials:
            add(entry, is_special=True, is_presale=False)

        return YorckDataset(
            cinemas=cinemas,
            movies=list(movies.values()),
            shows=list(shows.values()),
            cities=self._derive_cities(cinemas),
            genres=self._derive_genres(movies.values()),
        )

    async def search_cinemas(self, params: YorckCinemaSearchParams) -> list[YorckCinema]:
        """Search cinemas from the Yorck programme."""
        dataset = await self.get_dataset()
        return self.filter_cinemas(dataset.cinemas, params)

    async def get_cinema(self, cinema_id: str) -> YorckCinema:
        """Fetch a Yorck cinema by slug or Vista ID."""
        dataset = await self.get_dataset()
        return self.find_cinema(dataset.cinemas, cinema_id)

    async def search_movies(self, params: YorckMovieSearchParams) -> list[YorckMovie]:
        """Search movies/specials from the Yorck programme."""
        dataset = await self.get_dataset()
        return self.filter_movies(dataset.movies, params)

    async def get_movie(self, movie_id: str) -> YorckMovie:
        """Fetch a Yorck movie/special by ID, slug, or Vista ID."""
        dataset = await self.get_dataset()
        return self.find_movie(dataset.movies, movie_id)

    async def search_shows(self, params: YorckShowSearchParams) -> list[YorckShow]:
        """Search shows from the Yorck programme."""
        dataset = await self.get_dataset()
        return self.filter_shows(dataset.shows, params)

    async def get_show(self, show_id: str) -> YorckShow:
        """Fetch a Yorck show by session ID."""
        dataset = await self.get_dataset()
        return self.find_show(dataset.shows, show_id)

    async def search_cities(self, params: YorckCitySearchParams) -> list[YorckCity]:
        """Search cities derived from Yorck cinema addresses."""
        dataset = await self.get_dataset()
        return self.filter_cities(dataset.cities, params)

    async def list_genres(self, params: YorckGenreSearchParams) -> list[YorckGenre]:
        """List genres/labels derived from the Yorck programme."""
        dataset = await self.get_dataset()
        return self.filter_genres(dataset.genres, params)

    # ------------------------------------------------------------------
    # Filters / lookups (shared with the cache)
    # ------------------------------------------------------------------
    @staticmethod
    def filter_cinemas(
        cinemas: list[YorckCinema],
        params: YorckCinemaSearchParams,
    ) -> list[YorckCinema]:
        """Filter normalized Yorck cinemas."""
        results = [
            cinema
            for cinema in cinemas
            if _matches(cinema.name, params.search)
            or _matches(cinema.city, params.search)
            or _matches(cinema.district, params.search)
            or _matches(cinema.address, params.search)
        ]
        return results[: params.limit]

    @staticmethod
    def find_cinema(cinemas: list[YorckCinema], cinema_id: str) -> YorckCinema:
        """Return a cinema by slug or Vista ID."""
        for cinema in cinemas:
            if cinema_id in (cinema.id, cinema.slug, cinema.vista_id):
                return cinema
        raise YorckNotFoundError(f"Yorck cinema {cinema_id} not found")

    @staticmethod
    def filter_movies(
        movies: list[YorckMovie],
        params: YorckMovieSearchParams,
    ) -> list[YorckMovie]:
        """Filter normalized Yorck movies."""
        results = [
            movie
            for movie in movies
            if _matches(movie.title, params.search)
            or _matches(movie.original_title, params.search)
            or any(_matches(genre, params.search) for genre in movie.genres)
        ]
        return results[: params.limit]

    @staticmethod
    def find_movie(movies: list[YorckMovie], movie_id: str) -> YorckMovie:
        """Return a movie by ID, slug, or Vista ID."""
        for movie in movies:
            if movie_id in (movie.id, movie.slug, movie.vista_id):
                return movie
        raise YorckNotFoundError(f"Yorck movie {movie_id} not found")

    @staticmethod
    def filter_shows(shows: list[YorckShow], params: YorckShowSearchParams) -> list[YorckShow]:
        """Filter normalized Yorck shows."""
        results = list(shows)
        if params.date is not None:
            days = params.days or settings.yorck_sync_show_days
            end_date = params.date + dt.timedelta(days=days - 1)
            results = [
                show
                for show in results
                if show.date is not None and params.date <= show.date <= end_date
            ]
        if params.movie_id:
            results = [show for show in results if show.movie_id == params.movie_id]
        if params.cinema_id:
            results = [
                show
                for show in results
                if params.cinema_id in (show.cinema_id, show.cinema_vista_id)
            ]
        if params.search:
            results = [
                show
                for show in results
                if _matches(show.movie_title, params.search)
                or _matches(show.cinema_name, params.search)
            ]
        return sorted(
            results,
            key=lambda show: show.begins_at or dt.datetime.max.replace(tzinfo=dt.timezone.utc),
        )[: params.limit]

    @staticmethod
    def find_show(shows: list[YorckShow], show_id: str) -> YorckShow:
        """Return a show by session ID."""
        for show in shows:
            if show.id == show_id:
                return show
        raise YorckNotFoundError(f"Yorck show {show_id} not found")

    @staticmethod
    def filter_cities(cities: list[YorckCity], params: YorckCitySearchParams) -> list[YorckCity]:
        """Filter normalized Yorck cities."""
        return [city for city in cities if _matches(city.name, params.search)][: params.limit]

    @staticmethod
    def find_city(cities: list[YorckCity], city_id: str) -> YorckCity:
        """Return a city by ID or name."""
        for city in cities:
            if city.id == city_id or city.name == city_id:
                return city
        raise YorckNotFoundError(f"Yorck city {city_id} not found")

    @staticmethod
    def filter_genres(genres: list[YorckGenre], params: YorckGenreSearchParams) -> list[YorckGenre]:
        """Filter normalized Yorck genres."""
        return [genre for genre in genres if _matches(genre.name, params.search)][: params.limit]

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------
    def _detail_url(self, kind: str, slug: str | None) -> str | None:
        if not slug:
            return None
        return f"{self.client.base_url}/{self.client.locale}/{kind}/{slug}"

    def _normalize_cinemas(self, entries: Any) -> list[YorckCinema]:
        cinemas: list[YorckCinema] = []
        for entry in entries or []:
            fields = _fields(entry)
            slug = _as_str(fields.get("slug"))
            name = _as_str(fields.get("name"))
            if slug is None or name is None:
                continue
            address = _as_str(fields.get("address"))
            post_code, city = None, None
            if address:
                match = _ADDRESS_TAIL_RE.search(address)
                if match:
                    post_code, city = match.group(1), match.group(2).strip()
            coordinates = fields.get("coordinates") or {}
            cinemas.append(
                YorckCinema(
                    id=slug,
                    slug=slug,
                    vistaId=_as_str(fields.get("vistaId")),
                    name=name,
                    shortName=_as_str(fields.get("shortName")),
                    address=address,
                    postCode=post_code,
                    city=city,
                    district=_as_str(fields.get("district")),
                    latitude=coordinates.get("lat") if isinstance(coordinates, dict) else None,
                    longitude=coordinates.get("lon") if isinstance(coordinates, dict) else None,
                    phone=_as_str(fields.get("telephone")),
                    email=_as_str(fields.get("mail")),
                    numberOfAuditoriums=_as_int(fields.get("numberOfAuditoriums")),
                    accessibility=_as_str(fields.get("accessibility")),
                    shortDescription=_as_str(fields.get("shortDescription")),
                    heroImageUrl=_asset_url(fields.get("heroImage")),
                    detailUrl=self._detail_url("cinemas", slug),
                ),
            )
        return cinemas

    async def _fetch_film_details(
        self,
        entries: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Fetch per-film detail pages, keyed by slug; failures are tolerated."""
        slugs = sorted({slug for entry in entries if (slug := _as_str(_fields(entry).get("slug")))})
        if not slugs:
            return {}
        semaphore = asyncio.Semaphore(settings.yorck_detail_concurrency)

        async def fetch(slug: str) -> tuple[str, dict[str, Any] | None]:
            async with semaphore:
                try:
                    page = await self.client.get_page_data(f"films/{slug}")
                except Exception:
                    logger.warning("Failed to fetch Yorck film detail for %r", slug)
                    return slug, None
            return slug, _fields(page.get("film")) or None

        results = await asyncio.gather(*(fetch(slug) for slug in slugs))
        return {slug: fields for slug, fields in results if fields}

    def _entry_to_movie(
        self,
        entry: dict[str, Any],
        details: dict[str, dict[str, Any]],
        is_special: bool,
        is_presale: bool,
    ) -> YorckMovie | None:
        fields = _fields(entry)
        slug = _as_str(fields.get("slug"))
        title = _as_str(fields.get("title"))
        if title is None:
            return None
        # Programme-list entries are shallow; the film detail page adds credits,
        # descriptions, trailers, and TMDB IDs. Detail fields win where present.
        merged = {**fields, **(details.get(slug or "") or {})}
        vista_id = _as_str(merged.get("vistaId"))
        resource_id = (f"special-{slug}" if is_special else vista_id or slug) or title.casefold()

        genres = _as_string_list(merged.get("mainLabel"))
        genres.extend(_as_string_list(merged.get("additionalLabels")))
        genres.extend(_as_string_list(merged.get("category")))
        trailer_id = _as_str(merged.get("trailer1YouTubeId"))
        yorck_pick = merged.get("yorckPick")
        return YorckMovie(
            id=resource_id,
            slug=slug,
            vistaId=vista_id,
            title=title,
            originalTitle=_as_str(merged.get("originalTitle")),
            originalLanguage=_as_str(merged.get("originalLanguage")),
            tagline=_as_str(merged.get("tagline") or merged.get("specialSubline")),
            description=_rich_text(merged.get("about") or merged.get("aboutText")),
            runtime=_as_int(merged.get("runtime")),
            genres=list(dict.fromkeys(genres)),
            fsk=_as_int(merged.get("fsk")),
            descriptors=_as_string_list(merged.get("descriptors")),
            releaseDate=_as_date(merged.get("releaseDate")),
            year=_as_int(merged.get("year")),
            directors=_split_people(merged.get("director")),
            actors=_split_people(merged.get("cast")),
            writers=_split_people(merged.get("writer")),
            countries=_as_string_list(merged.get("countries")),
            distributor=_as_str(merged.get("distributor")),
            tmdbId=_as_int(merged.get("tmdbId")),
            trailerUrl=f"https://www.youtube.com/watch?v={trailer_id}" if trailer_id else None,
            posterUrl=_asset_url(merged.get("poster")),
            heroImageUrl=_asset_url(merged.get("heroImage") or merged.get("specialImage")),
            detailUrl=self._detail_url("specials" if is_special else "films", slug),
            isSpecial=is_special,
            isPresale=is_presale,
            yorckPick=yorck_pick if isinstance(yorck_pick, bool) else None,
        )

    def _session_to_show(
        self,
        session: Any,
        movie: YorckMovie,
        vista_to_cinema: dict[str, YorckCinema],
        name_to_cinema: dict[str, YorckCinema],
    ) -> YorckShow | None:
        fields = _fields(session)
        session_id = _entry_id(session)
        begins_at = _as_datetime(fields.get("startTime"))
        if session_id is None and begins_at is None:
            return None

        # Session IDs are "<cinema vistaId>-<session number>".
        cinema_vista_id = session_id.split("-", 1)[0] if session_id and "-" in session_id else None
        session_cinema = _fields(fields.get("cinema"))
        cinema_name = _as_str(session_cinema.get("name"))
        cinema = vista_to_cinema.get(cinema_vista_id or "") or name_to_cinema.get(
            (cinema_name or "").casefold(),
        )

        formats = _as_string_list(fields.get("formats"))
        return YorckShow(
            id=session_id or f"{movie.id}:{begins_at.isoformat()}",
            movieId=movie.id,
            movieTitle=movie.title,
            cinemaId=cinema.id if cinema else None,
            cinemaVistaId=cinema_vista_id or (cinema.vista_id if cinema else None),
            cinemaName=(cinema.name if cinema else None) or cinema_name,
            city=cinema.city if cinema else None,
            beginsAt=begins_at,
            date=begins_at.date() if begins_at else None,
            formats=formats,
            flags=formats,
            accessibility=_as_str(session_cinema.get("accessibility"))
            or (cinema.accessibility if cinema else None),
            runtime=movie.runtime,
            bookingUrl=movie.detail_url,
        )

    @staticmethod
    def _derive_cities(cinemas: list[YorckCinema]) -> list[YorckCity]:
        cities: dict[str, YorckCity] = {}
        for cinema in cinemas:
            if not cinema.city:
                continue
            city_id = cinema.city.casefold().replace(" ", "-")
            city = cities.setdefault(city_id, YorckCity(id=city_id, name=cinema.city))
            if cinema.id not in city.cinema_ids:
                city.cinema_ids.append(cinema.id)
        for city in cities.values():
            city.cinema_ids.sort()
        return list(cities.values())

    @staticmethod
    def _derive_genres(movies: Any) -> list[YorckGenre]:
        genres: dict[str, YorckGenre] = {}
        for movie in movies:
            for name in movie.genres:
                genre_id = name.casefold().replace(" ", "-")
                genres[genre_id] = YorckGenre(id=genre_id, name=name)
        return sorted(genres.values(), key=lambda genre: genre.name.casefold())
