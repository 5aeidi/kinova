"""Async HTTP client for Cinetixx endpoints."""

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import CinetixxAPIError

logger = logging.getLogger(__name__)


class CinetixxClient:
    """Thin async wrapper around httpx for Cinetixx HTTP requests."""

    def __init__(
        self,
        show_info_url: str = settings.cinetixx_show_info_url,
        cinema_search_url: str = settings.cinetixx_cinema_search_url,
        timeout: float = settings.cinetixx_request_timeout,
        pool_limit: int = settings.cinetixx_pool_limits,
    ) -> None:
        self.show_info_url = show_info_url
        self.cinema_search_url = cinema_search_url
        limits = httpx.Limits(max_keepalive_connections=pool_limit, max_connections=pool_limit * 2)
        self._client = httpx.AsyncClient(timeout=timeout, limits=limits)

    async def __aenter__(self) -> "CinetixxClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def get_show_info(self, mandator_id: int) -> tuple[str, str | None]:
        """Fetch legacy showtime data for a Cinetixx mandator ID."""
        logger.debug(
            "cinetixx.request endpoint=GetShowInfoV6 mandator_id=%s",
            mandator_id,
        )
        response = await self._client.get(self.show_info_url, params={"mandatorId": mandator_id})

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CinetixxAPIError(
                f"Upstream Cinetixx API returned HTTP {exc.response.status_code}",
            ) from exc

        return response.text, response.headers.get("content-type")

    async def search_cinemas(
        self,
        search: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        """Search Cinetixx booking cinemas, including their mandator IDs."""
        params: dict[str, Any] = {
            "search": search or "",
            "lat": lat or 0,
            "lon": lon or 0,
        }
        if page is not None:
            params["page"] = page
        if page_size is not None:
            params["pageSize"] = page_size

        logger.debug("cinetixx.request endpoint=cinemas.search search=%s", search)
        response = await self._client.get(self.cinema_search_url, params=params)
        return self._json_response(response)

    async def get_cinema(self, cinema_id: str) -> dict[str, Any]:
        """Fetch one Cinetixx booking cinema by cinema ID."""
        url = f"{self.cinema_search_url.rstrip('/')}/cinema/{cinema_id}"
        logger.debug("cinetixx.request endpoint=cinemas.cinema cinema_id=%s", cinema_id)
        response = await self._client.get(url)
        return self._json_response(response)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    @staticmethod
    def _json_response(response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CinetixxAPIError(
                f"Upstream Cinetixx API returned HTTP {exc.response.status_code}",
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise CinetixxAPIError("Cinetixx returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise CinetixxAPIError("Cinetixx returned an unexpected JSON shape")
        return data
