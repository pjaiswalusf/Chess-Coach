from typing import Annotated

from fastapi import APIRouter, Depends, Response

from chess_coach.api.dependencies import (
    get_component_health,
    get_system_metrics,
    get_system_report,
    get_system_status,
)
from chess_coach.api.schemas.contracts import SystemResponse
from chess_coach.api.schemas.system import (
    ComponentHealth,
    DependencyStatus,
    SystemMetrics,
    SystemStatusResponse,
)
from chess_coach.application.system import SystemStatus

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/status", response_model=SystemStatusResponse)
def system_status(
    status: Annotated[SystemStatus, Depends(get_system_status)],
) -> SystemStatusResponse:
    return SystemStatusResponse(
        api=DependencyStatus(state="available", detail="FastAPI is running."),
        stockfish=DependencyStatus(
            state=status.stockfish.state, detail=status.stockfish.detail
        ),
        ollama=DependencyStatus(state=status.ollama.state, detail=status.ollama.detail),
        ollama_model=DependencyStatus(
            state=status.ollama_model.state, detail=status.ollama_model.detail
        ),
    )


@router.get(
    "",
    response_model=SystemResponse,
    summary="Check local component availability and stored-game counts",
)
def report(
    status: Annotated[dict[str, object], Depends(get_system_report)],
) -> dict[str, object]:
    return status


@router.get(
    "/health",
    response_model=ComponentHealth,
    responses={503: {"model": ComponentHealth, "description": "A core check failed"}},
)
def component_health(
    response: Response,
    health: Annotated[ComponentHealth, Depends(get_component_health)],
) -> ComponentHealth:
    response.headers["Cache-Control"] = "no-store"
    if health.overall == "unavailable":
        response.status_code = 503
    return health


@router.get("/metrics", response_model=SystemMetrics)
def metrics(
    response: Response,
    measurement: Annotated[SystemMetrics, Depends(get_system_metrics)],
) -> SystemMetrics:
    response.headers["Cache-Control"] = "no-store"
    return measurement
