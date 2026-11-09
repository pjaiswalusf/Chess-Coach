import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config

from chess_coach.api import dependencies
from chess_coach.application.system import DependencyStatus
from chess_coach.cli import main
from chess_coach.config import Settings
from chess_coach.infrastructure.system import diagnostics
from chess_coach.observability.logging import configure_logging

READY = DependencyStatus("available", "Fixture ready")
OFFLINE = DependencyStatus("unavailable", "Start Ollama locally.", "OLLAMA_UNREACHABLE")
UNKNOWN = DependencyStatus("unknown", "Model readiness could not be checked.")
NO_ENGINE = DependencyStatus(
    "unavailable", "Stockfish was not found.", "STOCKFISH_NOT_FOUND"
)


@pytest.fixture
def checks(api, monkeypatch):
    _, _, _, _, settings, _, _ = api
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "probe_stockfish", lambda _: READY)
    monkeypatch.setattr(dependencies, "probe_ollama", lambda _: (READY, READY))
    monkeypatch.setattr(diagnostics, "probe_stockfish", lambda _: READY)
    monkeypatch.setattr(diagnostics, "probe_ollama", lambda _: (READY, READY))
    return api


def test_health_and_doctor_agree_on_degraded_optional_dependency(
    checks, monkeypatch, capsys
):
    client, *_ = checks
    assert client.get("/api/v1/system/health").json()["overall"] == "healthy"
    monkeypatch.setattr(dependencies, "probe_ollama", lambda _: (OFFLINE, UNKNOWN))
    monkeypatch.setattr(diagnostics, "probe_ollama", lambda _: (OFFLINE, UNKNOWN))
    response = client.get("/api/v1/system/health")
    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "degraded"
    assert body["components"]["ollama"]["code"] == "OLLAMA_UNREACHABLE"
    assert body["components"]["ollama_model"]["status"] == "skip"
    assert body["components"]["stockfish"]["status"] == "pass"
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/games").status_code == 200
    main(["doctor", "--deep"])
    output = capsys.readouterr().out
    assert "Overall status: DEGRADED" in output
    assert "Database integrity: SQLite and foreign-key checks passed." in output
    assert "Unavailable: new LLM explanations." in output
    with pytest.raises(SystemExit, match="^1$"):
        main(["doctor", "--strict"])


def test_missing_database_health_does_not_create_file(checks, tmp_path, monkeypatch):
    client, *_ = checks
    path = tmp_path / "missing ?#.db"
    monkeypatch.setattr(
        dependencies, "get_settings", lambda: Settings(database_path=path)
    )
    response = client.get("/api/v1/system/health")
    assert response.status_code == 503
    assert response.json()["components"]["database"]["code"] == "DATABASE_MISSING"
    assert response.json()["components"]["migrations"]["status"] == "skip"
    assert response.json()["overall"] == "unavailable"
    assert str(path) not in response.text
    assert not path.exists()
    assert client.get("/health").status_code == 200


def test_old_schema_blocks_analysis_but_liveness_remains(checks):
    client, _, _, _, settings, *_ = checks
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.downgrade(config, "c18a001")
    response = client.get("/api/v1/system/health")
    assert response.status_code == 503
    assert (
        response.json()["components"]["migrations"]["code"] == "MIGRATIONS_INCOMPATIBLE"
    )
    assert (
        "alembic upgrade head" in response.json()["components"]["migrations"]["action"]
    )
    assert (
        client.post("/api/v1/analysis-runs", json={}).json()["code"]
        == "MIGRATIONS_INCOMPATIBLE"
    )
    assert client.get("/health").status_code == 200
    assert diagnostics.database_checks(settings.database_path)[0].status == "pass"


def test_invalid_configuration_is_actionable(checks, monkeypatch, capsys):
    client, *_ = checks

    def invalid():
        return Settings(stockfish_threads=0)

    monkeypatch.setattr(dependencies, "get_settings", invalid)
    monkeypatch.setenv("CHESS_COACH_STOCKFISH_THREADS", "0")
    response = client.get("/api/v1/system/health")
    assert response.status_code == 503
    assert response.json()["components"]["configuration"]["code"] == "CONFIG_INVALID"
    assert client.get("/health").status_code == 200
    with pytest.raises(SystemExit, match="^1$"):
        main(["doctor"])
    assert "CHESS_COACH settings" in capsys.readouterr().out


def test_unwritable_directory_and_unexpected_doctor_failure(
    checks, monkeypatch, capsys
):
    client, *_ = checks

    def forbidden(**kwargs):
        raise PermissionError("PRIVATE_DATABASE_PATH")

    monkeypatch.setattr(diagnostics, "TemporaryFile", forbidden)
    response = client.get("/api/v1/system/health")
    assert response.status_code == 503
    assert (
        response.json()["components"]["data_directory"]["code"]
        == "DATA_DIRECTORY_UNAVAILABLE"
    )
    assert "PRIVATE_DATABASE_PATH" not in response.text

    def unexpected(_):
        raise RuntimeError("PRIVATE_TEST_USERNAME_123")

    monkeypatch.setattr(diagnostics, "probe_stockfish", unexpected)
    with pytest.raises(SystemExit, match="^2$"):
        main(["doctor"])
    output = capsys.readouterr()
    assert "Diagnostics could not finish" in output.out
    assert "DIAGNOSTICS_FAILED" in output.err
    assert "PRIVATE_TEST_USERNAME_123" not in output.err


