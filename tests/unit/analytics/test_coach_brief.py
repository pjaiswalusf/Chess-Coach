import chess

from chess_coach.analytics.coach_brief import (
    CoachExample,
    Finding,
    Pattern,
    classify,
    top_priority,
)


def test_priority_requires_distinct_games_and_links_matching_practice():
    examples = [
        Finding(
            Pattern.LOST_ADVANTAGE,
            CoachExample(
                game_id=game,
                ply=ply,
                move_label="2.Nf3",
                opponent="Fixture",
                detail="Lost the advantage.",
            ),
            puzzle_id,
            loss,
        )
        for game, ply, puzzle_id, loss in (
            (1, 3, None, 400),
            (1, 5, 10, 300),
            (2, 3, None, 250),
            (3, 3, None, 200),
        )
    ]
    assert top_priority(examples[:3]) is None
    priority = top_priority(examples)
    assert priority is not None
    assert priority.affected_games == 3
    assert [example.game_id for example in priority.examples] == [1, 2]
    assert priority.practice_puzzle_id == 10


def test_advantage_loss_requires_two_player_turns_of_advantage():
    board = chess.Board()
    assert classify(board, "g1f3", None, None, 220, 0, 200, -20, []) is None
    assert classify(board, "g1f3", None, None, 220, 150, 200, -20, ["e7e5"]) == (
        Pattern.LOST_ADVANTAGE,
        "Your engine evaluation fell from +2.00 to -0.20. The engine’s reply is e5.",
    )
