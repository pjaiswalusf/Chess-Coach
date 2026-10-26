from unittest.mock import patch

from chess_coach.cli import main


def test_cli_serves_api_on_loopback() -> None:
    with patch("chess_coach.cli.uvicorn.run") as run:
        main()
    run.assert_called_once_with("chess_coach.api.app:app", host="127.0.0.1", port=8000)
