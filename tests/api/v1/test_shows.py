"""Tests for show API endpoints."""

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


class TestListShows:
    def test_returns_shows(self, client: TestClient, mock_graphql_client: AsyncMock):
        mock_graphql_client.execute.return_value = {
            "shows": [
                {
                    "id": "42",
                    "name": "Dune 20:00",
                    "beginning": {"formatted": "20:00", "timestamp": 1718452800},
                    "isSoldOut": False,
                },
            ],
        }

        response = client.get("/api/v1/shows?cinemaId=123&date=2024-06-15&days=3")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "42"
        assert data[0]["isSoldOut"] is False

    def test_serializes_date_in_graphql_variables(
        self,
        client: TestClient,
        mock_graphql_client: AsyncMock,
    ):
        mock_graphql_client.execute.return_value = {"shows": []}

        client.get("/api/v1/shows?cinemaId=123&date=2024-06-15")

        variables = mock_graphql_client.execute.call_args.kwargs["variables"]
        assert variables["date"] == "2024-06-15"
        assert variables["cinemaId"] == "123"

    def test_missing_cinema_id_returns_validation_error(self, client: TestClient):
        response = client.get("/api/v1/shows")

        assert response.status_code == 422
