"""Engine evidence; all scores use White's perspective."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineResult:
    fen: str
    engine_name: str
    score_cp_white: int | None
    mate_white: int | None
    # Mate(0) loses its sign as an integer; retain the winning color explicitly.
    mate_winner: bool | None
    best_move_uci: str | None
    pv_uci: tuple[str, ...]
    depth: int | None
    nodes: int | None
