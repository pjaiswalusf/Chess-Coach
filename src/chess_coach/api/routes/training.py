"""HTTP contract for local puzzle practice."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from chess_coach.api.dependencies import get_query_service, get_training_service
from chess_coach.application.queries import QueryService
from chess_coach.application.training import TrainingService
from chess_coach.application.training_models import (
    AttemptResult,
    NextPuzzle,
    PuzzleStep,
    TrainingStats,
)
from chess_coach.application.training_transfer import TransferReport
from chess_coach.infrastructure.persistence.models import utc_now

router = APIRouter(prefix="/api/v1/training", tags=["training"])
Training = Annotated[TrainingService, Depends(get_training_service)]


class SubmitAttempt(BaseModel):
    submission_id: UUID
    move_uci: str = Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")
    retry_after_attempt_id: int | None = Field(default=None, gt=0)


class PlayPuzzle(BaseModel):
    submission_id: UUID
    retry_after_attempt_id: int | None = Field(default=None, gt=0)
    moves: list[Annotated[str, Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")]] = (
        Field(min_length=1, max_length=4)
    )


def player_id(
    queries: Annotated[QueryService, Depends(get_query_service)],
) -> int | None:
    return queries.store.historical_player_id()


Player = Annotated[int | None, Depends(player_id)]


@router.get("/next")
def next_puzzle(
    service: Training,
    player: Player,
    puzzle_id: Annotated[int | None, Query(gt=0)] = None,
) -> NextPuzzle:
    return service.next(player, utc_now(), puzzle_id)


@router.post("/{puzzle_id}/attempts")
def submit_attempt(
    puzzle_id: int, body: SubmitAttempt, service: Training, player: Player
) -> AttemptResult:
    return service.submit(
        player,
        puzzle_id,
        body.submission_id,
        body.move_uci,
        utc_now(),
        body.retry_after_attempt_id,
    )


@router.post("/{puzzle_id}/play")
def play_puzzle(
    puzzle_id: int, body: PlayPuzzle, service: Training, player: Player
) -> PuzzleStep:
    return service.play(
        player,
        puzzle_id,
        body.submission_id,
        body.moves,
        utc_now(),
        body.retry_after_attempt_id,
    )


@router.get("/stats")
def statistics(service: Training, player: Player) -> TrainingStats:
    return service.stats(player, utc_now())


@router.get("/progress")
def progress(service: Training, player: Player) -> TransferReport:
    return service.transfer(player)
