import pytest
from fastapi.testclient import TestClient

from chess_coach.api import dependencies
from chess_coach.api.app import app
from chess_coach.application.system import DependencyStatus

client = TestClient(app, base_url="http://127.0.0.1")


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_and_readiness_skip_optional_probes(api, monkeypatch):
    client, *_ = api

    def unexpected(_):
        raise AssertionError("Core health must not probe optional dependencies")

    monkeypatch.setattr(dependencies, "probe_stockfish", unexpected)
    monkeypatch.setattr(dependencies, "probe_ollama", unexpected)
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json() == {"status": "ready"}


@pytest.mark.parametrize("failure", ["corrupt", "unusable_parent"])
def test_unavailable_database_is_visible_without_fabricated_statistics(
    api, tmp_path, monkeypatch, failure
):
    client, _, _, _, settings, *_ = api
    fixture = tmp_path / "unavailable"
    fixture.write_bytes(b"corrupt SQLite database")
    settings.database_path = fixture if failure == "corrupt" else fixture / "db.sqlite"
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    assert client.get("/health/live").status_code == 200
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "not_ready",
        "code": "DATABASE_UNAVAILABLE"
        if failure == "corrupt"
        else "DATA_DIRECTORY_UNAVAILABLE",
    }
    system = client.get("/api/v1/system").json()
    assert system["components"]["database"]["status"] == "unavailable"
    assert system["statistics"] is None
    assert client.get("/api/v1/games").status_code == 503
    assert fixture.read_bytes() == b"corrupt SQLite database"


def test_migration_stamp_without_required_tables_is_not_ready(api):
    client, sessions, *_ = api
    with sessions.begin() as session:
        session.connection().exec_driver_sql("DROP TABLE games")
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "MIGRATIONS_INCOMPATIBLE"


def test_missing_stockfish_rejects_new_run_and_preserves_analysis(
    analyzed, monkeypatch
):
    client, _, _, _, settings, _, application = analyzed
    del application.dependency_overrides[dependencies.get_system_status]
    monkeypatch.setattr(dependencies, "_probe_cache", None)
    ready = DependencyStatus("available", "Fixture ready")
    monkeypatch.setattr(dependencies, "probe_ollama", lambda _: (ready, ready))
    settings.stockfish_executable = str(
        settings.database_path.parent / "missing-stockfish"
    )
    assert (
        client.get("/health/live").status_code
        == client.get("/health/ready").status_code
        == 200
    )
    system = client.get("/api/v1/system").json()
    assert system["components"]["stockfish"]["status"] == "unavailable"
    assert system["statistics"]["games_analyzed"] == 25
    existing = client.get("/api/v1/games/1/analysis").json()
    start = client.post("/api/v1/analysis-runs", json={})
    assert start.status_code == 503 and start.json()["code"] == "WORKER_UNAVAILABLE"
    assert "Stockfish" in start.json()["message"]
    assert client.get("/api/v1/games/1/analysis").json() == existing
    assert client.get("/api/v1/system").json()["statistics"] == system["statistics"]


def test_system_optional_probe_cache_expires_without_affecting_readiness(
    api, monkeypatch
):
    client, _, _, _, _settings, _, application = api
    del application.dependency_overrides[dependencies.get_system_status]
    monkeypatch.setattr(dependencies, "_probe_cache", None)
    now = 0
    monkeypatch.setattr(dependencies, "monotonic", lambda: now)
    ready = DependencyStatus("available", "Fixture ready")
    down = DependencyStatus("unavailable", "Fixture down")
    ollama = ready
    calls = []

    def engine_probe(_):
        calls.append("stockfish")
        return ready

    monkeypatch.setattr(dependencies, "probe_stockfish", engine_probe)
    monkeypatch.setattr(dependencies, "probe_ollama", lambda _: (ollama, ready))
    assert client.get("/api/v1/system").json()["status"] == "healthy"
    ollama = down
    assert client.get("/api/v1/system").json()["status"] == "healthy"
    now = 6
    report = client.get("/api/v1/system").json()
    assert report["status"] == "degraded"
    assert report["components"]["ollama"]["status"] == "unavailable"
    assert report["components"]["chesscom"] == {"status": "not_checked"}
    assert calls == ["stockfish", "stockfish"]
    assert client.get("/health/ready").status_code == 200
