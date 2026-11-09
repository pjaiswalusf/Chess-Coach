"""Local puzzle content, review transactions, and evidence reads."""

from datetime import datetime

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from chess_coach.application.errors import OperationError
from chess_coach.domain.analysis import ANALYSIS_VERSION, DRAW_POLICY
from chess_coach.domain.game_records import PARSER_VERSION, ParseStatus
from chess_coach.domain.training import POLICY
from chess_coach.infrastructure.persistence.models import (
    AnalysisRun,
    Game,
    GameAnalysisState,
    MoveAnalysis,
    PositionCache,
    Puzzle,
    PuzzleAttempt,
    TrackedPlayer,
)

Candidate = tuple[Game, MoveAnalysis, GameAnalysisState, AnalysisRun]


class TrainingRepository:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    @staticmethod
    def evidence(
        player_id: int,
    ) -> Select[Game, MoveAnalysis, GameAnalysisState, AnalysisRun]:
        return (
            select(Game, MoveAnalysis, GameAnalysisState, AnalysisRun)
            .join(MoveAnalysis, MoveAnalysis.game_id == Game.id)
            .join(
                GameAnalysisState,
                and_(
                    GameAnalysisState.game_id == Game.id,
                    GameAnalysisState.profile_hash == MoveAnalysis.profile_hash,
                    GameAnalysisState.analysis_version == MoveAnalysis.analysis_version,
                    GameAnalysisState.analysis_run_id == MoveAnalysis.analysis_run_id,
                ),
            )
            .join(AnalysisRun, AnalysisRun.id == GameAnalysisState.analysis_run_id)
            .where(
                Game.tracked_player_id == player_id,
                Game.result.in_(("win", "draw", "loss")),
                Game.parse_status == ParseStatus.READY,
                Game.parser_version == PARSER_VERSION,
                GameAnalysisState.status == "done",
                MoveAnalysis.mover == Game.player_color,
                AnalysisRun.tracked_player_id == player_id,
                AnalysisRun.profile_hash == MoveAnalysis.profile_hash,
                AnalysisRun.analysis_version == ANALYSIS_VERSION,
                MoveAnalysis.analysis_version == ANALYSIS_VERSION,
                AnalysisRun.draw_policy_version == DRAW_POLICY,
            )
        )

    def candidates(
        self, player_id: int, profile: str, after: int, limit: int
    ) -> tuple[str, list[Candidate]]:
        with self.sessions() as session:
            player = session.get(TrackedPlayer, player_id)
            if player is None:
                raise OperationError(
                    "PLAYER_NOT_FOUND", "Choose an imported player.", 404
                )
            if not session.scalar(
                select(AnalysisRun.id)
                .where(
                    AnalysisRun.tracked_player_id == player_id,
                    AnalysisRun.profile_hash == profile,
                    AnalysisRun.analysis_version == ANALYSIS_VERSION,
                    AnalysisRun.draw_policy_version == DRAW_POLICY,
                )
                .limit(1)
            ):
                raise OperationError(
                    "PROFILE_NOT_FOUND",
                    "Choose a compatible local analysis profile.",
                    404,
                )
            candidates = self.evidence(player_id).where(
                MoveAnalysis.profile_hash == profile,
                MoveAnalysis.id > after,
                or_(
                    MoveAnalysis.loss_cp >= POLICY.min_candidate_loss_cp,
                    and_(
                        MoveAnalysis.mate_before_winner.is_not(None),
                        MoveAnalysis.mate_before_winner
                        == (Game.player_color == "white"),
                        or_(
                            MoveAnalysis.mate_after_winner.is_(None),
                            MoveAnalysis.mate_after_winner
                            != MoveAnalysis.mate_before_winner,
                        ),
                    ),
                    and_(
                        MoveAnalysis.mate_before_winner.is_(None),
                        MoveAnalysis.mate_after_winner.is_not(None),
                        MoveAnalysis.mate_after_winner
                        != (Game.player_color == "white"),
                    ),
                ),
            )
            rows = session.execute(candidates.order_by(MoveAnalysis.id).limit(limit))
            return player.username, [
                (game, move, state, run) for game, move, state, run in rows
            ]

    def source_positions(
        self, state: GameAnalysisState, ply: int
    ) -> tuple[PositionCache, PositionCache] | None:
        if not state.position_ids or not 1 <= ply < len(state.position_ids):
            return None
        with self.sessions() as session:
            before = session.get(PositionCache, state.position_ids[ply - 1])
            after = session.get(PositionCache, state.position_ids[ply])
            return (before, after) if before is not None and after is not None else None

    def exists(self, player_id: int, game_id: int, ply: int) -> bool:
        with self.sessions() as session:
            return (
                session.scalar(
                    select(Puzzle.id).where(
                        Puzzle.tracked_player_id == player_id,
                        Puzzle.source_game_id == game_id,
                        Puzzle.source_ply == ply,
                    )
                )
                is not None
            )

    def publish(self, values: dict[str, object]) -> int | None:
        with self.sessions.begin() as session:
            return session.scalar(
                insert(Puzzle)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=["tracked_player_id", "source_game_id", "source_ply"]
                )
                .returning(Puzzle.id)
            )

    @staticmethod
    def due(now: datetime) -> ColumnElement[bool]:
        return and_(Puzzle.status == "active", Puzzle.next_review_at <= now)

    def next(self, player_id: int, now: datetime) -> Puzzle | None:
        with self.sessions() as session:
            return session.scalar(
                select(Puzzle)
                .where(Puzzle.tracked_player_id == player_id, self.due(now))
                .order_by(Puzzle.attempt_count == 0, Puzzle.next_review_at, Puzzle.id)
                .limit(1)
            )

    def counts(self, session: Session, player_id: int | None, now: datetime):
        # Aggregate per puzzle first so a puzzle with several attempts counts once.
        attempts = (
            select(
                PuzzleAttempt.puzzle_id.label("puzzle_id"),
                func.count().label("attempts"),
                func.sum(case((PuzzleAttempt.is_correct, 1), else_=0)).label("correct"),
            )
            .group_by(PuzzleAttempt.puzzle_id)
            .subquery()
        )
        statement = (
            select(
                Puzzle.theme,
                func.count(),
                func.count(attempts.c.puzzle_id),
                func.coalesce(func.sum(attempts.c.attempts), 0),
                func.coalesce(func.sum(attempts.c.correct), 0),
                func.sum(case((self.due(now), 1), else_=0)),
            )
            .outerjoin(attempts, attempts.c.puzzle_id == Puzzle.id)
            .group_by(Puzzle.theme)
            .order_by(Puzzle.theme)
        )
        if player_id is not None:
            statement = statement.where(Puzzle.tracked_player_id == player_id)
        return session.execute(statement).all()
