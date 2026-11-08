"""Immutable coaching contracts. Engine scores always retain White POV."""

from typing import Literal

import chess
from pydantic import ConfigDict, Field, model_validator

from chess_coach.domain.feature_models import EvidenceModel, GamePhase
from chess_coach.domain.game_records import PlayerColor
from chess_coach.domain.score_utils import calculate_loss_cp


class EngineScore(EvidenceModel):
    cp_white: int | None = Field(default=None, strict=True)
    mate_white: int | None = Field(default=None, strict=True)
    mate_winner: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def valid_score(self) -> EngineScore:
        if (self.cp_white is None) == (self.mate_white is None):
            raise ValueError("Exactly one CP or mate score is required")
        if (self.mate_white is None) != (self.mate_winner is None):
            raise ValueError("Mate requires its explicit winner, including mate zero")
        if self.mate_white and self.mate_winner != (self.mate_white > 0):
            raise ValueError("Mate sign disagrees with winner")
        return self


class MoveCoachingEvidence(EvidenceModel):
    schema_version: Literal["move-evidence-v1"] = "move-evidence-v1"
    game_id: int = Field(gt=0, strict=True)
    ply: int = Field(gt=0, strict=True)
    player_color: PlayerColor
    player_rating: int | None = Field(default=None, ge=0, strict=True)
    phase: GamePhase
    fen_before: str
    initial_fen: str
    history_uci: tuple[str, ...]
    history_before_start_unknown: bool
    played_move_uci: str
    best_move_uci: str
    best_line_uci: tuple[str, ...] = Field(min_length=1, max_length=16)
    played_refutation_uci: tuple[str, ...] = Field(max_length=16)
    before: EngineScore
    after: EngineScore
    loss_cp: int | None = Field(default=None, ge=0, strict=True)
    historical_theme_frequency: int | None = Field(default=None, ge=0, strict=True)
    completion_provenance: Literal["pgn_declaration", "chesscom_archive"]
    source_hash: str
    profile_hash: str
    engine_version: str
    analysis_version: str
    draw_policy: str
    feature_version: int = Field(ge=1)

    @model_validator(mode="after")
    def replay(self) -> MoveCoachingEvidence:
        if self.ply != len(self.history_uci) + 1:
            raise ValueError("Ply must match the supplied move history")
        board = chess.Board(self.initial_fen)
        if not board.is_valid():
            raise ValueError("Invalid starting position")
        for uci in self.history_uci:
            self._push(board, uci)
        if board.fen() != self.fen_before or board.turn != (
            self.player_color == "white"
        ):
            raise ValueError("History, position, and mover must agree")
        if self.best_line_uci[0] != self.best_move_uci:
            raise ValueError("Best variation must start with the best move")
        best = board.copy(stack=True)
        for uci in self.best_line_uci:
            self._push(best, uci)
        self._push(board, self.played_move_uci)
        outcome = board.outcome(claim_draw=False)
        if outcome:
            expected = (
                EngineScore(cp_white=0)
                if outcome.winner is None
                else EngineScore(mate_white=0, mate_winner=outcome.winner)
            )
            if self.after != expected or self.played_refutation_uci:
                raise ValueError("Terminal position contradicts after evidence")
        elif not self.played_refutation_uci or self.after.mate_white == 0:
            raise ValueError("Missing continuation or invalid mate zero")
        if self.before.mate_white == 0:
            raise ValueError("Cannot play from mate zero")
        for uci in self.played_refutation_uci:
            self._push(board, uci)
        expected_loss = None
        if self.before.cp_white is not None and self.after.cp_white is not None:
            expected_loss = calculate_loss_cp(
                self.before.cp_white, self.after.cp_white, self.player_color == "white"
            )
        if self.loss_cp != expected_loss:
            raise ValueError("Loss must use the mover perspective; mate is never CP")
        return self

    @staticmethod
    def _push(board: chess.Board, uci: str) -> None:
        move = chess.Move.from_uci(uci)
        if board.is_game_over(claim_draw=False) or move not in board.legal_moves:
            raise ValueError("Illegal move or variation")
        board.push(move)


class MoveExplanation(EvidenceModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    status: Literal["explained", "insufficient_evidence"]
    summary: str = Field(min_length=1, max_length=400)
    what_went_wrong: str = Field(default="", max_length=600)
    why_best_move_works: str = Field(default="", max_length=600)
    lesson: str = Field(default="", max_length=300)
    practice_tip: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def content(self) -> MoveExplanation:
        if not self.summary.strip():
            raise ValueError("Summary cannot be blank")
        details = (
            self.what_went_wrong,
            self.why_best_move_works,
            self.lesson,
            self.practice_tip,
        )
        if self.status == "explained" and any(not s.strip() for s in details):
            raise ValueError("Explained responses require every explanation field")
        if self.status == "insufficient_evidence" and any(details):
            raise ValueError("Abstentions cannot contain unsupported advice")
        return self


class HistoricalAdvice(EvidenceModel):
    pattern_id: str = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=1, max_length=600)
    practice_tip: str = Field(min_length=1, max_length=300)


class HistoricalExplanation(EvidenceModel):
    status: Literal["explained", "insufficient_evidence"]
    summary: str = Field(min_length=1, max_length=400)
    priorities: tuple[HistoricalAdvice, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def content(self) -> HistoricalExplanation:
        if not self.summary.strip() or (self.status == "explained") != bool(
            self.priorities
        ):
            raise ValueError(
                "Historical advice must have grounded priorities or abstain"
            )
        return self


class LLMHealth(EvidenceModel):
    status: Literal["ready", "server_unavailable", "model_missing", "check_failed"]
    server_reachable: bool
    model_installed: bool
    model: str
    model_digest: str | None = None
    message: str
