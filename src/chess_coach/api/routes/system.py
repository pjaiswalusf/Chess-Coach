from typing import Annotated

from fastapi import APIRouter, Depends

from chess_coach.api.dependencies import get_system_status
from chess_coach.api.schemas.system import DependencyStatus, SystemStatusResponse
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
