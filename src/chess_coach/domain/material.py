"""Material counts shared by analysis and puzzle verification."""

import chess

PIECE_VALUES = {1: 1, 2: 3, 3: 3, 4: 5, 5: 9}


def calculate_material(board: chess.Board) -> tuple[int, int]:
    def total(color: chess.Color) -> int:
        return sum(
            value * len(board.pieces(piece, color))
            for piece, value in PIECE_VALUES.items()
        )

    return total(chess.WHITE), total(chess.BLACK)
