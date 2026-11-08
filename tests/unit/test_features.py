"""Hand-calculated expectations for exact, heuristic, and unknown feature values."""

import json
from dataclasses import replace
from pathlib import Path

import chess
import pytest
from pydantic import ValidationError

from chess_coach.analytics.features import (
    FeatureInputError,
    calculate_material,
    extract_game_features,
)
from chess_coach.analytics.phases import classify_phase
from chess_coach.domain.feature_models import FeatureAnalysis, GamePhase
from chess_coach.domain.game_records import PlayerColor
from chess_coach.infrastructure.pgn.parser import parse_game

FIXTURES = Path(__file__).parents[1] / "fixtures/features"
CASES = json.loads((FIXTURES / "positions.json").read_text())


def parsed(body="1. e4 e5 2. Nf3 Nc6", control="600+5", player="TestPlayer"):
    return parse_game(
        f'[White "TestPlayer"]\n[Black "Opponent"]\n[Result "1-0"]\n[TimeControl "{control}"]\n\n{body} 1-0',
        player,
    )


def analysis(game, ply=1, **kwargs):
    move = game.moves[ply - 1]
    return FeatureAnalysis(
        ply=ply, fen_before=move.fen_before, played_move_uci=move.uci, **kwargs
    )


@pytest.mark.parametrize(
    "case", [c for c in CASES if "uci" in c], ids=lambda c: c["name"]
)
def test_exact_fixtures(case):
    board = chess.Board(case["fen"])
    move = chess.Move.from_uci(case["uci"])
    san = board.san(move)
    board.push(move)
    result = board.outcome().result() if board.outcome() else "1-0"
    pgn = f'[White "TestPlayer"]\n[Black "Opponent"]\n[Result "{result}"]\n[SetUp "1"]\n[FEN "{case["fen"]}"]\n\n{san} {result}'
    game = parse_game(pgn, "TestPlayer")
    f = extract_game_features(1, game, [analysis(game, best_move_uci=case["uci"])])[0]
    assert f.played_is_capture == f.best_is_capture == case["capture"]
    assert f.played_gives_check == f.best_gives_check == case["check"]
    assert f.material_balance_change == case["delta"]
    assert f.played_is_castling == case.get("castle", False)
    assert (
        f.played_mates_immediately
        == f.best_mates_immediately
        == case.get("mate", False)
    )
    assert f.minor_piece_repeated_move is None
    if case["name"] == "en passant":
        assert f.captured_piece_type == "pawn" and f.captured_piece_value == 1


@pytest.mark.parametrize(
    "case", [c for c in CASES if "phase" in c], ids=lambda c: c["name"]
)
def test_phase_fixtures(case):
    assert classify_phase(chess.Board(case["fen"]))[0] == case["phase"]


def test_phase_progression_and_unknown_setup():
    b = chess.Board()
    assert classify_phase(b, GamePhase.ENDGAME)[0] == GamePhase.ENDGAME
    assert classify_phase(b, GamePhase.MIDDLEGAME)[0] == GamePhase.MIDDLEGAME
    assert classify_phase(b, unknown_history=True)[0] == GamePhase.UNCLASSIFIED
    # Promoted material cannot reverse an established endgame.
    b = chess.Board("Q6k/8/8/8/8/8/7q/4K3 w - - 0 30")
    assert classify_phase(b, GamePhase.ENDGAME)[0] == GamePhase.ENDGAME


def test_material_and_development():
    assert calculate_material(chess.Board()) == (39, 39)
    game = parse_game((FIXTURES / "development.pgn").read_text(), "TestPlayer")
    fs = extract_game_features(1, game)
    assert len(fs) == 13
    assert fs[2].minor_pieces_on_starting_squares == 3
    assert fs[2].minor_piece_repeated_move is False
    assert fs[8].minor_piece_repeated_move is False  # other knight
    assert fs[10].minor_piece_repeated_move is True  # original g1 knight
    assert fs[6].has_castled is True and fs[6].castling_move_number == 4
    assert fs[9].has_castled is True and fs[9].castling_move_number == 5
    assert fs[12].queen_moved_early is True
    assert fs[0].queen_moved_early is False
    assert fs[6].king_on_central_file is False
    assert fs[0].king_on_central_file is True
    assert fs[0].time_used_seconds == 2 and fs[1].time_used_seconds == 4
    assert fs[2].elapsed_annotation_seconds == 2 and fs[2].time_source == "recorded"
    assert extract_game_features(1, game) == fs


