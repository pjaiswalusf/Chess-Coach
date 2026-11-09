import json

import chess
import pytest
from pydantic import ValidationError

from chess_coach.analytics.motifs import detect_events
from chess_coach.application.errors import OperationError
from chess_coach.domain.coaching_models import EngineScore, MoveCoachingEvidence
from chess_coach.domain.motif_models import ChessEventType, MotifTheme
from chess_coach.domain.score_utils import calculate_loss_cp
from chess_coach.evaluation.motifs import Candidate, load_dataset, score
from chess_coach.infrastructure.llm.motif_classifier import (
    motif_input,
    validate_prediction,
)


def snapshot(
    initial,
    history,
    played,
    best,
    refutation,
    before,
    after,
):
    board = chess.Board(initial)
    for uci in history:
        board.push_uci(uci)
    return MoveCoachingEvidence(
        game_id=1,
        ply=len(history) + 1,
        player_color="white" if board.turn else "black",
        phase="middlegame",
        fen_before=board.fen(),
        initial_fen=initial,
        history_uci=history,
        history_before_start_unknown=initial != chess.STARTING_FEN,
        played_move_uci=played,
        best_move_uci=best[0],
        best_line_uci=best,
        played_refutation_uci=refutation,
        before=before,
        after=after,
        loss_cp=(
            calculate_loss_cp(before.cp_white, after.cp_white, board.turn)
            if before.cp_white is not None and after.cp_white is not None
            else None
        ),
        completion_provenance="pgn_declaration",
        source_hash="fixture-game",
        profile_hash="fixture-profile",
        engine_version="fixture-engine",
        analysis_version="single-v1",
        draw_policy="automatic-only-v1",
        feature_version=1,
    )


def cp(value):
    return EngineScore(cp_white=value)


def mate(distance):
    return EngineScore(mate_white=distance, mate_winner=distance > 0)


def allows_mate(before=None):
    return snapshot(
        chess.STARTING_FEN,
        ("f2f3", "e7e5"),
        "g2g4",
        ("e2e4",),
        ("d8h4",),
        before or cp(-40),
        mate(-1),
    )


def kinds(move, previous=None):
    return {e.type for e in detect_events(move, previous).events}


def test_new_mate_vs_already_lost():
    assert kinds(allows_mate()) == {ChessEventType.MATE_ALLOWED}
    assert not kinds(allows_mate(mate(-2)))


def test_black_missed_mate_vs_retained_mate():
    args = (
        chess.STARTING_FEN,
        ("f2f3", "e7e5", "g2g4"),
        "d7d5",
        ("d8h4",),
        ("e2e4",),
        mate(-1),
    )
    assert kinds(snapshot(*args, cp(-120))) == {ChessEventType.MATE_MISSED}
    assert not kinds(snapshot(*args, mate(-3)))


@pytest.mark.parametrize(
    "fen,played,best,refutation,before,after",
    [
        (
            "8/8/8/8/8/8/k1KQ4/8 b - - 0 1",
            "a2a3",
            ("a2a1", "d2a5"),
            ("d2a5",),
            cp(900),
            mate(1),
        ),
        (
            "8/8/8/8/8/8/2KQ4/k7 w - - 0 1",
            "d2d8",
            ("d2a5",),
            ("a1a2", "d8a8"),
            mate(1),
            cp(900),
        ),
    ],
)
def test_legal_pv_with_contradictory_mate_score_is_rejected(
    fen, played, best, refutation, before, after
):
    with pytest.raises(ValidationError, match="Terminal variation contradicts"):
        snapshot(fen, (), played, best, refutation, before, after)


def test_material_loss_vs_trade_and_compensation():
    clear = (
        "1r4k1/8/8/8/8/1N6/8/R5K1 w - - 0 1",
        (),
        "a1a2",
        ("b3c5", "b8b7"),
        ("b8b3",),
        cp(10),
    )
    events = detect_events(snapshot(*clear, cp(-300))).events
    assert [(event.type, event.material_lost) for event in events] == [
        (ChessEventType.MATERIAL_LOSS, 3)
    ]
    assert not kinds(snapshot(*clear, cp(100)))
    exchange = snapshot(
        "4r2k/p7/5n2/8/8/8/8/K3R3 w - - 0 1",
        (),
        "e1e8",
        ("e1e5", "h8h7"),
        ("f6e8",),
        cp(100),
        cp(-300),
    )
    assert not kinds(exchange)
    defended = snapshot(
        "1r4k1/8/8/8/8/1N6/P7/R5K1 w - - 0 1",
        (),
        "a1b1",
        ("b3c5", "b8b7"),
        ("b8b3", "a2b3"),
        cp(100),
        cp(-300),
    )
    assert not kinds(defended)


