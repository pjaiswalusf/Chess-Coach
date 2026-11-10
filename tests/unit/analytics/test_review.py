import chess
import pytest

from chess_coach.analytics.opening_book import book_plies
from chess_coach.analytics.review import ReviewRating, rate_move


@pytest.mark.parametrize(
    ("loss", "rating"),
    [
        (None, ReviewRating.UNRATED),
        (29, ReviewRating.GOOD),
        (30, ReviewRating.INACCURACY),
        (79, ReviewRating.INACCURACY),
        (80, ReviewRating.MISTAKE),
        (149, ReviewRating.MISTAKE),
        (150, ReviewRating.BLUNDER),
    ],
)
def test_non_best_uses_existing_loss_bands(loss, rating):
    board = chess.Board()
    assert (
        rate_move(board, board.parse_san("e4"), [board.parse_san("d4")], loss, 0, None)
        == rating
    )


def test_engine_best_double_check_requires_non_losing_evaluation():
    board = chess.Board("4k3/8/8/8/4B3/8/8/4R1K1 w - - 0 1")
    played = board.parse_san("Bc6+")
    assert rate_move(board, played, [played], 0, 50, None) == ReviewRating.GREAT
    assert rate_move(board, played, [played], 0, -50, None) == ReviewRating.BEST


def test_engine_best_sacrifice_requires_a_saved_reply_and_retained_evaluation():
    board = chess.Board("6k1/8/8/8/8/8/P4R2/4K3 w - - 0 1")
    line = [chess.Move.from_uci(uci) for uci in ("f2f8", "g8f8", "e1e2")]
    assert rate_move(board, line[0], line, 0, 25, None) == ReviewRating.BRILLIANT
    assert rate_move(board, line[0], line[:2], 0, 25, None) == ReviewRating.BEST
    assert rate_move(board, line[0], line, 0, -25, None) == ReviewRating.BEST


def test_engine_best_checkmate_is_great_and_mate_stays_separate():
    board = chess.Board()
    for san in ("f3", "e5", "g4"):
        board.push_san(san)
    played = board.parse_san("Qh4#")
    assert (
        rate_move(board, played, [played], None, None, chess.BLACK)
        == ReviewRating.GREAT
    )


def test_book_stops_when_the_game_leaves_the_opening_catalog():
    moves = ("e2e4", "e7e5", "g1f3", "b8c6", "h1g1")
    assert book_plies(chess.STARTING_FEN, moves, unknown_history=False) == 4
    assert book_plies(chess.STARTING_FEN, moves, unknown_history=True) == 0


def test_book_does_not_mask_engine_evidence_of_a_mistake():
    board = chess.Board()
    played, best = board.parse_san("e4"), board.parse_san("d4")
    assert (
        rate_move(board, played, [best], 10, 0, None, in_book=True) == ReviewRating.BOOK
    )
    assert (
        rate_move(board, played, [best], 85, 0, None, in_book=True)
        == ReviewRating.MISTAKE
    )


def test_miss_requires_a_different_move_that_loses_a_forced_mate():
    board = chess.Board(
        "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    )
    played = board.parse_san("Qg5")
    best = board.parse_san("Qxf7#")
    assert (
        rate_move(
            board, played, [best], None, -60, None, before_mate_winner=chess.WHITE
        )
        == ReviewRating.MISS
    )
    assert (
        rate_move(
            board,
            played,
            [best],
            None,
            None,
            chess.WHITE,
            before_mate_winner=chess.WHITE,
        )
        == ReviewRating.UNRATED
    )
