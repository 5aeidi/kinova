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


class NaturalLanguageResult(BaseModel):
    """Unified response for a natural-language search."""

    model_config = ConfigDict(populate_by_name=True)

    prompt: str
    intent: str
    parsed: ParsedIntent
    cinemas: list[Cinema] = Field(default_factory=list)
    movies: list[Movie] = Field(default_factory=list)
    shows: list[Show] = Field(default_factory=list)
    total_results: int = Field(default=0, alias="totalResults")


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

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    async def _parse_prompt(self, request: NaturalLanguageQuery) -> ParsedIntent:
        today = dt.date.today()
        tomorrow = today + dt.timedelta(days=1)
        system_message = (
            f"You are a structured-intent parser for a cinema search API.\n"
            f"Today's date is {today.isoformat()} and tomorrow is {tomorrow.isoformat()}.\n"
            "\n"
            "Given a user prompt, extract the search intent and parameters. "
            "Respond ONLY with a JSON object matching this schema:\n"
            "\n"
            "{\n"
            '  "intent": "movies|shows|cinemas|unknown",\n'
            '  "searchQuery": "string or null",\n'
            '  "genres": ["list of genre names"],\n'
            '  "date": "YYYY-MM-DD or relative term today/tomorrow",\n'
            '  "location": "city/location name or null",\n'
            '  "cinemaId": "Kinoheld cinema ID or null",\n'
            '  "flags": ["list of show flags like OmU, OV, 3D, IMAX"],\n'
            '  "language": "language hint like English, German or null"\n'
            "}\n"
            "\n"
            "Rules:\n"
            '- "OmU" = original version with subtitles; '
            '"OV" = original version without subtitles; '
            '"englische Untertitel" / "English subtitles" should be flagged as "OmU".\n'
            '- Infer relative dates: "tomorrow" -> "tomorrow", "today" -> "today".\n'
            '- Infer genre from adjectives like "horror", "comedy", "action".\n'
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

        return ParsedIntent(
            intent=intent,
            search_query=None,
            genres=genres,
            date=date,
            location=None,
            flags=flags,
            language=language,
        )

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
        params = MovieSearchParams(
            search=parsed.search_query,
            location=parsed.location,
            limit=limit,
        )
        if use_cache:
            movies = await cache.search_movies(params)
        else:
            movies = await live_service.search_movies(params)

        # Post-filter by genre when not supported by upstream params.
        if parsed.genres:
            movies = self._filter_by_genres(movies, parsed.genres)

        if parsed.search_query and settings.llm_fallback_search_enabled and not movies:
            logger.info("No movies found by upstream search; trying fallback title search")
            movies = self._fallback_text_search(movies if use_cache else [], parsed.search_query)

        return movies[:limit]

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

        # Determine target movies when a title/genre is specified.
        movie_ids: set[str] | None = None
        if parsed.search_query or parsed.genres:
            movie_params = MovieSearchParams(
                search=parsed.search_query,
                location=parsed.location,
                limit=100,
            )
            if use_cache:
                candidate_movies = await cache.search_movies(movie_params)
            else:
                candidate_movies = await live_service.search_movies(movie_params)
            if parsed.genres:
                candidate_movies = self._filter_by_genres(candidate_movies, parsed.genres)
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
                if not cinema_shows:
                    # On-demand fill for the requested date range.
                    await cache.cache_shows_for_cinema(
                        live_service,
                        cinema.id,
                        self._date_range(date),
                    )
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