def test_concurrent_request_correlation_and_safe_unexpected_error(api, capsys):
    client, *_, app = api
    configure_logging()
    barrier = Barrier(2)
    logger = logging.getLogger("chess_coach.api.test")

    @app.get("/test-correlation")
    def correlate():
        barrier.wait(timeout=5)
        logger.info("test_request")
        return {}

    @app.get("/test-error")
    def fail():
        raise RuntimeError("SECRET_TEST_PROMPT_456")

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.get("/test-correlation"), range(2)))
    ids = {response.headers["X-Request-ID"] for response in responses}
    assert len(ids) == 2
    response = client.get("/test-error", headers={"X-Request-ID": "untrusted"})
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "SECRET_TEST_PROMPT_456" not in response.text
    assert response.headers["X-Request-ID"] != "untrusted"
    raw = capsys.readouterr().err
    assert "SECRET_TEST_PROMPT_456" not in raw
    events = [json.loads(line) for line in raw.splitlines()]
    assert {
        event["request_id"] for event in events if event["event"] == "test_request"
    } == ids
    failure = next(event for event in events if event["event"] == "internal_error")
    assert failure["request_id"] == response.headers["X-Request-ID"]


def test_cross_site_cannot_trigger_component_probes(checks, monkeypatch):
    client, *_ = checks

    def unexpected(_):
        pytest.fail("Cross-site request reached the probe")

    monkeypatch.setattr(dependencies, "probe_stockfish", unexpected)
    response = client.get(
        "/api/v1/system/health", headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "ORIGIN_NOT_ALLOWED"


def test_empty_system_metrics_are_unavailable(checks):
    client, *_ = checks
    response = client.get("/api/v1/system/metrics")
    assert response.status_code == 200
    assert response.json() == {
        "analysis": None,
        "coaching": {
            "window_days": 7,
            "sample_count": 0,
            "latency_p50_ms": None,
            "first_schema_failure_rate": None,
            "first_schema_sample_count": 0,
            "final_failure_rate": None,
        },
    }


def test_missing_stockfish_does_not_block_historical_analysis(analyzed, monkeypatch):
    client, _, _, _, settings, *_ = analyzed
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "probe_stockfish", lambda _: NO_ENGINE)
    monkeypatch.setattr(dependencies, "probe_ollama", lambda _: (READY, READY))
    body = client.get("/api/v1/system/health").json()
    assert body["overall"] == "degraded"
    assert body["components"]["stockfish"]["code"] == "STOCKFISH_NOT_FOUND"
    assert body["components"]["ollama_model"]["status"] == "pass"
    assert client.get("/api/v1/games/1/analysis").status_code == 200


def test_readonly_database_is_actionable(checks):
    client, _, _, _, settings, *_ = checks
    path = settings.database_path
    path.chmod(0o444)
    try:
        response = client.get("/api/v1/system/health")
        assert response.status_code == 503
        assert response.json()["components"]["database"]["code"] == "DATABASE_READ_ONLY"
        assert client.get("/health").status_code == 200
    finally:
        path.chmod(0o600)


def test_deep_database_check_detects_foreign_keys_without_repairing(checks):
    import sqlite3
    from contextlib import closing

    _, _, _, _, settings, *_ = checks
    with closing(sqlite3.connect(settings.database_path)) as connection:
        connection.executescript(
            "CREATE TABLE diagnostic_parent (id INTEGER PRIMARY KEY);"
            "CREATE TABLE diagnostic_child (parent_id INTEGER REFERENCES diagnostic_parent(id));"
            "INSERT INTO diagnostic_child VALUES (42);"
        )
    standard = diagnostics.database_checks(settings.database_path)
    assert [check.status for check in standard] == ["pass", "pass"]
    deep = diagnostics.database_checks(settings.database_path, deep=True)
    assert deep[-1].code == "DATABASE_INTEGRITY_FAILED"
    with closing(sqlite3.connect(settings.database_path)) as connection:
        assert connection.execute(
            "SELECT parent_id FROM diagnostic_child"
        ).fetchall() == [(42,)]


def test_corrupt_database_returns_safe_503(checks, tmp_path, monkeypatch):
    client, *_ = checks
    path = tmp_path / "corrupt.db"
    original = b"not a SQLite database"
    path.write_bytes(original)
    monkeypatch.setattr(
        dependencies, "get_settings", lambda: Settings(database_path=path)
    )
    response = client.get("/api/v1/system/health")
    assert response.status_code == 503
    assert response.json()["components"]["database"]["code"] == "DATABASE_UNAVAILABLE"
    assert response.json()["components"]["migrations"]["status"] == "skip"
    assert client.get("/health").status_code == 200
    assert path.read_bytes() == original
