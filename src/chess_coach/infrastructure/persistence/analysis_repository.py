"""Short SQLite transactions for persistent runs, compatible cache, and finalization."""

import logging
from datetime import timedelta
from pathlib import Path

import chess
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from chess_coach.application.errors import OperationError
from chess_coach.domain.analysis import (
    ACTIVE,
    AnalysisProfile,
    fingerprint,
    history_hash,
    transition,
    validate_result,
)
from chess_coach.domain.analysis import (
    AnalysisRunStatus as Status,
)
from chess_coach.domain.engine_types import EngineResult
from chess_coach.domain.game_records import PARSER_VERSION, ParsedGame, ParseStatus
from chess_coach.domain.score_utils import calculate_loss_cp
from chess_coach.infrastructure.analysis_lock import worker_is_locked
from chess_coach.infrastructure.persistence.models import (
    AnalysisRun,
    AnalysisRunGame,
    AnalysisWorkerState,
    Game,
    GameAnalysisState,
    GameAnalysisStatus,
    MoveAnalysis,
    PositionCache,
    TrackedPlayer,
    utc_now,
)
from chess_coach.infrastructure.persistence.operations import ensure_idle, reserve


class AnalysisError(OperationError):
    pass


def source_hash(game: Game) -> str:
    return fingerprint(
        [
            game.raw_pgn,
            game.platform,
            game.source_evidence,
            game.white_username,
            game.black_username,
            game.parser_version,
            game.chess_library_version,
            game.parsed_metadata,
        ]
    )


def profile_of(run: AnalysisRun) -> AnalysisProfile:
    return AnalysisProfile(
        run.engine_version,
        run.engine_config_json,
        run.analysis_version,
        run.draw_policy_version,
    )


def result_of(row: PositionCache) -> EngineResult:
    return EngineResult(
        row.fen,
        row.engine_version,
        row.score_cp_white,
        row.mate_distance_white,
        row.mate_winner,
        row.best_move_uci,
        tuple(row.pv_json),
        row.depth,
        row.nodes,
    )


