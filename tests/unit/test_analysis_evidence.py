from dataclasses import replace

import chess
import pytest

from chess_coach.domain.analysis import validate_result
from chess_coach.domain.engine_types import EngineResult


def evidence(board):
    return EngineResult(board.fen(), "test", 10, None, None, "e2e4", ("e2e4",), 5, 100)


@pytest.mark.parametrize(
    "changes",
    [
        {"fen": "wrong"},
        {"engine_name": "wrong"},
        {"score_cp_white": None},
        {"mate_white": 1},
        {"score_cp_white": True},
        {"nodes": -1},
        {"mate_winner": True},
        {"score_cp_white": None, "mate_white": 2, "mate_winner": False},
        {"pv_uci": ()},
        {"best_move_uci": "d2d4"},
        {"pv_uci": ("e2e4", "e2e3")},
    ],
)
def test_malformed_evidence_never_becomes_cache(changes):
    board = chess.Board()
    with pytest.raises(ValueError):
        validate_result(board, replace(evidence(board), **changes), "test")


def test_automatic_draw_is_zero_but_claimable_draw_is_not_terminal():
    board = chess.Board()
    for _ in range(2):
        for move in ("g1f3", "g8f6", "f3g1", "f6g8"):
            board.push_uci(move)
    assert (
        board.can_claim_threefold_repetition()
        and board.outcome(claim_draw=False) is None
    )
    validate_result(board, evidence(board), "test")
    for _ in range(2):
        for move in ("g1f3", "g8f6", "f3g1", "f6g8"):
            board.push_uci(move)
    draw = EngineResult(board.fen(), "test", 0, None, None, None, (), 0, 0)
    validate_result(board, draw, "test")
    with pytest.raises(ValueError):
        validate_result(board, replace(draw, score_cp_white=25), "test")
    with pytest.raises(ValueError):
        validate_result(
            board, replace(draw, best_move_uci="e2e4", pv_uci=("e2e4",)), "test"
        )


def test_malformed_uci_has_engine_error_code():
    board = chess.Board()
    with pytest.raises(ValueError, match='ENGINE_INVALID_RESULT'):
        validate_result(board, replace(evidence(board), best_move_uci='garbage', pv_uci=('garbage',)), 'test')
