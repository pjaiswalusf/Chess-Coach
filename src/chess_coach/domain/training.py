"""Conservative single-move puzzle policy, independent of storage and engine IO."""

from dataclasses import dataclass
from enum import StrEnum

import chess

from chess_coach.domain.analysis import validate_result
from chess_coach.domain.engine_types import EngineResult

GENERATOR_VERSION = 1


@dataclass(frozen=True)
class PuzzlePolicy:
    min_candidate_loss_cp: int = 120
    min_solution_gap_cp: int = 80
    min_solution_cp: int = -150
    min_legal_moves: int = 2
    multipv: int = 3


POLICY = PuzzlePolicy()


class Rejection(StrEnum):
    WRONG_PLAYER_TURN = "wrong_player_turn"
    INVALID_POSITION = "invalid_position"
    UNSUPPORTED_GAME = "unsupported_game"
    MISSING_ANALYSIS = "missing_analysis"
    INVALID_ENGINE_RESULT = "invalid_engine_result"
    AMBIGUOUS_SOLUTION = "ambiguous_solution"
    UNSTABLE_ENGINE_RESULT = "unstable_engine_result"
    INSUFFICIENT_TACTICAL_VALUE = "insufficient_tactical_value"


class Rejected(ValueError):
    def __init__(self, reason: Rejection):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Solution:
    move_uci: str
    pv: tuple[str, ...]
    theme: str
    difficulty: str


def _score(line: EngineResult, turn: chess.Color) -> tuple[int, int]:
    if line.mate_white is not None:
        wins = line.mate_winner == turn
        distance = abs(line.mate_white)
        return (1, -distance) if wins else (-1, distance)
    assert line.score_cp_white is not None
    return 0, line.score_cp_white if turn == chess.WHITE else -line.score_cp_white


def _validate_mate(board: chess.Board, line: EngineResult) -> None:
    if line.mate_white is None:
        return
    replay = board.copy(stack=True)
    for uci in line.pv_uci:
        replay.push_uci(uci)
    outcome = replay.outcome(claim_draw=False)
    if outcome is not None and outcome.winner != line.mate_winner:
        raise ValueError("PV outcome disagrees with mate score")
    if (
        line.mate_winner == board.turn
        and abs(line.mate_white) == 1
        and (len(line.pv_uci) != 1 or not replay.is_checkmate())
    ):
        raise ValueError("Mate in one requires an immediately mating move")


def verify_solution(
    board: chess.Board, original: str, lines: list[EngineResult], engine: str
) -> Solution:
    try:
        for line in lines:
            validate_result(board, line, engine)
            _validate_mate(board, line)
    except ValueError as exc:
        raise Rejected(Rejection.INVALID_ENGINE_RESULT) from exc
    expected = min(POLICY.multipv, board.legal_moves.count())
    if (
        len(lines) != expected
        or len({line.best_move_uci for line in lines}) != expected
        or len({line.depth for line in lines}) != 1
    ):
        raise Rejected(Rejection.INVALID_ENGINE_RESULT)

    scores = [_score(line, board.turn) for line in lines]
    if scores != sorted(scores, reverse=True):
        raise Rejected(Rejection.UNSTABLE_ENGINE_RESULT)

    best_type, best_value = scores[0]
    second_type, second_value = scores[1]
    best = lines[0]
    if best.best_move_uci == original:
        raise Rejected(Rejection.INSUFFICIENT_TACTICAL_VALUE)
    assert best.best_move_uci is not None
    if best_type == 1 and second_type < 1:
        return Solution(
            best.best_move_uci,
            best.pv_uci,
            "forced_mate",
            "easy" if best_value == -1 else "hard",
        )
    if (
        best_type != 0
        or second_type != 0
        or best_value - second_value < POLICY.min_solution_gap_cp
    ):
        raise Rejected(Rejection.AMBIGUOUS_SOLUTION)

    if best_value < POLICY.min_solution_cp:
        raise Rejected(Rejection.INSUFFICIENT_TACTICAL_VALUE)
    move = chess.Move.from_uci(best.best_move_uci)
    if board.gives_check(move):
        return Solution(best.best_move_uci, best.pv_uci, "forcing_check", "medium")
    if board.is_capture(move):
        return Solution(best.best_move_uci, best.pv_uci, "critical_capture", "medium")
    raise Rejected(Rejection.INSUFFICIENT_TACTICAL_VALUE)
