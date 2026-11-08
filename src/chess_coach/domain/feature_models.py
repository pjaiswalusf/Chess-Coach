"""Versioned evidence contracts. Unknown is distinct from a measured false/zero."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chess_coach.domain.game_records import PlayerColor

FEATURE_EXTRACTOR_VERSION = 1
PHASE_CLASSIFIER_VERSION = 1


class GamePhase(StrEnum):
    OPENING = "opening"
    MIDDLEGAME = "middlegame"
    ENDGAME = "endgame"
    UNCLASSIFIED = "unclassified"


class EvidenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class FeatureAnalysis(EvidenceModel):
    """Optional engine evidence, aligned to one played move; scores are White POV."""

    ply: int = Field(ge=1, strict=True)
    fen_before: str
    played_move_uci: str
    best_move_uci: str | None = None
    eval_before_cp_white: int | None = Field(default=None, strict=True)
    eval_after_cp_white: int | None = Field(default=None, strict=True)
    mate_before_white: int | None = Field(default=None, strict=True)
    mate_after_white: int | None = Field(default=None, strict=True)
    mate_before_winner: bool | None = Field(default=None, strict=True)
    mate_after_winner: bool | None = Field(default=None, strict=True)
    is_critical_error: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def scores(self) -> FeatureAnalysis:
        for side in ("before", "after"):
            cp = getattr(self, f"eval_{side}_cp_white")
            mate = getattr(self, f"mate_{side}_white")
            winner = getattr(self, f"mate_{side}_winner")
            if cp is not None and mate is not None:
                raise ValueError("Conflicting CP and mate evidence")
            if (mate is None) != (winner is None):
                raise ValueError("Mate evidence requires an explicit winning color")
            if mate is not None and mate != 0 and winner != (mate > 0):
                raise ValueError("Mate sign and winner disagree")
        return self


class MoveFeatures(EvidenceModel):
    game_id: int = Field(ge=1, strict=True)
    ply: int = Field(ge=1, strict=True)
    feature_version: int = Field(default=FEATURE_EXTRACTOR_VERSION, ge=1)
    phase_classifier_version: int = PHASE_CLASSIFIER_VERSION
    mover: PlayerColor
    tracked_player: PlayerColor
    phase: GamePhase
    phase_reason: str
    non_pawn_material: int = Field(ge=0)
    played_is_capture: bool
    played_gives_check: bool
    played_is_castling: bool
    played_mates_immediately: bool
    best_is_capture: bool | None
    best_gives_check: bool | None
    best_mates_immediately: bool | None
    captured_piece_type: str | None
    captured_piece_value: int = Field(ge=0)
    white_material_before: int = Field(ge=0)
    black_material_before: int = Field(ge=0)
    white_material_after: int = Field(ge=0)
    black_material_after: int = Field(ge=0)
    material_balance_before: int
    material_balance_after: int
    material_balance_change: int
    # Engine context is tracked-player POV on BOTH players' moves.
    engine_advantage_before: (
        Literal["large_advantage", "approximately_equal", "large_disadvantage"] | None
    )
    advantage_lost: bool | None
    advantage_created_after_opponent_move: bool | None
    player_preserved_existing_advantage: bool | None
    immediate_recapture_observed: bool
    player_had_advantage_before_exchange: bool | None
    queen_moved_early: bool
    minor_pieces_on_starting_squares: int | None
    minor_piece_repeated_move: bool | None
    has_castled: bool | None
    castling_side: Literal["kingside", "queenside"] | None
    castling_move_number: int | None
    king_on_central_file: bool
    time_used_seconds: float | None = Field(ge=0)
    time_remaining_seconds: float | None = Field(ge=0)
    clock_before_move_seconds: float | None = Field(ge=0)
    elapsed_annotation_seconds: float | None = Field(ge=0)
    time_source: Literal["recorded", "estimated", "unknown"]
    under_time_pressure: bool | None
    move_played_quickly: bool | None
    critical_error_on_fast_move: bool | None
    diagnostics: tuple[str, ...] = ()
