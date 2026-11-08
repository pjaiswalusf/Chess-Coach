import pytest

from chess_coach.analytics.patterns import advantages, castling, contexts, segments
from chess_coach.analytics.sample_policy import support


def test_partitions_and_unknowns(factory):
    games = tuple(
        factory(i, color="white" if i <= 10 else "black").model_copy(
            update={
                "eco": "UNKNOWN" if i == 20 else "B12",
                "time_class": "daily" if i > 10 else "blitz",
            }
        )
        for i in range(1, 21)
    )
    for dimension in ("color", "time_control", "eco"):
        result = segments(games, dimension)
        assert sum(s.summary.games_played for s in result) == 20
        assert sum(s.summary.moves.player_moves for s in result) == 100
    assert sum(s.summary.moves.player_moves for s in segments(games, "phase")) == 100
    assert segments(games, "color")[0].summary.games_played == 10


def test_opening_sample_and_first_errors(factory):
    games = tuple(
        factory(i).model_copy(
            update={"eco": "B12" if i <= 12 else "C00" if i <= 16 else "UNKNOWN"}
        )
        for i in range(1, 20)
    )
    groups = {s.key: s for s in segments(games, "eco")}
    assert [groups[k].summary.games_played for k in ("B12", "C00", "UNKNOWN")] == [
        12,
        4,
        3,
    ]
    assert groups["B12"].evidence_status == "sufficient"
    assert groups["C00"].evidence_status == "insufficient"
    assert groups["UNKNOWN"].evidence_status == "unavailable"
    errors = tuple(
        factory(i, losses=(0, 80, 150), phases=["opening"]) for i in range(1, 5)
    )
    result = segments(errors, "eco")[0]
    assert result.early_errors.numerator == result.early_errors.denominator == 4
    assert result.median_first_error_move == 2
    assert result.opening_moves.significant.per_100 == 100 / 3


def test_context_denominators_overlap_unknowns_and_baseline(factory):
    games = []
    for i in range(1, 11):
        g = factory(i, losses=(150, 0, 0, 0, 0), phases=["opening"])
        moves = tuple(
            m.model_copy(
                update={
                    "in_check": j < 2,
                    "after_capture": j < 2,
                    "under_time_pressure": None,
                }
            )
            for j, m in enumerate(g.moves)
        )
        games.append(g.model_copy(update={"moves": moves}))
    result = {c.key: c for c in contexts(tuple(games), 0)}
    check = result["in_check"]
    assert check.opportunities.critical.numerator == 10
    assert check.opportunities.critical.denominator == 20
    assert check.opportunities.critical.per_100 == 50
    assert check.comparison.player_moves == 30
    assert check.comparison.critical.numerator == 0
    assert check.evidence_status == "insufficient"
    assert result["after_capture"].opportunities == check.opportunities
    assert result["under_time_pressure"].unknown_moves == 50
    assert result["under_time_pressure"].evidence_status == "unavailable"
    assert sum(s.player_moves for s in check.strata.values()) == 20


@pytest.mark.parametrize(
    "values,result,winning,recover",
    [
        ([160, 170, 0], "win", 1, 0),
        ([160, 170, 0], "draw", 1, 0),
        ([160, 170, 0], "loss", 1, 0),
        ([160, 0, 0], "win", 0, 0),
        ([-160, -170, 0], "draw", 0, 1),
        ([160, 170, 160], "win", 1, 0),
    ],
)
def test_advantage_scenarios(factory, values, result, winning, recover):
    for color in ("white", "black"):
        g = factory(losses=(0,) * len(values), color=color, result=result)
        g = g.model_copy(
            update={
                "moves": tuple(
                    m.model_copy(update={"before_cp": v, "after_cp": v})
                    for m, v in zip(g.moves, values, strict=True)
                )
            }
        )
        output = advantages((g,))
        assert output.conversion.wins.denominator == winning
        assert output.recovery.nonloss.numerator == recover
        assert output.conversion.collapsed_game_ids == (
            (1,) if winning and values[-1] == 0 else ()
        )
        assert output.conversion.wins.numerator == (winning if result == "win" else 0)
        assert output.conversion.draws.numerator == (winning if result == "draw" else 0)
        assert output.conversion.losses.numerator == (
            winning if result == "loss" else 0
        )


