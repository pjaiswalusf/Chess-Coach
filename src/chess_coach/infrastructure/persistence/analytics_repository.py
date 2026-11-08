"""Batched, transaction-consistent reads. Never repairs or writes source evidence."""

from collections import defaultdict
from dataclasses import asdict
from time import perf_counter
from typing import TypeVar

import chess
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from chess_coach.analytics.cohorts import LIMITS
from chess_coach.analytics.contracts import (
    AnalysisStatus,
    AnalyticsRequest,
    Diagnostic,
    EvidenceDataset,
    GameEvidence,
    MoveEvidence,
)
from chess_coach.analytics.feature_config import DEFAULT_CONFIG
from chess_coach.analytics.sample_policy import severity
from chess_coach.application.parse_imported_games import ParseInput, _source_result
from chess_coach.domain.analysis import fingerprint, history_hash, validate_result
from chess_coach.domain.feature_models import (
    FEATURE_EXTRACTOR_VERSION,
    PHASE_CLASSIFIER_VERSION,
    FeatureAnalysis,
    GamePhase,
    MoveFeatures,
)
from chess_coach.domain.game_records import PARSER_VERSION, ParsedGame, ParseStatus
from chess_coach.domain.score_utils import calculate_loss_cp
from chess_coach.infrastructure.persistence.analysis_repository import (
    profile_of,
    result_of,
    source_hash,
)
from chess_coach.infrastructure.persistence.feature_repository import QUERY_FIELDS
from chess_coach.infrastructure.persistence.models import (
    AnalysisRun,
    Game,
    GameAnalysisState,
    MoveAnalysis,
    MoveFeature,
    PositionCache,
    TrackedPlayer,
)
from chess_coach.infrastructure.pgn.parser import parse_game

T = TypeVar("T")


def chunks(values: list[int]) -> list[list[int]]:
    return [values[i : i + 500] for i in range(0, len(values), 500)]


