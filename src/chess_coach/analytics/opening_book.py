"""Match the known opening prefix of a standard-start game."""

from functools import cache
from pathlib import Path

import chess


@cache
def _prefixes() -> frozenset[tuple[str, ...]]:
    catalog = Path(__file__).with_name("opening_lines.txt")
    with catalog.open(encoding="utf-8") as stream:
        lines = (tuple(line.split()) for line in stream if not line.startswith("#"))
        return frozenset(
            line[:ply] for line in lines for ply in range(1, len(line) + 1)
        )


def book_plies(
    initial_fen: str, moves: tuple[str, ...], *, unknown_history: bool
) -> int:
    """Stop at the first move outside the catalog, even if the game later transposes."""
    if unknown_history or initial_fen != chess.STARTING_FEN:
        return 0
    prefixes = _prefixes()
    for ply in range(1, len(moves) + 1):
        if moves[:ply] not in prefixes:
            return ply - 1
    return len(moves)
