"""Natural-language search service that translates prompts into Kinoheld queries."""

import datetime as dt
import logging

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.core.exceptions import KinoheldNotFoundError
from app.schemas.cinema import Cinema, CinemaSearchParams
from app.schemas.movie import Movie, MovieSearchParams
from app.schemas.show import Show, ShowSearchParams
from app.services.cache import KinoheldCache
from app.services.kinoheld import KinoheldService
from app.services.llm_client import LLMClient, LLMError

logger = logging.getLogger(__name__)


class NaturalLanguageQuery(BaseModel):
    """User-facing request body for the natural-language search endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    prompt: str = Field(..., min_length=1, description="Free-text user prompt")
    use_cache: bool = Field(
        default=False,
        alias="useCache",
        description="Use cached data instead of live Kinoheld requests",
    )
    location: str | None = Field(
        default=None,
        description="Optional city/location hint (overrides prompt inference)",
    )
    limit: int = Field(default=20, ge=1, le=100)


class ParsedIntent(BaseModel):
    """Structured intent extracted from a natural-language prompt."""

    model_config = ConfigDict(populate_by_name=True)

    intent: str = Field(
        default="movies",
        description="One of: movies, shows, cinemas, unknown",
    )
    search_query: str | None = Field(
        default=None,
        alias="searchQuery",
        description="Extracted free-text search term, e.g. movie title",
    )
    genres: list[str] = Field(default_factory=list, description="Genre names")
    date: str | None = Field(
        default=None,
        description="Target date as YYYY-MM-DD or relative term today/tomorrow",
    )
    location: str | None = Field(default=None, description="City or location name")
    cinema_id: str | None = Field(
        default=None,
        alias="cinemaId",
        description="Kinoheld cinema ID if explicitly mentioned",
    )
    flags: list[str] = Field(
        default_factory=list,
        description="Show flags to look for, e.g. ['OmU','OV','3D']",
    )
    language: str | None = Field(
        default=None,
        description="Language hint extracted from the prompt",
    )

    # Numeric / structured filters that Kinoheld does not support as query params.
    duration_min: int | None = Field(
        default=None,
        alias="durationMin",
        ge=0,
        description="Minimum movie duration in minutes",
    )
    duration_max: int | None = Field(
        default=None,
        alias="durationMax",
        ge=0,
        description="Maximum movie duration in minutes",
    )
    year_min: int | None = Field(
        default=None,
        alias="yearMin",
        description="Minimum production year",
    )
    year_max: int | None = Field(
        default=None,
        alias="yearMax",
        description="Maximum production year",
    )
    year: int | None = Field(default=None, description="Exact production year")
    rating_min: float | None = Field(
        default=None,
        alias="ratingMin",
        ge=0,
        le=10,
        description="Minimum IMDb rating",
    )
    rating_max: float | None = Field(
        default=None,
        alias="ratingMax",
        ge=0,
        le=10,
        description="Maximum IMDb rating",
    )
    actors: list[str] = Field(default_factory=list, description="Actor names")
    directors: list[str] = Field(default_factory=list, description="Director names")
    cast: list[str] = Field(
        default_factory=list,
        description="Any cast/creator names (actor or director)",
    )

    @field_validator("date")
    @classmethod
    def _normalise_relative_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value_lower = value.strip().lower()
        today = dt.date.today()
        if value_lower in {"today", "heute"}:
            return today.isoformat()
        if value_lower in {"tomorrow", "morgen"}:
            return (today + dt.timedelta(days=1)).isoformat()
        # Try to parse a few common formats.
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                return dt.datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
        # Return as-is if not parsed; downstream code will ignore invalid dates.
        return value


class StructuredSearchQuery(BaseModel):
    """Deterministic, UI-friendly search filters for the filter panel."""

    model_config = ConfigDict(populate_by_name=True)

    intent: str = Field(
        default="movies",
        description="One of: movies, shows, cinemas",
    )
    search_query: str | None = Field(
        default=None,
        alias="searchQuery",
        description="Free-text movie/cinema title search",
    )
    genres: list[str] = Field(default_factory=list, description="Genre names")
    date: str | None = Field(
        default=None,
        description="Target date as YYYY-MM-DD or relative term today/tomorrow",
    )
    location: str | None = Field(default=None, description="City or location name")
    cinema_id: str | None = Field(
        default=None,
        alias="cinemaId",
        description="Kinoheld cinema ID",
    )
    flags: list[str] = Field(
        default_factory=list,
        description="Show flags to look for, e.g. ['OmU','OV','3D']",
    )
    language: str | None = Field(
        default=None,
        description="Language hint for soft movie filtering",
    )
    duration_min: int | None = Field(
        default=None,
        alias="durationMin",
        ge=0,
        description="Minimum movie duration in minutes",
    )
    duration_max: int | None = Field(
        default=None,
        alias="durationMax",
        ge=0,
        description="Maximum movie duration in minutes",
    )
    year: int | None = Field(default=None, description="Exact production year")
    year_min: int | None = Field(
        default=None,
        alias="yearMin",
        description="Minimum production year",
    )
    year_max: int | None = Field(
        default=None,
        alias="yearMax",
        description="Maximum production year",
    )
    rating_min: float | None = Field(
        default=None,
        alias="ratingMin",
        ge=0,
        le=10,
        description="Minimum IMDb rating",
    )
    rating_max: float | None = Field(
        default=None,
        alias="ratingMax",
        ge=0,
        le=10,
        description="Maximum IMDb rating",
    )
    actors: list[str] = Field(default_factory=list, description="Actor names")
    directors: list[str] = Field(default_factory=list, description="Director names")
    cast: list[str] = Field(
        default_factory=list,
        description="Any cast/creator names when role is unclear",
    )
    use_cache: bool = Field(
        default=False,
        alias="useCache",
        description="Use cached data instead of live Kinoheld requests",
    )
    limit: int = Field(default=20, ge=1, le=100)

    _normalise_date = field_validator("date")(ParsedIntent._normalise_relative_date)


class SearchResult(BaseModel):
    """Unified response for any structured or natural-language search."""

    model_config = ConfigDict(populate_by_name=True)

    intent: str
    cinemas: list[Cinema] = Field(default_factory=list)
    movies: list[Movie] = Field(default_factory=list)
    shows: list[Show] = Field(default_factory=list)
    total_results: int = Field(default=0, alias="totalResults")


class NaturalLanguageResult(SearchResult):
    """Unified response for a natural-language search."""

    prompt: str
    parsed: ParsedIntent


class NaturalLanguageSearchService:
    """Orchestrate NL parsing, data fetching, and result ranking."""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def search(
        self,
        request: NaturalLanguageQuery,
        live_service: KinoheldService,
        cache: KinoheldCache,
    ) -> NaturalLanguageResult:
        """Run the full NL search pipeline."""
        parsed = await self._parse_prompt(request)
        location_override = request.location or parsed.location
        if location_override:
            parsed.location = location_override

        cinemas, movies, shows = await self._execute_intent(
            parsed,
            live_service,
            cache,
            request.use_cache,
            request.limit,
        )

        total = len(cinemas) + len(movies) + len(shows)
        return NaturalLanguageResult(
            prompt=request.prompt,
            intent=parsed.intent,
            parsed=parsed,
            cinemas=cinemas,
            movies=movies,
            shows=shows,
            total_results=total,
        )

    async def structured_search(
        self,
        request: StructuredSearchQuery,
        live_service: KinoheldService,
        cache: KinoheldCache,
    ) -> SearchResult:
        """Run a deterministic search using explicit UI filters."""
        parsed = self._structured_to_parsed(request)

        cinemas, movies, shows = await self._execute_intent(
            parsed,
            live_service,
            cache,
            request.use_cache,
            request.limit,
        )

        total = len(cinemas) + len(movies) + len(shows)
        return SearchResult(
            intent=parsed.intent,
            cinemas=cinemas,
            movies=movies,
            shows=shows,
            total_results=total,
        )

    @staticmethod
    def _structured_to_parsed(request: StructuredSearchQuery) -> ParsedIntent:
        """Convert a structured query into the internal ParsedIntent shape."""
        return ParsedIntent(
            intent=request.intent,
            search_query=request.search_query,
            genres=request.genres,
            date=request.date,
            location=request.location,
            cinema_id=request.cinema_id,
            flags=request.flags,
            language=request.language,
            duration_min=request.duration_min,
            duration_max=request.duration_max,
            year=request.year,
            year_min=request.year_min,
            year_max=request.year_max,
            rating_min=request.rating_min,
            rating_max=request.rating_max,
            actors=request.actors,
            directors=request.directors,
            cast=request.cast,
        )

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    async def _parse_prompt(self, request: NaturalLanguageQuery) -> ParsedIntent:
        today = dt.date.today()
        tomorrow = today + dt.timedelta(days=1)
        system_message = (
            "You are a structured-intent parser for a cinema search API. "
            "Extract every filter mentioned in the prompt and respond ONLY with a "
            "single JSON object.\n"
            f"Today's date is {today.isoformat()} and tomorrow is {tomorrow.isoformat()}.\n"
            "\n"
            "JSON schema:\n"
            "{\n"
            '  "intent": "movies|shows|cinemas|unknown",\n'
            '  "searchQuery": "free-text title or cinema name, or null",\n'
            '  "genres": ["genre names like Horror, Drama, Comedy"],\n'
            '  "date": "YYYY-MM-DD, today, tomorrow, or null",\n'
            '  "location": "city name or null",\n'
            '  "cinemaId": "Kinoheld cinema ID or null",\n'
            '  "flags": ["show flags: OmU, OV, 3D, IMAX, etc."],\n'
            '  "language": "English, German, etc., or null",\n'
            '  "durationMin": integer or null,\n'
            '  "durationMax": integer or null,\n'
            '  "year": integer or null,\n'
            '  "yearMin": integer or null,\n'
            '  "yearMax": integer or null,\n'
            '  "ratingMin": 0-10 float or null,\n'
            '  "ratingMax": 0-10 float or null,\n'
            '  "actors": ["actor names"],\n'
            '  "directors": ["director names"],\n'
            '  "cast": ["any actor or director names when role is unclear"]\n'
            "}\n"
            "\n"
            "Extraction rules:\n"
            "- Always set durationMax for phrases like 'under X minutes', 'below X min', "
            "'shorter than X'.\n"
            "- Always set durationMin for phrases like 'over X minutes', 'above X min', "
            "'longer than X'.\n"
            "- For 'X minutes' or 'X min' with no comparator, treat as durationMax.\n"
            "- For year ranges like '2020s', set yearMin=2020 and yearMax=2029.\n"
            "- 'from 2023' means yearMin=2023; 'before 2010' means yearMax=2009.\n"
            "- 'starring X', 'with X', 'in which X acts' -> actors=[X].\n"
            "- 'directed by X', 'by director X' -> directors=[X].\n"
            "- If it is unclear whether a person is actor or director, put them in cast.\n"
            '- "OmU" = original with subtitles; "OV" = original without subtitles; '
            '"English subtitles" /> "OmU".\n'
            '- If the prompt asks for showtimes/screenings, intent is "shows"; '
            'if it asks for cinemas/theatres, intent is "cinemas"; '
            'otherwise default to "movies".\n'
            "- Return only the JSON object, no markdown or explanation.\n"
        )
        try:
            data = await self.llm_client.chat_completion(
                system_message=system_message,
                user_message=request.prompt,
                response_format={"type": "json_object"},
            )
            return ParsedIntent.model_validate(data)
        except LLMError:
            logger.exception("LLM parsing failed; falling back to heuristic parser")
            return self._heuristic_parse(request.prompt)

    @staticmethod
    def _heuristic_parse(prompt: str) -> ParsedIntent:
        """Best-effort fallback parser when the LLM is unavailable."""
        text = prompt.lower()
        intent = "movies"
        if any(word in text for word in ("show", "screening", "vorstellung", "aufführung")):
            intent = "shows"
        elif any(word in text for word in ("cinema", "theater", "theatre", "kino")):
            intent = "cinemas"

        genres: list[str] = []
        for genre in ("horror", "comedy", "action", "drama", "thriller", "romance", "sci-fi"):
            if genre in text:
                genres.append(genre.capitalize())

        date: str | None = None
        if "tomorrow" in text or "morgen" in text:
            date = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        elif "today" in text or "heute" in text:
            date = dt.date.today().isoformat()

        flags: list[str] = []
        subtitle_phrases = ("english subtitles", "englische untertitel")
        if "omu" in text or any(phrase in text for phrase in subtitle_phrases):
            flags.append("OmU")
        elif "ov" in text or "original version" in text:
            flags.append("OV")
        if "3d" in text:
            flags.append("3D")

        language = "English" if any(phrase in text for phrase in ("english", "englisch")) else None

        duration_max = NaturalLanguageSearchService._extract_duration_max(text)

        return ParsedIntent(
            intent=intent,
            search_query=None,
            genres=genres,
            date=date,
            location=None,
            flags=flags,
            language=language,
            duration_max=duration_max,
        )

    @staticmethod
    def _extract_duration_max(text: str) -> int | None:
        """Best-effort regex for 'under X minutes' in the heuristic fallback."""
        import re

        match = re.search(
            r"(?:under|below|less than|shorter than)\s+(\d+)\s*(?:min|minutes?)",
            text,
        )
        if match:
            return int(match.group(1))
        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    async def _execute_intent(
        self,
        parsed: ParsedIntent,
        live_service: KinoheldService,
        cache: KinoheldCache,
        use_cache: bool,
        limit: int,
    ) -> tuple[list[Cinema], list[Movie], list[Show]]:
        if parsed.intent == "cinemas":
            cinemas = await self._search_cinemas(parsed, live_service, cache, use_cache, limit)
            return cinemas, [], []

        if parsed.intent == "shows":
            cinemas, movies, shows = await self._search_shows(
                parsed, live_service, cache, use_cache, limit
            )
            return cinemas, movies, shows

        # Default: movies
        movies = await self._search_movies(parsed, live_service, cache, use_cache, limit)
        return [], movies, []

    async def _search_cinemas(
        self,
        parsed: ParsedIntent,
        live_service: KinoheldService,
        cache: KinoheldCache,
        use_cache: bool,
        limit: int,
    ) -> list[Cinema]:
        params = CinemaSearchParams(
            search=parsed.search_query,
            location=parsed.location,
            limit=limit,
        )
        if use_cache:
            return await cache.search_cinemas(params)
        return await live_service.search_cinemas(params)

    async def _search_movies(
        self,
        parsed: ParsedIntent,
        live_service: KinoheldService,
        cache: KinoheldCache,
        use_cache: bool,
        limit: int,
    ) -> list[Movie]:
        # Fetch a generous candidate set so post-filters have enough data.
        candidate_limit = max(limit, 100)
        params = MovieSearchParams(
            search=parsed.search_query,
            location=parsed.location,
            limit=candidate_limit,
        )
        if use_cache:
            movies = await cache.search_movies(params)
        else:
            movies = await live_service.search_movies(params)

        # Apply deterministic post-filters.
        movies = self._apply_movie_filters(movies, parsed)

        if parsed.search_query and settings.llm_fallback_search_enabled and not movies:
            logger.info("No movies found by upstream search; trying fallback title search")
            movies = self._fallback_text_search(movies if use_cache else [], parsed.search_query)
            movies = self._apply_movie_filters(movies, parsed)

        return movies[:limit]

    def _apply_movie_filters(
        self,
        movies: list[Movie],
        parsed: ParsedIntent,
    ) -> list[Movie]:
        if parsed.genres:
            movies = self._filter_by_genres(movies, parsed.genres)
        if parsed.duration_min is not None or parsed.duration_max is not None:
            movies = self._filter_by_duration(movies, parsed.duration_min, parsed.duration_max)
        if parsed.year is not None or parsed.year_min is not None or parsed.year_max is not None:
            movies = self._filter_by_year(movies, parsed.year, parsed.year_min, parsed.year_max)
        if parsed.rating_min is not None or parsed.rating_max is not None:
            movies = self._filter_by_rating(movies, parsed.rating_min, parsed.rating_max)
        if parsed.actors or parsed.directors or parsed.cast:
            movies = self._filter_by_people(
                movies,
                actors=parsed.actors,
                directors=parsed.directors,
                cast=parsed.cast,
            )
        if parsed.language:
            movies = self._filter_by_language_hint(movies, parsed.language)
        return movies

    @staticmethod
    def _filter_by_duration(
        movies: list[Movie],
        min_minutes: int | None,
        max_minutes: int | None,
    ) -> list[Movie]:
        results = []
        for m in movies:
            if m.duration is None:
                continue
            if min_minutes is not None and m.duration < min_minutes:
                continue
            if max_minutes is not None and m.duration > max_minutes:
                continue
            results.append(m)
        return results

    @staticmethod
    def _filter_by_year(
        movies: list[Movie],
        year: int | None,
        year_min: int | None,
        year_max: int | None,
    ) -> list[Movie]:
        def _match(m: Movie) -> bool:
            if m.production_year is None:
                return False
            try:
                value = int(m.production_year)
            except (ValueError, TypeError):
                return False
            if year is not None and value != year:
                return False
            if year_min is not None and value < year_min:
                return False
            if year_max is not None and value > year_max:
                return False
            return True

        return [m for m in movies if _match(m)]

    @staticmethod
    def _filter_by_rating(
        movies: list[Movie],
        rating_min: float | None,
        rating_max: float | None,
    ) -> list[Movie]:
        results = []
        for m in movies:
            if m.imdb_rating is None:
                continue
            if rating_min is not None and m.imdb_rating < rating_min:
                continue
            if rating_max is not None and m.imdb_rating > rating_max:
                continue
            results.append(m)
        return results

    @staticmethod
    def _filter_by_people(
        movies: list[Movie],
        actors: list[str],
        directors: list[str],
        cast: list[str],
    ) -> list[Movie]:
        all_actors = {name.casefold() for name in actors + cast}
        all_directors = {name.casefold() for name in directors + cast}

        def _name_matches(persons: list, names: set[str]) -> bool:
            return any(p.name and p.name.casefold() in names for p in persons)

        return [
            m
            for m in movies
            if (all_actors and _name_matches(m.actors, all_actors))
            or (all_directors and _name_matches(m.directors, all_directors))
        ]

    @staticmethod
    def _filter_by_language_hint(movies: list[Movie], language: str) -> list[Movie]:
        """Soft filter: keep movies whose metadata mentions the language.

        Kinoheld does not expose a per-movie language field, so this is a
        best-effort heuristic based on title, description, and additional
        description. Use with caution.
        """
        lang = language.casefold()
        keywords = {
            "english": ["english", "englisch"],
            "german": ["german", "deutsch"],
            "french": ["french", "französisch"],
            "spanish": ["spanish", "spanisch"],
            "italian": ["italian", "italienisch"],
        }
        terms = keywords.get(lang, [lang])

        def _mentions(movie: Movie) -> bool:
            haystack = " ".join(
                part
                for part in (
                    movie.title,
                    movie.description,
                    movie.additional_description,
                )
                if part
            ).casefold()
            return any(term in haystack for term in terms)

        return [m for m in movies if _mentions(m)]

    async def _search_shows(
        self,
        parsed: ParsedIntent,
        live_service: KinoheldService,
        cache: KinoheldCache,
        use_cache: bool,
        limit: int,
    ) -> tuple[list[Cinema], list[Movie], list[Show]]:
        # Determine target cinemas.
        cinemas: list[Cinema] = []
        if parsed.cinema_id:
            try:
                cinemas = [await self._get_cinema(parsed.cinema_id, live_service, cache, use_cache)]
            except KinoheldNotFoundError:
                cinemas = []
        elif parsed.location:
            cinemas = await self._search_cinemas(parsed, live_service, cache, use_cache, limit=20)
        elif parsed.search_query:
            cinemas = await self._search_cinemas(parsed, live_service, cache, use_cache, limit=20)
        else:
            # No location/cinema context: search movies instead and explain via intent.
            movies = await self._search_movies(parsed, live_service, cache, use_cache, limit)
            return [], movies, []

        # Determine target movies when a title/genre/actor/director is specified.
        movie_ids: set[str] | None = None
        if parsed.search_query or parsed.genres or parsed.actors or parsed.directors or parsed.cast:
            movie_params = MovieSearchParams(
                search=parsed.search_query,
                location=parsed.location,
                limit=100,
            )
            if use_cache:
                candidate_movies = await cache.search_movies(movie_params)
            else:
                candidate_movies = await live_service.search_movies(movie_params)
            candidate_movies = self._apply_movie_filters(candidate_movies, parsed)
            movie_ids = {m.id for m in candidate_movies}

        shows: list[Show] = []
        for cinema in cinemas:
            date = self._safe_date(parsed.date)
            params = ShowSearchParams(
                cinema_id=cinema.id,
                date=date,
                days=settings.kinoheld_sync_show_days if date is None else None,
                movie_id=None,
            )
            if use_cache:
                cinema_shows = await cache.search_shows(params)
                date_range = self._date_range(date)
                missing_dates = await cache.get_missing_show_dates(cinema.id, date_range)
                if missing_dates:
                    await cache.cache_shows_for_cinema(live_service, cinema.id, missing_dates)
                    cinema_shows = await cache.search_shows(params)
            else:
                cinema_shows = await live_service.search_shows(params)

            if movie_ids is not None:
                cinema_shows = [s for s in cinema_shows if s.movie and s.movie.id in movie_ids]
            if parsed.flags:
                cinema_shows = self._filter_by_flags(cinema_shows, parsed.flags)
            shows.extend(cinema_shows)

        unique_movies: dict[str, Movie] = {}
        for show in shows:
            if show.movie and show.movie.id not in unique_movies:
                unique_movies[show.movie.id] = show.movie
        return cinemas, list(unique_movies.values()), shows[:limit]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _get_cinema(
        self,
        cinema_id: str,
        live_service: KinoheldService,
        cache: KinoheldCache,
        use_cache: bool,
    ) -> Cinema:
        if use_cache:
            return await cache.get_cinema(cinema_id)
        return await live_service.get_cinema(cinema_id)

    @staticmethod
    def _filter_by_genres(movies: list[Movie], genres: list[str]) -> list[Movie]:
        genre_names = {g.casefold() for g in genres}
        return [m for m in movies if any(g.name.casefold() in genre_names for g in m.genres)]

    @staticmethod
    def _filter_by_flags(shows: list[Show], flags: list[str]) -> list[Show]:
        wanted = {f.casefold() for f in flags}
        return [
            s
            for s in shows
            if any(f.code and f.code.casefold() in wanted for f in s.flags)
            or any(f.name.casefold() in wanted for f in s.flags)
        ]

    @staticmethod
    def _fallback_text_search(movies: list[Movie], query: str) -> list[Movie]:
        q = query.casefold()
        return [m for m in movies if q in m.title.casefold()]

    @staticmethod
    def _safe_date(date_str: str | None) -> dt.date | None:
        if not date_str:
            return None
        try:
            return dt.date.fromisoformat(date_str)
        except ValueError:
            return None

    @staticmethod
    def _date_range(date: dt.date | None) -> list[str]:
        if date is not None:
            return [date.isoformat()]
        today = dt.date.today()
        return [
            (today + dt.timedelta(days=offset)).isoformat()
            for offset in range(settings.kinoheld_sync_show_days)
        ]
