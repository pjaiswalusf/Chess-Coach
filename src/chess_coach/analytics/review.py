"""Local move-review labels based on verified single-pass engine evidence."""

from enum import StrEnum

import chess

from chess_coach.analytics.contracts import Severity
from chess_coach.analytics.features import calculate_material
from chess_coach.analytics.sample_policy import severity


class ReviewRating(StrEnum):
    BRILLIANT = "brilliant"
    GREAT = "great"
    BEST = "best"
    BOOK = "book"
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    MISS = "miss"
    BLUNDER = "blunder"
    UNRATED = "unrated"


_OTHER_MOVES = {
    Severity.CRITICAL: ReviewRating.BLUNDER,
    Severity.SIGNIFICANT: ReviewRating.MISTAKE,
    Severity.MINOR: ReviewRating.INACCURACY,
    Severity.NORMAL: ReviewRating.GOOD,
    None: ReviewRating.UNRATED,
}


def rate_move(
    before: chess.Board,
    played: chess.Move,
    line: list[chess.Move],
    loss_cp: int | None,
    after_cp_white: int | None,
    after_mate_winner: chess.Color | None,
    *,
    before_mate_winner: chess.Color | None = None,
    in_book: bool = False,
) -> ReviewRating:
    """Rate a played move and engine line that have already been checked for legality."""
    if not line:
        return ReviewRating.UNRATED
    mover = before.turn
    if played != line[0] and before_mate_winner == mover and after_mate_winner != mover:
        return ReviewRating.MISS
    band = severity(loss_cp)
    if in_book and band == Severity.NORMAL:
        return ReviewRating.BOOK
    if played != line[0]:
        return _OTHER_MOVES[band]

    after = before.copy(stack=False)
    after.push(played)
    if after.is_checkmate():
        return ReviewRating.GREAT

    non_losing = (
        after_mate_winner == mover
        if after_cp_white is None
        else (after_cp_white if mover else -after_cp_white) >= 0
    )
    if non_losing and band in (None, Severity.NORMAL):
        if (
            len(line) >= 3
            and line[1].to_square == played.to_square
            and after.is_capture(line[1])
        ):
            # Check the position after the mover's reply so immediate recaptures
            # and ordinary exchanges do not count as a sacrifice.
            reply = after.copy(stack=False)
            reply.push(line[1])
            reply.push(line[2])
            white_before, black_before = calculate_material(before)
            white_reply, black_reply = calculate_material(reply)
            drop = (white_before - black_before) - (white_reply - black_reply)
            if (drop if mover else -drop) >= 2:
                return ReviewRating.BRILLIANT
        if len(after.checkers()) == 2:
            return ReviewRating.GREAT

    return ReviewRating.BEST
