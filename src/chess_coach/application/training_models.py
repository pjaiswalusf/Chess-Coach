"""Response models for puzzle practice."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from chess_coach.domain.game_records import PlayerColor


class PublicPuzzle(BaseModel):
    id: int
    fen: str
    side_to_move: PlayerColor
    theme: str
    difficulty: str
    attempt_count: int
    legal_moves: list[str]
    solver_moves: int = 1


class NextPuzzle(BaseModel):
    puzzle: PublicPuzzle | None = None
    reason: Literal["NO_PUZZLES_DUE"] | None = None


class AttemptResult(BaseModel):
    attempt_id: int
    correct: bool
    submitted_move_uci: str
    solution_move_uci: str
    solution_san: str
    solution_pv_san: list[str]
    original_move_uci: str
    source_game_id: int
    source_ply: int
    source_profile_hash: str
    attempted_at: datetime
    next_review_at: datetime
    final_fen: str | None = None
    wrong_move_reason: str | None = None
    last_move_uci: str | None = None


class PuzzleContinuation(BaseModel):
    fen: str
    legal_moves: list[str]
    reply_san: str


class PuzzleStep(BaseModel):
    continuation: PuzzleContinuation | None = None
    result: AttemptResult | None = None


class ThemeStats(BaseModel):
    theme: str
    puzzles: int
    attempts: int
    correct: int
    accuracy: float | None


class TrainingStats(BaseModel):
    puzzles_total: int
    puzzles_attempted: int
    attempts_total: int
    correct_attempts: int
    incorrect_attempts: int
    accuracy: float | None
    puzzles_due: int
    average_attempts: float | None
    themes: list[ThemeStats]
    solve_streak: int = 0
