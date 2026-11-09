"""Keep fallback configuration and accidental HTTP calls isolated in pytest."""

import os

import httpx
import pytest

from chess_coach.config import get_settings


@pytest.fixture(autouse=True)
def isolate_integrations(tmp_path, monkeypatch, request):
    monkeypatch.setenv("CHESS_COACH_DATABASE_PATH", str(tmp_path / "unseeded.db"))
    if request.node.get_closest_marker("engine") is None:
        monkeypatch.setenv(
            "CHESS_COACH_STOCKFISH_EXECUTABLE", str(tmp_path / "stockfish")
        )
    get_settings.cache_clear()

    def unexpected(*args, **kwargs):
        pytest.fail(
            "Real HTTP requires an explicit integration test or a fake transport"
        )

    if not (
        request.node.name == "test_real_ollama_vertical_slice_opt_in"
        and os.environ.get("CHESS_COACH_REAL_OLLAMA") == "1"
    ):
        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", unexpected)
        monkeypatch.setattr(
            httpx.AsyncHTTPTransport, "handle_async_request", unexpected
        )
    yield
    get_settings.cache_clear()
