from typing import Literal

from pydantic import BaseModel

DependencyState = Literal["available", "unavailable", "unknown"]


class DependencyStatus(BaseModel):
    state: DependencyState
    detail: str | None = None


class SystemStatusResponse(BaseModel):
    api: DependencyStatus
    stockfish: DependencyStatus
    ollama: DependencyStatus
    ollama_model: DependencyStatus
