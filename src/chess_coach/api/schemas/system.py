from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from chess_coach.api.schemas.contracts import Statistics, TrainingHealth

DependencyState = Literal["available", "unavailable", "unknown"]


class DependencyStatus(BaseModel):
    state: DependencyState
    detail: str | None = None


class SystemStatusResponse(BaseModel):
    api: DependencyStatus
    stockfish: DependencyStatus
    ollama: DependencyStatus
    ollama_model: DependencyStatus


class ComponentCheck(BaseModel):
    status: Literal["pass", "warn", "fail", "skip"]
    required: bool
    message: str
    action: str | None = None
    code: str | None = None


class ComponentHealth(BaseModel):
    overall: Literal["healthy", "degraded", "unavailable"]
    components: dict[str, ComponentCheck]
    checked_at: datetime
    statistics: Statistics | None = None
    training: TrainingHealth | None = None
    analysis_version: str | None = None
    engine_version: str | None = None
    model: str | None = None


class AnalysisMetrics(BaseModel):
    run_id: str
    positions_per_second: float | None
    cache_hit_rate: float | None
    duration_ms: int | None
    games_per_hour: float | None


class CoachingMetrics(BaseModel):
    window_days: int
    sample_count: int
    latency_p50_ms: float | None
    first_schema_failure_rate: float | None
    first_schema_sample_count: int
    final_failure_rate: float | None


class SystemMetrics(BaseModel):
    analysis: AnalysisMetrics | None
    coaching: CoachingMetrics
