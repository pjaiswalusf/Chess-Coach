"""Serialized synchronous engine ownership. Recovery requires explicit start()."""

import shutil
from threading import RLock
from types import TracebackType
from typing import Self

import chess
import chess.engine

from chess_coach.config import Settings
from chess_coach.domain.engine_types import EngineResult
from chess_coach.domain.score_utils import normalize_score
from chess_coach.infrastructure.engine.exceptions import (
    EngineAnalysisError,
    EngineUnavailableError,
    InvalidPositionError,
)

_ERRORS = (chess.engine.EngineError, TimeoutError, OSError)


class StockfishAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = (settings or Settings()).model_copy(deep=True)
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = RLock()
        self.engine_name = ""

    def start(self) -> None:
        with self._lock:
            if self._engine is not None:
                return
            path = shutil.which(self.settings.stockfish_executable)
            if path is None:
                raise EngineUnavailableError(
                    "Stockfish executable not found; install Stockfish or set "
                    "CHESS_COACH_STOCKFISH_EXECUTABLE."
                )
            try:
                self._engine = chess.engine.SimpleEngine.popen_uci(
                    path, timeout=self.settings.stockfish_timeout_seconds
                )
                for name in ("Threads", "Hash"):
                    if name not in self._engine.options:
                        raise chess.engine.EngineError(f"Missing UCI option: {name}")
                self._engine.configure({
                    "Threads": self.settings.stockfish_threads,
                    "Hash": self.settings.stockfish_hash_mb,
                })
                self._engine.ping()
                self.engine_name = self._engine.id.get("name", "")
                if not self.engine_name.strip():
                    raise chess.engine.EngineError("Missing UCI engine identity")
            except _ERRORS as exc:
                self._discard()
                raise EngineUnavailableError("Stockfish startup failed; check binary and configuration") from exc

    def _discard(self) -> None:
        engine, self._engine = self._engine, None
        if engine is not None:
            engine.close()
            try:
                engine.returncode.result(timeout=self.settings.stockfish_timeout_seconds)
            except TimeoutError as exc:
                # Retain ownership so a new process cannot replace an unconfirmed exit.
                self._engine = engine
                raise EngineAnalysisError("Stockfish process exit could not be confirmed") from exc

    def check_health(self) -> bool:
        with self._lock:
            if self._engine is None:
                return False
            try:
                self._engine.ping()
                return True
            except _ERRORS:
                self._discard()
                return False

    def analyze(self, board: chess.Board, *, nodes: int | None = None,
                game: object | None = None) -> EngineResult:
        with self._lock:
            budget = self.settings.stockfish_nodes if nodes is None else nodes
            if type(budget) is not int or not 0 < budget <= self.settings.stockfish_max_nodes:
                raise ValueError("Node budget must be a positive integer within configured maximum")
            if type(board) is not chess.Board or board.chess960 or not board.is_valid():
                raise InvalidPositionError("Only valid standard chess positions are supported")
            position = board.copy(stack=True)
            replay = position.root()
            if not replay.is_valid():
                raise InvalidPositionError("Invalid starting position")
            for move in position.move_stack:
                if replay.is_game_over(claim_draw=False) or move not in replay.legal_moves:
                    raise InvalidPositionError("Invalid move history")
                replay.push(move)
            if replay.fen() != position.fen():
                raise InvalidPositionError("Board does not match its move history")
            if self._engine is None:
                raise EngineUnavailableError("Start Stockfish before analysis")
            outcome = position.outcome(claim_draw=False)
            if outcome is not None:
                return EngineResult(position.fen(), self.engine_name,
                                    0 if outcome.winner is None else None,
                                    0 if outcome.winner is not None else None,
                                    outcome.winner, None, (), None, None)
            try:
                info = self._engine.analyse(
                    position,
                    chess.engine.Limit(nodes=budget, time=self.settings.stockfish_search_seconds),
                    game=game if game is not None else object(),
                )
                score = info.get("score")
                pv = info.get("pv")
                if not isinstance(score, chess.engine.PovScore) or not pv:
                    raise EngineAnalysisError("Engine returned no score or principal variation")
                if info.get("lowerbound") or info.get("upperbound"):
                    raise EngineAnalysisError("Engine returned only a score bound")
                cp, mate = normalize_score(score)
                if (cp is None) == (mate is None):
                    raise EngineAnalysisError("Engine returned an invalid score")
                replay = position.copy(stack=True)
                for move in pv:
                    if not isinstance(move, chess.Move) or move not in replay.legal_moves:
                        raise EngineAnalysisError("Engine returned an illegal principal variation")
                    replay.push(move)
                for key in ("depth", "nodes"):
                    value = info.get(key)
                    if value is not None and (type(value) is not int or value < 0):
                        raise EngineAnalysisError("Engine returned invalid search metadata")
                moves = tuple(move.uci() for move in pv)
                winner = (score.white() > chess.engine.Cp(0)) if mate is not None else None
                return EngineResult(position.fen(), self.engine_name, cp, mate, winner,
                                    moves[0], moves, info.get("depth"), info.get("nodes"))
            except (*_ERRORS, EngineAnalysisError) as exc:
                self._discard()
                raise EngineAnalysisError("Stockfish analysis failed; restart explicitly before retrying") from exc

    def close(self) -> None:
        with self._lock:
            engine, self._engine = self._engine, None
            if engine is None:
                return
            try:
                engine.quit()
                engine.returncode.result(timeout=self.settings.stockfish_timeout_seconds)
            except _ERRORS as exc:
                raise EngineAnalysisError("Stockfish shutdown failed") from exc
            finally:
                engine.close()
                try:
                    engine.returncode.result(timeout=self.settings.stockfish_timeout_seconds)
                except TimeoutError as exc:
                    self._engine = engine
                    raise EngineAnalysisError("Stockfish process exit could not be confirmed") from exc

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None, traceback: TracebackType | None) -> None:
        if exc is not None:
            with self._lock:
                try:
                    self._discard()
                except EngineAnalysisError:
                    # Preserve the caller's original exception while retaining ownership.
                    pass
        else:
            self.close()
