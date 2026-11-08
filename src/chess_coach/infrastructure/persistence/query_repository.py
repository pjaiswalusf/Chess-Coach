"""Read projections and single-player configuration in short transactions."""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, sessionmaker

from chess_coach.application.errors import OperationError
from chess_coach.domain.analysis import ANALYSIS_VERSION
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
    profile_of,
    source_hash,
)
from chess_coach.infrastructure.persistence.models import (
    AnalysisRun,
    AnalysisWorkerState,
    Game,
    GameAnalysisState,
    GameAnalysisStatus,
    MoveAnalysis,
    Platform,
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
    def _item(g: Game, state: GameAnalysisState | None) -> dict[str, object]:
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
            return {
                "items": [self._item(g, found.get(g.id)) for g in games],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def game(self, game_id: int) -> dict[str, object]:
        profile = self.profile()
        with self.sessions() as s:
            g = s.get(Game, game_id)
            p = self._player(s)
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

    def game_analysis(self, game_id: int, profile: str | None) -> dict[str, object]:
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
                    moves = [
                        {c.name: getattr(m, c.name) for c in m.__table__.columns}
                        for m in s.scalars(
                            select(MoveAnalysis)
                            .where(
                                MoveAnalysis.game_id == game_id,
                                MoveAnalysis.profile_hash == profile,
                            )
                            .order_by(MoveAnalysis.ply)
                        )
                    ]
            return {
                "game_id": game_id,
                "status": status,
                "profile_hash": profile,
                "engine_version": run.engine_version if run else None,
                "analysis_version": run.analysis_version if run else None,
                "moves": moves,
            }

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
            }
