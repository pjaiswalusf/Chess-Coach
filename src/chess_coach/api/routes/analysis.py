from typing import Annotated

from fastapi import APIRouter, Depends, Query

from chess_coach.api.dependencies import get_analysis_service
from chess_coach.api.schemas.analysis import (
    CreateRun,
    MoveResponse,
    RunResponse,
    WorkerResponse,
)
from chess_coach.application.analysis import AnalysisService

router = APIRouter(prefix="/api/v1", tags=["analysis"])
Service = Annotated[AnalysisService, Depends(get_analysis_service)]


@router.post("/analysis-runs", response_model=RunResponse, status_code=202)
def create_run(body: CreateRun, service: Service) -> dict[str, object]:
    return service.detail(service.create(body.tracked_player_id).id)


@router.get("/analysis-runs", response_model=list[RunResponse])
def list_runs(service: Service) -> list[dict[str, object]]:
    return service.list_runs()


@router.get("/analysis-runs/{run_id}", response_model=RunResponse)
def get_run(run_id: int, service: Service) -> dict[str, object]:
    return service.detail(run_id)


@router.post("/analysis-runs/{run_id}/cancel", response_model=RunResponse)
def cancel_run(run_id: int, service: Service) -> dict[str, object]:
    return service.cancel(run_id)


@router.get("/analysis-worker", response_model=WorkerResponse)
def worker_status(service: Service) -> dict[str, object]:
    return service.status()


@router.get("/games/{game_id}/analysis", response_model=list[MoveResponse])
def game_analysis(
    game_id: int,
    service: Service,
    profile_hash: Annotated[str, Query(pattern=r"^[a-f0-9]{64}$")],
) -> list[dict[str, object]]:
    return service.moves(game_id, profile_hash)
