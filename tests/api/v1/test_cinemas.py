"""Tests for cinema API endpoints."""

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


class TestListCinemas:
    def test_returns_cinemas(self, client: TestClient, mock_graphql_client: AsyncMock):
        mock_graphql_client.execute.return_value = {
            "cinemas": [
                {
                    "id": "1",
                    "name": "Kino Berlin",
                    "thumbnail": [{"url": "https://example.com/t.png"}],
                    "heroImage": [{"url": "https://example.com/h.jpg"}],
                },
            ],
        }

        response = client.get("/api/v1/cinemas")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "1"
        assert data[0]["thumbnail"]["url"] == "https://example.com/t.png"


class TestGetCinema:
    def test_returns_cinema(self, client: TestClient, mock_graphql_client: AsyncMock):
        mock_graphql_client.execute.return_value = {
            "cinema": {
                "id": "1",
                "name": "Kino Berlin",
                "thumbnail": [{"url": "https://example.com/t.png"}],
                "heroImage": [{"url": "https://example.com/h.jpg"}],
            },
        }

        response = client.get("/api/v1/cinemas/1")

        assert response.status_code == 200
        assert response.json()["id"] == "1"

    def test_not_found(self, client: TestClient, mock_graphql_client: AsyncMock):
        mock_graphql_client.execute.return_value = {"cinema": None}

        response = client.get("/api/v1/cinemas/missing")

        assert response.status_code == 404
        assert response.json()["detail"] == "Cinema missing not found"
