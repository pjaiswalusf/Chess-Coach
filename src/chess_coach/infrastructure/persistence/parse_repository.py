"""Short atomic parsing transactions; share the import lock during local batches."""

from contextlib import AbstractContextManager, nullcontext
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import chess
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chess_coach.application.parse_imported_games import ParseInput
from chess_coach.domain.game_records import (
    PARSER_VERSION,
    ParsedGame,
    ParseStatus,
    PGNParseError,
)
from chess_coach.infrastructure.persistence.models import Game, TrackedPlayer
from chess_coach.infrastructure.persistence.sync_repository import SyncRepository


class ParseRepository:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        database_path: Path,
        *,
        lock_already_held: bool = False,
    ):
        self.sessions = sessions
        self.lock_already_held = lock_already_held
        self._lock = SyncRepository(sessions, database_path)

    def guard(self) -> AbstractContextManager[None]:
        return nullcontext() if self.lock_already_held else self._lock.guard()

    def recover(self, username: str) -> int:
        with self.sessions.begin() as session:
            rows = session.scalars(
                select(Game)
                .join(TrackedPlayer)
                .where(
                    TrackedPlayer.username == username,
                    Game.parse_status == ParseStatus.PARSING,
                )
            ).all()
            for row in rows:
                row.parse_status = ParseStatus.PENDING
            return len(rows)

    def candidates(self, username: str, retry: bool) -> list[int]:
        with self.sessions() as session:
            query = (
                select(Game.id)
                .join(TrackedPlayer)
                .where(TrackedPlayer.username == username)
            )
            if not retry:
                query = query.where(Game.parse_status == ParseStatus.PENDING)
            return list(session.scalars(query.order_by(Game.id)))

    def begin(self, game_id: int, now: datetime) -> ParseInput:
        with self.sessions.begin() as session:
            game = session.get(Game, game_id)
            if game is None:
                raise ValueError("Game no longer exists; refresh the local batch.")
            player = session.get(TrackedPlayer, game.tracked_player_id)
            assert player is not None
            game.parse_status = ParseStatus.PARSING
            game.parse_attempted_at = now
            return ParseInput(
                game.id,
                game.raw_pgn,
                player.username,
                game.platform,
                game.white_username,
                game.black_username,
                game.source_evidence,
            )

    def finish(self, game_id: int, outcome: ParsedGame | PGNParseError) -> None:
        with self.sessions.begin() as session:
            game = session.get(Game, game_id)
            if game is None or game.parse_status != ParseStatus.PARSING:
                raise ValueError(
                    "Game is not in the parsing state; restart the local batch."
                )
            game.parser_version = PARSER_VERSION
            game.chess_library_version = chess.__version__
            if isinstance(outcome, PGNParseError):
                game.parse_status = outcome.status
                game.parse_reason = outcome.reason_code
                game.parse_error = outcome.safe_error_message
                game.parsed_metadata = None
            else:
                metadata = asdict(outcome)
                del metadata[
                    "moves"
                ]  # Phase 9 reconstructs the typed sequence from raw PGN.
                metadata["total_plies"] = outcome.total_plies
                game.parsed_metadata = metadata
                game.player_color, game.result = (
                    outcome.player_color,
                    outcome.player_result,
                )
                game.eco_code = outcome.eco or game.eco_code
                game.opening_name = outcome.opening_name or game.opening_name
                game.eco_url = outcome.eco_url or game.eco_url
                game.time_control = outcome.time_control.raw or game.time_control
                game.parse_status = ParseStatus.READY
                game.parse_reason = game.parse_error = None

    def eligible_ids(self) -> list[int]:
        """Only current, fully committed validation is eligible for future analysis."""
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(Game.id)
                    .where(
                        Game.parse_status == ParseStatus.READY,
                        Game.parser_version == PARSER_VERSION,
                        Game.chess_library_version == chess.__version__,
                        Game.parsed_metadata.is_not(None),
                    )
                    .order_by(Game.id)
                )
            )
