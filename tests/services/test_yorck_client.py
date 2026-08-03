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
            if "cdn.contentful.com" in request.url.host:
                return httpx.Response(500, json={"message": "boom"})
            return httpx.Response(200, text=_page_html())

        client = _client_with(handler)
        try:
            with pytest.raises(YorckAPIError):
                await client.get_session_seating()
        finally:
            await client.close()


def _page_html(chunk: str = "/_next/static/chunks/pages/_app-abc123.js") -> str:
    return f'<html><body><script src="{chunk}"></script></body></html>'


def _bundle(space: str = "spacenew", token: str = "TOKEN-FROM-THE-SITE-BUNDLE") -> str:
    return f'x=(0,u.createClient)({{space:"{space}",accessToken:"{token}",environment:"master"}});'


@pytest.mark.asyncio
class TestContentfulCredentialRotation:
    async def test_rejected_token_is_rescraped_and_request_retried(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "cdn.contentful.com":
                token = request.url.params["access_token"]
                calls.append(f"cda:{token}")
                if token != "TOKEN-FROM-THE-SITE-BUNDLE":
                    return httpx.Response(401, json={"message": "access token invalid"})
                return httpx.Response(
                    200,
                    json={
                        "total": 1,
                        "items": [
                            {"sys": {"id": "1002-1"}, "fields": {"allocatedSeating": False}},
                        ],
                    },
                )
            if request.url.path.endswith(".js"):
                calls.append("bundle")
                return httpx.Response(200, text=_bundle())
            calls.append("page")
            return httpx.Response(200, text=_page_html())

        client = _client_with(handler)
        try:
            seating = await client.get_session_seating()
        finally:
            await client.close()

        assert seating == {"1002-1": False}
        # Configured token rejected, credentials re-scraped from the site, retry wins.
        assert calls[0].startswith("cda:")
        assert calls[1:3] == ["page", "bundle"]
        assert calls[3] == "cda:TOKEN-FROM-THE-SITE-BUNDLE"
        # The scraped space replaces the configured one too.
        assert await client.get_contentful_credentials() == (
            "spacenew",
            "TOKEN-FROM-THE-SITE-BUNDLE",
        )

    async def test_scraped_credentials_are_reused_without_rescraping(self):
        bundle_fetches = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal bundle_fetches
            if request.url.host == "cdn.contentful.com":
                if request.url.params["access_token"] != "TOKEN-FROM-THE-SITE-BUNDLE":
                    return httpx.Response(401, json={"message": "access token invalid"})
                return httpx.Response(200, json={"total": 0, "items": []})
            if request.url.path.endswith(".js"):
                bundle_fetches += 1
                return httpx.Response(200, text=_bundle())
            return httpx.Response(200, text=_page_html())

        client = _client_with(handler)
        try:
            await client.get_session_seating()
            await client.get_session_seating()
        finally:
            await client.close()

        assert bundle_fetches == 1

    async def test_unscrapable_bundle_surfaces_the_original_failure(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "cdn.contentful.com":
                return httpx.Response(401, json={"message": "access token invalid"})
            if request.url.path.endswith(".js"):
                return httpx.Response(200, text="no credentials in here")
            return httpx.Response(200, text=_page_html())

        client = _client_with(handler)
        try:
            with pytest.raises(YorckAPIError):
                await client.get_session_seating()
        finally:
            await client.close()
