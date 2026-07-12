"""Tests for the Cinetixx cache."""

import json
from unittest.mock import AsyncMock

import pytest

from app.schemas.cinetixx import CinetixxShowSearchParams
from app.services.cinetixx import CinetixxService
from app.services.cinetixx_cache import CinetixxCache
from tests.services.test_cinetixx_service import SAMPLE_ROW


@pytest.mark.asyncio
class TestCinetixxCache:
    async def test_caches_mandator_and_serves_normalized_resources(self):
        client = AsyncMock()
        client.get_show_info.return_value = (
            json.dumps({"shows": [SAMPLE_ROW]}),
            "application/json",
        )
        service = CinetixxService(client)
        cache = CinetixxCache()

        await cache.cache_mandator(service, 42)

        shows = await cache.search_shows(CinetixxShowSearchParams(mandator_id=42, movie_id="456"))
        snapshot = cache.snapshot()

        assert [show.id for show in shows] == ["123"]
        assert snapshot["mandators"] == [42]
        assert snapshot["shows"] == 1
        client.get_show_info.assert_awaited_once_with(42)
