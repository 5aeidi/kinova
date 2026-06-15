"""Tests for movie API endpoints."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_application
from app.services.kinoheld import KinoheldService


@pytest.fixture
def client(mock_graphql_client: AsyncMock):
    app = create_application()

    async def override():
        yield KinoheldService(mock_graphql_client)

    from app.api.deps import get_kinoheld_service

    app.dependency_overrides[get_kinoheld_service] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestListMovies:
    def test_returns_movies(self, client: TestClient, mock_graphql_client: AsyncMock):
        mock_graphql_client.execute.return_value = {
            "movies": [
                {
                    "id": "99",
                    "title": "Dune",
                    "thumb": [{"url": "https://example.com/t.jpg"}],
                    "heroImage": [{"url": "https://example.com/h.jpg"}],
                },
            ],
        }

        response = client.get("/api/v1/movies")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "99"
        assert data[0]["thumb"]["url"] == "https://example.com/t.jpg"


class TestGetMovie:
    def test_not_found(self, client: TestClient, mock_graphql_client: AsyncMock):
        mock_graphql_client.execute.return_value = {"movie": None}

        response = client.get("/api/v1/movies/missing")

        assert response.status_code == 404
        assert response.json()["detail"] == "Movie missing not found"
