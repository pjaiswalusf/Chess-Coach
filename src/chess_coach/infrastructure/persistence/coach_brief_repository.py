"""Read current-profile move evidence and matching due puzzles for the Coach brief."""

import chess
from sqlalchemy import String, and_, cast, func, literal, select
from sqlalchemy.orm import Session, sessionmaker

from chess_coach.analytics.coach_brief import CoachExample, Finding, classify
from chess_coach.analytics.contracts import AnalyticsReport
from chess_coach.analytics.sample_policy import CRITICAL_LOSS_CP
from chess_coach.infrastructure.persistence.models import (
    Game,
    GameAnalysisState,
    MoveAnalysis,
    PositionCache,
    Puzzle,
    utc_now,
)
from chess_coach.infrastructure.persistence.training_repository import (
    TrainingRepository,
)


def coach_findings(
    sessions: sessionmaker[Session], report: AnalyticsReport
) -> list[Finding]:
    refs = set(report.analyzed_move_refs)
    game_ids = {game_id for game_id, _ in refs}
    if not game_ids:
        return []
    profile = report.request.profile_hash
    statement = (
        select(Game, MoveAnalysis, PositionCache.pv_json, Puzzle.id)
        .join(MoveAnalysis, MoveAnalysis.game_id == Game.id)
        .join(
            GameAnalysisState,
            and_(
                GameAnalysisState.game_id == Game.id,
                GameAnalysisState.analysis_run_id == MoveAnalysis.analysis_run_id,
                GameAnalysisState.profile_hash == profile,
            ),
        )
        .outerjoin(
            PositionCache,
            PositionCache.id
            == func.json_extract(
                GameAnalysisState.position_ids,
                literal("$[") + cast(MoveAnalysis.ply, String) + "]",
            ),
        )
        .outerjoin(
            Puzzle,
            and_(
                Puzzle.tracked_player_id == Game.tracked_player_id,
                Puzzle.source_game_id == Game.id,
                Puzzle.source_ply == MoveAnalysis.ply,
                Puzzle.source_profile_hash == profile,
                TrainingRepository.due(utc_now()),
            ),
        )
        .where(
            Game.id.in_(game_ids),
            Game.tracked_player_id == report.request.player_id,
            MoveAnalysis.profile_hash == profile,
            MoveAnalysis.analysis_version == report.request.analysis_version,
            MoveAnalysis.mover == Game.player_color,
        )
        .order_by(Game.played_at.desc(), Game.id.desc(), MoveAnalysis.ply)
    )
    findings = []
    previous: dict[int, int | None] = {}
    with sessions() as session:
        for game, row, reply, puzzle_id in session.execute(statement):
            if (game.id, row.ply) not in refs:
                continue
            sign = 1 if row.mover == "white" else -1
            before = (
                sign * row.eval_before_cp_white
                if row.eval_before_cp_white is not None
                else None
            )
            previous_cp = previous.get(game.id)
            previous[game.id] = before
            if not row.best_move_uci or row.played_move_uci == row.best_move_uci:
                continue
            if (row.loss_cp or 0) < CRITICAL_LOSS_CP and row.mate_before_winner != (
                sign == 1
            ):
                continue
            board = chess.Board(row.fen_before)
            detected = classify(
                board,
                row.played_move_uci,
                row.mate_before_winner,
                row.mate_after_winner,
                row.loss_cp or 0,
                previous_cp,
                before,
                sign * row.eval_after_cp_white
                if row.eval_after_cp_white is not None
                else None,
                reply or [],
            )
            if detected:
                pattern, detail = detected
                findings.append(
                    Finding(
                        pattern,
                        CoachExample(
                            game_id=game.id,
                            ply=row.ply,
                            move_label=f"{row.move_number}{'.' if sign == 1 else '...'}{row.played_move_san}",
                            opponent=game.black_username
                            if sign == 1
                            else game.white_username,
                            detail=detail,
                        ),
                        puzzle_id,
                        row.loss_cp or 0,
                    )
                )
    return findings
