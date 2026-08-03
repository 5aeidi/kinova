"""Async HTTP client for the Yorck Kinogruppe public Next.js data endpoints."""

import asyncio
import logging
import re
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import YorckAPIError

logger = logging.getLogger(__name__)

_BUILD_ID_RE = re.compile(r'"buildId"\s*:\s*"([^"]+)"')
_CONTENTFUL_PAGE_SIZE = 1000


class YorckClient:
    """Thin async wrapper around httpx for Yorck data requests.

    Yorck serves its programme as Next.js data JSON under
    ``/_next/data/<buildId>/<locale>/<path>.json``. The build ID changes on every
    site deploy, so it is scraped from an HTML page, memoized, and re-resolved
    once when a data request comes back 404 with the cached ID.
    """

    def __init__(
        self,
        base_url: str = settings.yorck_base_url,
        locale: str = settings.yorck_locale,
        timeout: float = settings.yorck_request_timeout,
        pool_limit: int = settings.yorck_pool_limits,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.locale = locale.strip("/")
        limits = httpx.Limits(max_keepalive_connections=pool_limit, max_connections=pool_limit * 2)
        self._client = httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=True)
        self._build_id: str | None = None
        self._build_id_lock = asyncio.Lock()

    async def __aenter__(self) -> "YorckClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def get_build_id(self, force_refresh: bool = False) -> str:
        """Return the current Next.js build ID, scraping it from the cinemas page."""
        async with self._build_id_lock:
            if self._build_id is not None and not force_refresh:
                return self._build_id

            url = f"{self.base_url}/{self.locale}/cinemas"
            logger.debug("yorck.request endpoint=build-id url=%s", url)
            try:
                response = await self._client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise YorckAPIError(f"Failed to load Yorck build ID page: {exc}") from exc

            match = _BUILD_ID_RE.search(response.text)
            if match is None:
                raise YorckAPIError("Could not find a Next.js buildId on the Yorck site")
            self._build_id = match.group(1)
            logger.info("Resolved Yorck Next.js build ID %s", self._build_id)
            return self._build_id

    async def get_page_data(self, path: str) -> dict[str, Any]:
        """Fetch ``pageProps`` for a Yorck page path such as ``cinemas`` or ``films``.

        Retries once with a freshly scraped build ID when the cached one has been
        invalidated by a site deploy (the data route then returns 404).
        """
        build_id = await self.get_build_id()
        response = await self._request_page(build_id, path)
        if response.status_code == 404 and self._build_id == build_id:
            build_id = await self.get_build_id(force_refresh=True)
            response = await self._request_page(build_id, path)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise YorckAPIError(
                f"Upstream Yorck API returned HTTP {exc.response.status_code} for {path!r}",
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise YorckAPIError("Yorck returned invalid JSON") from exc

        page_props = data.get("pageProps") if isinstance(data, dict) else None
        if not isinstance(page_props, dict):
            raise YorckAPIError("Yorck returned an unexpected JSON shape")
        return page_props

    async def get_session_seating(self) -> dict[str, bool]:
        """Return ``{session id: allocatedSeating}`` for every upcoming session.

        The Next.js programme data omits ``allocatedSeating``, but the booking flow
        needs it to decide whether a session starts at seat selection or straight at
        ticket selection. It is read from the same Contentful space the website
        itself queries client-side, projecting only the one field.
        """
        url = (
            f"{settings.yorck_contentful_base_url.rstrip('/')}"
            f"/spaces/{settings.yorck_contentful_space_id}"
            f"/environments/{settings.yorck_contentful_environment}/entries"
        )
        params: dict[str, Any] = {
            "access_token": settings.yorck_contentful_access_token,
            "content_type": "session",
            "select": "sys.id,fields.allocatedSeating",
            "include": 0,
            "limit": _CONTENTFUL_PAGE_SIZE,
        }

        seating: dict[str, bool] = {}
        skip = 0
        while True:
            logger.debug("yorck.request endpoint=session-seating skip=%d", skip)
            try:
                response = await self._client.get(url, params={**params, "skip": skip})
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise YorckAPIError(f"Failed to load Yorck session seating: {exc}") from exc

            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list) or not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                sys_block = item.get("sys")
                fields = item.get("fields")
                if not isinstance(sys_block, dict) or not isinstance(fields, dict):
                    continue
                session_id = sys_block.get("id")
                allocated = fields.get("allocatedSeating")
                if session_id is not None and isinstance(allocated, bool):
                    seating[str(session_id)] = allocated

            skip += len(items)
            total = payload.get("total")
            if not isinstance(total, int) or skip >= total:
                break
        return seating

    async def _request_page(self, build_id: str, path: str) -> httpx.Response:
        url = f"{self.base_url}/_next/data/{build_id}/{self.locale}/{path.strip('/')}.json"
        logger.debug("yorck.request endpoint=page-data path=%s", path)
        try:
            return await self._client.get(url)
        except httpx.HTTPError as exc:
            raise YorckAPIError(f"Yorck request failed for {path!r}: {exc}") from exc
