"""Transport-only player and completed-game queries."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from chess_coach.api.dependencies import get_query_service
from chess_coach.api.schemas.contracts import (
    GameAnalysisResponse,
    GameDetail,
    GamePage,
    PlayerInput,
    PlayerResponse,
    TimeClass,
)
from chess_coach.application.queries import QueryService

router = APIRouter(prefix="/api/v1", tags=["games and player"])
Service = Annotated[QueryService, Depends(get_query_service)]
PositiveID = Annotated[int, Path(gt=0, description="Persistent database integer ID")]


@router.get("/player", response_model=PlayerResponse, summary="Read the tracked player")
def player(service: Service) -> dict[str, object]:
    return service.player()


@router.put(
    "/player",
    response_model=PlayerResponse,
    summary="Configure the tracked player without importing games",
)
def set_player(body: PlayerInput, service: Service) -> dict[str, object]:
    return service.set_player(body.username)


@router.get(
    "/games", response_model=GamePage, summary="List completed historical games"
)
def games(
    service: Service,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Maximum games returned")
    ] = 20,
    offset: Annotated[
        int, Query(ge=0, description="Games skipped in date/ID descending order")
    ] = 0,
    time_class: TimeClass | None = None,
    player_color: Literal["white", "black"] | None = None,
    analysis_status: Literal["pending", "running", "completed", "failed"] | None = None,
) -> dict[str, object]:
    return service.games(limit, offset, time_class, player_color, analysis_status)


@router.get(
    "/games/{game_id}",
    response_model=GameDetail,
    summary="Read one stored game and its PGN",
)
def game(game_id: PositiveID, service: Service) -> dict[str, object]:
    return service.game(game_id)


@router.get(
    "/games/{game_id}/analysis",
    response_model=GameAnalysisResponse,
    summary="Read stored engine evidence without starting analysis",
)
def game_analysis(
    game_id: PositiveID,
    service: Service,
    profile_hash: Annotated[
        str | None,
        Query(
            pattern=r"^[a-f0-9]{64}$",
            description="Explicit analysis profile; otherwise use the registered/latest profile",
        ),
    ] = None,
) -> dict[str, object]:
    return service.game_analysis(game_id, profile_hash)