class AnalysisRepository:
    def __init__(self, sessions: sessionmaker[Session], database: Path):
        self.sessions, self.database = sessions, database

    def register(self, profile: AnalysisProfile, status: str = "ready") -> None:
        with self.sessions.begin() as s:
            s.merge(
                AnalysisWorkerState(
                    id=1,
                    engine_version=profile.engine,
                    config_json=profile.config,
                    heartbeat_at=utc_now(),
                    status=status,
                )
            )

    def heartbeat(self, run_id: int | None = None) -> None:
        with self.sessions.begin() as s:
            s.execute(
                update(AnalysisWorkerState)
                .where(AnalysisWorkerState.id == 1)
                .values(heartbeat_at=utc_now())
            )
            if run_id:
                s.execute(
                    update(AnalysisRun)
                    .where(AnalysisRun.id == run_id)
                    .values(last_heartbeat_at=utc_now())
                )

    def worker_status(self) -> dict[str, object]:
        with self.sessions() as s:
            w = s.get(AnalysisWorkerState, 1)
            alive = bool(
                w
                and w.status == "ready"
                and w.heartbeat_at > utc_now() - timedelta(seconds=30)
                and worker_is_locked(self.database)
            )
            return {
                "available": alive,
                "engine_version": w.engine_version if w else None,
                "heartbeat_at": w.heartbeat_at if w else None,
            }

    def available_profile(self) -> AnalysisProfile:
        if not self.worker_status()["available"]:
            raise AnalysisError(
                "WORKER_UNAVAILABLE",
                "Check that Stockfish is installed and configured, then start uv run chess-coach analysis-worker and retry.",
                503,
            )
        with self.sessions() as s:
            w = s.get(AnalysisWorkerState, 1)
            assert w is not None
            return AnalysisProfile(w.engine_version, w.config_json)

    def create(self, player_id: int, profile: AnalysisProfile) -> int:
        with self.sessions.begin() as s:
            reserve(s)
            try:
                ensure_idle(s)
            except OperationError as exc:
                raise AnalysisError(exc.code, str(exc), exc.status) from None
            if s.get(TrackedPlayer, player_id) is None:
                raise AnalysisError(
                    "PLAYER_NOT_FOUND", "Select an imported player.", 404
                )
            games = s.scalars(
                select(Game)
                .where(Game.tracked_player_id == player_id)
                .order_by(Game.id)
            ).all()
            run = AnalysisRun(
                tracked_player_id=player_id,
                engine_version=profile.engine,
                analysis_version=profile.version,
                engine_config_hash=profile.config_hash,
                engine_config_json=profile.config,
                draw_policy_version=profile.draw_policy,
                profile_hash=profile.hash,
            )
            s.add(run)
            s.flush()
            for g in games:
                if (
                    g.parse_status != ParseStatus.READY
                    or g.parser_version != PARSER_VERSION
                    or g.chess_library_version != chess.__version__
                    or not g.parsed_metadata
                ):
                    run.games_excluded += 1
                    continue
                skipped = self.compatible(s, g, profile)
                s.add(
                    AnalysisRunGame(
                        run_id=run.id,
                        game_id=g.id,
                        source_hash=source_hash(g),
                        status="skipped" if skipped else "pending",
                    )
                )
                run.games_total += 1
                run.games_skipped += int(skipped)
            if run.games_total == run.games_skipped:
                self._transition(run, Status.RUNNING)
                self._transition(run, Status.DONE)
            return run.id

    @staticmethod
    def compatible(s: Session, game: Game, profile: AnalysisProfile) -> bool:
        state = s.scalar(
            select(GameAnalysisState).where(
                GameAnalysisState.game_id == game.id,
                GameAnalysisState.profile_hash == profile.hash,
                GameAnalysisState.analysis_version == profile.version,
            )
        )
        n = (game.parsed_metadata or {}).get("total_plies")
        if (
            not state
            or state.status != GameAnalysisStatus.DONE
            or state.source_hash != source_hash(game)
        ):
            return False
        if (
            not isinstance(n, int)
            or not state.position_ids
            or len(state.position_ids) != n + 1
        ):
            return False
        rows = s.scalars(
            select(MoveAnalysis)
            .where(
                MoveAnalysis.game_id == game.id,
                MoveAnalysis.profile_hash == profile.hash,
            )
            .order_by(MoveAnalysis.ply)
        ).all()
        if [r.ply for r in rows] != list(range(1, n + 1)):
            return False
        unknown = bool((game.parsed_metadata or {}).get("history_before_start_unknown"))
        positions = {
            row.id: row
            for row in s.scalars(
                select(PositionCache).where(PositionCache.id.in_(state.position_ids))
            )
        }
        try:
            board = chess.Board(str((game.parsed_metadata or {}).get("initial_fen")))
            for i, identity in enumerate(state.position_ids):
                cached = positions.get(identity)
                if cached is None or (
                    cached.engine_version,
                    cached.analysis_version,
                    cached.config_hash,
                    cached.draw_policy_version,
                ) != (
                    profile.engine,
                    profile.version,
                    profile.config_hash,
                    profile.draw_policy,
                ):
                    return False
                if cached.history_hash != history_hash(board, unknown):
                    return False
                validate_result(board, result_of(cached), profile.engine)
                if i < n:
                    row = rows[i]
                    if (
                        row.fen_before,
                        row.best_move_uci,
                        row.eval_before_cp_white,
                        row.mate_before_white,
                        row.mate_before_winner,
                        row.pv_json,
                    ) != (
                        cached.fen,
                        cached.best_move_uci,
                        cached.score_cp_white,
                        cached.mate_distance_white,
                        cached.mate_winner,
                        cached.pv_json,
                    ):
                        return False
                    following = positions.get(state.position_ids[i + 1])
                    if following is None or (
                        row.eval_after_cp_white,
                        row.mate_after_white,
                        row.mate_after_winner,
                    ) != (
                        following.score_cp_white,
                        following.mate_distance_white,
                        following.mate_winner,
                    ):
                        return False
                    expected_loss = None
                    if (
                        cached.score_cp_white is not None
                        and following.score_cp_white is not None
                    ):
                        expected_loss = calculate_loss_cp(
                            cached.score_cp_white, following.score_cp_white, board.turn
                        )
                    if row.loss_cp != expected_loss or row.mover != (
                        "white" if board.turn else "black"
                    ):
                        return False
                    played = chess.Move.from_uci(row.played_move_uci)
                    if (
                        played not in board.legal_moves
                        or row.played_move_san != board.san(played)
                        or row.move_number != board.fullmove_number
                    ):
                        return False
                    board.push(played)
            return board.fen() == (game.parsed_metadata or {}).get("final_fen")
        except ValueError:
            return False

    @staticmethod
    def _transition(run: AnalysisRun, target: Status) -> None:
        transition(run.status, target)
        run.status = target
        if target == Status.RUNNING:
            run.started_at = run.started_at or utc_now()
        else:
            run.finished_at = utc_now()

    def get(self, run_id: int) -> AnalysisRun:
        with self.sessions() as s:
            run = s.get(AnalysisRun, run_id)
            if run is None:
                raise AnalysisError("RUN_NOT_FOUND", "Refresh the run list.", 404)
            return run

    def runs(self) -> list[AnalysisRun]:
        with self.sessions() as s:
            return list(
                s.scalars(select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(50))
            )

    def players(self) -> list[tuple[int, str]]:
        with self.sessions() as s:
            return [
                (p.id, p.username)
                for p in s.scalars(select(TrackedPlayer).order_by(TrackedPlayer.id))
            ]

    def members(self, run_id: int) -> list[AnalysisRunGame]:
        self.get(run_id)
        with self.sessions() as s:
            return list(
                s.scalars(
                    select(AnalysisRunGame)
                    .where(AnalysisRunGame.run_id == run_id)
                    .order_by(AnalysisRunGame.game_id)
                )
            )

    def cancel(self, run_id: int) -> None:
        with self.sessions.begin() as s:
            s.execute(
                update(AnalysisRun)
                .where(AnalysisRun.id == run_id)
                .values(cancel_requested=True)
            )
            run = s.get(AnalysisRun, run_id)
            if run is None:
                raise AnalysisError("RUN_NOT_FOUND", "Refresh the run list.", 404)
            if run.status not in ACTIVE:
                raise AnalysisError("RUN_TERMINAL", "This run has already stopped.")
            if run.status == Status.PENDING:
                self._transition(run, Status.CANCELLED)

    def claim(self, profile: AnalysisProfile) -> int | None:
        with self.sessions.begin() as s:
            s.execute(
                update(AnalysisWorkerState)
                .where(AnalysisWorkerState.id == 1)
                .values(id=1)
            )
            run = s.scalar(
                select(AnalysisRun)
                .where(AnalysisRun.status == Status.PENDING)
                .order_by(AnalysisRun.id)
            )
            if run is None:
                return None
            self._transition(run, Status.RUNNING)
            if run.profile_hash != profile.hash:
                run.error_code = "ANALYSIS_PROFILE_MISMATCH"
                run.error_message = (
                    "Restore the original engine/settings or create a new run."
                )
                self._transition(run, Status.FAILED)
                failed_id = run.id
            else:
                run.last_heartbeat_at = utc_now()
                return run.id
        self._log_profile_mismatch(failed_id)
        return None

    @staticmethod
    def _log_profile_mismatch(run_id: int) -> None:
        logging.getLogger(__name__).warning(
            "analysis_failed",
            extra={
                "run_id": run_id,
                "component": "analysis",
                "status": "failed",
                "error_code": "ANALYSIS_PROFILE_MISMATCH",
            },
        )

    def recover(self, profile: AnalysisProfile) -> None:
        """Caller MUST hold the OS worker guard; heartbeat alone is never ownership."""
        failed: list[int] = []
        with self.sessions.begin() as s:
            for run in s.scalars(
                select(AnalysisRun).where(AnalysisRun.status == Status.RUNNING)
            ):
                if run.profile_hash != profile.hash:
                    run.error_code = "ANALYSIS_PROFILE_MISMATCH"
                    self._transition(run, Status.FAILED)
                    failed.append(run.id)
                    continue
                for member in s.scalars(
                    select(AnalysisRunGame).where(
                        AnalysisRunGame.run_id == run.id,
                        AnalysisRunGame.status == "running",
                    )
                ):
                    member.status = "pending"
                s.execute(
                    update(GameAnalysisState)
                    .where(
                        GameAnalysisState.analysis_run_id == run.id,
                        GameAnalysisState.status == GameAnalysisStatus.RUNNING,
                    )
                    .values(status=GameAnalysisStatus.PENDING)
                )
                # Explicit recovery exception to the normal terminal transition policy.
                run.status = Status.PENDING
                run.error_code = "RUN_INTERRUPTED"
        for run_id in failed:
            self._log_profile_mismatch(run_id)

    def begin_game(self, run_id: int, game_id: int) -> tuple[Game, str]:
        with self.sessions.begin() as s:
            member = s.get(AnalysisRunGame, (run_id, game_id))
            run, game = s.get(AnalysisRun, run_id), s.get(Game, game_id)
            assert member and run and game
            if member.status != "pending" or run.status != Status.RUNNING:
                raise ValueError("Game is not pending in an active run")
            member.status = "running"
            member.attempt_count += 1
            if (
                member.source_hash != source_hash(game)
                or game.parse_status != ParseStatus.READY
            ):
                raise ValueError(
                    "INVALID_GAME: source changed; revalidate and start another run"
                )
            player = s.get(TrackedPlayer, game.tracked_player_id)
            assert player
            state = s.scalar(
                select(GameAnalysisState).where(
                    GameAnalysisState.game_id == game_id,
                    GameAnalysisState.profile_hash == run.profile_hash,
                )
            )
            if state is None:
                state = GameAnalysisState(
                    game_id=game_id,
                    analysis_version=run.analysis_version,
                    profile_hash=run.profile_hash,
                )
                s.add(state)
            state.status = GameAnalysisStatus.RUNNING
            state.analysis_run_id, state.started_at = run_id, utc_now()
            return game, player.username

    def cached(
        self, board: chess.Board, unknown: bool, profile: AnalysisProfile
    ) -> PositionCache | None:
        with self.sessions() as s:
            row = s.scalar(
                select(PositionCache).where(
                    PositionCache.fen == board.fen(),
                    PositionCache.history_hash == history_hash(board, unknown),
                    PositionCache.history_before_start_unknown == unknown,
                    PositionCache.engine_version == profile.engine,
                    PositionCache.analysis_version == profile.version,
                    PositionCache.config_hash == profile.config_hash,
                    PositionCache.draw_policy_version == profile.draw_policy,
                )
            )
            if row:
                if row.initial_fen != board.root().fen() or row.moves_uci_json != [
                    m.uci() for m in board.move_stack
                ]:
                    raise ValueError("ENGINE_INVALID_RESULT: cache history mismatch")
                validate_result(board, result_of(row), profile.engine)
            return row

    def save_position(
        self,
        run_id: int,
        board: chess.Board,
        unknown: bool,
        profile: AnalysisProfile,
        result: EngineResult,
        seconds: float,
    ) -> int:
        try:
            validate_result(board, result, profile.engine)
        except ValueError:
            if seconds:
                self.record_engine_time(run_id, seconds)
            raise
        with self.sessions.begin() as s:
            row = PositionCache(
                fen=board.fen(),
                initial_fen=board.root().fen(),
                moves_uci_json=[m.uci() for m in board.move_stack],
                history_hash=history_hash(board, unknown),
                history_before_start_unknown=unknown,
                engine_version=profile.engine,
                analysis_version=profile.version,
                config_hash=profile.config_hash,
                draw_policy_version=profile.draw_policy,
                score_cp_white=result.score_cp_white,
                mate_distance_white=result.mate_white,
                mate_winner=result.mate_winner,
                best_move_uci=result.best_move_uci,
                pv_json=list(result.pv_uci),
                depth=result.depth or 0,
                nodes=result.nodes or 0,
            )
            s.add(row)
            run = s.get(AnalysisRun, run_id)
            assert run
            terminal = board.is_game_over(claim_draw=False)
            run.terminal_positions += int(terminal)
            run.positions_analyzed += int(not terminal)
            run.engine_seconds += seconds
            run.last_heartbeat_at = utc_now()
            s.flush()
            return row.id

    def record_lookup(self, run_id: int, *, hit: bool) -> None:
        counter = AnalysisRun.cache_hits if hit else AnalysisRun.cache_misses
        with self.sessions.begin() as s:
            s.execute(
                update(AnalysisRun)
                .where(AnalysisRun.id == run_id)
                .values(
                    {counter: counter + 1, AnalysisRun.last_heartbeat_at: utc_now()}
                )
            )

    def record_engine_time(self, run_id: int, seconds: float) -> None:
        with self.sessions.begin() as s:
            s.execute(
                update(AnalysisRun)
                .where(AnalysisRun.id == run_id)
                .values(
                    engine_seconds=AnalysisRun.engine_seconds + seconds,
                )
            )

    def record_interruption(self, run_id: int, duration_ms: int) -> None:
        with self.sessions.begin() as s:
            run = s.get(AnalysisRun, run_id)
            assert run
            run.active_duration_ms = (run.active_duration_ms or 0) + duration_ms

    def finalize(
        self,
        run_id: int,
        game_id: int,
        parsed: ParsedGame,
        profile: AnalysisProfile,
        positions: list[int],
    ) -> None:
        if len(positions) != parsed.total_plies + 1:
            raise ValueError("Missing required positions")
        with self.sessions.begin() as s:
            run, game = s.get(AnalysisRun, run_id), s.get(Game, game_id)
            member = s.get(AnalysisRunGame, (run_id, game_id))
            assert run and game and member
            if (
                run.status != Status.RUNNING
                or member.status != "running"
                or run.profile_hash != profile.hash
            ):
                raise ValueError("Finalization is not owned by this running attempt")
            if member.source_hash != source_hash(game):
                raise ValueError("INVALID_GAME: source changed during analysis")
            board = chess.Board(parsed.initial_fen)
            evidence: list[EngineResult] = []
            for i, identity in enumerate(positions):
                row = s.get(PositionCache, identity)
                if not row or (
                    row.engine_version,
                    row.analysis_version,
                    row.config_hash,
                    row.draw_policy_version,
                ) != (
                    profile.engine,
                    profile.version,
                    profile.config_hash,
                    profile.draw_policy,
                ):
                    raise ValueError("Incompatible position evidence")
                if row.history_hash != history_hash(
                    board, parsed.history_before_start_unknown
                ):
                    raise ValueError("Incompatible position history")
                result = result_of(row)
                validate_result(board, result, profile.engine)
                evidence.append(result)
                if i < parsed.total_plies:
                    move = parsed.moves[i]
                    if move.ply_index != i + 1 or move.fen_before != board.fen():
                        raise ValueError("Invalid move indexing")
                    board.push_uci(move.uci)
            # Replace only incomplete evidence for this exact profile, atomically.
            s.execute(
                delete(MoveAnalysis).where(
                    MoveAnalysis.game_id == game_id,
                    MoveAnalysis.profile_hash == profile.hash,
                )
            )
            for move, before, after in zip(
                parsed.moves, evidence, evidence[1:], strict=False
            ):
                loss = None
                if (
                    before.score_cp_white is not None
                    and after.score_cp_white is not None
                ):
                    loss = calculate_loss_cp(
                        before.score_cp_white,
                        after.score_cp_white,
                        move.mover_color == "white",
                    )
                s.add(
                    MoveAnalysis(
                        game_id=game_id,
                        analysis_run_id=run_id,
                        profile_hash=profile.hash,
                        analysis_version=profile.version,
                        ply=move.ply_index,
                        move_number=move.move_number,
                        mover=move.mover_color,
                        fen_before=move.fen_before,
                        played_move_uci=move.uci,
                        played_move_san=move.san,
                        best_move_uci=before.best_move_uci,
                        eval_before_cp_white=before.score_cp_white,
                        eval_after_cp_white=after.score_cp_white,
                        mate_before_white=before.mate_white,
                        mate_after_white=after.mate_white,
                        mate_before_winner=before.mate_winner,
                        mate_after_winner=after.mate_winner,
                        loss_cp=loss,
                        pv_json=list(before.pv_uci),
                    )
                )
            state = s.scalar(
                select(GameAnalysisState).where(
                    GameAnalysisState.game_id == game_id,
                    GameAnalysisState.profile_hash == profile.hash,
                )
            )
            if state is None:
                state = GameAnalysisState(
                    game_id=game_id,
                    analysis_version=profile.version,
                    profile_hash=profile.hash,
                )
                s.add(state)
            state.status, state.analysis_run_id = GameAnalysisStatus.DONE, run_id
            state.position_ids, state.source_hash = positions, source_hash(game)
            state.finished_at = utc_now()
            member.status = "done"
            run.games_completed += 1

    def fail_game(self, run_id: int, game_id: int, code: str) -> None:
        with self.sessions.begin() as s:
            member, run = (
                s.get(AnalysisRunGame, (run_id, game_id)),
                s.get(AnalysisRun, run_id),
            )
            assert member and run
            member.status, member.error_code = "failed", code
            state = s.scalar(
                select(GameAnalysisState).where(
                    GameAnalysisState.game_id == game_id,
                    GameAnalysisState.profile_hash == run.profile_hash,
                )
            )
            if state is None:
                state = GameAnalysisState(
                    game_id=game_id,
                    analysis_version=run.analysis_version,
                    profile_hash=run.profile_hash,
                )
                s.add(state)
            state.status, state.error_message = GameAnalysisStatus.FAILED, code
            state.finished_at = utc_now()
            state.analysis_run_id = run_id
            run.games_failed += 1
            run.error_count += 1

    def finish(
        self, run_id: int, code: str | None = None, *, duration_ms: int | None = None
    ) -> None:
        with self.sessions.begin() as s:
            run = s.get(AnalysisRun, run_id)
            assert run
            if code:
                run.error_code = code
                run.error_message = "Inspect worker diagnostics, correct the cause, then start a new run."
                target = Status.FAILED
            elif run.cancel_requested:
                target = Status.CANCELLED
            elif (
                run.games_completed + run.games_failed + run.games_skipped
                != run.games_total
            ):
                raise ValueError("Cannot finish a run with unresolved games")
            else:
                target = (
                    Status.COMPLETED_WITH_ERRORS if run.games_failed else Status.DONE
                )
                run.error_code = None
            if target in (Status.CANCELLED, Status.FAILED):
                for member in s.scalars(
                    select(AnalysisRunGame).where(
                        AnalysisRunGame.run_id == run_id,
                        AnalysisRunGame.status == "running",
                    )
                ):
                    member.status = "pending"
                s.execute(
                    update(GameAnalysisState)
                    .where(
                        GameAnalysisState.analysis_run_id == run_id,
                        GameAnalysisState.status == GameAnalysisStatus.RUNNING,
                    )
                    .values(status=GameAnalysisStatus.PENDING)
                )
            if duration_ms is not None:
                run.active_duration_ms = (run.active_duration_ms or 0) + duration_ms
            self._transition(run, target)

    def moves(self, game_id: int, profile_hash: str) -> list[MoveAnalysis]:
        with self.sessions() as s:
            state = s.scalar(
                select(GameAnalysisState).where(
                    GameAnalysisState.game_id == game_id,
                    GameAnalysisState.profile_hash == profile_hash,
                    GameAnalysisState.status == GameAnalysisStatus.DONE,
                )
            )
            if state is None:
                raise AnalysisError(
                    "ANALYSIS_NOT_FOUND",
                    "Complete analysis for this profile first.",
                    404,
                )
            game = s.get(Game, game_id)
            run = (
                s.get(AnalysisRun, state.analysis_run_id)
                if state.analysis_run_id
                else None
            )
            if (
                game is None
                or run is None
                or not self.compatible(s, game, profile_of(run))
            ):
                raise AnalysisError(
                    "ANALYSIS_INCOMPLETE",
                    "Evidence is incomplete or changed; start a new compatible run.",
                )
            return list(
                s.scalars(
                    select(MoveAnalysis)
                    .where(
                        MoveAnalysis.game_id == game_id,
                        MoveAnalysis.profile_hash == profile_hash,
                    )
                    .order_by(MoveAnalysis.ply)
                )
            )
