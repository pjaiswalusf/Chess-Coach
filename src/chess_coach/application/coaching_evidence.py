"""Build coaching only from compatible persisted, completed-game evidence."""

from chess_coach.analytics.motifs import detect_events
from chess_coach.application.errors import OperationError
from chess_coach.domain.coaching_models import MoveCoachingEvidence
from chess_coach.domain.motif_models import MotifEvidence
from chess_coach.infrastructure.persistence.coaching_repository import (
    CoachingRepository,
)


class EvidenceBuilder:
    def __init__(self, store: CoachingRepository):
        self.store = store

    def move(
        self, game_id: int, ply: int, profile: str | None = None
    ) -> MoveCoachingEvidence:
        try:
            return self.store.move_evidence(game_id, ply, profile)
        except OperationError:
            raise
        except ValueError:
            raise OperationError(
                "EVIDENCE_INCOMPLETE",
                "Revalidate the game and complete compatible engine analysis.",
            ) from None

    def motif(
        self, game_id: int, ply: int, profile: str | None = None
    ) -> MotifEvidence:
        try:
            move, previous = self.store.tracked_move_evidence(game_id, ply, profile)
            return detect_events(move, previous)
        except OperationError:
            raise
        except ValueError:
            raise OperationError(
                "EVIDENCE_INCOMPLETE",
                "Revalidate the game and complete compatible engine analysis.",
            ) from None
