"""Serialize conflicting operation admission using SQLite's write reservation."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from chess_coach.application.errors import OperationError
from chess_coach.domain.analysis import ACTIVE
from chess_coach.infrastructure.persistence.models import (
    AnalysisRun,
    ImportRun,
    RunStatus,
    TrackedPlayer,
)


def reserve(s: Session) -> None:
    # Even an empty-table UPDATE obtains the write reservation before reads.
    s.execute(update(TrackedPlayer).values(id=TrackedPlayer.id))


def ensure_idle(s: Session) -> None:
    if s.scalar(select(AnalysisRun.id).where(AnalysisRun.status.in_(ACTIVE))):
        raise OperationError(
            "ANALYSIS_ALREADY_RUNNING",
            "Wait for the active run before starting another analysis.",
        )
    if s.scalar(
        select(ImportRun.id).where(
            ImportRun.status.in_((RunStatus.PENDING, RunStatus.RUNNING))
        )
    ):
        raise OperationError("SYNC_ALREADY_RUNNING", "Wait for the active sync run.")
