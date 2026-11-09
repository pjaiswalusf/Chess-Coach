"""Separate immutable chess observations from optional model suggestions."""

from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from chess_coach.domain.coaching_models import MoveCoachingEvidence
from chess_coach.domain.feature_models import EvidenceModel

TAXONOMY_VERSION: Final = "motif-v1"
DETECTOR_VERSION: Final = "motif-detector-v1"
MOTIF_SCHEMA_VERSION = "motif-prediction-v1"


class ChessEventType(StrEnum):
    MATE_ALLOWED = "MATE_ALLOWED"
    MATE_MISSED = "MATE_MISSED"
    MATERIAL_LOSS = "MATERIAL_LOSS"
    WINNING_OPPORTUNITY_LOST = "WINNING_OPPORTUNITY_LOST"


type FactId = Literal["before", "after", "best_line", "played_line", "previous_before"]


class MotifTheme(StrEnum):
    HANGING_PIECE = "HANGING_PIECE"
    MISSED_TACTIC = "MISSED_TACTIC"
    KING_SAFETY = "KING_SAFETY"
    DEVELOPMENT = "DEVELOPMENT"
    BAD_TRADE = "BAD_TRADE"
    PAWN_STRUCTURE = "PAWN_STRUCTURE"
    ENDGAME_TECHNIQUE = "ENDGAME_TECHNIQUE"
    CONVERSION = "CONVERSION"
    OTHER = "OTHER"


class ChessEvent(EvidenceModel):
    id: str
    type: ChessEventType
    game_id: int
    ply: int
    verified: Literal[True] = True
    detector_version: Literal["motif-detector-v1"] = DETECTOR_VERSION
    supporting_facts: tuple[FactId, ...]
    material_lost: int | None = None


class MotifEvidence(EvidenceModel):
    move: MoveCoachingEvidence
    taxonomy_version: Literal["motif-v1"] = TAXONOMY_VERSION
    previous_before_cp_white: int | None = Field(default=None, strict=True)
    events: tuple[ChessEvent, ...]


class MotifPrediction(EvidenceModel):
    """Constrained output; authoritative explanations are rendered from events."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    status: Literal["suggested", "insufficient_evidence"]
    theme: MotifTheme | None
    supporting_evidence_ids: tuple[str, ...] = Field(max_length=len(ChessEventType))

    @model_validator(mode="after")
    def consistent(self) -> Self:
        refs = self.supporting_evidence_ids
        if self.status == "insufficient_evidence":
            if self.theme is not None or refs:
                raise ValueError("An abstention cannot make claims")
        elif self.theme is None or not refs or len(refs) != len(set(refs)):
            raise ValueError("A suggested theme requires unique supporting evidence")
        return self
