"""Historical analysis orchestration; HTTP never invokes the engine."""

import logging
from collections.abc import Callable
from threading import Event
from time import monotonic
from typing import Protocol

import chess

from chess_coach.application.parse_imported_games import ParseInput, _source_result
from chess_coach.config import Settings
from chess_coach.domain.analysis import AnalysisProfile
from chess_coach.domain.engine_types import EngineResult
from chess_coach.domain.game_records import PGNParseError
from chess_coach.infrastructure.engine.exceptions import (
    EngineAnalysisError,
    EngineUnavailableError,
)
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
    profile_of,
)
from chess_coach.infrastructure.persistence.models import AnalysisRun
from chess_coach.infrastructure.pgn.parser import parse_game

logger = logging.getLogger(__name__)


def configured_profile(settings: Settings, engine: str) -> AnalysisProfile:
    return AnalysisProfile(
        engine,
        {
            "threads": settings.stockfish_threads,
            "hash_mb": settings.stockfish_hash_mb,
            "nodes": settings.stockfish_nodes,
            "search_seconds": settings.stockfish_search_seconds,
            "multipv": 1,
            "chess_version": chess.__version__,
            "score_policy": "white-mate-separate-v1",
        },
    )


class Engine(Protocol):
    engine_name: str

    def start(self) -> None: ...
    def close(self) -> None: ...
    def analyze(
        self,
        board: chess.Board,
        *,
        nodes: int | None = None,
        game: object | None = None,
    ) -> EngineResult: ...


class AnalysisProcessor:
    def __init__(
        self,
        store: AnalysisRepository,
        engine: Engine,
        settings: Settings,
        stop: Event | None = None,
        checkpoint: Callable[[str, int], None] | None = None,
    ):
        self.store, self.engine, self.settings = store, engine, settings
        self.stop = stop or Event()
        self.checkpoint = checkpoint or (lambda event, identity: None)

    def process(self, run_id: int) -> None:
        profile = profile_of(self.store.get(run_id))
        for member in self.store.members(run_id):
            if member.status != "pending":
                continue
            if self.stop.is_set():
                return  # RUNNING is explicitly recovered under the lock on restart.
            if self.store.get(run_id).cancel_requested:
                break
            game_id = member.game_id
            try:
                game, username = self.store.begin_game(run_id, game_id)
                parse_started = monotonic()
                expected, final_fen = _source_result(
                    ParseInput(
                        game.id,
                        game.raw_pgn,
                        username,
                        game.platform,
                        game.white_username,
                        game.black_username,
                        game.source_evidence,
                    )
                )
                parsed = parse_game(
                    game.raw_pgn,
                    username,
                    max_bytes=self.settings.pgn_max_bytes,
                    source_final_fen=final_fen,
                )
                if expected is not None and parsed.source_result != expected:
                    raise ValueError("INVALID_GAME: source result mismatch")
                if (
                    parsed.white_username.casefold(),
                    parsed.black_username.casefold(),
                ) != (game.white_username.casefold(), game.black_username.casefold()):
                    raise ValueError("INVALID_GAME: player mismatch")
                logger.info(
                    "analysis_timing",
                    extra={
                        "run_id": run_id,
                        "game_id": game_id,
                        "operation": "reconstruction",
                        "duration_seconds": monotonic() - parse_started,
                    },
                )
                board = chess.Board(parsed.initial_fen)
                positions: list[int] = []
                cache_seconds = 0.0
                for i in range(parsed.total_plies + 1):
                    if self.stop.is_set():
                        return
                    if self.store.get(run_id).cancel_requested:
                        self.store.finish(run_id)
                        return
                    self.store.heartbeat(run_id)
                    cache_started = monotonic()
                    row = self.store.cached(
                        board, parsed.history_before_start_unknown, profile
                    )
                    cache_seconds += monotonic() - cache_started
                    if row is not None:
                        self.store.hit(run_id)
                        positions.append(row.id)
                    else:
                        begin = monotonic()
                        outcome = board.outcome(claim_draw=False)
                        if outcome is not None:
                            result = EngineResult(
                                board.fen(),
                                profile.engine,
                                0 if outcome.winner is None else None,
                                0 if outcome.winner is not None else None,
                                outcome.winner,
                                None,
                                (),
                                0,
                                0,
                            )
                            seconds = 0.0
                        else:
                            result = self._search(board, profile)
                            seconds = monotonic() - begin
                        positions.append(
                            self.store.save_position(
                                run_id,
                                board,
                                parsed.history_before_start_unknown,
                                profile,
                                result,
                                seconds,
                            )
                        )
                    self.checkpoint("position", i)
                    if i < parsed.total_plies:
                        board.push_uci(parsed.moves[i].uci)
                logger.info(
                    "analysis_timing",
                    extra={
                        "run_id": run_id,
                        "game_id": game_id,
                        "operation": "cache_lookup",
                        "duration_seconds": cache_seconds,
                    },
                )
                finalize_started = monotonic()
                self.store.finalize(run_id, game_id, parsed, profile, positions)
                logger.info(
                    "game_completed",
                    extra={
                        "run_id": run_id,
                        "game_id": game_id,
                        "operation": "finalization",
                        "duration_seconds": monotonic() - finalize_started,
                    },
                )
                self.checkpoint("game", game_id)
            except EngineAnalysisError, EngineUnavailableError:
                logger.exception(
                    "engine_failure", extra={"run_id": run_id, "game_id": game_id}
                )
                self.store.fail_game(run_id, game_id, "ENGINE_UNAVAILABLE")
                self.store.finish(run_id, "ENGINE_UNAVAILABLE")
                return
            except (PGNParseError, ValueError) as exc:
                code = (
                    "ENGINE_INVALID_RESULT"
                    if str(exc).startswith("ENGINE_INVALID_RESULT")
                    else "INVALID_GAME"
                )
                logger.warning(
                    "game_failed",
                    extra={"run_id": run_id, "game_id": game_id, "error_code": code},
                )
                self.store.fail_game(run_id, game_id, code)
        self.store.finish(run_id)

    def _search(self, board: chess.Board, profile: AnalysisProfile) -> EngineResult:
        for attempt in range(2):
            try:
                # New UCI game clears search state for reproducible context isolation.
                return self.engine.analyze(
                    board, nodes=int(profile.config["nodes"]), game=object()
                )
            except EngineAnalysisError, EngineUnavailableError:
                if attempt:
                    raise
                self.engine.close()
                self.engine.start()
                if self.engine.engine_name != profile.engine:
                    raise EngineUnavailableError("Engine identity changed during retry")
        raise AssertionError("Unreachable")


