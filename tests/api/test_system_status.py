from fastapi.testclient import TestClient

from chess_coach.api.app import app
from chess_coach.api.dependencies import get_system_status
from chess_coach.application.system import DependencyStatus, SystemStatus


def test_status_serializes_independent_readiness_without_running_integrations() -> None:
    def fake_status() -> SystemStatus:
        return SystemStatus(
            stockfish=DependencyStatus("unavailable", "Stockfish was not found."),
            ollama=DependencyStatus("available", "Ollama is reachable."),
            ollama_model=DependencyStatus(
                "unavailable", "Install the configured model."
            ),
        )

    app.dependency_overrides[get_system_status] = fake_status
    try:
        response = TestClient(app).get("/api/v1/system/status")
    finally:
        app.dependency_overrides.pop(get_system_status)
    assert response.status_code == 200
    assert response.json() == {
        "api": {"state": "available", "detail": "FastAPI is running."},
        "stockfish": {"state": "unavailable", "detail": "Stockfish was not found."},
        "ollama": {"state": "available", "detail": "Ollama is reachable."},
        "ollama_model": {
            "state": "unavailable",
            "detail": "Install the configured model.",
        },
    }
