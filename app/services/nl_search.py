"""Natural-language search service that translates prompts into Kinoheld queries."""

import contextlib
import datetime as dt
import logging
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import settings
from app.core.exceptions import KinoheldNotFoundError
from app.schemas.cinema import Cinema, CinemaSearchParams
from app.schemas.cinetixx import (
    CinetixxCinemaSearchParams,
    CinetixxMovieSearchParams,
    CinetixxShowSearchParams,
)
from app.schemas.movie import Movie, MovieSearchParams
from app.schemas.show import ShowSearchParams
from app.schemas.unified import UnifiedCinema, UnifiedMovie, UnifiedShow
from app.schemas.yorck import (
    YorckCinemaSearchParams,
    YorckMovieSearchParams,
    YorckShowSearchParams,
)
from app.services.cache import KinoheldCache
from app.services.cinetixx_cache import CinetixxCache
from app.services.kinoheld import KinoheldService
from app.services.llm_client import LLMClient, LLMError
from app.services.unified import (
    cinetixx_cinema_to_unified,
    cinetixx_movie_to_unified,
    cinetixx_show_to_unified,
    kinoheld_cinema_to_unified,
    kinoheld_movie_to_unified,
    kinoheld_show_to_unified,
    yorck_cinema_to_unified,
    yorck_movie_to_unified,
    yorck_show_to_unified,
)
from app.services.yorck_cache import YorckCache

logger = logging.getLogger(__name__)


def _contains(value: str | None, query: str | None) -> bool:
    """Case-insensitive substring match; a missing query matches everything."""
    if not query:
        return True
    if not value:
        return False
    return query.casefold() in value.casefold()


@dataclass
class SourceCaches:
    """Non-Kinoheld sources a search may draw on.

    These are read from their periodic caches rather than fetched live: a live
    Cinetixx or Yorck read means pulling a whole provider programme, which would
    add tens of seconds to a search request. ``useCache`` therefore governs the
    Kinoheld path only.
    """

    cinetixx: CinetixxCache | None = None
    yorck: YorckCache | None = None


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


def _normalise_relative_date(value: str | None) -> str | None:
    """Normalise relative/localised date terms to an ISO date string."""
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
        return _normalise_relative_date(value)


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

    @field_validator("date")
    @classmethod
    def _normalise_date(cls, value: str | None) -> str | None:
        return _normalise_relative_date(value)