def test_king_walk_not_castling_and_knight_return():
    fs = extract_game_features(1, parsed("1. e4 e5 2. Ke2 Nf6 3. Nf3 Ng8 4. Ng1"))
    assert fs[2].has_castled is False and fs[2].castling_move_number is None
    assert fs[-1].minor_pieces_on_starting_squares == 4
    assert fs[-1].minor_piece_repeated_move is True


@pytest.mark.parametrize("player,sign", [("TestPlayer", 1), ("Opponent", -1)])
@pytest.mark.parametrize(
    "before,after,lost,band",
    [
        (220, 20, True, "large_advantage"),
        (200, 190, False, "large_advantage"),
        (150, 50, True, "large_advantage"),
        (149, 50, False, "approximately_equal"),
        (-150, -200, False, "large_disadvantage"),
    ],
)
def test_player_perspective(player, sign, before, after, lost, band):
    game = parsed(player=player)
    fs = extract_game_features(
        1,
        game,
        [
            analysis(
                game,
                eval_before_cp_white=sign * before,
                eval_after_cp_white=sign * after,
            )
        ],
    )
    assert fs[0].engine_advantage_before == band
    assert fs[0].advantage_lost is lost


def test_context_opponent_opportunity_and_exchange():
    game = parsed("1. e4 d5 2. exd5 Qxd5")
    fs = extract_game_features(
        1,
        game,
        [
            analysis(game, 2, eval_before_cp_white=20, eval_after_cp_white=200),
            analysis(game, 3, eval_before_cp_white=200, eval_after_cp_white=200),
        ],
    )
    assert fs[1].advantage_created_after_opponent_move is True
    assert fs[2].player_preserved_existing_advantage is True
    assert fs[2].immediate_recapture_observed is False
    assert fs[3].immediate_recapture_observed is True
    assert fs[3].player_had_advantage_before_exchange is True


def test_missing_and_mate_evidence():
    game = parsed()
    f = extract_game_features(1, game)[0]
    assert f.best_is_capture is f.best_gives_check is f.best_mates_immediately is None
    assert f.advantage_lost is f.engine_advantage_before is None
    assert f.critical_error_on_fast_move is None
    f = extract_game_features(
        1,
        game,
        [
            analysis(
                game,
                mate_before_white=-3,
                mate_before_winner=False,
                eval_after_cp_white=0,
            )
        ],
    )[0]
    assert f.advantage_lost is f.engine_advantage_before is None
    for values in [
        {"eval_before_cp_white": 1, "mate_before_white": 1, "mate_before_winner": True},
        {"mate_before_white": 0},
        {"mate_before_white": -2, "mate_before_winner": True},
        {"eval_before_cp_white": True},
    ]:
        with pytest.raises(ValidationError):
            analysis(game, **values)


@pytest.mark.parametrize("best", ["e2e5", "bogus", "0000"])
def test_illegal_best_rejected(best):
    game = parsed()
    with pytest.raises(FeatureInputError, match="INVALID_BEST_MOVE"):
        extract_game_features(1, game, [analysis(game, best_move_uci=best)])