@pytest.mark.parametrize("color", ["white", "black"])
def test_sustained_advantage_lost_uses_mover_perspective(color):
    history = ("e2e4", "e7e5")
    if color == "white":
        moves = ("d2d3", ("g1f3",), ("g8f6",))
        sign = 1
    else:
        history += ("g1f3",)
        moves = ("d7d6", ("b8c6",), ("d2d4",))
        sign = -1
    args = (chess.STARTING_FEN, history, *moves, cp(sign * 200))
    assert kinds(snapshot(*args, cp(sign * 49)), sign * 150) == {
        ChessEventType.WINNING_OPPORTUNITY_LOST
    }
    assert not kinds(snapshot(*args, cp(sign * 190)), sign * 150)
    assert not kinds(snapshot(*args, cp(sign * 49)), sign * 149)
    assert not kinds(snapshot(*args, cp(sign * 49)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("fen_before", "invalid"),
        ("initial_fen", "8/8/8/8/8/8/8/8 w - - 0 1"),
        ("played_move_uci", "e8e6"),
        ("best_move_uci", "e8e6"),
        ("best_line_uci", ["e2e4", "e8e6"]),
        ("played_refutation_uci", ["e2e4"]),
        ("player_color", "black"),
        ("before", None),
    ],
)
def test_invalid_snapshots_rejected(field, value):
    payload = allows_mate().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        MoveCoachingEvidence.model_validate(payload)


def test_prediction_validates_refs_and_never_accepts_prose():
    evidence = detect_events(allows_mate())
    event = evidence.events[0]
    valid = {
        "status": "suggested",
        "theme": "KING_SAFETY",
        "supporting_evidence_ids": [event.id],
    }
    assert (
        validate_prediction(json.dumps(valid), evidence).theme == MotifTheme.KING_SAFETY
    )
    for invalid in (
        valid | {"supporting_evidence_ids": ["not supplied"]},
        valid | {"theme": "BAD_TRADE"},
    ):
        with pytest.raises(OperationError, match="not supported"):
            validate_prediction(json.dumps(invalid), evidence)
    for invalid in (
        valid | {"best_move": "g2g4", "cp": 100},
        valid | {"status": "insufficient_evidence"},
        valid | {"supporting_evidence_ids": [event.id, event.id]},
    ):
        with pytest.raises(ValidationError):
            validate_prediction(json.dumps(invalid), evidence)
    payload = json.loads(motif_input(evidence))
    assert not {"history_uci", "raw_pgn", "source_hash"} & payload.keys()


def test_dataset_no_game_leakage_and_metrics_count_abstentions(tmp_path):
    move = allows_mate()
    rows = [
        Candidate(
            sample_id=f"case_{i}",
            split="dev",
            evidence=move,
            human_label=label,
            reviewer="fixture reviewer",
        )
        for i, label in enumerate(
            ("KING_SAFETY", "KING_SAFETY", "MISSED_TACTIC", "AMBIGUOUS")
        )
    ]
    result = score(
        rows,
        {
            "case_0": "KING_SAFETY",
            "case_1": "ABSTAIN",
            "case_2": "FAILED",
            "case_3": "ABSTAIN",
        },
    )
    assert result["all_position_accuracy"] == 0.25
    assert result["selective_accuracy"] == 1
    assert result["eligible_coverage"] == pytest.approx(1 / 3)
    assert result["macro_f1"] == pytest.approx(1 / 3)
    assert sum(map(sum, result["confusion_matrix"])) == 4
    path = tmp_path / "dataset.jsonl"
    second = rows[1].model_dump(mode="json")
    second["split"] = "heldout"
    second["evidence"]["source_hash"] = "other-hash-same-game"
    path.write_text(rows[0].model_dump_json() + "\n" + json.dumps(second))
    with pytest.raises(ValueError, match="Game leakage"):
        load_dataset(path)
    second["evidence"]["game_id"] = 2
    path.write_text(rows[0].model_dump_json() + "\n" + json.dumps(second))
    with pytest.raises(ValueError, match="Position leakage"):
        load_dataset(path)


def test_dataset_conversion_requires_compatible_prior_evidence():
    move = allows_mate()
    prior = snapshot(
        chess.STARTING_FEN, (), "f2f3", ("e2e4",), ("e7e5",), cp(200), cp(20)
    )
    row = Candidate(sample_id="valid", split="dev", evidence=move, previous_move=prior)
    assert row.previous_before_cp_white == 200
    mismatched = prior.model_dump(mode="json") | {"profile_hash": "another-profile"}
    with pytest.raises(ValidationError, match="prior move in the same analysis"):
        Candidate.model_validate(
            row.model_dump(mode="json") | {"previous_move": mismatched}
        )
