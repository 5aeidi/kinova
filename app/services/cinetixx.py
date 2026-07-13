"""High-level service for Cinetixx source data."""

import datetime as dt
import json
import logging
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
    CinetixxMandator,
    CinetixxMandatorSearchParams,
    CinetixxMovie,
    CinetixxMovieSearchParams,
    CinetixxPrice,
    CinetixxShow,
    CinetixxShowInfo,
    CinetixxShowInfoParams,
    CinetixxShowSearchParams,
)
from app.services.cinetixx_client import CinetixxClient

logger = logging.getLogger(__name__)


def _matches(value: str | None, query: str | None) -> bool:
    """Case-insensitive substring match; a missing query matches everything."""
    if query is None:
        return True
    if value is None:
        return False
    return query.casefold() in value.casefold()


def _key_token(key: str) -> str:
    """Normalize Cinetixx field names across camelCase, snake_case, and XML tags."""
    return re.sub(r"[^a-z0-9]", "", key.casefold())


def _row_value(row: dict[str, Any], *keys: str) -> Any:
    """Return a row value using exact or normalized field-name matching."""
    for key in keys:
        if key in row:
            return row[key]

    key_tokens = {_key_token(key) for key in keys}
    for row_key, value in row.items():
        if isinstance(row_key, str) and _key_token(row_key) in key_tokens:
            return value
    return None


def _row_attribute(row: dict[str, Any], *keys: str) -> Any:
    """Return an XML attribute value parsed by `_element_to_data`."""
    attributes = row.get("attributes")
    if not isinstance(attributes, dict):
        return None
    return _row_value(attributes, *keys)


def _scalar_value(value: Any) -> Any:
    """Extract scalar text from an XML element representation when present."""
    if isinstance(value, dict) and "text" in value:
        return value["text"]
    return value


