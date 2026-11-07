import chess
import chess.engine
import pytest

from chess_coach.domain.score_utils import calculate_loss_cp, normalize_score


@pytest.mark.parametrize("score,color,expected", [
    (chess.engine.Cp(120), chess.WHITE, (120, None)),
    (chess.engine.Cp(120), chess.BLACK, (-120, None)),
    (chess.engine.Mate(2), chess.WHITE, (None, 2)),
    (chess.engine.Mate(2), chess.BLACK, (None, -2)),
    (chess.engine.Mate(0), chess.WHITE, (None, 0)),
])
def test_normalize(score, color, expected):
    assert normalize_score(chess.engine.PovScore(score, color)) == expected


@pytest.mark.parametrize("before,after,color,loss", [
    (80, -120, True, 200), (-80, 120, False, 200),
    (30, 80, True, 0), (80, 30, False, 0), (0, 0, True, 0),
])
def test_loss(before, after, color, loss):
    assert calculate_loss_cp(before, after, color) == loss


@pytest.mark.parametrize("bad", [None, chess.engine.Mate(1), True, 1.2])
def test_mate_and_noninteger_rejected(bad):
    with pytest.raises(ValueError):
        calculate_loss_cp(bad, 0, True)
