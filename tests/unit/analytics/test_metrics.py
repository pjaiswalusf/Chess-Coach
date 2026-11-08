import pytest
from pydantic import ValidationError

from chess_coach.analytics.contracts import Rate
from chess_coach.analytics.metrics import move_metrics, summarize
from chess_coach.analytics.sample_policy import severity


def test_hand_calculated_losses(factory):
    game = factory()
    metrics = move_metrics(game.moves)
    assert (
        metrics.player_moves,
        metrics.comparable_moves,
        metrics.excluded_losses,
    ) == (5, 4, 1)
    assert metrics.total_loss_cp == 295
    assert metrics.mean_loss_cp == 73.75
    assert metrics.median_loss_cp == 57.5
    assert metrics.significant == Rate(numerator=1, denominator=4, per_100=25)
    assert metrics.critical == Rate(numerator=1, denominator=4, per_100=25)


def test_outcomes_and_weighted_mean(factory):
    games = tuple(
        factory(i + 1, result="win" if i < 4 else "draw" if i < 6 else "loss")
        for i in range(10)
    )
    summary = summarize(games)
    assert (summary.wins, summary.draws, summary.losses) == (4, 2, 4)
    assert summary.win_rate.per_100 == 40
    assert summary.score_percentage == 50
    moves = (
        factory(losses=(20,) * 100, phases=["opening"]).moves
        + factory(2, losses=(60,) * 300, phases=["middlegame"]).moves
    )
    assert move_metrics(moves).mean_loss_cp == 50


def test_empty_and_unavailable(factory):
    assert summarize(()).score_percentage is None
    assert move_metrics(()).critical.per_100 is None
    unknown = factory(losses=(None,)).moves
    result = move_metrics(unknown)
    assert result.mean_loss_cp is result.median_loss_cp is None
    assert result.classifiable_moves == 0 and result.excluded_losses == 1


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_loss_rejected(factory, value):
    with pytest.raises(ValidationError):
        type(factory().moves[0]).model_validate(
            factory().moves[0].model_dump() | {"loss_cp": value}
        )


@pytest.mark.parametrize(
    "loss,expected",
    [
        (None, None),
        (0, "normal"),
        (29, "normal"),
        (30, "minor"),
        (79, "minor"),
        (80, "significant"),
        (149, "significant"),
        (150, "critical"),
    ],
)
def test_severity_boundaries(loss, expected):
    assert severity(loss) == expected


def test_contradictory_rate_and_scores(factory):
    with pytest.raises(ValidationError):
        Rate(numerator=2, denominator=1, per_100=200)
    with pytest.raises(ValidationError):
        type(factory().moves[0]).model_validate(
            factory().moves[0].model_dump() | {"mate_before": 2}
        )