class AnalysisService:
    def __init__(self, store: AnalysisRepository):
        self.store = store

    def create(self, player_id: int | None = None) -> AnalysisRun:
        from chess_coach.application.errors import OperationError

        players = self.store.players()
        if not players:
            raise OperationError(
                "PLAYER_NOT_CONFIGURED", "Configure the tracked player first."
            )
        if len(players) != 1 or (player_id is not None and player_id != players[0][0]):
            raise OperationError(
                "PLAYER_MISMATCH", "Select the single configured player."
            )
        player_id = players[0][0]
        return self.store.get(
            self.store.create(player_id, self.store.available_profile())
        )

    def detail(self, run_id: int) -> dict[str, object]:
        run = self.store.get(run_id)
        processed = run.games_completed + run.games_failed + run.games_skipped
        return {
            **{c.name: getattr(run, c.name) for c in run.__table__.columns},
            "run_id": run.id,
            "storage_status": run.status,
            "status": {
                "pending": "queued",
                "running": "running",
                "done": "completed",
                "completed_with_errors": "failed",
                "cancelled": "failed",
                "failed": "failed",
            }[run.status],
            "error_message": "Analysis stopped. Check backend logs and retry pending work."
            if run.error_code or run.error_message
            else None,
            "progress_percent": 100 * processed / run.games_total
            if run.games_total
            else 100,
            "successful_percent": 100
            * (run.games_completed + run.games_skipped)
            / run.games_total
            if run.games_total
            else 100,
            "worker_available": self.store.worker_status()["available"],
            "games": [
                {
                    "game_id": m.game_id,
                    "status": m.status,
                    "attempt_count": m.attempt_count,
                    "error_code": m.error_code,
                }
                for m in self.store.members(run_id)
            ],
        }

    def list_runs(self) -> list[dict[str, object]]:
        return [self.detail(r.id) for r in self.store.runs()]

    def cancel(self, run_id: int) -> dict[str, object]:
        self.store.cancel(run_id)
        return self.detail(run_id)

    def status(self) -> dict[str, object]:
        return {
            **self.store.worker_status(),
            "database": "healthy",
            "players": [
                {"id": p, "username": name} for p, name in self.store.players()
            ],
        }

    def moves(self, game_id: int, profile_hash: str) -> list[dict[str, object]]:
        return [
            {c.name: getattr(m, c.name) for c in m.__table__.columns}
            for m in self.store.moves(game_id, profile_hash)
        ]
