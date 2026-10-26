import subprocess
from unittest.mock import patch

import httpx
import pytest

from chess_coach.config import Settings
from chess_coach.infrastructure.system.probes import probe_ollama, probe_stockfish


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    # Isolate both environment overrides and the developer's .env file.
    import os

    for key in list(os.environ):
        if key.upper().startswith("CHESS_COACH_"):
            monkeypatch.delenv(key)
    return Settings(_env_file=None)


def test_stockfish_probe_reports_missing_executable(settings: Settings) -> None:
    with patch(
        "chess_coach.infrastructure.system.probes.shutil.which", return_value=None
    ):
        result = probe_stockfish(settings)
    assert result.state == "unavailable"
    assert "not found" in result.detail


@pytest.mark.parametrize(
    ("stdout", "code", "expected"),
    [
        ("id name Stockfish 17\nuciok\nreadyok\n", 0, "available"),
        ("hello\n", 0, "unavailable"),
        ("id name OtherEngine\nuciok\nreadyok\n", 0, "unavailable"),
        ("id name Stockfish\nuciok\n", 0, "unavailable"),
        ("id name Stockfish\nuciok\nreadyok\n", 1, "unavailable"),
    ],
)
def test_stockfish_requires_successful_handshake(
    settings: Settings, stdout: str, code: int, expected: str
) -> None:
    with (
        patch(
            "chess_coach.infrastructure.system.probes.shutil.which",
            return_value="/private/stockfish",
        ),
        patch(
            "chess_coach.infrastructure.system.probes.subprocess.run",
            return_value=subprocess.CompletedProcess([], code, stdout, ""),
        ),
    ):
        result = probe_stockfish(settings)
    assert result.state == expected
    assert "/private" not in result.detail


@pytest.mark.parametrize(
    "error", [OSError("/secret/path"), subprocess.TimeoutExpired("/secret/path", 2)]
)
def test_stockfish_failure_is_safe(settings: Settings, error: Exception) -> None:
    with (
        patch(
            "chess_coach.infrastructure.system.probes.shutil.which",
            return_value="/secret/path",
        ),
        patch(
            "chess_coach.infrastructure.system.probes.subprocess.run", side_effect=error
        ),
    ):
        result = probe_stockfish(settings)
    assert result.state == "unavailable"
    assert "/secret" not in result.detail


@pytest.mark.parametrize(
    ("models", "state"),
    [
        ([{"name": "qwen3.5:4b-q4_K_M"}], "available"),
        ([], "unavailable"),
        ([{"name": "other:latest"}], "unavailable"),
        ([{}], "unknown"),
        ("invalid", "unknown"),
    ],
)
def test_ollama_reports_service_and_model_separately(
    settings: Settings, models: object, state: str
) -> None:
    response = httpx.Response(
        200,
        json={"models": models},
        request=httpx.Request("GET", "http://local/api/tags"),
    )
    with patch(
        "chess_coach.infrastructure.system.probes.httpx.get", return_value=response
    ):
        service, model = probe_ollama(settings)
    assert service.state == "available"
    assert model.state == state


@pytest.mark.parametrize("content", [b"not json", b"null", b"{}", b"[]"])
def test_ollama_invalid_response(settings: Settings, content: bytes) -> None:
    response = httpx.Response(
        200, content=content, request=httpx.Request("GET", "http://local/api/tags")
    )
    with patch(
        "chess_coach.infrastructure.system.probes.httpx.get", return_value=response
    ):
        service, model = probe_ollama(settings)
    assert service.state == "available"
    assert model.state == "unknown"


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("secret address"), httpx.ReadTimeout("secret address")]
)
def test_ollama_network_failure_is_safe(settings: Settings, error: Exception) -> None:
    with patch("chess_coach.infrastructure.system.probes.httpx.get", side_effect=error):
        service, model = probe_ollama(settings)
    assert service.state == "unavailable"
    assert model.state == "unknown"
    assert "secret" not in service.detail


def test_ollama_http_failure_is_safe(settings: Settings) -> None:
    response = httpx.Response(
        500, request=httpx.Request("GET", "http://secret/api/tags")
    )
    with patch(
        "chess_coach.infrastructure.system.probes.httpx.get", return_value=response
    ):
        service, model = probe_ollama(settings)
    assert service.state == "unavailable"
    assert model.state == "unknown"
    assert "secret" not in service.detail


def test_ollama_default_latest_tag(settings: Settings) -> None:
    settings.ollama_model = "example"
    response = httpx.Response(
        200,
        json={"models": [{"name": "example:latest"}]},
        request=httpx.Request("GET", "http://local/api/tags"),
    )
    with patch(
        "chess_coach.infrastructure.system.probes.httpx.get", return_value=response
    ):
        _, model = probe_ollama(settings)
    assert model.state == "available"
