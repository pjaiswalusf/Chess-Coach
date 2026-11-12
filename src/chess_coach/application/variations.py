"""Explore a hypothetical line anchored to compatible, completed game evidence."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import chess

from chess_coach.application.errors import OperationError
from chess_coach.domain.analysis import validate_result
from chess_coach.domain.engine_types import EngineResult
from chess_coach.infrastructure.engine.exceptions import ChessEngineError
from chess_coach.infrastructure.persistence.query_repository import QueryRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VariationEvaluation:
    cp: int | None
    mate: int | None
    white_wins: bool | None
    best_move: str | None
    continuation: str
    engine: str | None


@dataclass(frozen=True)
class VariationPosition:
    fen: str
    side_to_move: str
    legal_moves: list[str]
    san: str | None
    outcome: str | None
    evaluation: VariationEvaluation | None


class VariationService:
    def __init__(
        self, store: QueryRepository, search: Callable[[chess.Board], EngineResult]
    ) -> None:
        self.store, self.search = store, search

    def position(
        self,
        game_id: int,
        profile: str,
        ply: int,
        line: list[str],
        *,
        evaluate: bool,
    ) -> VariationPosition:
        report, recorded = self.store.game_analysis(game_id, profile)
        fen = report["initial_fen"]
        if report["status"] != "completed" or not isinstance(fen, str):
            raise OperationError(
                "REVIEW_UNAVAILABLE",
                "Load compatible analysis of this completed game to explore a variation.",
                409,
            )
        if ply > len(recorded):
            raise OperationError(
                "INVALID_BRANCH", "Choose a position in the recorded game.", 422
            )

        board = chess.Board(fen)
        for move in recorded[:ply]:
            board.push_uci(str(move["played_move_uci"]))

        san = None
        for uci in line:
            try:
                if board.is_game_over(claim_draw=False):
                    raise ValueError("Terminal position")
                move_to_play = board.parse_uci(uci)
            except ValueError:
                raise OperationError(
                    "ILLEGAL_VARIATION_MOVE",
                    "That move is illegal in this variation.",
                    422,
                ) from None
            san = board.san(move_to_play)
            board.push(move_to_play)

        outcome = board.outcome(claim_draw=False)
        evaluation = None
        if outcome:
            evaluation = VariationEvaluation(
                0 if outcome.winner is None else None,
                0 if outcome.winner is not None else None,
                outcome.winner,
                None,
                "",
                None,
            )
        elif evaluate:
            try:
                result = self.search(board)
                validate_result(board, result, result.engine_name)
                evaluation = VariationEvaluation(
                    result.score_cp_white,
                    result.mate_white,
                    result.mate_winner,
                    result.best_move_uci,
                    board.variation_san(
                        [chess.Move.from_uci(uci) for uci in result.pv_uci]
                    ),
                    result.engine_name,
                )
            except OperationError:
                raise
            except (ChessEngineError, ValueError) as exc:
                logger.warning(
                    "variation_search_failed", extra={"game_id": game_id}, exc_info=exc
                )
                raise OperationError(
                    "VARIATION_ENGINE_UNAVAILABLE",
                    "Could not evaluate this position. Check Stockfish and retry.",
                    503,
                ) from exc
        return VariationPosition(
            board.fen(),
            "white" if board.turn else "black",
            [] if outcome else [move.uci() for move in board.legal_moves],
            san,
            outcome.result() if outcome else None,
            evaluation,
        )
