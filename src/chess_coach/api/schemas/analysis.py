"""Explicit public contracts for completed-game analysis."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from chess_coach.domain.analysis import AnalysisRunStatus


class CreateRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tracked_player_id: int | None = Field(default=None, gt=0)
    scope: Literal["pending"] = "pending"


class RunGame(BaseModel):
    game_id: int
    status: str
    attempt_count: int
    error_code: str | None


class RunProgress(BaseModel):
    id: int
    tracked_player_id: int
    run_id: int
    status: Literal["queued", "running", "completed", "failed"]
    storage_status: AnalysisRunStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_heartbeat_at: datetime | None
    profile_hash: str
    engine_version: str
    analysis_version: str
    engine_config_json: dict[str, int | float | str]
    draw_policy_version: str
    games_total: int
    games_completed: int
    games_failed: int
    games_skipped: int
    games_excluded: int
    positions_analyzed: int
    terminal_positions: int
    cache_hits: int
    cache_misses: int
    engine_seconds: float
    cancel_requested: bool
    error_code: str | None
    error_message: str | None
    progress_percent: float
    successful_percent: float
    worker_available: bool


class RunProgressResponse(RunProgress):
    games_remaining: int = Field(ge=0)


class RunResponse(RunProgress):
    games: list[RunGame]


class Player(BaseModel):
    id: int
    username: str


class WorkerResponse(BaseModel):
    available: bool
    engine_version: str | None
    heartbeat_at: datetime | None
    database: str
    players: list[Player]


class MoveResponse(BaseModel):
    game_id: int
    profile_hash: str
    ply: int
    move_number: int
    mover: str
    played_move_uci: str
    played_move_san: str
    fen_before: str
    best_move_uci: str | None
    eval_before_cp_white: int | None
    eval_after_cp_white: int | None
    mate_before_white: int | None
    mate_after_white: int | None
    mate_before_winner: bool | None
    mate_after_winner: bool | None
    loss_cp: int | None
    pv_json: list[str]
    evidence_kind: str = "single_pass_estimate"


class ReviewVariationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    ply: int = Field(ge=0, strict=True)
    line: list[Annotated[str, Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")]] = Field(
        max_length=256
    )
    evaluate: bool = False


class ReviewEngineLine(BaseModel):
    cp: int | None
    mate: int | None
    white_wins: bool | None
    best_move: str | None
    continuation: str


class ReviewVariationEvaluation(ReviewEngineLine):
    engine: str | None
    alternatives: list[ReviewEngineLine]


class ReviewVariationResponse(BaseModel):
    fen: str
    side_to_move: Literal["white", "black"]
    legal_moves: list[str]
    san: str | None
    outcome: Literal["1-0", "0-1", "1/2-1/2"] | None
    evaluation: ReviewVariationEvaluation | None
