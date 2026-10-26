import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from chess_coach.config import Settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.upper().startswith("CHESS_COACH_"):
            monkeypatch.delenv(key)


@pytest.mark.parametrize("field", ["stockfish_threads", "stockfish_hash_mb"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_engine_resources_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(f"CHESS_COACH_{field.upper()}", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("url", ["not-a-url", "ftp://localhost", ""])
def test_ollama_host_requires_http_url(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("CHESS_COACH_OLLAMA_HOST", url)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_load_env_file_and_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "CHESS_COACH_STOCKFISH_THREADS=2\nCHESS_COACH_STOCKFISH_HASH_MB=128\n"
    )
    monkeypatch.setenv("CHESS_COACH_STOCKFISH_THREADS", "3")
    settings = Settings()
    assert settings.stockfish_threads == 3
    assert settings.stockfish_hash_mb == 128
    assert settings.database_path == Path("data/chess_coach.db")
