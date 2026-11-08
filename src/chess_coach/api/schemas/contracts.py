"""Frontend contracts; persistence records never cross the HTTP boundary."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from chess_coach.analytics.contracts import (
    AnalyticsHealthReport,
    ContextMetric,
    ReportStatus,
    Segment,
    Summary,
    Weakness,
)
from chess_coach.api.schemas.analysis import MoveResponse
from chess_coach.domain.game_records import GameResult, PlayerColor
from chess_coach.domain.sync import normalize_username

RunStatus = Literal["queued", "running", "completed", "failed"]
GameStatus = Literal["pending", "running", "completed", "failed", "incompatible"]
TimeClass = Literal["bullet", "blitz", "rapid", "daily"]


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, str] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class PlayerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["chess.com"] = "chess.com"
    username: str = Field(min_length=1, max_length=100)

    @field_validator("username")
    @classmethod
    def username_format(cls, value: str) -> str:
        return normalize_username(value)


class Player(BaseModel):
    id: int = Field(gt=0)
    platform: Literal["chess.com"]
    username: str


class PlayerResponse(BaseModel):
    configured: bool
    player: Player | None


class SyncInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AcceptedRun(BaseModel):
    run_id: int = Field(gt=0)
    status: RunStatus


class SyncProgress(BaseModel):
    archives_total: int | None = Field(ge=0)
    archives_processed: int = Field(ge=0)
    games_seen: int = Field(ge=0)
    games_inserted: int = Field(ge=0)
    games_existing: int = Field(ge=0)
    games_failed: int = Field(ge=0)


class SyncRunResponse(AcceptedRun):
    started_at: datetime | None
    finished_at: datetime | None
    progress: SyncProgress
    error: ErrorResponse | None
    recoverable: bool


class GameItem(BaseModel):
    id: int
    played_at: datetime
    opponent: str
    player_color: PlayerColor
    result: GameResult
    time_class: str | None
    opening_name: str | None
    analysis_status: GameStatus


class GamePage(BaseModel):
    items: list[GameItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class GameDetail(GameItem):
    white_username: str
    black_username: str
    white_rating: int | None
    black_rating: int | None
    eco_code: str | None
    time_control: str | None
    raw_pgn: str
    completion_provenance: Literal["chesscom_archive", "pgn_declaration"]


class GameAnalysisResponse(BaseModel):
    game_id: int
    status: GameStatus
    profile_hash: str | None
    engine_version: str | None
    analysis_version: str | None
    moves: list[MoveResponse]


class AnalyticsFilters(BaseModel):
    window: Literal["last_20", "last_50", "last_100", "all"] = "last_50"
    color: Literal["white", "black", "all"] = "all"
    time_class: Literal["bullet", "blitz", "rapid", "daily", "all"] = "all"
    profile_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class AnalyticsBase(BaseModel):
    filters: AnalyticsFilters
    profile_hash: str | None
    status: ReportStatus
    analytics_version: str = "longitudinal-v1"
    policy_version: str = "support-v1"
    selected_game_ids: tuple[int, ...]
    health: AnalyticsHealthReport | None


class SummaryResponse(AnalyticsBase):
    metrics: Summary | None


class SegmentsResponse(AnalyticsBase):
    items: tuple[Segment, ...]


class PatternsResponse(AnalyticsBase):
    ranker_version: str = "weakness-ranker-v1"
    patterns: dict[str, tuple[Weakness, ...]]
    contexts: tuple[ContextMetric, ...]


class Component(BaseModel):
    status: Literal["available", "unavailable", "unknown"]
    model: str | None = None
    version: str | None = None


class Components(BaseModel):
    database: Component
    stockfish: Component
    ollama: Component


class Statistics(BaseModel):
    games_stored: int
    games_analyzed: int
    pending_games: int


class SystemResponse(BaseModel):
    status: Literal["healthy", "degraded", "unavailable"]
    components: Components
    statistics: Statistics | None
    checked_at: datetime
