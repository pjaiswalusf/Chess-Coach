from datetime import UTC, datetime, timedelta

from chess_coach.analytics.contracts import GameEvidence, MoveEvidence
from chess_coach.analytics.trends import recent_trends


def game(game_id, *, color="white", control="600+5", status="done"):
    moves = tuple(
        MoveEvidence(
            game_id=game_id,
            ply=i,
            move_number=i,
            mover=color,
            before_cp=150,
            after_cp=150 if game_id > 10 else 0,
            loss_cp=0 if game_id > 10 else 150,
            severity="normal" if game_id > 10 else "critical",
        )
        for i in range(1, 7)
    )
    return GameEvidence(
        game_id=game_id,
        played_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=game_id),
        color=color,
        result="win",
        time_class="rapid",
        time_control=control,
        provenance="test",
        analysis_status=status,
        expected_player_moves=len(moves),
        moves=moves,
    )


def test_trends_compare_disjoint_periods_with_the_same_color_and_clock():
    games = tuple(game(i) for i in range(1, 21))
    (trend,) = recent_trends(
        games + (game(21, color="black"), game(22, control="900+0"))
    )
    assert set(trend.earlier.game_ids) == set(range(1, 11))
    assert set(trend.recent.game_ids) == set(range(11, 21))
    assert trend.earlier.critical.model_dump() == {
        "numerator": 60,
        "denominator": 60,
        "per_100": 100.0,
    }
    assert trend.recent.critical.per_100 == 0


def test_trend_does_not_skip_a_pending_game_to_claim_a_comparison():
    games = tuple(game(i) for i in range(1, 21))
    assert not recent_trends(games + (game(21, status="pending"),))
    assert not recent_trends(games[1:])


def test_trend_requires_fifty_classifiable_moves_per_period():
    def with_moves(game_id, count):
        original = game(game_id)
        return original.model_copy(
            update={"moves": original.moves[:count], "expected_player_moves": count}
        )

    all_games = tuple(with_moves(i, 5) for i in range(1, 21))
    assert recent_trends(all_games)[0].recent.critical.denominator == 50
    assert not recent_trends(all_games[:-1] + (with_moves(20, 4),))
    assert (
        recent_trends(all_games[:-1] + (with_moves(20, 6),))[
            0
        ].recent.critical.denominator
        == 51
    )
