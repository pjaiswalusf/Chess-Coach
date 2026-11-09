"""Thin coaching admission and read-only result endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from chess_coach.api.dependencies import (
    get_coaching_service,
    get_llm_health,
    get_query_service,
)
from chess_coach.application.coaching import (
    CoachingResponse,
    CoachingService,
    MotifHealth,
    MotifResponse,
)
from chess_coach.application.queries import QueryService
from chess_coach.domain.coaching_models import LLMHealth

router = APIRouter(prefix="/api/v1", tags=["coaching"])
Service = Annotated[CoachingService, Depends(get_coaching_service)]
GameId = Annotated[int, Path(gt=0)]
Ply = Annotated[int, Path(gt=0)]
Profile = Annotated[str | None, Query(min_length=1, max_length=64)]


@router.get("/system/llm", response_model=LLMHealth)
def llm_health(health: Annotated[LLMHealth, Depends(get_llm_health)]) -> LLMHealth:
    return health


@router.get("/system/motifs", response_model=MotifHealth)
def motif_health(service: Service) -> MotifHealth:
    return service.motif_health()


@router.get("/games/{game_id}/moves/{ply}/explanation", response_model=CoachingResponse)
def get_explanation(
    game_id: GameId, ply: Ply, service: Service, profile_hash: Profile = None
) -> CoachingResponse:
    return service.move(game_id, ply, profile=profile_hash)


@router.post(
    "/games/{game_id}/moves/{ply}/explanation", response_model=CoachingResponse
)
def request_explanation(
    game_id: GameId,
    ply: Ply,
    service: Service,
    response: Response,
    profile_hash: Profile = None,
) -> CoachingResponse:
    result = service.move(game_id, ply, generate=True, profile=profile_hash)
    response.status_code = 202 if result.status in {"queued", "running"} else 200
    return result


@router.get("/coaching-jobs/{job_id}", response_model=CoachingResponse)
def job(job_id: Annotated[int, Path(gt=0)], service: Service) -> CoachingResponse:
    return service.job(job_id)


@router.get("/games/{game_id}/moves/{ply}/motif", response_model=MotifResponse)
def get_motif(
    game_id: GameId, ply: Ply, service: Service, profile_hash: Profile = None
) -> MotifResponse:
    return service.motif(game_id, ply, profile=profile_hash)


@router.post("/games/{game_id}/moves/{ply}/motif", response_model=MotifResponse)
def request_motif(
    game_id: GameId,
    ply: Ply,
    service: Service,
    response: Response,
    profile_hash: Profile = None,
) -> MotifResponse:
    result = service.motif(game_id, ply, generate=True, profile=profile_hash)
    response.status_code = 202 if result.status in {"queued", "running"} else 200
    return result


@router.get(
    "/coaching/history",
    response_model=CoachingResponse,
    operation_id="get_historical_coaching",
)
@router.post(
    "/coaching/history",
    response_model=CoachingResponse,
    operation_id="request_historical_coaching",
)
def history(
    request: Request,
    service: Service,
    queries: Annotated[QueryService, Depends(get_query_service)],
    response: Response,
    window: Annotated[str, Query(pattern="^(all|last_20|last_50|last_100)$")] = "all",
    color: Annotated[str, Query(pattern="^(all|white|black)$")] = "all",
    time_class: Annotated[str, Query(max_length=32)] = "all",
    profile_hash: Profile = None,
) -> CoachingResponse:
    # GET is strictly read-only; only POST admits generation.
    from chess_coach.application.errors import OperationError

    report = queries.report(window, color, time_class, profile_hash)
    if report is None:
        raise OperationError(
            "PLAYER_NOT_CONFIGURED",
            "Set the tracked player before requesting historical coaching.",
        )
    result = service.history(report, generate=request.method == "POST")
    response.status_code = 202 if result.status in {"queued", "running"} else 200
    return result
