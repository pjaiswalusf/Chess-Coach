from pathlib import Path

import chess
import pytest

from chess_coach.domain.game_records import PGNParseError
from chess_coach.infrastructure.pgn.parser import parse_game

FIXTURES = Path(__file__).parents[1] / "fixtures/pgn"


def pgn(name):
    return (FIXTURES / f"{name}.pgn").read_text()


@pytest.mark.parametrize(
    "name,plies,result",
    [
        ("white_win", 6, "win"),
        ("black_win", 4, "loss"),
        ("draw", 2, "draw"),
        ("checkmate", 7, "win"),
        ("timeout", 2, "win"),
    ],
)
def test_valid(name, plies, result):
    game = parse_game(pgn(name), " PRATIK ")
    assert game.total_plies == plies
    assert game.player_color == "white" and game.player_result == result
    board = chess.Board(game.initial_fen)
    for index, move in enumerate(game.moves, 1):
        assert move.ply_index == index and move.fen_before == board.fen()
        actual = chess.Move.from_uci(move.uci)
        assert actual in board.legal_moves and move.san == board.san(actual)
        board.push(actual)
        assert move.fen_after == board.fen()
    assert game.final_fen == board.fen()
    assert board.is_checkmate() == (name in {"black_win", "checkmate"})
    assert game.moves[0].clock_after_seconds is None
    assert game.opening_name is None


@pytest.mark.parametrize(
    "name,white,black",
    [
        ("white_win", "win", "loss"),
        ("black_win", "loss", "win"),
        ("draw", "draw", "draw"),
    ],
)
def test_perspectives(name, white, black):
    assert parse_game(pgn(name), "Pratik").player_result == white
    game = parse_game(pgn(name), "Opponent")
    assert game.player_result == black and game.player_color == "black"


@pytest.mark.parametrize(
    "name,reason",
    [
        ("illegal", "INVALID_MOVES"),
        ("invalid_fen", "INVALID_START_POSITION"),
        ("missing_player", "INVALID_PLAYER_METADATA"),
    ],
)
def test_invalid_fixtures(name, reason):
    with pytest.raises(PGNParseError) as failure:
        parse_game(pgn(name), "Pratik")
    assert failure.value.reason_code == reason
    assert failure.value.status == "parse_failed"


@pytest.mark.parametrize(
    "replacement,reason",
    [
        (lambda s: s.replace("1-0", "*"), "UNKNOWN_RESULT"),
        (lambda s: s.replace('[Result "1-0"]', ""), "UNKNOWN_RESULT"),
        (lambda s: s.rsplit("1-0", 1)[0], "UNKNOWN_RESULT"),
        (lambda s: s.rsplit("1-0", 1)[0] + "0-1", "RESULT_MISMATCH"),
        (lambda s: s.replace("e4", "garbage e4"), "INVALID_MOVES"),
        (lambda s: s.replace("e4", "e4garbage"), "INVALID_MOVES"),
        (lambda s: s + " e4", "INVALID_MOVES"),
        (lambda s: '[Variant "Chess960"]\n' + s, "UNSUPPORTED_VARIANT"),
        (lambda s: '[Variant "unknown"]\n' + s, "UNSUPPORTED_VARIANT"),
        (lambda s: s + "\n" + s, "MULTIPLE_GAMES"),
        (lambda s: s.replace("e4", "--"), "INVALID_MOVES"),
        (lambda s: s.replace("e4", "e4 {unclosed"), "INVALID_MOVES"),
        (lambda s: s.replace("e4", "e4 )"), "INVALID_MOVES"),
    ],
)
def test_strict_boundary(replacement, reason):
    with pytest.raises(PGNParseError) as failure:
        parse_game(replacement(pgn("white_win")), "Pratik")
    assert failure.value.reason_code == reason


@pytest.mark.parametrize(
    "raw,reason",
    [(None, "EMPTY_PGN"), (" ", "EMPTY_PGN"), ("x" * 1001, "PGN_TOO_LARGE")],
)
def test_input(raw, reason):
    with pytest.raises(PGNParseError) as failure:
        parse_game(raw, "Pratik", max_bytes=1000)
    assert failure.value.reason_code == reason