def test_alignment_and_required_input_rejections():
    game = parsed()
    a = analysis(game)
    for evidence in [
        [a, a],
        [a.model_copy(update={"ply": 99})],
        [a.model_copy(update={"fen_before": "wrong"})],
        [a.model_copy(update={"played_move_uci": "d2d4"})],
    ]:
        with pytest.raises(FeatureInputError):
            extract_game_features(1, game, evidence)
    variants = [
        replace(game, source_result="*"),
        replace(game, final_fen="wrong"),
        replace(game, initial_fen=game.moves[1].fen_before),
        replace(game, moves=(replace(game.moves[0], fen_after="wrong"),)),
        replace(game, moves=(replace(game.moves[0], uci="invalid"),)),
        replace(game, moves=(replace(game.moves[0], uci="e2e5"),)),
        replace(game, moves=(replace(game.moves[0], ply_index=2),)),
    ]
    for variant in variants:
        with pytest.raises(FeatureInputError):
            extract_game_features(1, variant)
    with pytest.raises(FeatureInputError):
        extract_game_features(0, game)


@pytest.mark.parametrize(
    "control,body,used,source,diagnostic",
    [
        ("600+5", "1. e4 {[%clk 0:10:03]} e5", 2, "estimated", False),
        ("600+5", "1. e4 {[%clk 0:10:03] [%emt 0:00:07]} e5", 7, "recorded", False),
        ("600+5", "1. e4 {[%clk 0:10:09]} e5", None, "unknown", True),
        ("600+5", "1. e4 e5", None, "unknown", False),
        ("40/7200:3600", "1. e4 {[%clk 1:59:59]} e5", None, "unknown", False),
        ("40/7200:3600", "1. e4 {[%emt 0:00:07]} e5", 7, "recorded", False),
    ],
)
def test_clock_semantics(control, body, used, source, diagnostic):
    f = extract_game_features(1, parsed(body, control))[0]
    assert f.time_used_seconds == used and f.time_source == source
    assert ("clock_inconsistent" in f.diagnostics) == diagnostic
    if "clk" not in body:
        assert f.time_remaining_seconds is None


def test_pressure_is_before_and_own_clock_gaps():
    fs = extract_game_features(
        1,
        parsed(
            "1. e4 {[%clk 0:00:20]} e5 {[%clk 0:09:00]} 2. Nf3 {[%clk 0:00:22]} Nc6 3. Bc4 Nf6 4. d3 {[%clk 0:00:10]}"
        ),
    )
    assert fs[0].under_time_pressure is False  # started with 600, ended with 20
    assert fs[1].under_time_pressure is False
    assert fs[2].under_time_pressure is True and fs[2].time_used_seconds == 3
    assert fs[6].time_used_seconds is None and fs[6].under_time_pressure is None
    assert fs[3].time_used_seconds is None


@pytest.mark.parametrize(
    "critical,elapsed,expected",
    [(True, 2, True), (False, 2, False), (True, 4, False), (None, 2, None)],
)
def test_fast_critical(critical, elapsed, expected):
    game = parsed(f"1. e4 {{[%emt 0:00:0{elapsed}]}} e5")
    f = extract_game_features(1, game, [analysis(game, is_critical_error=critical)])[0]
    assert f.critical_error_on_fast_move is expected


def test_unknown_custom_clock_and_invalid_optional_values():
    game = replace(parsed(), history_before_start_unknown=True)
    f = extract_game_features(1, game)[0]
    assert f.clock_before_move_seconds is None and f.under_time_pressure is None
    for value in [-1, float("nan"), float("inf")]:
        bad = replace(
            game,
            moves=(replace(game.moves[0], clock_after_seconds=value), *game.moves[1:]),
        )
        f = extract_game_features(1, bad)[0]
        assert f.time_remaining_seconds is None and "clock_invalid" in f.diagnostics


def test_black_material_balance():
    game = parsed("1. e4 d5 2. exd5 Qxd5", player="Opponent")
    fs = extract_game_features(1, game)
    assert fs[2].material_balance_after == 1
    assert fs[3].mover == PlayerColor.BLACK
    assert fs[3].material_balance_before == -1 and fs[3].material_balance_after == 0


def test_no_clocks_means_unknown_pressure_for_both_players():
    fs = extract_game_features(1, parsed())
    assert all(f.under_time_pressure is None for f in fs)
    assert all(f.time_used_seconds is None for f in fs)


