"""Pure score arithmetic. Mate is never converted into centipawns."""

import chess
import chess.engine


def normalize_score(score: chess.engine.PovScore) -> tuple[int | None, int | None]:
    white = score.white()
    return white.score(), white.mate()


def calculate_loss_cp(before_cp_white: int, after_cp_white: int, mover: chess.Color) -> int:
    """Provisional loss from independent searches; reject mate/optional scores."""
    if type(before_cp_white) is not int or type(after_cp_white) is not int:
        raise ValueError("Centipawn loss requires two integer centipawn scores")
    if type(mover) is not bool:
        raise ValueError("Mover must be a chess color")
    return max(0, (1 if mover else -1) * (before_cp_white - after_cp_white))
