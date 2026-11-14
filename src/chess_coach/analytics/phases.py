"""Conservative material heuristic with monotone phase progression."""

import chess

from chess_coach.analytics.feature_config import (
    DEFAULT_CONFIG,
    FeatureConfig,
)
from chess_coach.domain.feature_models import GamePhase
from chess_coach.domain.material import PIECE_VALUES


def classify_phase(
    board: chess.Board,
    previous: GamePhase | None = None,
    *,
    unknown_history: bool = False,
    config: FeatureConfig = DEFAULT_CONFIG,
) -> tuple[GamePhase, str, int]:
    material = sum(
        value * len(board.pieces(piece, color))
        for piece, value in PIECE_VALUES.items()
        if piece != chess.PAWN
        for color in chess.COLORS
    )
    if previous == GamePhase.ENDGAME:
        return GamePhase.ENDGAME, "endgame_retained", material
    if material <= config.endgame_material:
        return GamePhase.ENDGAME, "low_non_pawn_material", material
    if unknown_history:
        return GamePhase.UNCLASSIFIED, "unknown_starting_history", material
    if (
        previous == GamePhase.MIDDLEGAME
        or board.fullmove_number > config.opening_last_move
    ):
        return GamePhase.MIDDLEGAME, "opening_window_complete", material
    return GamePhase.OPENING, "early_standard_game", material