def test_contradictory_scores_and_terminal_evidence():
    game = parsed()
    with pytest.raises(FeatureInputError, match="SCORE_POSITION_CONFLICT"):
        extract_game_features(
            1, game, [analysis(game, mate_before_white=0, mate_before_winner=True)]
        )
    with pytest.raises(FeatureInputError, match="ADJACENT_SCORE_CONFLICT"):
        extract_game_features(
            1,
            game,
            [
                analysis(game, eval_after_cp_white=20),
                analysis(game, 2, eval_before_cp_white=30),
            ],
        )
    mate_game = parse_game(
        '[White "TestPlayer"]\n[Black "Opponent"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1',
        "TestPlayer",
    )
    with pytest.raises(FeatureInputError, match="SCORE_POSITION_CONFLICT"):
        extract_game_features(
            1, mate_game, [analysis(mate_game, 4, eval_after_cp_white=-900)]
        )
    fs = extract_game_features(
        1,
        mate_game,
        [analysis(mate_game, 4, mate_after_white=0, mate_after_winner=False)],
    )
    assert fs[-1].advantage_lost is None
    with pytest.raises(FeatureInputError, match="RESULT_MISMATCH"):
        extract_game_features(1, replace(mate_game, source_result="1-0"))


def test_queen_after_opening_window_not_early():
    # Legal sequence of pawn moves avoids automatic repetitions.
    game = parsed(
        "1. e4 e5 2. a3 a6 3. b3 b6 4. c3 c6 5. d3 d6 6. f3 f6 7. g3 g6 8. h3 h6 9. a4 a5 10. b4 b5 11. Qe2"
    )
    assert extract_game_features(1, game)[-1].queen_moved_early is False


def test_terminal_draw_evaluation_must_be_zero():
    game = parse_game(
        '[White "TestPlayer"]\n[Black "Opponent"]\n[Result "1/2-1/2"]\n[SetUp "1"]\n[FEN "7k/5K2/8/6Q1/8/8/8/8 w - - 0 1"]\n\n1. Qg6 1/2-1/2',
        "TestPlayer",
    )
    # Qg6 is stalemate: h7/g8/g7 all attacked, h8 not checked.
    f = extract_game_features(1, game, [analysis(game, eval_after_cp_white=0)])[0]
    assert f.played_mates_immediately is False
    with pytest.raises(FeatureInputError, match="SCORE_POSITION_CONFLICT"):
        extract_game_features(1, game, [analysis(game, eval_after_cp_white=100)])


def test_real_historical_game_categories():
    tactical_game = parse_game(
        (FIXTURES / "historical_tactical.pgn").read_text(), "TestPlayer"
    )
    tactical = extract_game_features(1, tactical_game)
    assert len(tactical) == 14
    assert tactical[7].played_gives_check is True  # Qa5+
    assert tactical[10].captured_piece_type == "queen"  # Bxb5
    assert tactical[10].material_balance_change == 9
    assert tactical[11].immediate_recapture_observed is True  # cxb5
    assert all(f.phase == "opening" for f in tactical)
    middle_game = parse_game(
        (FIXTURES / "historical_middle.pgn").read_text(), "TestPlayer"
    )
    middle = extract_game_features(2, middle_game)
    assert len(middle) == 80
    assert middle[6].played_is_castling and middle[17].played_is_castling
    assert middle[20].phase == "middlegame"
    assert middle[-1].played_mates_immediately  # Re1#
    assert middle[-1].non_pawn_material == 16  # two rooks, bishop, knight
    assert middle[-1].phase == "middlegame"  # queenless is not sufficient
    end_game = parse_game((FIXTURES / "historical_endgame.pgn").read_text(), "Opponent")
    end = extract_game_features(3, end_game)
    assert len(end) == 139
    assert end[51].non_pawn_material == 16  # two rooks, two knights before Rxh4
    assert end[52].non_pawn_material == 13  # knight removed, Nd7+
    assert end[51].phase == "middlegame" and end[52].phase == "endgame"
    assert all(f.phase == "endgame" for f in end[52:])
    assert end[-1].played_mates_immediately  # Qc1#