def test_missing_mate_pending_excluded_and_crossings(factory):
    unknown = factory()
    pending = factory(2, status="pending")
    result = advantages((unknown, pending))
    assert result.conversion.excluded_game_ids == (1, 2)
    g = factory(losses=(0,) * 7)
    values = [0, 160, 170, 0, 180, 180, 0]
    g = g.model_copy(
        update={
            "moves": tuple(
                m.model_copy(update={"before_cp": v})
                for m, v in zip(g.moves, values, strict=True)
            )
        }
    )
    result = {c.key: c for c in contexts((g,), None)}["advantage_crossing"]
    assert result.opportunities.player_moves == 2
    assert result.unknown_moves == 1
    assert advantages((g,)).conversion.wins.denominator == 1


def test_castling_reached_decision_and_custom_history(factory):
    g = factory(1, losses=(0,) * 15)
    moves = tuple(
        m.model_copy(update={"castled": m.move_number == 10}) for m in g.moves
    )
    g = g.model_copy(update={"moves": moves})
    result = castling(
        (
            g,
            factory(2, losses=(0,) * 10),
            factory(3, losses=(0,) * 15),
            factory(4, castling_history_known=False),
        )
    )
    assert result.by_move_15.numerator == 1 and result.by_move_15.denominator == 2
    assert result.by_move_15.per_100 == 50
    assert result.all_games.denominator == 3
    assert result.excluded_games == 1


@pytest.mark.parametrize(
    "n,status",
    [(0, "unavailable"), (9, "insufficient"), (10, "sufficient"), (11, "sufficient")],
)
def test_game_support_boundary(n, status):
    assert support(n, n, 10, 10) == status


@pytest.mark.parametrize(
    "moves,games,status",
    [
        (49, 5, "insufficient"),
        (50, 4, "insufficient"),
        (50, 5, "sufficient"),
        (51, 6, "sufficient"),
        (100, 1, "insufficient"),
        (29, 10, "insufficient"),
        (30, 9, "insufficient"),
        (30, 10, "sufficient"),
        (31, 11, "sufficient"),
    ],
)
def test_move_support_boundaries(moves, games, status):
    minimum = (30, 10) if moves <= 31 else (50, 5)
    assert support(moves, games, *minimum) == status


def test_castling_uses_board_facts_with_unclassifiable_loss(factory):
    g = factory(losses=(None,))
    g = g.model_copy(
        update={"moves": (g.moves[0].model_copy(update={"castled": True}),)}
    )
    assert castling((g,)).all_games.numerator == 1


@pytest.mark.parametrize(
    "coverage,status",
    [(0.79, "unavailable"), (0.8, "sufficient"), (0.81, "sufficient")],
)
def test_clock_coverage_boundary(factory, coverage, status):
    games = tuple(factory(i, losses=(0, 0, 0)) for i in range(1, 11))
    games = tuple(
        g.model_copy(
            update={
                "moves": tuple(
                    m.model_copy(update={"under_time_pressure": True}) for m in g.moves
                )
            }
        )
        for g in games
    )
    metric = next(
        c for c in contexts(games, coverage) if c.key == "under_time_pressure"
    )
    assert metric.evidence_status == status


def test_collapse_on_final_opponent_move_and_mate_exclusion(factory):
    g = factory(losses=(0, 0))
    g = g.model_copy(
        update={
            "moves": tuple(
                m.model_copy(update={"before_cp": 160, "after_cp": 160})
                for m in g.moves
            ),
            "evaluation_path": (160, 160, 160, 160, 0),
        }
    )
    assert advantages((g,)).conversion.collapsed_game_ids == (1,)
    g = g.model_copy(update={"evaluation_path": (160, 160, 160, 160, None)})
    assert advantages((g,)).conversion.excluded_game_ids == (1,)


@pytest.mark.parametrize(
    "n,status", [(9, "insufficient"), (10, "sufficient"), (11, "sufficient")]
)
def test_actual_opening_guard_boundary(factory, n, status):
    assert (
        segments(tuple(factory(i) for i in range(1, n + 1)), "eco")[0].evidence_status
        == status
    )