def test_identity_and_final_evidence():
    for username in ("", "SomeoneElse"):
        with pytest.raises(PGNParseError):
            parse_game(pgn("white_win"), username)
    with pytest.raises(PGNParseError, match="FINAL_POSITION_MISMATCH"):
        parse_game(pgn("white_win"), "Pratik", source_final_fen=chess.STARTING_FEN)
    with pytest.raises(PGNParseError, match="RESULT_MISMATCH"):
        parse_game(pgn("checkmate").replace("1-0", "0-1"), "Pratik")
    final = "r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 4"
    assert (
        parse_game(pgn("white_win"), "Pratik", source_final_fen=final).final_fen
        == final
    )


def test_clocks_and_metadata():
    game = parse_game(pgn("clocks"), "Pratik")
    assert game.total_plies == 4
    assert [m.clock_after_seconds for m in game.moves] == [275, 290, 272, None]
    assert [m.elapsed_seconds for m in game.moves] == [8, 15, 8, None]
    assert [m.elapsed_source for m in game.moves] == [
        "recorded",
        "estimated",
        "estimated",
        "unknown",
    ]
    assert game.eco == "C20" and game.opening_name == "King's Pawn Game"
    assert game.eco_url.startswith("https://")
    unsupported = parse_game(pgn("clocks").replace("300+5", "40/7200:3600"), "Pratik")
    assert unsupported.moves[1].elapsed_seconds is None
    negative = parse_game(pgn("clocks").replace("0:04:32", "0:05:32"), "Pratik")
    assert negative.moves[2].elapsed_seconds is None


def test_custom_start():
    game = parse_game(pgn("custom"), "Pratik")
    assert game.history_before_start_unknown
    assert [m.move_number for m in game.moves] == [20, 21]
    assert [m.mover_color for m in game.moves] == ["black", "white"]
    assert game.moves[0].elapsed_seconds is None
    assert game.final_fen == "8/5k2/8/8/8/8/5K2/R7 b - - 19 21"


@pytest.mark.parametrize(
    "body",
    [
        "(1. e4 e5) 1-0",
        "1. e4 (()) e5 1-0",
        "1. e4 () e5 1-0",
        "1. e4 $" + "9" * 5000 + " e5 1-0",
    ],
)
def test_malformed_structure_and_huge_nag_are_typed_rejections(body):
    raw = '[White "Pratik"]\n[Black "Opponent"]\n[Result "1-0"]\n\n' + body
    with pytest.raises(PGNParseError, match="INVALID_MOVES"):
        parse_game(raw, "Pratik")


@pytest.mark.parametrize("tag", ["clk", "emt"])
def test_extreme_clock_annotations_are_unknown(tag):
    raw = pgn("white_win").replace("e4", "e4 {[%" + tag + " " + "9" * 5000 + ":00:00]}")
    game = parse_game(raw, "Pratik")
    assert game.total_plies == 6
    assert game.moves[0].clock_after_seconds is None
    assert game.moves[0].elapsed_seconds is None


@pytest.mark.parametrize(
    "control,base,increment",
    [("600", 600, 0), ("600+5", 600, 5), ("180+2", 180, 2), ("1/86400", None, None)],
)
def test_supported_time_controls(control, base, increment):
    game = parse_game(pgn("clocks").replace("300+5", control), "Pratik")
    assert game.time_control.base_seconds == base
    assert game.time_control.increment_seconds == increment
    assert game.time_control.raw == control


def test_missing_clock_breaks_same_player_estimate_chain():
    game = parse_game(
        pgn("clocks").replace("{[%clk 0:04:35] [%emt 0:00:08]}", ""), "Pratik"
    )
    assert game.moves[2].elapsed_seconds is None


def test_unknown_results_for_either_player_and_safe_logs(caplog):
    for username in ("Pratik", "Opponent"):
        with pytest.raises(PGNParseError) as failure:
            parse_game(pgn("white_win").replace("1-0", "*"), username)
        assert failure.value.status == "incomplete"
    with pytest.raises(PGNParseError):
        parse_game(pgn("illegal"), "Pratik")
    assert "Bh6" not in caplog.text and "Pratik" not in caplog.text
