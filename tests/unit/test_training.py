from datetime import UTC, datetime, timedelta, timezone

import chess
import pytest

from chess_coach.application.training import _compare
from chess_coach.domain.engine_types import EngineResult
from chess_coach.domain.game_records import PlayerColor
from chess_coach.domain.review_schedule import schedule
from chess_coach.domain.training import (
    Rejected,
    Rejection,
    Solution,
    continuation,
    verify_solution,
)

NOW = datetime(2026, 12, 30, 22, 17, tzinfo=timezone(timedelta(hours=-5)))


@pytest.mark.parametrize(
    ("streak", "correct", "expected_streak", "days"),
    [
        (0, False, 0, 1),
        (3, False, 0, 1),
        (0, True, 1, 3),
        (1, True, 2, 7),
        (2, True, 3, 14),
        (3, True, 4, 30),
        (12, True, 13, 30),
    ],
)
def test_review_intervals(streak, correct, expected_streak, days):
    new_streak, date = schedule(NOW, streak, correct)
    assert new_streak == expected_streak
    assert date == NOW.astimezone(UTC) + timedelta(days=days)
    assert date.tzinfo is UTC


@pytest.mark.parametrize(("now", "streak"), [(NOW.replace(tzinfo=None), 0), (NOW, -1)])
def test_invalid_review_state(now, streak):
    with pytest.raises(ValueError):
        schedule(now, streak, True)


def line(board, move, score, *, mate=None, pv=None, depth=10):
    return EngineResult(
        board.fen(),
        "fake",
        score,
        mate,
        None if mate is None else mate > 0,
        move,
        pv or (move,),
        depth,
        100,
    )


@pytest.mark.parametrize(
    ("color", "moves", "scores", "original"),
    [
        (chess.WHITE, ("e4d5", "g1f3", "d2d4"), (140, 50, 20), "b1c3"),
        (chess.BLACK, ("e5d4", "g8f6", "d7d5"), (-140, -50, -20), "b8c6"),
    ],
)
def test_solution_ranked_from_solver_perspective(color, moves, scores, original):
    board = chess.Board()
    for uci in ("e2e4", "d7d5"):
        board.push_uci(uci)
    if color == chess.BLACK:
        board = board.mirror()
    results = [line(board, move, score) for move, score in zip(moves, scores)]
    solution = verify_solution(board, original, results, "fake")
    assert solution.move_uci == moves[0]
    assert solution.theme == "critical_capture"
    with pytest.raises(Rejected, match=Rejection.AMBIGUOUS_SOLUTION):
        close = line(board, moves[1], scores[0])
        verify_solution(board, original, [results[0], close, results[2]], "fake")
    with pytest.raises(Rejected, match=Rejection.INVALID_ENGINE_RESULT):
        illegal = line(board, moves[0], scores[0], pv=(moves[0], "a1a8"))
        verify_solution(board, original, [illegal, *results[1:]], "fake")
    with pytest.raises(Rejected, match=Rejection.INVALID_ENGINE_RESULT):
        shallow = line(board, moves[1], scores[1], depth=9)
        verify_solution(board, original, [results[0], shallow, results[2]], "fake")
    with pytest.raises(Rejected, match=Rejection.INSUFFICIENT_TACTICAL_VALUE):
        verify_solution(board, moves[0], results, "fake")


def test_large_gap_does_not_publish_a_clearly_losing_position():
    board = chess.Board()
    for move in ("e2e4", "d7d5"):
        board.push_uci(move)
    moves = [
        line(board, uci, score)
        for uci, score in (("e4d5", -151), ("g1f3", -300), ("b1c3", -400))
    ]
    with pytest.raises(Rejected, match=Rejection.INSUFFICIENT_TACTICAL_VALUE):
        verify_solution(board, "g1f3", moves, "fake")


def test_mate_compared_separately_and_second_mate_is_ambiguous():
    board = chess.Board(
        "r1bqkbnr/p1pp1ppp/1pn5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 2 4"
    )
    mate = line(board, "f3f7", None, mate=1)
    alternate = line(board, "f3g3", 180)
    third = line(board, "f3h3", 120)
    assert (
        verify_solution(board, "f3h3", [mate, alternate, third], "fake").theme
        == "forced_mate"
    )
    with pytest.raises(Rejected, match=Rejection.INVALID_ENGINE_RESULT):
        false_mate = line(board, "f3g3", None, mate=1)
        verify_solution(board, "f3h3", [false_mate, alternate, third], "fake")
    with pytest.raises(Rejected, match=Rejection.AMBIGUOUS_SOLUTION):
        verify_solution(
            board, "f3h3", [mate, line(board, "f3g3", None, mate=3), third], "fake"
        )


def test_material_line_must_survive_the_opponents_reply():
    board = chess.Board()
    board.push_uci("e2e4")
    board.push_uci("d7d5")
    winning = Solution(
        "e4d5", ("e4d5", "b8c6", "d5c6", "a7a6"), "critical_capture", "medium"
    )
    exchanged = Solution(
        "e4d5", ("e4d5", "e7e6", "d5e6", "c8e6"), "critical_capture", "medium"
    )
    result = continuation(board, winning)
    assert (result.theme, result.solve_plies) == ("material_gain", 4)
    assert continuation(board, exchanged).solve_plies == 1


def test_mate_continuation_requires_actual_checkmate():
    board = chess.Board("5k2/5ppp/2B2q2/p3p3/8/8/P1P2PPP/1R1Q2K1 w - - 0 24")
    setup = Solution("b1b8", ("b1b8", "f8e7"), "forced_mate", "hard")
    mate = Solution("b1b8", (*setup.pv, "b8e8"), "forced_mate", "hard")
    assert continuation(board, setup).solve_plies == 1
    assert continuation(board, mate).solve_plies == 3


def test_transfer_rates_require_both_game_and_move_support():
    cohort = ("rapid", "600+5", PlayerColor.WHITE, "profile", "single-v1")
    before = {i: [20, 2] for i in range(10)}
    after = {i: [20, 1] for i in range(10, 20)}
    complete = _compare(cohort, {False: before, True: after})
    assert complete.before.errors_per_100 == 10
    assert complete.after.errors_per_100 == 5
    assert complete.change_per_100 == -5
    assert complete.relative_change_percent == -50
    assert complete.before.game_ids == list(range(10))
    for low in ({10: [200, 5]}, {i: [9, 0] for i in range(10, 20)}, {}):
        partial = _compare(cohort, {False: before, True: low})
        assert partial.after.errors_per_100 is None
        assert partial.change_per_100 is None
    zero = _compare(cohort, {False: {i: [10, 0] for i in range(10)}, True: after})
    assert zero.change_per_100 == 5
    assert zero.relative_change_percent is None
