from unittest.mock import patch

from chess_coach.cli import main


def test_cli_serves_api_on_loopback() -> None:
    with patch("chess_coach.cli.uvicorn.run") as run:
        main([])
    run.assert_called_once_with(
        "chess_coach.api.app:app", host="127.0.0.1", port=8000, access_log=False
    )


def test_sync_cli_report_and_partial_exit(capsys, tmp_path, monkeypatch):
    import pytest

    from chess_coach.domain.sync import SyncReport

    monkeypatch.setenv("CHESS_COACH_DATABASE_PATH", str(tmp_path / "cli.db"))
    with patch("chess_coach.cli.SyncGamesService") as service:
        service.return_value.sync.return_value = SyncReport(
            status="COMPLETED", games_inserted=3
        )
        main(["sync", "--username", "example", "--month", "2026/01", "--force"])
        assert '"games_inserted": 3' in capsys.readouterr().out
        service.return_value.sync.return_value = SyncReport(status="PARTIAL")
        with pytest.raises(SystemExit, match="1"):
            main(["sync", "--username", "example"])


def test_sync_cli_missing_schema_actionable_error(capsys, tmp_path, monkeypatch):
    import pytest

    monkeypatch.setenv("CHESS_COACH_DATABASE_PATH", str(tmp_path / "empty.db"))
    with pytest.raises(SystemExit, match="1"):
        main(["sync-status", "--username", "example"])
    assert "alembic upgrade head" in capsys.readouterr().out


def test_serve_can_start_with_invalid_settings(monkeypatch):
    monkeypatch.setenv("CHESS_COACH_STOCKFISH_THREADS", "0")
    with patch("chess_coach.cli.uvicorn.run") as run:
        main(["serve"])
    run.assert_called_once()
