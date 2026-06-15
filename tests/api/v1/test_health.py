"""Tests for the health endpoint."""

from fastapi.testclient import TestClient

from app.main import create_application


def test_health_check():
    app = create_application()
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "Kinova"
