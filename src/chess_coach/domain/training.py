"""Conservative puzzle policy, independent of storage and engine IO."""

from dataclasses import dataclass, replace
from enum import StrEnum

import chess

from chess_coach.domain.analysis import validate_result
from chess_coach.domain.engine_types import EngineResult
from chess_coach.domain.material import calculate_material

GENERATOR_VERSION = 2


@dataclass(frozen=True)
class PuzzlePolicy:
    min_candidate_loss_cp: int = 120
    min_solution_gap_cp: int = 80
    min_solution_cp: int = -150
    min_legal_moves: int = 2
    multipv: int = 3
    max_solver_moves: int = 4
    min_material_gain: int = 2


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
    solve_plies: int = 1


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


def ranked_scores(
    board: chess.Board, lines: list[EngineResult], engine: str
) -> list[tuple[int, int]]:
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
    return scores


def decisive_move(scores: list[tuple[int, int]]) -> bool:
    if len(scores) == 1:
        return True
    best_type, best_value = scores[0]
    second_type, second_value = scores[1]
    return (best_type == 1 and second_type < 1) or (
        best_type == second_type == 0
        and best_value - second_value >= POLICY.min_solution_gap_cp
    )


def verified_followup(scores: list[tuple[int, int]]) -> bool:
    # A shorter forced mate is a distinct objective even if a slower mate exists.
    return decisive_move(scores) or (
        scores[0][0] == scores[1][0] == 1 and scores[0][1] > scores[1][1]
    )


def verify_solution(
    board: chess.Board, original: str, lines: list[EngineResult], engine: str
) -> Solution:
    scores = ranked_scores(board, lines, engine)
    if len(scores) < POLICY.min_legal_moves:
        raise Rejected(Rejection.INVALID_ENGINE_RESULT)
    best_type, best_value = scores[0]
    best = lines[0]
    if best.best_move_uci == original:
        raise Rejected(Rejection.INSUFFICIENT_TACTICAL_VALUE)
    assert best.best_move_uci is not None
    if not decisive_move(scores):
        raise Rejected(Rejection.AMBIGUOUS_SOLUTION)
    if best_type == 1:
        return Solution(
            best.best_move_uci,
            best.pv_uci,
            "forced_mate",
            "easy" if best_value == -1 else "hard",
        )
    if best_type != 0 or best_value < POLICY.min_solution_cp:
        raise Rejected(Rejection.INSUFFICIENT_TACTICAL_VALUE)
    move = chess.Move.from_uci(best.best_move_uci)
    if board.gives_check(move):
        return Solution(best.best_move_uci, best.pv_uci, "forcing_check", "medium")
    if board.is_capture(move):
        return Solution(best.best_move_uci, best.pv_uci, "critical_capture", "medium")
    return Solution(best.best_move_uci, best.pv_uci, "material_gain", "hard")


def continuation(board: chess.Board, deep: Solution) -> Solution:
    """Find a bounded line through mate or a material gain after the reply."""
    replay = board.copy(stack=True)
    solver = board.turn
    white, black = calculate_material(board)
    initial = white - black
    captured_later = False
    for ply, uci in enumerate(deep.pv[: POLICY.max_solver_moves * 2], start=1):
        move = chess.Move.from_uci(uci)
        if ply > 1 and replay.turn == solver and replay.is_capture(move):
            captured_later = True
        replay.push(move)
        if replay.is_checkmate():
            if deep.theme == "forced_mate" and replay.turn != solver:
                return replace(deep, solve_plies=ply)
            break
        if replay.is_game_over(claim_draw=True):
            break
        if deep.theme != "forced_mate" and ply % 2 == 0 and captured_later:
            white, black = calculate_material(replay)
            gain = (white - black - initial) * (1 if solver == chess.WHITE else -1)
            if gain >= POLICY.min_material_gain:
                return replace(
                    deep, theme="material_gain", difficulty="hard", solve_plies=ply
                )
    if deep.theme == "material_gain":
        raise Rejected(Rejection.INSUFFICIENT_TACTICAL_VALUE)
    return deep
