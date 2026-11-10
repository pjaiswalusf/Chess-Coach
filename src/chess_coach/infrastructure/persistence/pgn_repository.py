"""Atomic file-import persistence; no network or engine operations."""

from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING

import chess
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chess_coach.application.errors import OperationError
from chess_coach.domain.game_records import PARSER_VERSION, ParseStatus
from chess_coach.infrastructure.persistence.models import (
    Game,
    ImportRejection,
    ImportRun,
    Platform,
    RunStatus,
    TrackedPlayer,
    utc_now,
)
from chess_coach.infrastructure.persistence.operations import ensure_idle, reserve

if TYPE_CHECKING:
    from chess_coach.application.import_pgn import FileGame


class PGNRepository:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def save(
        self, username: str, played_at: datetime, records: list[FileGame]
    ) -> dict[str, int]:
        now = utc_now()
        with self.sessions.begin() as session:
            reserve(session)
            ensure_idle(session)
            players = list(session.scalars(select(TrackedPlayer)))
            if len(players) > 1 or (players and players[0].username != username):
                raise OperationError(
                    "PLAYER_SWITCH_UNSUPPORTED",
                    "Use the configured tracked player; existing history is preserved.",
                )
            player = (
                players[0]
                if players
                else TrackedPlayer(platform=Platform.CHESS_COM, username=username)
            )
            session.add(player)
            session.flush()
            run = ImportRun(
                tracked_player_id=player.id, started_at=now, status=RunStatus.RUNNING
            )
            session.add(run)
            session.flush()
            inserted = existing = rejected = 0
            for index, record in enumerate(records):
                parsed = record.parsed
                if parsed is None:
                    session.add(
                        ImportRejection(
                            import_run_id=run.id,
                            year=played_at.year,
                            month=played_at.month,
                            record_index=index,
                            reason=record.error,
                            raw_pgn=record.raw,
                        )
                    )
                    rejected += 1
                    continue
                if (
                    session.scalar(
                        select(Game.id).where(Game.canonical_hash == record.identity)
                    )
                    is not None
                ):
                    existing += 1
                    continue
                metadata = asdict(parsed)
                del metadata["moves"]
                metadata["total_plies"] = parsed.total_plies
                session.add(
                    Game(
                        tracked_player_id=player.id,
                        platform=Platform.PGN,
                        canonical_hash=record.identity,
                        raw_pgn=record.raw,
                        played_at=played_at,
                        white_username=parsed.white_username,
                        black_username=parsed.black_username,
                        player_color=parsed.player_color,
                        result=parsed.player_result,
                        time_control=parsed.time_control.raw,
                        eco_code=parsed.eco,
                        opening_name=parsed.opening_name,
                        eco_url=parsed.eco_url,
                        source_evidence={
                            "import_run_id": run.id,
                            "completion_provenance": "pgn_declaration",
                            "played_at_provenance": "user_supplied",
                            "identity_version": "pgn-file-v1",
                        },
                        parse_status=ParseStatus.READY,
                        parser_version=PARSER_VERSION,
                        chess_library_version=chess.__version__,
                        parse_attempted_at=now,
                        parsed_metadata=metadata,
                    )
                )
                session.flush()
                inserted += 1
            run.games_seen = len(records)
            run.games_inserted, run.games_existing, run.games_failed = (
                inserted,
                existing,
                rejected,
            )
            run.status = (
                RunStatus.SUCCEEDED
                if not rejected
                else RunStatus.PARTIAL
                if inserted or existing
                else RunStatus.FAILED
            )
            run.finished_at = utc_now()
            run.summary_json = {"source": "pgn", "games_quarantined": rejected}
            return {
                "run_id": run.id,
                "inserted": inserted,
                "existing": existing,
                "rejected": rejected,
            }
