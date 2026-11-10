"""Read projections and single-player configuration in short transactions."""

import chess
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, sessionmaker

from chess_coach.analytics.opening_book import book_plies
from chess_coach.analytics.review import rate_move
from chess_coach.analytics.sample_policy import CRITICAL_LOSS_CP
from chess_coach.application.errors import OperationError
from chess_coach.domain.analysis import ACTIVE, ANALYSIS_VERSION
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
    profile_of,
    source_hash,
)
from chess_coach.infrastructure.persistence.models import (
    AnalysisRun,
    AnalysisWorkerState,
    CoachingOutput,
    Game,
    GameAnalysisState,
    GameAnalysisStatus,
    ImportRun,
    MoveAnalysis,
    Platform,
    PositionCache,
    RunStatus,
    TrackedPlayer,
)
from chess_coach.infrastructure.persistence.operations import ensure_idle, reserve


def public_game_status(state: GameAnalysisState | None, game: Game) -> str:
    if state is None:
        return "pending"
    if state.status == GameAnalysisStatus.DONE:
        if state.source_hash != source_hash(game):
            return "incompatible"
        return "completed"
    return str(state.status)


class QueryRepository:
    def __init__(self, sessions: sessionmaker[Session], analysis: AnalysisRepository):
        self.sessions, self.analysis = sessions, analysis

    @staticmethod
    def _player(s: Session) -> TrackedPlayer | None:
        players = list(
            s.scalars(
                select(TrackedPlayer)
                .where(TrackedPlayer.platform == Platform.CHESS_COM)
                .order_by(TrackedPlayer.id)
                .limit(2)
            )
        )
        if len(players) > 1:
            raise OperationError(
                "MULTIPLE_PLAYERS",
                "This API supports one tracked Chess.com player. Use the CLI for existing multiple-player datasets.",
            )
        return players[0] if players else None

    def player(self) -> dict[str, object]:
        with self.sessions() as s:
            p = self._player(s)
            return {
                "configured": p is not None,
                "player": {"id": p.id, "platform": p.platform, "username": p.username}
                if p
                else None,
            }

    @classmethod
    def _historical_player(cls, session: Session) -> TrackedPlayer | None:
        configured = cls._player(session)
        if configured is not None:
            return configured
        players = list(
            session.scalars(
                select(TrackedPlayer)
                .where(TrackedPlayer.platform == Platform.PGN)
                .limit(2)
            )
        )
        if len(players) > 1:
            raise OperationError(
                "MULTIPLE_PLAYERS", "Use a single tracked player for local practice."
            )
        return players[0] if players else None

    def historical_player_id(self) -> int | None:
        with self.sessions() as session:
            player = self._historical_player(session)
            return player.id if player is not None else None

    def player_id(self) -> int:
        with self.sessions() as s:
            p = self._player(s)
            if p is None:
                raise OperationError(
                    "PLAYER_NOT_CONFIGURED",
                    "Set the tracked player before starting work.",
                )
            return p.id

    def set_player(self, username: str) -> dict[str, object]:
        with self.sessions.begin() as s:
            reserve(s)
            p = self._player(s)
            if p is None or p.username != username:
                ensure_idle(s)
                if p is not None:
                    raise OperationError(
                        "PLAYER_SWITCH_UNSUPPORTED",
                        "Existing history is preserved. Switching the tracked player is not supported in this version.",
                    )
                s.add(TrackedPlayer(platform=Platform.CHESS_COM, username=username))
        return self.player()

    def latest_runs(self) -> dict[str, int | None]:
        with self.sessions() as s:
            player = self._player(s)
            if player is None:
                return {"sync_run_id": None, "analysis_run_id": None}
            return {
                "sync_run_id": s.scalar(
                    select(ImportRun.id)
                    .where(ImportRun.tracked_player_id == player.id)
                    .order_by(
                        ImportRun.status.in_(
                            (RunStatus.PENDING, RunStatus.RUNNING)
                        ).desc(),
                        ImportRun.id.desc(),
                    )
                    .limit(1)
                ),
                "analysis_run_id": s.scalar(
                    select(AnalysisRun.id)
                    .where(AnalysisRun.tracked_player_id == player.id)
                    .order_by(
                        AnalysisRun.status.in_(ACTIVE).desc(), AnalysisRun.id.desc()
                    )
                    .limit(1)
                ),
            }

    def profile(self) -> str | None:
        with self.sessions() as s:
            worker = s.get(AnalysisWorkerState, 1)
            if worker is not None:
                from chess_coach.domain.analysis import AnalysisProfile

                return AnalysisProfile(worker.engine_version, worker.config_json).hash
            return s.scalar(
                select(AnalysisRun.profile_hash)
                .order_by(AnalysisRun.id.desc())
                .limit(1)
            )

    @staticmethod
    def _state(profile: str | None) -> Select[GameAnalysisState]:
        return select(GameAnalysisState).where(
            GameAnalysisState.profile_hash == profile,
            GameAnalysisState.analysis_version == ANALYSIS_VERSION,
        )

    @staticmethod
    def _item(
        g: Game, state: GameAnalysisState | None, critical: int | None = None
    ) -> dict[str, object]:
        return {
            k: getattr(g, k)
            for k in (
                "id",
                "played_at",
                "player_color",
                "result",
                "time_class",
                "opening_name",
            )
        } | {
            "opponent": g.black_username
            if g.player_color == "white"
            else g.white_username,
            "player_rating": g.white_rating
            if g.player_color == "white"
            else g.black_rating,
            "critical_errors": critical,
            "analysis_status": "pending"
            if state is None
            else "completed"
            if state.status == GameAnalysisStatus.DONE
            else str(state.status),
        }

    def games(
        self,
        limit: int,
        offset: int,
        time_class: str | None,
        color: str | None,
        status: str | None,
        result: str | None = None,
    ) -> dict[str, object]:
        profile = self.profile()
        with self.sessions() as s:
            player = self._player(s)
            query = select(Game).where(
                Game.tracked_player_id == (player.id if player else -1)
            )
            if time_class:
                query = query.where(Game.time_class == time_class)
            if color:
                query = query.where(Game.player_color == color)
            if result:
                query = query.where(Game.result == result)
            # Bounded game page plus one state query; no move analyses are loaded.
            if status:
                matching = select(GameAnalysisState.id).where(
                    GameAnalysisState.game_id == Game.id,
                    GameAnalysisState.profile_hash == profile,
                    GameAnalysisState.analysis_version == ANALYSIS_VERSION,
                )
                if status == "pending":
                    query = query.where(
                        ~matching.where(GameAnalysisState.status != "pending").exists()
                    )
                else:
                    query = query.where(
                        matching.where(
                            GameAnalysisState.status
                            == ("done" if status == "completed" else status)
                        ).exists()
                    )
            total = s.scalar(select(func.count()).select_from(query.subquery())) or 0
            games = list(
                s.scalars(
                    query.order_by(Game.played_at.desc(), Game.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            ids = [g.id for g in games]
            found = {
                st.game_id: st
                for st in s.scalars(
                    self._state(profile).where(GameAnalysisState.game_id.in_(ids))
                )
            }
            compatible = {
                g.id: (g.parsed_metadata or {}).get("total_plies")
                for g in games
                if public_game_status(found.get(g.id), g) == "completed"
            }
            # Bounded aggregate over this page only. The review endpoint still
            # performs deep evidence validation before exposing specific moves.
            losses = (
                {
                    game_id: critical
                    for game_id, total_moves, classifiable, critical in s.execute(
                        select(
                            MoveAnalysis.game_id,
                            func.count(),
                            func.count().filter(
                                MoveAnalysis.mover == Game.player_color,
                                MoveAnalysis.loss_cp.is_not(None),
                            ),
                            func.count().filter(
                                MoveAnalysis.mover == Game.player_color,
                                MoveAnalysis.loss_cp >= CRITICAL_LOSS_CP,
                            ),
                        )
                        .join(Game, Game.id == MoveAnalysis.game_id)
                        .where(
                            MoveAnalysis.game_id.in_(compatible),
                            MoveAnalysis.profile_hash == profile,
                            MoveAnalysis.analysis_version == ANALYSIS_VERSION,
                        )
                        .group_by(MoveAnalysis.game_id)
                    )
                    if total_moves == compatible[game_id] and classifiable
                }
                if compatible
                else {}
            )
            return {
                "items": [
                    self._item(g, found.get(g.id), losses.get(g.id)) for g in games
                ],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def game(self, game_id: int) -> dict[str, object]:
        profile = self.profile()
        with self.sessions() as s:
            g = s.get(Game, game_id)
            p = self._historical_player(s)
            if g is None or p is None or g.tracked_player_id != p.id:
                raise OperationError(
                    "GAME_NOT_FOUND", "The requested game was not found.", 404
                )
            state = s.scalar(
                self._state(profile).where(GameAnalysisState.game_id == game_id)
            )
            return (
                self._item(g, state)
                | {
                    k: getattr(g, k)
                    for k in (
                        "white_username",
                        "black_username",
                        "white_rating",
                        "black_rating",
                        "eco_code",
                        "time_control",
                        "raw_pgn",
                    )
                }
                | {
                    "completion_provenance": "chesscom_archive"
                    if g.platform == Platform.CHESS_COM
                    else "pgn_declaration"
                }
            )

    def game_analysis(
        self, game_id: int, profile: str | None
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        self.game(game_id)  # enforce single-player ownership and not-found semantics
        profile = profile or self.profile()
        with self.sessions() as s:
            g = s.get(Game, game_id)
            assert g is not None
            state = s.scalar(
                self._state(profile).where(GameAnalysisState.game_id == game_id)
            )
            status = public_game_status(state, g)
            run = (
                s.get(AnalysisRun, state.analysis_run_id)
                if state and state.analysis_run_id
                else None
            )
            moves: list[dict[str, object]] = []
            initial_fen: str | None = None
            if status == "completed":
                if (
                    state is None
                    or run is None
                    or profile_of(run).hash != profile
                    or run.analysis_version != state.analysis_version
                    or run.tracked_player_id != g.tracked_player_id
                    or not self.analysis.compatible(s, g, profile_of(run))
                ):
                    status = "incompatible"
                else:
                    rows = s.scalars(
                        select(MoveAnalysis)
                        .where(
                            MoveAnalysis.game_id == game_id,
                            MoveAnalysis.profile_hash == profile,
                        )
                        .order_by(MoveAnalysis.ply)
                    ).all()
                    assert state.position_ids
                    final = s.get(PositionCache, state.position_ids[-1])
                    if final is None:
                        status = "incompatible"
                    else:
                        initial_fen = rows[0].fen_before if rows else final.fen
                        opening_plies = book_plies(
                            initial_fen,
                            tuple(move.played_move_uci for move in rows),
                            unknown_history=final.history_before_start_unknown,
                        )
                        next_fens = (
                            [m.fen_before for m in rows[1:]] + [final.fen]
                            if rows
                            else []
                        )
                        for move, after in zip(rows, next_fens, strict=True):
                            before = chess.Board(move.fen_before)
                            line = [chess.Move.from_uci(uci) for uci in move.pv_json]
                            moves.append(
                                {
                                    c.name: getattr(move, c.name)
                                    for c in move.__table__.columns
                                }
                                | {
                                    "fen_after": after,
                                    "pv_san": before.variation_san(line),
                                    "rating": rate_move(
                                        before,
                                        chess.Move.from_uci(move.played_move_uci),
                                        line,
                                        move.loss_cp,
                                        move.eval_after_cp_white,
                                        move.mate_after_winner,
                                        before_mate_winner=move.mate_before_winner,
                                        in_book=move.ply <= opening_plies,
                                    ),
                                }
                            )
            return {
                "game_id": game_id,
                "status": status,
                "profile_hash": profile,
                "engine_version": run.engine_version if run else None,
                "analysis_version": run.analysis_version if run else None,
                "initial_fen": initial_fen,
            }, moves

    def statistics(self) -> dict[str, int]:
        profile = self.profile()
        with self.sessions() as s:
            s.execute(select(1))
            total = s.scalar(select(func.count()).select_from(Game)) or 0
            # A bounded-query completion projection. Deep legality/history validation
            # belongs to the per-game evidence read, not a browser status poll.
            move_counts = dict(
                s.execute(
                    select(MoveAnalysis.game_id, func.count())
                    .where(
                        MoveAnalysis.profile_hash == profile,
                        MoveAnalysis.analysis_version == ANALYSIS_VERSION,
                    )
                    .group_by(MoveAnalysis.game_id)
                ).all()
            )
            completed = 0
            for g, state, run in s.execute(
                select(Game, GameAnalysisState, AnalysisRun)
                .join(GameAnalysisState, GameAnalysisState.game_id == Game.id)
                .join(AnalysisRun, AnalysisRun.id == GameAnalysisState.analysis_run_id)
                .where(
                    GameAnalysisState.profile_hash == profile,
                    GameAnalysisState.analysis_version == ANALYSIS_VERSION,
                    GameAnalysisState.status == GameAnalysisStatus.DONE,
                )
            ):
                plies = (g.parsed_metadata or {}).get("total_plies")
                if (
                    profile_of(run).hash == profile
                    and state.source_hash == source_hash(g)
                    and isinstance(plies, int)
                    and len(state.position_ids or []) == plies + 1
                    and move_counts.get(g.id, 0) == plies
                ):
                    completed += 1
            return {
                "games_stored": total,
                "games_analyzed": completed,
                "pending_games": total - completed,
                "positions_cached": s.scalar(
                    select(func.count()).select_from(PositionCache)
                )
                or 0,
                "active_sync_runs": s.scalar(
                    select(func.count())
                    .select_from(ImportRun)
                    .where(ImportRun.status.in_((RunStatus.PENDING, RunStatus.RUNNING)))
                )
                or 0,
                "active_analysis_runs": s.scalar(
                    select(func.count())
                    .select_from(AnalysisRun)
                    .where(AnalysisRun.status.in_(ACTIVE))
                )
                or 0,
                "active_coaching_jobs": s.scalar(
                    select(func.count())
                    .select_from(CoachingOutput)
                    .where(CoachingOutput.status.in_(("queued", "running")))
                )
                or 0,
            }
