"""Seed a new disposable SQLite file for the opt-in real Stockfish browser test."""

import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from random import Random

import chess
import chess.pgn
from alembic import command
from alembic.config import Config

from chess_coach.config import Settings
from chess_coach.domain.analysis import fingerprint
from chess_coach.domain.game_records import PARSER_VERSION
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.models import Game, TrackedPlayer
from chess_coach.infrastructure.persistence.session import create_session_factory
from chess_coach.infrastructure.pgn.parser import parse_game


def main(database: Path) -> None:
    if database.exists():
        raise SystemExit("Supply a new disposable database path.")
    os.environ["CHESS_COACH_DATABASE_PATH"] = str(database)
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_database_engine(Settings(database_path=database).database_url)
    try:
        with create_session_factory(engine).begin() as session:
            player = TrackedPlayer(platform="chess.com", username="fixture_player")
            session.add(player)
            session.flush()
            for i in range(10):
                rng = Random(i)
                board = chess.Board()
                for _ in range(24):
                    if board.is_game_over(claim_draw=False):
                        break
                    board.push(rng.choice(list(board.legal_moves)))
                game = chess.pgn.Game.from_board(board)
                game.headers["White"] = player.username
                game.headers["Black"] = f"Fixture_{i}"
                game.headers["Result"] = (
                    board.result() if board.is_game_over() else "1-0"
                )
                game.headers["TimeControl"] = "600+5"
                raw = str(game)
                parsed = parse_game(raw, player.username)
                metadata = asdict(parsed)
                del metadata["moves"]
                metadata["total_plies"] = parsed.total_plies
                session.add(
                    Game(
                        tracked_player_id=player.id,
                        platform="pgn",
                        canonical_hash=fingerprint(raw),
                        raw_pgn=raw,
                        played_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i),
                        white_username=parsed.white_username,
                        black_username=parsed.black_username,
                        player_color=parsed.player_color,
                        result=parsed.player_result,
                        time_class="rapid",
                        time_control="600+5",
                        parse_status="ready",
                        parser_version=PARSER_VERSION,
                        chess_library_version=chess.__version__,
                        parsed_metadata=metadata,
                    )
                )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