class EvidenceError(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise EvidenceError(code)


class AnalyticsRepository:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def load(self, request: AnalyticsRequest) -> EvidenceDataset:
        # The project's SQLite engine disables legacy transaction mode. BEGIN is
        # issued for reads too, so WAL writers cannot change this report's snapshot.
        with self.sessions.begin() as s:
            s.execute(text("PRAGMA query_only=ON"))
            try:
                return self._load(s, request)
            finally:
                s.execute(text("PRAGMA query_only=OFF"))

    def _load(self, s: Session, request: AnalyticsRequest) -> EvidenceDataset:
        start = perf_counter()
        integrity = list(s.scalars(text("PRAGMA integrity_check"))) == ["ok"]
        foreign_keys = not s.execute(text("PRAGMA foreign_key_check")).first()
        if not integrity or not foreign_keys:
            return EvidenceDataset(
                database_integrity=integrity, foreign_keys=foreign_keys
            )
        player = s.get(TrackedPlayer, request.player_id)
        if player is None:
            raise ValueError("PLAYER_NOT_FOUND: select an imported player")
        query = select(Game).where(
            Game.tracked_player_id == request.player_id,
            Game.parse_status == ParseStatus.READY,
            Game.result.in_(("win", "draw", "loss")),
        )
        if request.color is not None:
            query = query.where(Game.player_color == request.color)
        if request.time_class is not None:
            query = query.where(
                func.coalesce(func.nullif(Game.time_class, ""), "UNKNOWN")
                == request.time_class
            )
        if request.start_date is not None:
            query = query.where(
                Game.played_at >= request.start_date, Game.played_at < request.end_date
            )
        query = query.order_by(Game.played_at.desc(), Game.id.desc())
        if request.window in LIMITS:
            query = query.limit(LIMITS[request.window])
        games = list(s.scalars(query))
        ids = [g.id for g in games]
        states: dict[int, list[GameAnalysisState]] = defaultdict(list)
        analyses: dict[int, list[MoveAnalysis]] = defaultdict(list)
        features: dict[int, list[MoveFeature]] = defaultdict(list)
        for batch in chunks(ids):
            for state in s.scalars(
                select(GameAnalysisState).where(GameAnalysisState.game_id.in_(batch))
            ):
                states[state.game_id].append(state)
            for row in s.scalars(
                select(MoveAnalysis)
                .where(
                    MoveAnalysis.game_id.in_(batch),
                    MoveAnalysis.profile_hash == request.profile_hash,
                )
                .order_by(MoveAnalysis.ply)
            ):
                analyses[row.game_id].append(row)
            for feature in s.scalars(
                select(MoveFeature)
                .where(
                    MoveFeature.game_id.in_(batch),
                    MoveFeature.profile_hash == request.profile_hash,
                    MoveFeature.feature_version == FEATURE_EXTRACTOR_VERSION,
                )
                .order_by(MoveFeature.ply)
            ):
                features[feature.game_id].append(feature)
        run_ids = sorted(
            {
                st.analysis_run_id
                for values in states.values()
                for st in values
                if st.profile_hash == request.profile_hash
                and st.analysis_run_id is not None
            }
        )
        runs = {
            r.id: r
            for batch in chunks(run_ids)
            for r in s.scalars(select(AnalysisRun).where(AnalysisRun.id.in_(batch)))
        }
        position_ids = sorted(
            {
                p
                for values in states.values()
                for st in values
                if st.profile_hash == request.profile_hash
                for p in (st.position_ids or [])
            }
        )
        positions = {
            p.id: p
            for batch in chunks(position_ids)
            for p in s.scalars(select(PositionCache).where(PositionCache.id.in_(batch)))
        }
        fetched = perf_counter()
        result = []
        errors: list[Diagnostic] = []
        warnings: list[Diagnostic] = []
        for g in games:
            try:
                result.append(
                    self._game(
                        g,
                        player.username,
                        request,
                        states[g.id],
                        analyses[g.id],
                        features[g.id],
                        runs,
                        positions,
                        warnings,
                    )
                )
            except EvidenceError as exc:
                errors.append(Diagnostic(code=str(exc), game_id=g.id))
            except ValueError, TypeError, KeyError, AttributeError:
                errors.append(Diagnostic(code="INVALID_STORED_EVIDENCE", game_id=g.id))
        # Keep failed games in the selected cohort, even when no calculation is safe.
        present = {g.game_id: g for g in result}
        for g in games:
            if g.id not in present:
                present[g.id] = GameEvidence(
                    game_id=g.id,
                    played_at=g.played_at,
                    color=g.player_color,
                    result=g.result,
                    provenance="invalid",
                    analysis_status=AnalysisStatus.INCOMPATIBLE,
                    expected_player_moves=0,
                )
        return EvidenceDataset(
            games=tuple(present[g.id] for g in games),
            errors=tuple(errors),
            warnings=tuple(warnings),
            retrieval_seconds=fetched - start,
            validation_seconds=perf_counter() - fetched,
        )

    def _game(
        self,
        g: Game,
        username: str,
        request: AnalyticsRequest,
        states: list[GameAnalysisState],
        rows: list[MoveAnalysis],
        feature_rows: list[MoveFeature],
        runs: dict[int, AnalysisRun],
        positions: dict[int, PositionCache],
        warnings: list[Diagnostic],
    ) -> GameEvidence:
        require(
            g.parser_version == PARSER_VERSION
            and g.chess_library_version == chess.__version__,
            "GAME_REVALIDATION_REQUIRED",
        )
        source = ParseInput(
            g.id,
            g.raw_pgn,
            username,
            g.platform,
            g.white_username,
            g.black_username,
            g.source_evidence,
        )
        expected_result, final_fen = _source_result(source)
        parsed = parse_game(g.raw_pgn, username, source_final_fen=final_fen)
        require(
            expected_result is None or parsed.source_result == expected_result,
            "SOURCE_RESULT_INVALID",
        )
        require(
            (
                parsed.white_username.casefold(),
                parsed.black_username.casefold(),
                parsed.player_color,
                parsed.player_result,
            )
            == (
                g.white_username.strip().casefold(),
                g.black_username.strip().casefold(),
                g.player_color,
                g.result,
            ),
            "PLAYER_ATTRIBUTION_INVALID",
        )
        metadata = asdict(parsed)
        del metadata["moves"]
        metadata["total_plies"] = parsed.total_plies
        if expected_result is not None:
            metadata["completion_provenance"] = "chesscom_archive"
        require(g.parsed_metadata == metadata, "PARSED_METADATA_INVALID")
        total = sum(m.mover_color == g.player_color for m in parsed.moves)
        exact = [st for st in states if st.profile_hash == request.profile_hash]
        require(len(exact) <= 1, "DUPLICATE_ANALYSIS_STATE")
        status = "incompatible" if states and not exact else "not_analyzed"
        moves: tuple[MoveEvidence, ...] = ()
        fs: dict[int, MoveFeatures] = {}
        if exact:
            st = exact[0]
            status = str(st.status)
            if st.analysis_version != request.analysis_version:
                status = "incompatible"
            elif status == "done":
                require(st.source_hash == source_hash(g), "ANALYSIS_SOURCE_CHANGED")
                run = runs.get(st.analysis_run_id or -1)
                require(run is not None, "ANALYSIS_PROVENANCE_MISSING")
                assert run is not None
                require(
                    profile_of(run).hash == request.profile_hash
                    and run.analysis_version == request.analysis_version
                    and run.tracked_player_id == request.player_id,
                    "INCOMPATIBLE_ANALYSIS",
                )
                self._validate_analysis(g, parsed, st, rows, run, positions)
                fs = self._features(g, source, rows, feature_rows, request.profile_hash)
                if not fs:
                    warnings.append(Diagnostic(code="FEATURES_NOT_READY", game_id=g.id))
                previous_capture = None
                built = []
                for source_move, row in zip(parsed.moves, rows, strict=True):
                    if row.mover == g.player_color:
                        f = fs.get(row.ply)
                        sign = 1 if g.player_color == "white" else -1
                        base = parsed.time_control.base_seconds
                        pressure = None
                        if (
                            f
                            and f.clock_before_move_seconds is not None
                            and base is not None
                            and base > 0
                        ):
                            pressure = f.clock_before_move_seconds <= base * 0.1
                        built.append(
                            MoveEvidence(
                                game_id=g.id,
                                ply=row.ply,
                                move_number=row.move_number,
                                mover=g.player_color,
                                phase=f.phase if f else GamePhase.UNCLASSIFIED,
                                loss_cp=row.loss_cp,
                                severity=severity(row.loss_cp),
                                before_cp=None
                                if row.eval_before_cp_white is None
                                else sign * row.eval_before_cp_white,
                                after_cp=None
                                if row.eval_after_cp_white is None
                                else sign * row.eval_after_cp_white,
                                mate_before=row.mate_before_white,
                                mate_after=row.mate_after_white,
                                mate_before_winner=row.mate_before_winner,
                                mate_after_winner=row.mate_after_winner,
                                in_check=chess.Board(row.fen_before).is_check(),
                                after_capture=previous_capture,
                                under_time_pressure=pressure,
                                castled=f.played_is_castling if f else None,
                            )
                        )
                    previous_capture = chess.Board(source_move.fen_before).is_capture(
                        chess.Move.from_uci(source_move.uci)
                    )
                moves = tuple(built)
        return GameEvidence(
            game_id=g.id,
            played_at=g.played_at,
            color=g.player_color,
            result=g.result,
            time_class=g.time_class or "UNKNOWN",
            time_control=g.time_control or "UNKNOWN",
            eco=g.eco_code or "UNKNOWN",
            opening_name=g.opening_name,
            provenance="chesscom_archive" if expected_result else "pgn_declaration",
            history_before_start_unknown=parsed.history_before_start_unknown,
            castling_history_known=not parsed.history_before_start_unknown,
            analysis_status=AnalysisStatus(status),
            expected_player_moves=total,
            moves=moves,
            evaluation_path=tuple(
                (
                    None
                    if r.eval_before_cp_white is None
                    else (1 if g.player_color == "white" else -1)
                    * r.eval_before_cp_white
                )
                for r in rows
            )
            + (
                (
                    None
                    if rows[-1].eval_after_cp_white is None
                    else (1 if g.player_color == "white" else -1)
                    * rows[-1].eval_after_cp_white
                ),
            )
            if moves and rows
            else (),
            features_available=bool(fs),
        )

    @staticmethod
    def _validate_analysis(
        g: Game,
        parsed: ParsedGame,
        st: GameAnalysisState,
        rows: list[MoveAnalysis],
        run: AnalysisRun,
        positions: dict[int, PositionCache],
    ) -> None:
        require(len({r.ply for r in rows}) == len(rows), "DUPLICATE_MOVE_ANALYSIS")
        require(
            [r.ply for r in rows] == list(range(1, parsed.total_plies + 1)),
            "MISSING_MOVE_ANALYSIS",
        )
        require(
            all(r.analysis_version == run.analysis_version for r in rows),
            "INCOMPATIBLE_ANALYSIS",
        )
        require(
            st.position_ids is not None
            and len(st.position_ids) == parsed.total_plies + 1,
            "MISSING_POSITION_EVIDENCE",
        )
        profile = profile_of(run)
        board = chess.Board(parsed.initial_fen)
        cached = []
        for i, identity in enumerate(st.position_ids or []):
            p = positions.get(identity)
            require(p is not None, "MISSING_POSITION_EVIDENCE")
            assert p is not None
            require(
                (
                    p.engine_version,
                    p.analysis_version,
                    p.config_hash,
                    p.draw_policy_version,
                )
                == (
                    profile.engine,
                    profile.version,
                    profile.config_hash,
                    profile.draw_policy,
                ),
                "INCOMPATIBLE_ANALYSIS",
            )
            require(
                p.history_hash
                == history_hash(board, parsed.history_before_start_unknown)
                and p.fen == board.fen()
                and p.initial_fen == parsed.initial_fen
                and p.history_before_start_unknown
                == parsed.history_before_start_unknown
                and p.moves_uci_json == [m.uci() for m in board.move_stack],
                "POSITION_HISTORY_INVALID",
            )
            validate_result(board, result_of(p), profile.engine)
            cached.append(p)
            if i < len(parsed.moves):
                board.push_uci(parsed.moves[i].uci)
        for move, row, before, after in zip(
            parsed.moves, rows, cached, cached[1:], strict=False
        ):
            require(
                (
                    row.mover,
                    row.move_number,
                    row.fen_before,
                    row.played_move_uci,
                    row.played_move_san,
                )
                == (
                    move.mover_color,
                    move.move_number,
                    move.fen_before,
                    move.uci,
                    move.san,
                ),
                "PLAYER_ATTRIBUTION_INVALID",
            )
            require(
                (
                    row.eval_before_cp_white,
                    row.mate_before_white,
                    row.mate_before_winner,
                    row.best_move_uci,
                    row.pv_json,
                    row.eval_after_cp_white,
                    row.mate_after_white,
                    row.mate_after_winner,
                )
                == (
                    before.score_cp_white,
                    before.mate_distance_white,
                    before.mate_winner,
                    before.best_move_uci,
                    before.pv_json,
                    after.score_cp_white,
                    after.mate_distance_white,
                    after.mate_winner,
                ),
                "ANALYSIS_SCORE_INVALID",
            )
            loss = (
                None
                if before.score_cp_white is None or after.score_cp_white is None
                else calculate_loss_cp(
                    before.score_cp_white,
                    after.score_cp_white,
                    move.mover_color == "white",
                )
            )
            require(row.loss_cp == loss, "INVALID_LOSS")
            require(
                row.severity is None or row.severity == severity(loss),
                "SEVERITY_POLICY_MISMATCH",
            )

    @staticmethod
    def _features(
        g: Game,
        source: ParseInput,
        rows: list[MoveAnalysis],
        stored: list[MoveFeature],
        profile: str,
    ) -> dict[int, MoveFeatures]:
        analyses = [
            FeatureAnalysis(
                ply=r.ply,
                fen_before=r.fen_before,
                played_move_uci=r.played_move_uci,
                best_move_uci=r.best_move_uci,
                eval_before_cp_white=r.eval_before_cp_white,
                eval_after_cp_white=r.eval_after_cp_white,
                mate_before_white=r.mate_before_white,
                mate_after_white=r.mate_after_white,
                mate_before_winner=r.mate_before_winner,
                mate_after_winner=r.mate_after_winner,
                is_critical_error=None
                if r.severity is None
                else r.severity == "critical",
            )
            for r in rows
        ]
        identity = fingerprint(
            [
                asdict(source),
                source_hash(g),
                profile,
                [a.model_dump(mode="json") for a in analyses],
                asdict(DEFAULT_CONFIG),
                FEATURE_EXTRACTOR_VERSION,
                PHASE_CLASSIFIER_VERSION,
                PARSER_VERSION,
                chess.__version__,
            ]
        )
        selected = [r for r in stored if r.input_hash == identity]
        if not selected:
            return {}
        require(
            [r.ply for r in selected] == list(range(1, len(rows) + 1)),
            "FEATURE_SET_INVALID",
        )
        result = {}
        for row, analysis in zip(selected, rows, strict=True):
            f = MoveFeatures.model_validate(row.features_json)
            require(
                row.content_hash == fingerprint(row.features_json)
                and f.game_id == g.id
                and f.ply == row.ply
                and f.feature_version == row.feature_version
                and f.phase_classifier_version == PHASE_CLASSIFIER_VERSION
                and row.phase_classifier_version == f.phase_classifier_version
                and f.mover == analysis.mover
                and f.tracked_player == g.player_color
                and all(getattr(row, k) == getattr(f, k) for k in QUERY_FIELDS),
                "FEATURE_CONTENT_INVALID",
            )
            result[f.ply] = f
        return result
