from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExternalGame:
    external_id: str
    pgn: str
    played_at: datetime
    white_username: str
    black_username: str


@dataclass(frozen=True)
class EngineAnalysis:
    score_cp_white: int | None
    mate_white: int | None
    best_move_uci: str | None
    principal_variation: tuple[str, ...]


@dataclass(frozen=True)
class CoachResponse:
    summary: str
    lesson: str
