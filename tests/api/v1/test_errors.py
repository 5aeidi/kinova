"""Tests for error responses, including CORS headers."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_application


@pytest.fixture
def error_client():
    app = create_application()

    async def override_service():
        raise RuntimeError("simulated unexpected error")

    from app.api.deps import get_kinoheld_service

    app.dependency_overrides[get_kinoheld_service] = override_service

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.dependency_overrides.clear()


def test_error_response_includes_cors_headers(error_client: TestClient):
    response = error_client.get(
        "/api/v1/cinemas",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 500
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert response.json()["detail"] == "An unexpected error occurred."
