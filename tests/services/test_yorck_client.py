"""Tests for the Yorck HTTP client."""

import httpx
import pytest

from app.core.exceptions import YorckAPIError
from app.services.yorck_client import YorckClient


def _client_with(handler) -> YorckClient:
    client = YorckClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.asyncio
class TestSessionSeating:
    async def test_pages_until_total_is_reached(self):
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            skip = int(request.url.params["skip"])
            items = [
                {"sys": {"id": f"1002-{skip + i}"}, "fields": {"allocatedSeating": i % 2 == 0}}
                for i in range(2)
            ]
            return httpx.Response(200, json={"total": 4, "skip": skip, "items": items})

        client = _client_with(handler)
        try:
            seating = await client.get_session_seating()
        finally:
            await client.close()

        assert seating == {
            "1002-0": True,
            "1002-1": False,
            "1002-2": True,
            "1002-3": False,
        }
        assert [int(r.url.params["skip"]) for r in requests] == [0, 2]
        assert requests[0].url.params["content_type"] == "session"

    async def test_skips_entries_without_a_boolean_flag(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "total": 3,
                    "items": [
                        {"sys": {"id": "1002-1"}, "fields": {"allocatedSeating": True}},
                        {"sys": {"id": "1002-2"}, "fields": {}},
                        {"fields": {"allocatedSeating": False}},
                    ],
                },
            )

        client = _client_with(handler)
        try:
            seating = await client.get_session_seating()
        finally:
            await client.close()

        assert seating == {"1002-1": True}

    async def test_upstream_failure_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "invalid token"})

        client = _client_with(handler)
        try:
            with pytest.raises(YorckAPIError):
                await client.get_session_seating()
        finally:
            await client.close()
