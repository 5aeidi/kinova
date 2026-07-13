"""Tests for the Cinetixx cache."""

import json
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.schemas.cinetixx import CinetixxMandatorSearchParams, CinetixxShowSearchParams
from app.services.cinetixx import CinetixxService
from app.services.cinetixx_cache import CinetixxCache
from tests.services.test_cinetixx_service import SAMPLE_DISCOVERY, SAMPLE_ROW


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

    async def test_refresh_keeps_on_demand_mandators_when_no_sync_ids(self, monkeypatch):
        monkeypatch.setattr(settings, "cinetixx_sync_mandator_ids", [])
        client = AsyncMock()
        client.get_show_info.return_value = (
            json.dumps({"shows": [SAMPLE_ROW]}),
            "application/json",
        )
        service = CinetixxService(client)
        cache = CinetixxCache()

        await cache.cache_mandator(service, 42)
        await cache.refresh(service)

        snapshot = cache.snapshot()
        assert snapshot["mandators"] == [42]
        assert snapshot["shows"] == 1
        assert client.get_show_info.await_count == 2

    async def test_refresh_keeps_stale_mandator_when_fetch_fails(self, monkeypatch):
        monkeypatch.setattr(settings, "cinetixx_sync_mandator_ids", [])
        client = AsyncMock()
        client.get_show_info.side_effect = [
            (json.dumps({"shows": [SAMPLE_ROW]}), "application/json"),
            RuntimeError("upstream unavailable"),
        ]
        service = CinetixxService(client)
        cache = CinetixxCache()

        await cache.cache_mandator(service, 42)
        await cache.refresh(service)

        snapshot = cache.snapshot()
        assert snapshot["mandators"] == [42]
        assert snapshot["shows"] == 1
        assert client.get_show_info.await_count == 2

    async def test_refresh_discovers_configured_searches(self, monkeypatch):
        monkeypatch.setattr(settings, "cinetixx_sync_discovery_searches", ["acud"])
        monkeypatch.setattr(settings, "cinetixx_sync_mandator_ids", [])
        monkeypatch.setattr(settings, "cinetixx_discovery_terms", ["a"])
        client = AsyncMock()
        client.search_cinemas.return_value = {
            "searchList": [{"searchObject": SAMPLE_DISCOVERY}],
        }
        client.get_show_info.return_value = (
            json.dumps({"shows": [SAMPLE_ROW]}),
            "application/json",
        )
        service = CinetixxService(client)
        cache = CinetixxCache()

        await cache.refresh(service)

        snapshot = cache.snapshot()
        discovered = await cache.search_mandators(CinetixxMandatorSearchParams(search="acud"))
        assert snapshot["discovered_mandators"] == 1
        assert snapshot["mandators"] == [1627457285]
        assert discovered[0].mandator_id == 1627457285
        assert client.search_cinemas.await_count == 2
        client.get_show_info.assert_awaited_once_with(1627457285)
