"""Async GraphQL HTTP client built on httpx."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import KinoheldAPIError

logger = logging.getLogger(__name__)


class GraphQLClient:
    """Thin async wrapper around httpx for GraphQL requests."""

    def __init__(
        self,
        url: str = settings.kinoheld_graphql_url,
        timeout: float = settings.kinoheld_request_timeout,
        pool_limit: int = settings.kinoheld_pool_limits,
    ) -> None:
        self.url = url
        self.timeout = timeout
        limits = httpx.Limits(max_keepalive_connections=pool_limit, max_connections=pool_limit * 2)
        self._client = httpx.AsyncClient(timeout=timeout, limits=limits)

    async def __aenter__(self) -> "GraphQLClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query/mutation and return the ``data`` payload."""
        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        if operation_name is not None:
            payload["operationName"] = operation_name

        logger.debug(
            "graphql.request url=%s operation=%s",
            self.url,
            operation_name,
        )

        response = await self._client.post(self.url, json=payload)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise KinoheldAPIError(
                f"Upstream GraphQL API returned HTTP {exc.response.status_code}",
            ) from exc

        body = response.json()

        if errors := body.get("errors"):
            messages = [e.get("message", "Unknown GraphQL error") for e in errors]
            raise KinoheldAPIError(
                f"GraphQL errors: {'; '.join(messages)}",
                upstream_errors=errors,
            )

        return body.get("data", {})

    async def close(self) -> None:
        await self._client.aclose()


@asynccontextmanager
async def get_graphql_client() -> AsyncGenerator[GraphQLClient, None]:
    """Dependency-managed client lifecycle context manager."""
    async with GraphQLClient() as client:
        yield client
