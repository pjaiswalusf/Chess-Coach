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


def opening_evidence(history: tuple[str, ...], played: str) -> MoveCoachingEvidence:
    board = chess.Board()
    for uci in history:
        board.push_uci(uci)
    after = board.copy()
    after.push_uci(played)
    reply = next(iter(after.legal_moves)).uci()
    return MoveCoachingEvidence(
        game_id=1,
        ply=len(history) + 1,
        player_color="white" if board.turn else "black",
        phase="opening",
        fen_before=board.fen(),
        initial_fen=chess.STARTING_FEN,
        history_uci=history,
        history_before_start_unknown=False,
        played_move_uci=played,
        best_move_uci=played,
        best_line_uci=(played, reply),
        played_refutation_uci=(reply,),
        before={"cp_white": 20},
        after={"cp_white": 20},
        loss_cp=0,
        completion_provenance="pgn_declaration",
        source_hash="test",
        profile_hash="test",
        engine_version="fixture",
        analysis_version="single-v1",
        draw_policy="automatic-only-v1",
        feature_version=1,
    )


def test_opening_remarks_explain_space_and_bishop_diagonal():
    remark = build_move_breakdown(opening_evidence((), "e2e4")).remark
    assert "space in the center" in remark
    assert "diagonal for the bishop on f1" in remark
    assert "Stockfish’s top move" in remark


def test_knight_development_explains_the_actual_pawn_attack():
    remark = build_move_breakdown(opening_evidence(("e2e4", "e7e5"), "g1f3")).remark
    assert "knight off the back rank" in remark
    assert "attacks the pawn on e5" in remark


def test_black_development_explains_center_without_claiming_an_attack():
    remark = build_move_breakdown(
        opening_evidence(("e2e4", "e7e5", "g1f3"), "b8c6")
    ).remark
    assert "knight off the back rank" in remark
    assert "d4 and e5" in remark
    assert "attacks the pawn" not in remark


def test_returned_knight_is_not_described_as_new_development():
    remark = build_move_breakdown(
        opening_evidence(("g1f3", "g8f6", "f3g1", "f6g8"), "g1f3")
    ).remark
    assert "off the back rank" not in remark


def test_en_passant_remark_names_the_captured_pawns_actual_square():
    remark = build_move_breakdown(
        opening_evidence(("e2e4", "a7a6", "e4e5", "d7d5"), "e5d6")
    ).remark
    assert "Capturing the pawn on d5." in remark
    assert "pawn on d6" not in remark
