import chess

from chess_coach.analytics.move_breakdown import build_move_breakdown
from chess_coach.application.coaching import validated_output
from chess_coach.domain.coaching_models import MoveCoachingEvidence


def test_breakdown_explains_the_queen_capture_and_missed_mate():
    board = chess.Board()
    history = ("e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6")
    for uci in history:
        board.push_uci(uci)
    payload = {
        "game_id": 1,
        "ply": 7,
        "player_color": "white",
        "phase": "opening",
        "fen_before": board.fen(),
        "initial_fen": chess.STARTING_FEN,
        "history_uci": history,
        "history_before_start_unknown": False,
        "played_move_uci": "h5h6",
        "best_move_uci": "h5f7",
        "best_line_uci": ("h5f7",),
        "played_refutation_uci": ("g7h6",),
        "before": {"mate_white": 1, "mate_winner": True},
        "after": {"cp_white": -883},
        "completion_provenance": "pgn_declaration",
        "source_hash": "test",
        "profile_hash": "test",
        "engine_version": "fixture",
        "analysis_version": "single-v1",
        "draw_policy": "automatic-only-v1",
        "feature_version": 1,
    }
    evidence = MoveCoachingEvidence.model_validate(payload)
    breakdown = build_move_breakdown(evidence)
    assert breakdown.played.san == "4. Qh6 gxh6"
    assert breakdown.played.key_fact == "4... gxh6 captures the queen on h6."
    assert breakdown.alternative is not None
    assert breakdown.alternative.san == "4. Qxf7#"
    assert breakdown.alternative.key_fact == "4. Qxf7# delivers checkmate."
    assert "mate in 1 for White to -8.83" in breakdown.assessment
    practice = validated_output(
        '{"status":"insufficient_evidence","focus":null}', evidence
    )
    assert practice.model_dump() == {"status": "explained", "focus": "mate"}

    best_move = MoveCoachingEvidence.model_validate(
        payload
        | {
            "played_move_uci": "h5f7",
            "played_refutation_uci": (),
            "after": {"mate_white": 0, "mate_winner": True},
        }
    )
    breakdown = build_move_breakdown(best_move)
    assert breakdown.alternative is None
    assert breakdown.played.key_fact == "4. Qxf7# delivers checkmate."
