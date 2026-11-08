from fastapi.testclient import TestClient

from chess_coach.api.app import app

client = TestClient(app, base_url="http://127.0.0.1")


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
