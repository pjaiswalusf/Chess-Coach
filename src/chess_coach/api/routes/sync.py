from typing import Annotated

from fastapi import APIRouter, Depends, Path

from chess_coach.api.dependencies import get_job_service
from chess_coach.api.schemas.contracts import AcceptedRun, SyncInput, SyncRunResponse
from chess_coach.application.jobs import JobService

router = APIRouter(prefix="/api/v1/sync-runs", tags=["sync"])
Service = Annotated[JobService, Depends(get_job_service)]


@router.post(
    "",
    status_code=202,
    response_model=AcceptedRun,
    summary="Queue a persistent archive synchronization",
)
def start_sync(body: SyncInput, service: Service) -> dict[str, object]:
    return service.start_sync()


@router.get(
    "/{run_id}",
    response_model=SyncRunResponse,
    summary="Read persisted synchronization progress",
)
def sync_progress(
    run_id: Annotated[int, Path(gt=0)], service: Service
) -> dict[str, object]:
    return service.sync_progress(run_id)
