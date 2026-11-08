"""Versioned analysis identity and validation, independent of persistence."""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

import chess

from chess_coach.domain.engine_types import EngineResult

ANALYSIS_VERSION = "single-v1"
DRAW_POLICY = "automatic-only-v1"


class AnalysisRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE = (AnalysisRunStatus.PENDING, AnalysisRunStatus.RUNNING)


def transition(current: AnalysisRunStatus, target: AnalysisRunStatus) -> None:
    allowed = {
        AnalysisRunStatus.PENDING: {
            AnalysisRunStatus.RUNNING,
            AnalysisRunStatus.CANCELLED,
        },
        AnalysisRunStatus.RUNNING: set(AnalysisRunStatus) - set(ACTIVE),
    }
    if target not in allowed.get(current, set()):
        raise ValueError(f"Invalid analysis transition: {current} -> {target}")


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class AnalysisProfile:
    engine: str
    config: dict[str, int | float | str]
    version: str = ANALYSIS_VERSION
    draw_policy: str = DRAW_POLICY

    @property
    def config_hash(self) -> str:
        return fingerprint(self.config)

    @property
    def hash(self) -> str:
        return fingerprint([self.engine, self.config, self.version, self.draw_policy])


def history_hash(board: chess.Board, unknown: bool) -> str:
    return fingerprint(
        [board.root().fen(), [m.uci() for m in board.move_stack], unknown]
    )


def validate_result(board: chess.Board, result: EngineResult, engine: str) -> None:
    if result.fen != board.fen() or result.engine_name != engine:
        raise ValueError("ENGINE_INVALID_RESULT: position or engine identity mismatch")
    if (result.score_cp_white is None) == (result.mate_white is None):
        raise ValueError("ENGINE_INVALID_RESULT: expected exactly one score")
    for value in (result.score_cp_white, result.mate_white, result.depth, result.nodes):
        if value is not None and type(value) is not int:
            raise ValueError("ENGINE_INVALID_RESULT: noninteger evidence")
    if any(v is not None and v < 0 for v in (result.depth, result.nodes)):
        raise ValueError("ENGINE_INVALID_RESULT: negative search metadata")
    if result.mate_white is None:
        if result.mate_winner is not None:
            raise ValueError("ENGINE_INVALID_RESULT: unexpected mate winner")
    elif type(result.mate_winner) is not bool or (
        result.mate_white != 0 and result.mate_winner != (result.mate_white > 0)
    ):
        raise ValueError("ENGINE_INVALID_RESULT: invalid mate winner")
    outcome = board.outcome(claim_draw=False)
    if outcome:
        if result.best_move_uci is not None or result.pv_uci:
            raise ValueError("ENGINE_INVALID_RESULT: terminal PV")
        if outcome.winner is None:
            valid = result.score_cp_white == 0 and result.mate_white is None
        else:
            valid = result.mate_white == 0 and result.mate_winner == outcome.winner
        if not valid:
            raise ValueError("ENGINE_INVALID_RESULT: terminal score")
        return
    if (
        result.mate_white == 0
        or not result.pv_uci
        or result.best_move_uci != result.pv_uci[0]
    ):
        raise ValueError("ENGINE_INVALID_RESULT: missing or inconsistent PV")
    replay = board.copy(stack=True)
    for uci in result.pv_uci:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            raise ValueError("ENGINE_INVALID_RESULT: malformed PV move") from None
        if replay.is_game_over(claim_draw=False) or move not in replay.legal_moves:
            raise ValueError("ENGINE_INVALID_RESULT: illegal PV")
        replay.push(move)
