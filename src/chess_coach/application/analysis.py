"""Historical analysis orchestration; HTTP never invokes the engine."""

import logging
from collections.abc import Callable
from threading import Event
from time import perf_counter
from typing import Literal, Protocol

import chess
from structlog.contextvars import bound_contextvars

from chess_coach.application.parse_imported_games import (
    ParseInput,
    parse_game_with_source,
)
from chess_coach.config import Settings
from chess_coach.domain.analysis import AnalysisProfile
from chess_coach.domain.engine_types import EngineResult
from chess_coach.domain.game_records import ParsedGame, PGNParseError
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
from chess_coach.infrastructure.system.diagnostics import require_current_database
from chess_coach.observability.logging import elapsed_ms

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
        with bound_contextvars(run_id=str(run_id), component="analysis"):
            started = perf_counter()
            try:
                run = self.store.get(run_id)
                logger.info(
                    "analysis_started",
                    extra={
                        "game_count": run.games_total,
                        "engine_version": run.engine_version,
                    },
                )
                result = self._process(run_id, profile_of(run))
                duration = elapsed_ms(started)
                if result == "RUN_INTERRUPTED":
                    self.store.record_interruption(run_id, duration)
                    logger.info(
                        "analysis_interrupted",
                        extra={"duration_ms": duration, "status": "running"},
                    )
                    return
                self.store.finish(run_id, result, duration_ms=duration)
                run = self.store.get(run_id)
            except Exception:
                logger.exception(
                    "analysis_failed",
                    extra={
                        "duration_ms": elapsed_ms(started),
                        "error_code": "ANALYSIS_PROCESSING_FAILED",
                    },
                )
                raise
            succeeded = run.status == "done"
            logger.log(
                logging.INFO if succeeded else logging.WARNING,
                "analysis_finished" if succeeded else "analysis_failed",
                extra={
                    "status": run.status,
                    "duration_ms": run.active_duration_ms,
                    "games_completed": run.games_completed,
                    "positions_analyzed": run.positions_analyzed,
                    "terminal_positions": run.terminal_positions,
                    "cache_hits": run.cache_hits,
                    "cache_misses": run.cache_misses,
                    "engine_duration_ms": round(run.engine_seconds * 1000),
                    "error_code": run.error_code
                    or {
                        "cancelled": "RUN_CANCELLED",
                        "completed_with_errors": "GAMES_FAILED",
                    }.get(run.status),
                },
            )

    def _process(self, run_id: int, profile: AnalysisProfile) -> str | None:
        try:
            self.engine.start()
            if self.engine.engine_name != profile.engine:
                return "ANALYSIS_PROFILE_MISMATCH"
        except EngineAnalysisError, EngineUnavailableError:
            logger.exception(
                "engine_failure", extra={"error_code": "ENGINE_UNAVAILABLE"}
            )
            return "ENGINE_UNAVAILABLE"
        for member in self.store.members(run_id):
            if member.status != "pending":
                continue
            if self.stop.is_set():
                return "RUN_INTERRUPTED"  # Recovered under the lock on restart.
            if self.store.get(run_id).cancel_requested:
                break
            game_id = member.game_id
            try:
                interruption = self._analyze_game(run_id, game_id, profile)
                if interruption is not None:
                    return "RUN_INTERRUPTED" if interruption == "stopped" else None
            except EngineAnalysisError, EngineUnavailableError:
                logger.exception(
                    "engine_failure", extra={"run_id": run_id, "game_id": game_id}
                )
                self.store.fail_game(run_id, game_id, "ENGINE_UNAVAILABLE")
                return "ENGINE_UNAVAILABLE"
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
        return None

    def _analyze_game(
        self, run_id: int, game_id: int, profile: AnalysisProfile
    ) -> Literal["stopped", "cancelled"] | None:
        game_started = perf_counter()
        game, username = self.store.begin_game(run_id, game_id)
        parse_started = perf_counter()
        parsed, expected = parse_game_with_source(
            ParseInput(
                game.id,
                game.raw_pgn,
                username,
                game.platform,
                game.white_username,
                game.black_username,
                game.source_evidence,
            ),
            parse_game,
            max_bytes=self.settings.pgn_max_bytes,
        )
        if expected is not None and parsed.source_result != expected:
            raise ValueError("INVALID_GAME: source result mismatch")
        if (
            parsed.white_username.casefold(),
            parsed.black_username.casefold(),
        ) != (game.white_username.casefold(), game.black_username.casefold()):
            raise ValueError("INVALID_GAME: player mismatch")
        logger.debug(
            "analysis_timing",
            extra={
                "run_id": run_id,
                "game_id": game_id,
                "operation": "reconstruction",
                "duration_ms": elapsed_ms(parse_started),
            },
        )
        board = chess.Board(parsed.initial_fen)
        positions: list[int] = []
        cache_seconds = 0.0
        for i in range(parsed.total_plies + 1):
            if self.stop.is_set():
                return "stopped"
            if self.store.get(run_id).cancel_requested:
                return "cancelled"
            position_id, lookup_seconds = self._analyze_position(
                run_id, game_id, board, parsed, profile
            )
            positions.append(position_id)
            cache_seconds += lookup_seconds
            self.checkpoint("position", i)
            if i < parsed.total_plies:
                board.push_uci(parsed.moves[i].uci)
        logger.debug(
            "analysis_timing",
            extra={
                "run_id": run_id,
                "game_id": game_id,
                "operation": "cache_lookup",
                "duration_ms": round(cache_seconds * 1000),
            },
        )
        self.store.finalize(run_id, game_id, parsed, profile, positions)
        logger.info(
            "game_completed",
            extra={
                "run_id": run_id,
                "game_id": game_id,
                "operation": "game_analysis",
                "duration_ms": elapsed_ms(game_started),
            },
        )
        self.checkpoint("game", game_id)
        return None

    def _analyze_position(
        self,
        run_id: int,
        game_id: int,
        board: chess.Board,
        parsed: ParsedGame,
        profile: AnalysisProfile,
    ) -> tuple[int, float]:
        cache_started = perf_counter()
        row = self.store.cached(board, parsed.history_before_start_unknown, profile)
        cache_seconds = perf_counter() - cache_started
        hit = row is not None
        self.store.record_lookup(run_id, hit=hit)
        logger.debug(
            "cache_hit" if hit else "cache_miss",
            extra={"game_id": game_id, "cache_type": "engine_position"},
        )
        if row is not None:
            return row.id, cache_seconds
        seconds = 0.0
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
        else:
            result, seconds = self._search(run_id, board, profile)
        return self.store.save_position(
            run_id, board, parsed.history_before_start_unknown, profile, result, seconds
        ), cache_seconds

    def _search(
        self, run_id: int, board: chess.Board, profile: AnalysisProfile
    ) -> tuple[EngineResult, float]:
        seconds = 0.0
        try:
            for attempt in range(2):
                try:
                    # New UCI game clears search state for reproducible context isolation.
                    started = perf_counter()
                    try:
                        result = self.engine.analyze(
                            board, nodes=int(profile.config["nodes"]), game=object()
                        )
                    finally:
                        seconds += perf_counter() - started
                    return result, seconds
                except EngineAnalysisError, EngineUnavailableError:
                    if attempt:
                        raise
                    self.engine.close()
                    self.engine.start()
                    if self.engine.engine_name != profile.engine:
                        raise EngineUnavailableError(
                            "Engine identity changed during retry"
                        )
        except EngineAnalysisError, EngineUnavailableError:
            self.store.record_engine_time(run_id, seconds)
            raise
        raise AssertionError("Unreachable")


class AnalysisService:
    def __init__(self, store: AnalysisRepository):
        self.store = store

    def create(self, player_id: int | None = None) -> AnalysisRun:
        from chess_coach.application.errors import OperationError

        require_current_database(self.store.database)
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
        run_id = self.store.create(player_id, self.store.available_profile())
        logger.info("analysis_queued", extra={"run_id": run_id})
        return self.store.get(run_id)

    def progress(self, run_id: int) -> dict[str, object]:
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
            "games_remaining": max(0, run.games_total - processed),
        }

    def detail(self, run_id: int) -> dict[str, object]:
        return self.progress(run_id) | {
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
