"""High-level service for Cinetixx source data."""

import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from app.core.config import settings
from app.core.exceptions import CinetixxAPIError, CinetixxNotFoundError
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
    CinetixxPrice,
    CinetixxShow,
    CinetixxShowInfo,
    CinetixxShowInfoParams,
    CinetixxShowSearchParams,
)
from app.services.cinetixx_client import CinetixxClient


def _matches(value: str | None, query: str | None) -> bool:
    """Case-insensitive substring match; a missing query matches everything."""
    if query is None:
        return True
    if value is None:
        return False
    return query.casefold() in value.casefold()


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


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "ja"}:
            return True
        if normalized in {"false", "0", "no", "nein"}:
            return False
    return None


def _as_datetime(value: Any) -> dt.datetime | None:
    text = _as_str(value)
    if text is None:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _split_people(value: Any) -> list[str]:
    text = _as_str(value)
    if text is None:
        return []
    return [part.strip() for part in re.split(r"[,;/|]", text) if part.strip()]


class CinetixxService:
    """Business logic layer for Cinetixx source-specific endpoints."""

    def __init__(self, client: CinetixxClient) -> None:
        self.client = client

    async def get_show_info(self, params: CinetixxShowInfoParams) -> CinetixxShowInfo:
        """Fetch and parse legacy Cinetixx showtime data."""
        body, content_type = await self.client.get_show_info(params.mandator_id)
        return CinetixxShowInfo(
            mandatorId=params.mandator_id,
            contentType=content_type,
            data=self._parse_body(body, content_type),
        )

    async def get_show_info_by_mandator(self, mandator_id: int) -> CinetixxShowInfo:
        """Fetch and parse legacy Cinetixx showtime data by mandator ID."""
        return await self.get_show_info(CinetixxShowInfoParams(mandator_id=mandator_id))

    async def get_dataset(self, mandator_id: int | None = None) -> CinetixxDataset:
        """Fetch and normalize Cinetixx program data for one or more mandators."""
        datasets: list[CinetixxDataset] = []
        for resolved_id in self._resolve_mandator_ids(mandator_id):
            show_info = await self.get_show_info(CinetixxShowInfoParams(mandator_id=resolved_id))
            datasets.append(self.normalize_show_info(show_info))
        return self.merge_datasets(datasets)

    async def search_cinemas(self, params: CinetixxCinemaSearchParams) -> list[CinetixxCinema]:
        """Search cinemas derived from Cinetixx program data."""
        dataset = await self.get_dataset(params.mandator_id)
        return self.filter_cinemas(dataset.cinemas, params)

    async def get_cinema(
        self,
        cinema_id: str,
        mandator_id: int | None = None,
    ) -> CinetixxCinema:
        """Fetch a derived Cinetixx cinema by ID."""
        cinemas = await self.search_cinemas(CinetixxCinemaSearchParams(mandator_id=mandator_id))
        for cinema in cinemas:
            if cinema.id == cinema_id or cinema.cinema_id == cinema_id:
                return cinema
        raise CinetixxNotFoundError(f"Cinetixx cinema {cinema_id} not found")

    async def search_movies(self, params: CinetixxMovieSearchParams) -> list[CinetixxMovie]:
        """Search movies/events derived from Cinetixx program data."""
        dataset = await self.get_dataset(params.mandator_id)
        return self.filter_movies(dataset.movies, params)

    async def get_movie(self, movie_id: str, mandator_id: int | None = None) -> CinetixxMovie:
        """Fetch a derived Cinetixx movie/event by ID."""
        movies = await self.search_movies(CinetixxMovieSearchParams(mandator_id=mandator_id))
        for movie in movies:
            if movie.id == movie_id or movie.movie_id == movie_id or movie.event_id == movie_id:
                return movie
        raise CinetixxNotFoundError(f"Cinetixx movie {movie_id} not found")

    async def search_shows(self, params: CinetixxShowSearchParams) -> list[CinetixxShow]:
        """Search shows derived from Cinetixx program data."""
        dataset = await self.get_dataset(params.mandator_id)
        return self.filter_shows(dataset.shows, params)

    async def get_show(self, show_id: str, mandator_id: int | None = None) -> CinetixxShow:
        """Fetch a derived Cinetixx show by ID."""
        shows = await self.search_shows(CinetixxShowSearchParams(mandator_id=mandator_id))
        for show in shows:
            if show.id == show_id or show.show_id == show_id:
                return show
        raise CinetixxNotFoundError(f"Cinetixx show {show_id} not found")

    async def search_cities(self, params: CinetixxCitySearchParams) -> list[CinetixxCity]:
        """Search cities derived from Cinetixx program data."""
        dataset = await self.get_dataset(params.mandator_id)
        return self.filter_cities(dataset.cities, params)

    async def list_genres(self, params: CinetixxGenreSearchParams) -> list[CinetixxGenre]:
        """List genres/categories derived from Cinetixx program data."""
        dataset = await self.get_dataset(params.mandator_id)
        return self.filter_genres(dataset.genres, params)

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------
    def normalize_show_info(self, show_info: CinetixxShowInfo) -> CinetixxDataset:
        """Normalize a Cinetixx show-info payload into searchable resources."""
        rows = self._extract_show_rows(show_info.data)
        shows = [self._row_to_show(row, show_info.mandator_id) for row in rows]
        return CinetixxDataset(
            cinemas=self._derive_cinemas(shows),
            movies=self._derive_movies(rows, shows),
            shows=shows,
            cities=self._derive_cities(shows),
            genres=self._derive_genres(rows),
        )

    @classmethod
    def merge_datasets(cls, datasets: list[CinetixxDataset]) -> CinetixxDataset:
        """Merge multiple normalized datasets, de-duplicating by resource ID."""
        cinemas: dict[str, CinetixxCinema] = {}
        movies: dict[str, CinetixxMovie] = {}
        shows: dict[str, CinetixxShow] = {}
        cities: dict[str, CinetixxCity] = {}
        genres: dict[str, CinetixxGenre] = {}

        for dataset in datasets:
            cinemas.update({item.id: item for item in dataset.cinemas})
            movies.update({item.id: item for item in dataset.movies})
            shows.update({item.id: item for item in dataset.shows})
            genres.update({item.id: item for item in dataset.genres})
            for city in dataset.cities:
                existing = cities.get(city.id)
                if existing is None:
                    cities[city.id] = city
                else:
                    existing_ids = set(existing.mandator_ids)
                    existing.mandator_ids = sorted(existing_ids | set(city.mandator_ids))

        return CinetixxDataset(
            cinemas=list(cinemas.values()),
            movies=list(movies.values()),
            shows=list(shows.values()),
            cities=list(cities.values()),
            genres=sorted(genres.values(), key=lambda item: item.name.casefold()),
        )

    @staticmethod
    def filter_cinemas(
        cinemas: list[CinetixxCinema],
        params: CinetixxCinemaSearchParams,
    ) -> list[CinetixxCinema]:
        """Filter normalized Cinetixx cinemas."""
        results = [
            cinema
            for cinema in cinemas
            if _matches(cinema.name, params.search)
            or _matches(cinema.city, params.search)
            or _matches(cinema.region, params.search)
        ]
        return results[: params.limit]

    @staticmethod
    def filter_movies(
        movies: list[CinetixxMovie],
        params: CinetixxMovieSearchParams,
    ) -> list[CinetixxMovie]:
        """Filter normalized Cinetixx movies."""
        results = [
            movie
            for movie in movies
            if _matches(movie.title, params.search)
            or _matches(movie.short_title, params.search)
            or any(_matches(genre, params.search) for genre in movie.genres)
        ]
        return results[: params.limit]

    @staticmethod
    def filter_shows(
        shows: list[CinetixxShow],
        params: CinetixxShowSearchParams,
    ) -> list[CinetixxShow]:
        """Filter normalized Cinetixx shows."""
        results = list(shows)
        if params.date is not None:
            days = params.days or settings.cinetixx_sync_show_days
            end_date = params.date + dt.timedelta(days=days - 1)
            results = [
                show
                for show in results
                if show.date is not None and params.date <= show.date <= end_date
            ]
        if params.movie_id:
            results = [
                show
                for show in results
                if show.movie_id == params.movie_id or show.event_id == params.movie_id
            ]
        if params.cinema_id:
            results = [show for show in results if show.cinema_id == params.cinema_id]
        if params.search:
            results = [
                show
                for show in results
                if _matches(show.movie_title, params.search)
                or _matches(show.text, params.search)
                or _matches(show.cinema_name, params.search)
            ]
        return sorted(
            results,
            key=lambda show: show.begins_at or dt.datetime.max.replace(tzinfo=dt.timezone.utc),
        )[: params.limit]

    @staticmethod
    def filter_cities(
        cities: list[CinetixxCity],
        params: CinetixxCitySearchParams,
    ) -> list[CinetixxCity]:
        """Filter normalized Cinetixx cities."""
        return [city for city in cities if _matches(city.name, params.search)][: params.limit]

    @staticmethod
    def filter_genres(
        genres: list[CinetixxGenre],
        params: CinetixxGenreSearchParams,
    ) -> list[CinetixxGenre]:
        """Filter normalized Cinetixx genres."""
        return [genre for genre in genres if _matches(genre.name, params.search)][: params.limit]

    def _resolve_mandator_ids(self, mandator_id: int | None) -> list[int]:
        if mandator_id is not None:
            return [mandator_id]
        return list(settings.cinetixx_sync_mandator_ids)

    @classmethod
    def _extract_show_rows(cls, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, dict):
            root = data.get("string") if set(data.keys()) == {"string"} else data
            if root is not data:
                return cls._extract_show_rows(root)
            if cls._looks_like_show_row(data):
                return [data]
            rows: list[dict[str, Any]] = []
            for value in data.values():
                rows.extend(cls._extract_show_rows(value))
            return rows
        if isinstance(data, list):
            if all(isinstance(item, dict) for item in data) and any(
                cls._looks_like_show_row(item) for item in data
            ):
                return [item for item in data if isinstance(item, dict)]
            rows = []
            for item in data:
                rows.extend(cls._extract_show_rows(item))
            return rows
        return []

    @staticmethod
    def _looks_like_show_row(row: dict[str, Any]) -> bool:
        show_keys = {
            "showId",
            "show_id",
            "showBeginning",
            "bookingLink",
            "movieId",
            "eventId",
            "veranstaltungstitel",
            "kino",
            "cinemaId",
            "saal",
        }
        return any(key in row for key in show_keys)

    @classmethod
    def _row_to_show(cls, row: dict[str, Any], fallback_mandator_id: int) -> CinetixxShow:
        mandator_id = _as_int(row.get("mandatorId")) or fallback_mandator_id
        show_id = _as_str(row.get("showId") or row.get("id"))
        movie_id = _as_str(row.get("movieId"))
        event_id = _as_str(row.get("eventId"))
        begins_at = _as_datetime(row.get("showBeginning") or row.get("startday"))
        flags = cls._extract_flags(row)
        prices = [
            CinetixxPrice(
                amount=price.get("amount") if isinstance(price, dict) else None,
                category=_as_str(price.get("categorie") or price.get("category"))
                if isinstance(price, dict)
                else None,
                area=_as_str(price.get("area")) if isinstance(price, dict) else None,
                isDefault=_as_bool(price.get("default")) if isinstance(price, dict) else None,
            )
            for price in row.get("prices", [])
            if isinstance(price, dict)
        ]
        return CinetixxShow(
            id=show_id or f"{mandator_id}:{movie_id or event_id or len(str(row))}",
            mandatorId=mandator_id,
            showId=show_id,
            movieId=movie_id,
            eventId=event_id,
            movieTitle=_as_str(row.get("veranstaltungstitel") or row.get("title")),
            text=_as_str(row.get("text")),
            beginsAt=begins_at,
            date=begins_at.date() if begins_at else None,
            bookingUrl=_as_str(row.get("bookingLink")),
            cinemaId=_as_str(row.get("cinemaId")),
            cinemaName=_as_str(row.get("kino")),
            cityId=_as_str(row.get("cityId")),
            city=_as_str(row.get("stadt")),
            auditoriumId=_as_str(row.get("auditoriumId")),
            auditoriumName=_as_str(row.get("saal")),
            language=_as_str(row.get("language") or row.get("sprachversion")),
            version=_as_str(row.get("versiontype")),
            audioType=_as_str(row.get("audiotype")),
            ageRating=_as_str(row.get("altersfreigabe")),
            duration=_as_int(row.get("spieldauerEvent")),
            is3d=_as_bool(row.get("flag3D")),
            hasSeatSelection=_as_bool(row.get("seatselection")),
            salesStart=_as_datetime(row.get("verkaufsstart")),
            salesEnd=_as_datetime(row.get("verkaufsende")),
            reservationStart=_as_datetime(row.get("reservierungsstart")),
            reservationEnd=_as_datetime(row.get("reservierungsende")),
            flags=flags,
            prices=prices,
            raw=row,
        )

    @staticmethod
    def _extract_flags(row: dict[str, Any]) -> list[str]:
        flags: list[str] = []
        if _as_bool(row.get("flag3D")):
            flags.append("3D")
        for key in ("sprachversion", "versiontype", "language", "audiotype", "aspectratio"):
            value = _as_str(row.get(key))
            if value and value not in flags:
                flags.append(value)
        type_value = row.get("type")
        if isinstance(type_value, dict):
            value = _as_str(type_value.get("value") or type_value.get("key"))
            if value and value not in flags:
                flags.append(value)
        return flags

    @classmethod
    def _derive_cinemas(cls, shows: list[CinetixxShow]) -> list[CinetixxCinema]:
        cinemas: dict[str, CinetixxCinema] = {}
        for show in shows:
            cinema_id = show.cinema_id or str(show.mandator_id)
            cinemas[cinema_id] = CinetixxCinema(
                id=cinema_id,
                mandatorId=show.mandator_id,
                cinemaId=show.cinema_id,
                name=show.cinema_name or f"Cinetixx mandator {show.mandator_id}",
                cityId=show.city_id,
                city=show.city,
            )
        return list(cinemas.values())

    @classmethod
    def _derive_movies(
        cls,
        rows: list[dict[str, Any]],
        shows: list[CinetixxShow],
    ) -> list[CinetixxMovie]:
        movies: dict[str, CinetixxMovie] = {}
        rows_by_show = {show.id: row for show, row in zip(shows, rows, strict=False)}
        for show in shows:
            row = rows_by_show.get(show.id, show.raw)
            movie_id = show.movie_id
            event_id = show.event_id
            title = show.movie_title or show.text or "Untitled Cinetixx event"
            resource_id = movie_id or event_id or title.casefold()
            genres = cls._genre_values(row)
            categories = [value for value in row.get("categories", []) if isinstance(value, str)]
            movies[resource_id] = CinetixxMovie(
                id=resource_id,
                movieId=movie_id,
                eventId=event_id,
                title=title,
                shortTitle=_as_str(row.get("veranstaltungskurztitel")),
                description=_as_str(row.get("text")),
                shortDescription=_as_str(row.get("textShort")),
                duration=show.duration,
                genres=genres,
                categories=categories,
                actors=_split_people(row.get("actor")),
                directors=_split_people(row.get("director")),
                screenWriters=_split_people(row.get("screenWriter")),
                year=_as_str(row.get("year")),
                country=_as_str(row.get("country")),
                artwork=_as_str(row.get("artwork") or row.get("image1")),
                artworkBig=_as_str(row.get("artworkBig")),
                trailerUrl=_as_str(row.get("eventTrailer")),
                movieUrl=_as_str(row.get("movieLink")),
            )
        return list(movies.values())

    @staticmethod
    def _derive_cities(shows: list[CinetixxShow]) -> list[CinetixxCity]:
        cities: dict[str, CinetixxCity] = {}
        for show in shows:
            if not show.city:
                continue
            city_id = show.city_id or show.city.casefold()
            city = cities.setdefault(
                city_id,
                CinetixxCity(id=city_id, name=show.city, mandatorIds=[]),
            )
            if show.mandator_id not in city.mandator_ids:
                city.mandator_ids.append(show.mandator_id)
        for city in cities.values():
            city.mandator_ids.sort()
        return list(cities.values())

    @classmethod
    def _derive_genres(cls, rows: list[dict[str, Any]]) -> list[CinetixxGenre]:
        genres: dict[str, CinetixxGenre] = {}
        for row in rows:
            for value in cls._genre_values(row):
                genre_id = value.casefold().replace(" ", "-")
                genres[genre_id] = CinetixxGenre(id=genre_id, name=value)
        return list(genres.values())

    @staticmethod
    def _genre_values(row: dict[str, Any]) -> list[str]:
        values: list[str] = []
        genre = _as_str(row.get("genre"))
        if genre:
            values.extend(part.strip() for part in re.split(r"[,;/|]", genre) if part.strip())
        categories = row.get("categories")
        if isinstance(categories, list):
            values.extend(
                value.strip() for value in categories if isinstance(value, str) and value.strip()
            )
        return list(dict.fromkeys(values))

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------
    @classmethod
    def _parse_body(cls, body: str, content_type: str | None) -> Any:
        """Parse Cinetixx response bodies without assuming a stable legacy shape."""
        text = body.strip()
        if not text:
            return None

        if cls._looks_like_json(text, content_type):
            return cls._parse_json(text)

        if text.startswith("<"):
            return cls._parse_xml(text)

        return text

    @staticmethod
    def _looks_like_json(text: str, content_type: str | None) -> bool:
        if content_type and "json" in content_type.lower():
            return True
        return text.startswith("{") or text.startswith("[")

    @staticmethod
    def _parse_json(text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise CinetixxAPIError("Cinetixx returned invalid JSON") from exc

    @classmethod
    def _parse_xml(cls, text: str) -> dict[str, Any]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise CinetixxAPIError("Cinetixx returned invalid XML") from exc

        root_text = (root.text or "").strip()
        if not list(root) and cls._looks_like_json(root_text, None):
            return {cls._strip_namespace(root.tag): cls._parse_json(root_text)}

        return {cls._strip_namespace(root.tag): cls._element_to_data(root)}

    @classmethod
    def _element_to_data(cls, element: ET.Element) -> Any:
        children = list(element)
        attributes = {cls._strip_namespace(key): value for key, value in element.attrib.items()}
        text = (element.text or "").strip()

        if not children:
            if attributes:
                data: dict[str, Any] = {"attributes": attributes}
                if text:
                    data["text"] = text
                return data
            return text or None

        data = {}
        if attributes:
            data["attributes"] = attributes
        if text:
            data["text"] = text

        for child in children:
            key = cls._strip_namespace(child.tag)
            child_data = cls._element_to_data(child)
            if key in data:
                existing = data[key]
                if isinstance(existing, list):
                    existing.append(child_data)
                else:
                    data[key] = [existing, child_data]
            else:
                data[key] = child_data

        return data

    @staticmethod
    def _strip_namespace(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]