class SearchResult(BaseModel):
    """Unified response for any structured or natural-language search."""

    model_config = ConfigDict(populate_by_name=True)

    intent: str
    cinemas: list[UnifiedCinema] = Field(default_factory=list)
    movies: list[UnifiedMovie] = Field(default_factory=list)
    shows: list[UnifiedShow] = Field(default_factory=list)
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
        sources: SourceCaches | None = None,
    ) -> NaturalLanguageResult:
        """Run the full NL search pipeline."""
        parsed = await self._parse_prompt(request, await self._genre_vocabulary(cache))
        location_override = request.location or parsed.location
        if location_override:
            parsed.location = location_override

        cinemas, movies, shows = await self._execute_intent(
            parsed,
            live_service,
            cache,
            sources or SourceCaches(),
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
        sources: SourceCaches | None = None,
    ) -> SearchResult:
        """Run a deterministic search using explicit UI filters."""
        parsed = self._structured_to_parsed(request)

        cinemas, movies, shows = await self._execute_intent(
            parsed,
            live_service,
            cache,
            sources or SourceCaches(),
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
    @staticmethod
    async def _genre_vocabulary(cache: KinoheldCache) -> list[str]:
        """Fetch the real genre tags to ground the parser; never fatal if empty."""
        try:
            return await cache.genre_vocabulary(settings.nl_genre_vocabulary_limit)
        except Exception:
            logger.warning("Could not build genre vocabulary; parsing ungrounded")
            return []

    async def _parse_prompt(
        self,
        request: NaturalLanguageQuery,
        genre_vocabulary: list[str] | None = None,
    ) -> ParsedIntent:
        today = dt.date.today()
        tomorrow = today + dt.timedelta(days=1)
        # Without the real tags the model invents English names ("Comedy") that never
        # match a German catalogue ("Komödie"), so those searches return nothing.
        if genre_vocabulary:
            genre_field = '  "genres": ["copy exact names from Available genres"],\n'
            genre_rules = (
                "- Available genres (copy these spellings exactly; pick every one that "
                "fits, or [] if none do; never invent a genre): "
                + ", ".join(genre_vocabulary)
                + "\n"
                "- Match the user's wording to these even across languages, e.g. "
                '"funny"/"comedy" -> the German comedy tags in the list.\n'
            )
        else:
            genre_field = '  "genres": ["genre names like Horror, Drama, Comedy"],\n'
            genre_rules = ""
        system_message = (
            "You are a structured-intent parser for a cinema search API. "
            "Extract every filter mentioned in the prompt and respond ONLY with a "
            "single JSON object.\n"
            f"Today's date is {today.isoformat()} and tomorrow is {tomorrow.isoformat()}.\n"
            "\n"
            "JSON schema:\n"
            "{\n"
            '  "intent": "movies|shows|cinemas|unknown",\n'
            '  "searchQuery": "the prompt\'s salient subject (title/name), or null '
            'only for a genuine open-ended browse",\n'
            + genre_field
            + '  "date": "YYYY-MM-DD, today, tomorrow, or null",\n'
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
            "- searchQuery: copy the prompt's salient subject verbatim — a movie title, "
            "franchise name, or cinema name — even if it is short, foreign-language, "
            "accented, or contains unusual punctuation (e.g. 'Chéri, ich komme' or "
            "'Tuner' are titles, not noise; copy them as-is). If the whole prompt is "
            "essentially just a name, that name IS the searchQuery — do not leave it "
            "null because it looks unfamiliar.\n"
            "- searchQuery is null ONLY for a genuine open-ended browse with no named "
            "subject, e.g. 'what's playing in Berlin', 'movies tonight', 'horror films'. "
            "Genre-only or filter-only prompts also leave searchQuery null.\n"
            "- When genuinely unsure whether a prompt names a subject or not, prefer "
            "copying it into searchQuery over leaving it null: a wrong guess still "
            "returns a title-filtered result, while a wrong null silently returns the "
            "entire unfiltered catalogue.\n"
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
            "- Return only the JSON object, no markdown or explanation.\n" + genre_rules
        )
        try:
            data = await self.llm_client.chat_completion(
                system_message=system_message,
                user_message=request.prompt,
                response_format={"type": "json_object"},
            )
        except LLMError:
            logger.exception("LLM parsing failed; falling back to heuristic parser")
            return self._heuristic_parse(request.prompt)

        try:
            return ParsedIntent.model_validate(self._normalise_llm_fields(data))
        except ValidationError:
            # The model is asked for arrays but, for a prompt with nothing to put in
            # one, sometimes emits null instead of []; normalising should already
            # cover that. A validation error surviving normalisation means a shape
            # the model returned that we did not anticipate — degrade to the
            # heuristic parser rather than 500 the request over a JSON quirk.
            logger.warning("LLM response failed validation even after normalising: %r", data)
            return self._heuristic_parse(request.prompt)

    _LIST_FIELDS = ("genres", "flags", "actors", "directors", "cast")

    @classmethod
    def _normalise_llm_fields(cls, data: object) -> object:
        """Coerce a null list field to ``[]``.

        The JSON schema in the prompt asks for arrays, but the model sometimes
        emits ``null`` for "nothing here" instead — Groq's JSON mode does not
        enforce the schema, only that the output is valid JSON.
        """
        if not isinstance(data, dict):
            return data
        return {
            key: ([] if key in cls._LIST_FIELDS and value is None else value)
            for key, value in data.items()
        }

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
    @staticmethod
    def _has_any_filter(parsed: ParsedIntent) -> bool:
        """Whether the parser extracted anything to actually search on.

        ``location`` is excluded deliberately: it is usually supplied by the caller
        rather than extracted from the prompt, so it says nothing about whether the
        prompt itself was understood.
        """
        return any(
            (
                parsed.search_query,
                parsed.genres,
                parsed.date,
                parsed.cinema_id,
                parsed.flags,
                parsed.language,
                parsed.duration_min is not None,
                parsed.duration_max is not None,
                parsed.year is not None,
                parsed.year_min is not None,
                parsed.year_max is not None,
                parsed.rating_min is not None,
                parsed.rating_max is not None,
                parsed.actors,
                parsed.directors,
                parsed.cast,
            ),
        )

    async def _execute_intent(
        self,
        parsed: ParsedIntent,
        live_service: KinoheldService,
        cache: KinoheldCache,
        sources: SourceCaches,
        use_cache: bool,
        limit: int,
    ) -> tuple[list[UnifiedCinema], list[UnifiedMovie], list[UnifiedShow]]:
        # An unparseable prompt yields no intent and no filters. Falling through to
        # the movie branch would run an unfiltered browse and return the whole
        # catalogue, which reads as a confident answer rather than a failure. A
        # genuine browse ("what's playing in Berlin") parses as intent=movies, so it
        # is unaffected.
        if parsed.intent == "unknown" and not self._has_any_filter(parsed):
            logger.info("Prompt yielded no intent and no filters; returning no results")
            return [], [], []

        if parsed.intent == "cinemas":
            cinemas = await self._search_cinemas(
                parsed, live_service, cache, sources, use_cache, limit
            )
            return cinemas, [], []

        if parsed.intent == "shows":
            return await self._search_shows(parsed, live_service, cache, sources, use_cache, limit)

        # Default: movies
        movies = await self._search_movies(parsed, live_service, cache, sources, use_cache, limit)
        return [], movies, []

    async def _search_cinemas(
        self,
        parsed: ParsedIntent,
        live_service: KinoheldService,
        cache: KinoheldCache,
        sources: SourceCaches,
        use_cache: bool,
        limit: int,
    ) -> list[UnifiedCinema]:
        params = CinemaSearchParams(
            search=parsed.search_query,
            location=parsed.location,
            limit=limit,
        )
        if use_cache:
            kinoheld = await cache.search_cinemas(params)
        else:
            kinoheld = await live_service.search_cinemas(params)
        results = [kinoheld_cinema_to_unified(item) for item in kinoheld]

        # Cinetixx and Yorck cinemas both carry city/district text, so the location
        # doubles as the search term when no explicit title was given.
        term = parsed.search_query or parsed.location
        if sources.cinetixx is not None:
            cinetixx = await sources.cinetixx.search_cinemas(
                CinetixxCinemaSearchParams(search=term, limit=limit),
            )
            results.extend(cinetixx_cinema_to_unified(item) for item in cinetixx)
        if sources.yorck is not None:
            yorck = await sources.yorck.search_cinemas(
                YorckCinemaSearchParams(search=term, limit=limit),
            )
            results.extend(yorck_cinema_to_unified(item) for item in yorck)

        return results[:limit]

    async def _search_movies(
        self,
        parsed: ParsedIntent,
        live_service: KinoheldService,
        cache: KinoheldCache,
        sources: SourceCaches,
        use_cache: bool,
        limit: int,
    ) -> list[UnifiedMovie]:
        # Fetch a generous candidate set so post-filters have enough data.
        candidate_limit = max(limit, 100)
        movies = await self._kinoheld_movies(
            parsed,
            live_service,
            cache,
            use_cache,
            candidate_limit,
            search=parsed.search_query,
        )
        movies.extend(await self._extra_source_movies(parsed, sources, candidate_limit))

        # Apply deterministic post-filters.
        movies = self._apply_movie_filters(movies, parsed)

        if parsed.search_query and settings.llm_fallback_search_enabled and not movies:
            # Upstream's own matching is stricter than a substring match, so retry
            # against a broad unfiltered slice locally. Previously this passed an
            # always-empty list and so could never return anything.
            logger.info("No movies found by upstream search; trying fallback title search")
            candidates = await self._kinoheld_movies(
                parsed,
                live_service,
                cache,
                use_cache,
                candidate_limit,
                search=None,
            )
            candidates.extend(await self._extra_source_movies(parsed, sources, candidate_limit, ""))
            movies = self._apply_movie_filters(
                self._fallback_text_search(candidates, parsed.search_query),
                parsed,
            )

        return movies[:limit]

    @staticmethod
    async def _kinoheld_movies(
        parsed: ParsedIntent,
        live_service: KinoheldService,
        cache: KinoheldCache,
        use_cache: bool,
        limit: int,
        search: str | None,
    ) -> list[UnifiedMovie]:
        params = MovieSearchParams(search=search, location=parsed.location, limit=limit)
        movies = (
            await cache.search_movies(params)
            if use_cache
            else await live_service.search_movies(params)
        )
        return [kinoheld_movie_to_unified(movie) for movie in movies]

    async def _extra_source_movies(
        self,
        parsed: ParsedIntent,
        sources: SourceCaches,
        limit: int,
        search_override: str | None = None,
    ) -> list[UnifiedMovie]:
        """Cinetixx and Yorck movies, scoped to the requested location.

        Neither provider's movie search takes a location, and both span more than
        one city, so the location is applied by way of their cached shows: a movie
        qualifies when it screens at a venue in the requested place.
        """
        search = parsed.search_query if search_override is None else search_override
        results: list[UnifiedMovie] = []

        if sources.cinetixx is not None:
            movies = await sources.cinetixx.search_movies(
                CinetixxMovieSearchParams(search=search or None, limit=1000),
            )
            if parsed.location:
                dataset = await sources.cinetixx.get_dataset()
                playing = {
                    identifier
                    for show in dataset.shows
                    if _contains(show.city, parsed.location)
                    or _contains(show.cinema_name, parsed.location)
                    for identifier in (show.movie_id, show.event_id)
                    if identifier
                }
                movies = [
                    movie
                    for movie in movies
                    if playing & {movie.id, movie.movie_id, movie.event_id}
                ]
            results.extend(cinetixx_movie_to_unified(movie) for movie in movies[:limit])

        if sources.yorck is not None:
            movies = await sources.yorck.search_movies(
                YorckMovieSearchParams(search=search or None, limit=1000),
            )
            if parsed.location:
                dataset = await sources.yorck.get_dataset()
                if not any(
                    _contains(cinema.city, parsed.location)
                    or _contains(cinema.district, parsed.location)
                    or _contains(cinema.name, parsed.location)
                    for cinema in dataset.cinemas
                ):
                    movies = []
            results.extend(yorck_movie_to_unified(movie) for movie in movies[:limit])

        return results

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
        sources: SourceCaches,
        use_cache: bool,
        limit: int,
    ) -> tuple[list[UnifiedCinema], list[UnifiedMovie], list[UnifiedShow]]:
        # Determine target cinemas.
        cinemas: list[UnifiedCinema] = []
        if parsed.cinema_id:
            try:
                cinemas = [
                    kinoheld_cinema_to_unified(
                        await self._get_cinema(parsed.cinema_id, live_service, cache, use_cache),
                    ),
                ]
            except KinoheldNotFoundError:
                cinemas = []
        elif parsed.location or parsed.search_query:
            # Only Kinoheld here: this list drives the per-cinema show fetch below and
            # is capped, so mixing the other sources in would push their venues out of
            # the cap while their shows still arrived, leaving those unattributable.
            # They are added back from the shows actually found.
            params = CinemaSearchParams(
                search=parsed.search_query,
                location=parsed.location,
                limit=20,
            )
            found = (
                await cache.search_cinemas(params)
                if use_cache
                else await live_service.search_cinemas(params)
            )
            cinemas = [kinoheld_cinema_to_unified(item) for item in found]
        else:
            # No location/cinema context: search movies instead and explain via intent.
            movies = await self._search_movies(
                parsed, live_service, cache, sources, use_cache, limit
            )
            return [], movies, []

        # Determine target movies when a title/genre/actor/director is specified.
        movie_ids: set[str] | None = None
        if parsed.search_query or parsed.genres or parsed.actors or parsed.directors or parsed.cast:
            candidate_movies = await self._kinoheld_movies(
                parsed, live_service, cache, use_cache, 100, search=parsed.search_query
            )
            candidate_movies.extend(await self._extra_source_movies(parsed, sources, 1000))
            movie_ids = {m.id for m in self._apply_movie_filters(candidate_movies, parsed)}

        date = self._safe_date(parsed.date)
        shows: list[UnifiedShow] = []
        for cinema in (item for item in cinemas if item.source == "kinoheld"):
            params = ShowSearchParams(
                cinema_id=cinema.source_id,
                date=date,
                days=settings.kinoheld_sync_show_days if date is None else None,
                movie_id=None,
            )
            if use_cache:
                cinema_shows = await cache.search_shows(params)
                missing_dates = await cache.get_missing_show_dates(
                    cinema.source_id,
                    self._date_range(date),
                )
                if missing_dates:
                    await cache.cache_shows_for_cinema(
                        live_service,
                        cinema.source_id,
                        missing_dates,
                    )
                    cinema_shows = await cache.search_shows(params)
            else:
                cinema_shows = await live_service.search_shows(params)
            shows.extend(kinoheld_show_to_unified(show) for show in cinema_shows)

        extra_shows, extra_cinemas = await self._extra_source_shows(parsed, sources, date)
        shows.extend(extra_shows)

        if movie_ids is not None:
            shows = [s for s in shows if s.movie and s.movie.id in movie_ids]
        if parsed.flags:
            shows = self._filter_by_flags(shows, parsed.flags)

        surviving = {show.source for show in shows}
        cinemas.extend(item for item in extra_cinemas if item.source in surviving)

        unique_movies: dict[tuple[str, str], UnifiedMovie] = {}
        for show in shows:
            if show.movie is None:
                continue
            key = (show.source, show.movie.id)
            if key not in unique_movies:
                unique_movies[key] = UnifiedMovie(
                    **show.movie.model_dump(by_alias=True),
                    source=show.source,
                    sourceId=show.movie.id,
                )
        return cinemas, list(unique_movies.values()), shows[:limit]

    async def _extra_source_shows(
        self,
        parsed: ParsedIntent,
        sources: SourceCaches,
        date: dt.date | None,
    ) -> tuple[list[UnifiedShow], list[UnifiedCinema]]:
        """Cinetixx and Yorck shows for the date, plus the venues they screen at.

        A ``Show`` carries no reference back to its cinema, so the venues are what
        let a client attribute these screenings; they are resolved here from the
        shows that actually survived filtering.
        """
        days = settings.kinoheld_sync_show_days if date is None else None
        start = date or dt.date.today()
        shows: list[UnifiedShow] = []
        cinema_ids: dict[str, set[str]] = {"cinetixx": set(), "yorck": set()}

        def in_location(city: str | None, cinema_name: str | None) -> bool:
            if not parsed.location:
                return True
            return _contains(city, parsed.location) or _contains(cinema_name, parsed.location)

        if sources.cinetixx is not None:
            for show in await sources.cinetixx.search_shows(
                CinetixxShowSearchParams(date=start, days=days, limit=1000),
            ):
                if in_location(show.city, show.cinema_name):
                    shows.append(cinetixx_show_to_unified(show))
                    if show.cinema_id:
                        cinema_ids["cinetixx"].add(show.cinema_id)

        if sources.yorck is not None:
            for show in await sources.yorck.search_shows(
                YorckShowSearchParams(date=start, days=days, limit=1000),
            ):
                if in_location(show.city, show.cinema_name):
                    shows.append(yorck_show_to_unified(show))
                    if show.cinema_id:
                        cinema_ids["yorck"].add(show.cinema_id)

        cinemas: list[UnifiedCinema] = []
        for cinema_id in sorted(cinema_ids["cinetixx"]):
            with contextlib.suppress(Exception):
                cinemas.append(
                    cinetixx_cinema_to_unified(await sources.cinetixx.get_cinema(cinema_id)),
                )
        for cinema_id in sorted(cinema_ids["yorck"]):
            with contextlib.suppress(Exception):
                cinemas.append(yorck_cinema_to_unified(await sources.yorck.get_cinema(cinema_id)))
        return shows, cinemas

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
        """Keep movies carrying any requested genre, tolerating compound tags.

        Grounding the parser in the real vocabulary gets most of the way, but the
        catalogue splits one concept across many labels, so a request for
        ``Komödie`` should still match ``Actionkomödie`` and ``Familienkomödie``.
        """
        wanted = {name.casefold().strip() for name in genres if name and name.strip()}
        if not wanted:
            return movies

        def matches(movie: Movie) -> bool:
            for genre in movie.genres:
                actual = (genre.name or "").casefold().strip()
                if not actual:
                    continue
                if any(w == actual or w in actual or actual in w for w in wanted):
                    return True
            return False

        return [movie for movie in movies if matches(movie)]

    @staticmethod
    def _filter_by_flags(shows: list[UnifiedShow], flags: list[str]) -> list[UnifiedShow]:
        wanted = {f.casefold() for f in flags}
        return [
            s
            for s in shows
            if any(f.code and f.code.casefold() in wanted for f in s.flags)
            or any(f.name.casefold() in wanted for f in s.flags)
        ]

    @staticmethod
    def _fallback_text_search(movies: list[UnifiedMovie], query: str) -> list[UnifiedMovie]:
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