def _as_str(value: Any) -> str | None:
    value = _scalar_value(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    value = _scalar_value(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    value = _scalar_value(value)
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


def _as_string_list(value: Any) -> list[str]:
    value = _scalar_value(value)
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

    async def discover_mandators(
        self,
        params: CinetixxMandatorSearchParams,
    ) -> list[CinetixxMandator]:
        """Discover Cinetixx mandator IDs from the booking cinema index."""
        if params.cinema_id:
            payload = await self.client.get_cinema(params.cinema_id)
            mandator = self._payload_to_mandator(payload)
            if mandator is None:
                raise CinetixxNotFoundError(f"Cinetixx cinema {params.cinema_id} not found")
            return [mandator]

        payload = await self.client.search_cinemas(
            search=params.search,
            lat=params.lat,
            lon=params.lon,
            page=params.page,
            page_size=params.limit,
        )
        return self._extract_mandators(payload)[: params.limit]

    async def discover_all_mandators(self) -> list[CinetixxMandator]:
        """Discover every mandator reachable through the public booking index.

        Cinetixx's unauthenticated endpoint is a text search, not a directory:
        a blank query returns no results. Search its built-in index terms and
        de-duplicate the returned cinemas to enumerate mandators without
        accepting IDs from callers or requiring configuration.
        """
        mandators: dict[str, CinetixxMandator] = {}
        page_size = settings.cinetixx_discovery_page_size
        terms = settings.cinetixx_discovery_terms or list("abcdefghijklmnopqrstuvwxyz0123456789")
        for term in terms:
            for page in range(1, settings.cinetixx_discovery_max_pages + 1):
                payload = await self.client.search_cinemas(
                    search=term,
                    page=page,
                    page_size=page_size,
                )
                discovered = self._extract_mandators(payload)
                new_count = sum(item.cinema_id not in mandators for item in discovered)
                mandators.update({item.cinema_id: item for item in discovered})
                logger.info(
                    "Cinetixx mandator discovery term=%r page %d: %d results, %d total",
                    term,
                    page,
                    len(discovered),
                    len(mandators),
                )

                # Cinetixx normally returns a short final page. Some deployments ignore
                # pagination entirely; a duplicate page prevents an endless re-fetch.
                if len(discovered) < page_size or new_count == 0:
                    break
            else:
                logger.warning(
                    "Cinetixx discovery term=%r stopped at configured %d-page safety limit",
                    term,
                    settings.cinetixx_discovery_max_pages,
                )
        return list(mandators.values())

    async def get_dataset(self, mandator_id: int | None = None) -> CinetixxDataset:
        """Fetch and normalize Cinetixx program data for one or more mandators."""
        datasets: list[CinetixxDataset] = []
        mandators: dict[int, CinetixxMandator] = {}
        if mandator_id is not None:
            mandator_ids = [mandator_id]
        else:
            discovered = await self.discover_all_mandators()
            mandators = {item.mandator_id: item for item in discovered}
            mandator_ids = sorted(set(mandators) | set(settings.cinetixx_sync_mandator_ids))
        for resolved_id in mandator_ids:
            show_info = await self.get_show_info(CinetixxShowInfoParams(mandator_id=resolved_id))
            datasets.append(
                self._normalize_and_enrich(show_info, mandators.get(resolved_id)),
            )
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

    def _normalize_and_enrich(
        self,
        show_info: CinetixxShowInfo,
        mandator: CinetixxMandator | None,
    ) -> CinetixxDataset:
        """Normalize programme rows and attach booking-index metadata."""
        return self.enrich_dataset(self.normalize_show_info(show_info), mandator)

    @staticmethod
    def enrich_dataset(
        dataset: CinetixxDataset,
        mandator: CinetixxMandator | None,
    ) -> CinetixxDataset:
        """Add booking-index cinema metadata missing from legacy programme rows."""
        if mandator is None:
            return dataset

        cinemas = []
        matched_mandator = False
        for cinema in dataset.cinemas:
            if cinema.mandator_id != mandator.mandator_id:
                cinemas.append(cinema)
                continue
            matched_mandator = True
            cinemas.append(
                cinema.model_copy(
                    update={
                        "cinema_id": cinema.cinema_id or mandator.cinema_id,
                        "name": cinema.name or mandator.cinema_name or mandator.name,
                        "city": cinema.city or mandator.city,
                        "address": mandator.address,
                        "post_code": mandator.post_code,
                        "phone": mandator.phone,
                        "latitude": mandator.latitude,
                        "longitude": mandator.longitude,
                        "program_url": mandator.program_url,
                        "pretty_program_url": mandator.pretty_program_url,
                        "special_event_image_url": mandator.special_event_image_url,
                    },
                ),
            )
        if not matched_mandator:
            cinemas.append(
                CinetixxCinema(
                    id=mandator.cinema_id,
                    mandatorId=mandator.mandator_id,
                    cinemaId=mandator.cinema_id,
                    name=mandator.cinema_name or mandator.name,
                    city=mandator.city,
                    address=mandator.address,
                    postCode=mandator.post_code,
                    phone=mandator.phone,
                    latitude=mandator.latitude,
                    longitude=mandator.longitude,
                    programUrl=mandator.program_url,
                    prettyProgramUrl=mandator.pretty_program_url,
                    specialEventImageUrl=mandator.special_event_image_url,
                ),
            )
        return dataset.model_copy(update={"cinemas": cinemas})

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

    @staticmethod
    def filter_mandators(
        mandators: list[CinetixxMandator],
        params: CinetixxMandatorSearchParams,
    ) -> list[CinetixxMandator]:
        """Filter discovered Cinetixx mandators."""
        results = []
        for mandator in mandators:
            if params.cinema_id and mandator.cinema_id != params.cinema_id:
                continue
            if (
                _matches(mandator.name, params.search)
                or _matches(mandator.cinema_name, params.search)
                or _matches(mandator.mandator_name, params.search)
                or _matches(mandator.address, params.search)
                or _matches(mandator.city, params.search)
            ):
                results.append(mandator)
        return results[: params.limit]

    @classmethod
    def _extract_mandators(cls, data: Any) -> list[CinetixxMandator]:
        if isinstance(data, dict):
            raw_items = data.get("searchList")
            if isinstance(raw_items, list):
                return cls._mandators_from_items(raw_items)
            if data.get("id") is not None or data.get("mandatorId") is not None:
                mandator = cls._payload_to_mandator(data)
                return [mandator] if mandator else []
        if isinstance(data, list):
            return cls._mandators_from_items(data)
        return []

    @classmethod
    def _mandators_from_items(cls, items: list[Any]) -> list[CinetixxMandator]:
        mandators: dict[str, CinetixxMandator] = {}
        for item in items:
            raw = item.get("searchObject") if isinstance(item, dict) else item
            mandator = cls._payload_to_mandator(raw)
            if mandator is not None:
                mandators[mandator.cinema_id] = mandator
        return list(mandators.values())

    @staticmethod
    def _payload_to_mandator(payload: Any) -> CinetixxMandator | None:
        if not isinstance(payload, dict):
            return None

        cinema_id = _as_str(payload.get("id") or payload.get("cinemaId"))
        mandator_id = _as_int(payload.get("mandatorId"))
        if cinema_id is None or mandator_id is None:
            return None

        return CinetixxMandator(
            cinemaId=cinema_id,
            mandatorId=mandator_id,
            name=_as_str(payload.get("name")),
            cinemaName=_as_str(payload.get("cinemaName")),
            mandatorName=_as_str(payload.get("mandatorName")),
            address=_as_str(payload.get("address")),
            city=_as_str(payload.get("city")),
            postCode=_as_str(payload.get("postCode")),
            phone=_as_str(payload.get("phone")),
            latitude=payload.get("latitude"),
            longitude=payload.get("longitude"),
            hasShows=_as_bool(payload.get("hasShows")),
            programUrl=_as_str(payload.get("_urlProgram") or payload.get("programUrl")),
            prettyProgramUrl=_as_str(
                payload.get("_urlPrettyProgram") or payload.get("prettyProgramUrl"),
            ),
            giftCardsUrl=_as_str(payload.get("_urlGiftCards") or payload.get("giftCardsUrl")),
            cardBalanceUrl=_as_str(
                payload.get("_urlCardBalance") or payload.get("cardBalanceUrl"),
            ),
            specialEventImageUrl=_as_str(
                payload.get("urlSpecialEventImage") or payload.get("specialEventImageUrl"),
            ),
        )

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
        normalized = {_key_token(key) for key in row if isinstance(key, str)}
        return bool(normalized & {_key_token(key) for key in show_keys})

    @classmethod
    def _row_to_show(cls, row: dict[str, Any], fallback_mandator_id: int) -> CinetixxShow:
        mandator_id = _as_int(_row_value(row, "mandatorId")) or fallback_mandator_id
        show_id = _as_str(_row_value(row, "showId", "id") or _row_attribute(row, "id"))
        movie_id = _as_str(_row_value(row, "movieId"))
        event_id = _as_str(_row_value(row, "eventId"))
        begins_at = _as_datetime(_row_value(row, "showBeginning", "startday"))
        flags = cls._extract_flags(row)
        prices = cls._extract_prices(row)
        return CinetixxShow(
            id=show_id or f"{mandator_id}:{movie_id or event_id or len(str(row))}",
            mandatorId=mandator_id,
            showId=show_id,
            movieId=movie_id,
            eventId=event_id,
            movieTitle=_as_str(_row_value(row, "veranstaltungstitel", "title")),
            text=_as_str(_row_value(row, "text")),
            beginsAt=begins_at,
            date=begins_at.date() if begins_at else None,
            bookingUrl=_as_str(_row_value(row, "bookingLink")),
            cinemaId=_as_str(_row_value(row, "cinemaId")),
            cinemaName=_as_str(_row_value(row, "kino")),
            cityId=_as_str(_row_value(row, "cityId")),
            city=_as_str(_row_value(row, "stadt")),
            auditoriumId=_as_str(_row_value(row, "auditoriumId")),
            auditoriumName=_as_str(_row_value(row, "saal")),
            language=_as_str(_row_value(row, "language", "sprachversion")),
            version=_as_str(_row_value(row, "versiontype")),
            audioType=_as_str(_row_value(row, "audiotype")),
            ageRating=_as_str(_row_value(row, "altersfreigabe")),
            duration=_as_int(_row_value(row, "spieldauerEvent")),
            is3d=_as_bool(_row_value(row, "flag3D")),
            hasSeatSelection=_as_bool(_row_value(row, "seatselection")),
            salesStart=_as_datetime(_row_value(row, "verkaufsstart")),
            salesEnd=_as_datetime(_row_value(row, "verkaufsende")),
            reservationStart=_as_datetime(_row_value(row, "reservierungsstart")),
            reservationEnd=_as_datetime(_row_value(row, "reservierungsende")),
            flags=flags,
            prices=prices,
            raw=row,
        )

    @staticmethod
    def _extract_flags(row: dict[str, Any]) -> list[str]:
        flags: list[str] = []
        if _as_bool(_row_value(row, "flag3D")):
            flags.append("3D")
        for key in ("sprachversion", "versiontype", "language", "audiotype", "aspectratio"):
            value = _as_str(_row_value(row, key))
            if value and value not in flags:
                flags.append(value)
        type_value = _row_value(row, "type")
        if isinstance(type_value, dict):
            value = _as_str(
                type_value
                or _row_value(type_value, "value", "key")
                or _row_attribute(type_value, "key"),
            )
            if value and value not in flags:
                flags.append(value)
        else:
            value = _as_str(type_value)
            if value and value not in flags:
                flags.append(value)
        return flags

    @staticmethod
    def _extract_prices(row: dict[str, Any]) -> list[CinetixxPrice]:
        raw_prices = _row_value(row, "prices", "price")
        price_items = raw_prices if isinstance(raw_prices, list) else [raw_prices]
        prices: list[CinetixxPrice] = []
        for price in price_items:
            if price is None:
                continue
            if isinstance(price, dict):
                prices.append(
                    CinetixxPrice(
                        amount=_row_value(price, "amount"),
                        category=_as_str(_row_value(price, "categorie", "category") or price),
                        area=_as_str(_row_value(price, "area")),
                        isDefault=_as_bool(_row_value(price, "default", "isDefault")),
                    ),
                )
                continue
            category = _as_str(price)
            if category:
                prices.append(CinetixxPrice(category=category))
        return prices

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
            categories = _as_string_list(_row_value(row, "categories"))
            movies[resource_id] = CinetixxMovie(
                id=resource_id,
                movieId=movie_id,
                eventId=event_id,
                title=title,
                shortTitle=_as_str(_row_value(row, "veranstaltungskurztitel")),
                description=_as_str(_row_value(row, "text")),
                shortDescription=_as_str(_row_value(row, "textShort")),
                duration=show.duration,
                genres=genres,
                categories=categories,
                actors=_split_people(_row_value(row, "actor")),
                directors=_split_people(_row_value(row, "director")),
                screenWriters=_split_people(_row_value(row, "screenWriter")),
                year=_as_str(_row_value(row, "year")),
                country=_as_str(_row_value(row, "country")),
                artwork=_as_str(_row_value(row, "artwork", "image1")),
                artworkBig=_as_str(_row_value(row, "artworkBig")),
                trailerUrl=_as_str(_row_value(row, "eventTrailer")),
                movieUrl=_as_str(_row_value(row, "movieLink")),
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
        genre = _as_str(_row_value(row, "genre"))
        if genre:
            values.extend(part.strip() for part in re.split(r"[,;/|]", genre) if part.strip())
        values.extend(_as_string_list(_row_value(row, "categories")))
        values = [value for value in values if value != "-"]
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
