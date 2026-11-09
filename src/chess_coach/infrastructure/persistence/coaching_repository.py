"""Short independent transactions for coaching evidence and durable job state."""

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import SQLAlchemyError

from chess_coach.analytics.phases import classify_phase
from chess_coach.analytics.sample_policy import ADVANTAGE_CP
from chess_coach.application.errors import OperationError
from chess_coach.domain.analysis import fingerprint
from chess_coach.domain.coaching_models import EngineScore, MoveCoachingEvidence
from chess_coach.domain.feature_models import FEATURE_EXTRACTOR_VERSION
from chess_coach.domain.game_records import ParseStatus
from chess_coach.domain.motif_models import MotifEvidence
from chess_coach.infrastructure.persistence.analysis_repository import (
    profile_of,
    source_hash,
)
from chess_coach.infrastructure.persistence.models import (
    AnalysisRun,
    CoachingOutput,
    Game,
    GameAnalysisState,
    MotifEventSnapshot,
    MoveAnalysis,
    PositionCache,
    utc_now,
)
from chess_coach.infrastructure.persistence.query_repository import QueryRepository


class CoachingRepository:
    def __init__(self, queries: QueryRepository):
        self.queries = queries
        self.sessions = queries.sessions

    def motif_schema_ready(self) -> bool:
        try:
            with self.sessions() as s:
                for table in (
                    Game,
                    GameAnalysisState,
                    MoveAnalysis,
                    PositionCache,
                    MotifEventSnapshot,
                    CoachingOutput,
                ):
                    s.execute(select(table).limit(0))
        except SQLAlchemyError:
            return False
        return True

    def record_events(self, evidence: MotifEvidence) -> None:
        # Taxonomy revisions don't change the identity of a verified observation.
        payload = evidence.model_dump(mode="json", exclude={"taxonomy_version"})
        with self.sessions.begin() as s:
            s.execute(
                insert(MotifEventSnapshot)
                .values(
                    evidence_hash=fingerprint(payload),
                    game_id=evidence.move.game_id,
                    ply=evidence.move.ply,
                    evidence_json=payload,
                )
                .on_conflict_do_nothing(
                    index_elements=[MotifEventSnapshot.evidence_hash]
                )
            )

    def evaluation_move_keys(self, limit: int) -> list[tuple[int, int]]:
        """Suggest review positions from existing analysis, without inference."""
        player = self.queries.player_id()
        profile = self.queries.profile()
        if not profile:
            return []
        move = MoveAnalysis
        priority = case(
            (move.mate_before_winner.is_distinct_from(move.mate_after_winner), 2),
            (move.loss_cp >= ADVANTAGE_CP, 1),
            else_=0,
        )
        ranked = (
            select(
                move.game_id,
                move.ply,
                Game.player_color,
                Game.time_class,
                func.row_number()
                .over(
                    partition_by=move.game_id,
                    order_by=(priority.desc(), move.loss_cp.desc(), move.ply),
                )
                .label("per_game"),
            )
            .join(Game, Game.id == move.game_id)
            .join(
                GameAnalysisState,
                (GameAnalysisState.game_id == move.game_id)
                & (GameAnalysisState.profile_hash == move.profile_hash)
                & (GameAnalysisState.analysis_version == move.analysis_version),
            )
            .where(
                Game.tracked_player_id == player,
                Game.parse_status == ParseStatus.READY,
                move.mover == Game.player_color,
                move.profile_hash == profile,
                GameAnalysisState.status == "done",
            )
            .subquery()
        )
        # Round-robin by game first, then by available color/time-control strata.
        strata = select(
            ranked.c.game_id,
            ranked.c.ply,
            ranked.c.per_game,
            func.row_number()
            .over(
                partition_by=(
                    ranked.c.per_game,
                    ranked.c.player_color,
                    ranked.c.time_class,
                ),
                order_by=ranked.c.game_id,
            )
            .label("per_stratum"),
        ).subquery()
        with self.sessions() as s:
            return [
                (game_id, ply)
                for game_id, ply in s.execute(
                    select(strata.c.game_id, strata.c.ply)
                    .order_by(strata.c.per_game, strata.c.per_stratum, strata.c.game_id)
                    .limit(limit)
                )
            ]

    def move_evidence(
        self, game_id: int, ply: int, profile: str | None = None
    ) -> MoveCoachingEvidence:
        return self._move_evidence(game_id, ply, profile)[0]

    def tracked_move_evidence(
        self, game_id: int, ply: int, profile: str | None = None
    ) -> tuple[MoveCoachingEvidence, int | None]:
        return self._move_evidence(game_id, ply, profile, tracked_only=True)

    def _move_evidence(
        self, game_id: int, ply: int, profile: str | None, *, tracked_only: bool = False
    ) -> tuple[MoveCoachingEvidence, int | None]:
        self.queries.game(game_id)  # enforce ownership
        profile = profile or self.queries.profile()
        with self.sessions() as s:
            game = s.get(Game, game_id)
            assert game is not None
            state = s.scalar(
                select(GameAnalysisState).where(
                    GameAnalysisState.game_id == game_id,
                    GameAnalysisState.profile_hash == profile,
                )
            )
            if state is None or state.status != "done":
                raise OperationError(
                    "ANALYSIS_NOT_READY",
                    "Complete engine analysis before requesting coaching.",
                )
            run = (
                s.get(AnalysisRun, state.analysis_run_id)
                if state.analysis_run_id
                else None
            )
            if (
                game.parse_status != ParseStatus.READY
                or run is None
                or run.tracked_player_id != game.tracked_player_id
                or profile_of(run).hash != profile
                or not self.queries.analysis.compatible(s, game, profile_of(run))
            ):
                raise OperationError(
                    "EVIDENCE_INCOMPLETE",
                    "Complete compatible engine analysis before retrying.",
                )
            rows = list(
                s.scalars(
                    select(MoveAnalysis)
                    .where(
                        MoveAnalysis.game_id == game_id,
                        MoveAnalysis.profile_hash == profile,
                    )
                    .order_by(MoveAnalysis.ply)
                )
            )
            if ply < 1 or ply > len(rows):
                raise OperationError(
                    "MOVE_NOT_FOUND",
                    "Choose an analyzed move from this completed game.",
                    404,
                )
            row = rows[ply - 1]
            if tracked_only and row.mover != game.player_color:
                raise OperationError(
                    "MOVE_NOT_TRACKED",
                    "Choose a move made by the tracked player.",
                    422,
                )
            previous = rows[ply - 3].eval_before_cp_white if ply >= 3 else None
            assert state.position_ids and row.best_move_uci
            before = s.get(PositionCache, state.position_ids[ply - 1])
            after = s.get(PositionCache, state.position_ids[ply])
            assert before and after
            metadata = game.parsed_metadata or {}
            if (
                before.initial_fen != metadata.get("initial_fen")
                or before.moves_uci_json != [r.played_move_uci for r in rows[: ply - 1]]
                or before.history_before_start_unknown
                != bool(metadata.get("history_before_start_unknown"))
            ):
                raise ValueError(
                    "Cached replay does not match the completed game's history"
                )
            # Replay history with the existing phase classifier, preserving monotone phases.
            import chess

            board = chess.Board(before.initial_fen)
            phase = None
            for uci in before.moves_uci_json:
                phase, _, _ = classify_phase(
                    board, phase, unknown_history=before.history_before_start_unknown
                )
                board.push_uci(uci)
            phase, _, _ = classify_phase(
                board, phase, unknown_history=before.history_before_start_unknown
            )
            evidence = MoveCoachingEvidence(
                game_id=game_id,
                ply=ply,
                player_color=row.mover,
                player_rating=game.white_rating
                if row.mover == "white"
                else game.black_rating,
                phase=phase,
                fen_before=row.fen_before,
                initial_fen=before.initial_fen,
                history_uci=tuple(before.moves_uci_json),
                history_before_start_unknown=before.history_before_start_unknown,
                played_move_uci=row.played_move_uci,
                best_move_uci=row.best_move_uci,
                best_line_uci=tuple(before.pv_json[:16]),
                played_refutation_uci=tuple(after.pv_json[:16]),
                before=EngineScore(
                    cp_white=before.score_cp_white,
                    mate_white=before.mate_distance_white,
                    mate_winner=before.mate_winner,
                ),
                after=EngineScore(
                    cp_white=after.score_cp_white,
                    mate_white=after.mate_distance_white,
                    mate_winner=after.mate_winner,
                ),
                loss_cp=row.loss_cp,
                completion_provenance="chesscom_archive"
                if game.platform == "chess.com"
                else "pgn_declaration",
                source_hash=source_hash(game),
                profile_hash=profile,
                engine_version=run.engine_version,
                analysis_version=run.analysis_version,
                draw_policy=run.draw_policy_version,
                feature_version=FEATURE_EXTRACTOR_VERSION,
            )
            return evidence, previous

    def get(self, job_id: int) -> CoachingOutput:
        with self.sessions() as s:
            row = s.get(CoachingOutput, job_id)
            if row is None:
                raise OperationError(
                    "COACHING_NOT_FOUND", "Refresh the coaching request.", 404
                )
            return row

    def find(
        self,
        evidence_hash: str,
        model: str,
        generation: dict[str, object],
        prompt: str,
        schema: str,
        digest: str | None = None,
    ) -> CoachingOutput | None:
        with self.sessions() as s:
            rows = s.scalars(
                select(CoachingOutput)
                .where(
                    CoachingOutput.evidence_hash == evidence_hash,
                    CoachingOutput.model_name == model,
                    CoachingOutput.prompt_version == prompt,
                    CoachingOutput.schema_version == schema,
                )
                .order_by(CoachingOutput.id.desc())
            )
            return next(
                (
                    r
                    for r in rows
                    if r.generation_json == generation
                    and (digest is None or r.model_digest == digest)
                ),
                None,
            )

    def enqueue(
        self,
        kind: str,
        evidence: dict[str, object],
        model: str,
        digest: str,
        generation: dict[str, object],
        prompt: str,
        schema: str,
    ) -> CoachingOutput:
        key = fingerprint([kind, evidence, model, digest, generation, prompt, schema])
        with self.sessions.begin() as s:
            # Reserve the SQLite writer before lookup to serialize duplicate submissions.
            s.execute(
                update(CoachingOutput).where(CoachingOutput.id == -1).values(id=-1)
            )
            row = s.scalar(
                select(CoachingOutput).where(CoachingOutput.cache_key == key)
            )
            if row is None:
                row = CoachingOutput(
                    cache_key=key,
                    output_type=kind,
                    evidence_hash=fingerprint(evidence),
                    evidence_json=evidence,
                    model_name=model,
                    model_digest=digest,
                    generation_json=generation,
                    prompt_version=prompt,
                    schema_version=schema,
                )
                s.add(row)
            elif row.status == "failed":
                row.status, row.error_code, row.output_json = "queued", None, None
                row.updated_at = utc_now()
            s.flush()
            return row

    def recover(self) -> None:
        """Caller holds the same kernel guard used for generation."""
        with self.sessions.begin() as s:
            s.execute(
                update(CoachingOutput)
                .where(CoachingOutput.status == "running")
                .values(
                    status="queued",
                    error_code="COACHING_INTERRUPTED",
                    updated_at=utc_now(),
                )
            )

    def claim(self) -> CoachingOutput | None:
        with self.sessions.begin() as s:
            s.execute(
                update(CoachingOutput).where(CoachingOutput.id == -1).values(id=-1)
            )
            row = s.scalar(
                select(CoachingOutput)
                .where(CoachingOutput.status == "queued")
                .order_by(CoachingOutput.id)
            )
            if row:
                row.status, row.error_code, row.updated_at = "running", None, utc_now()
                s.flush()
            return row

    def attempt(self, job_id: int) -> None:
        with self.sessions.begin() as s:
            row = s.get(CoachingOutput, job_id)
            assert row and row.status == "running"
            row.attempt_count += 1

    def finish(
        self,
        job_id: int,
        output: dict[str, object] | None,
        error: str | None,
        latency: int,
        metrics: dict[str, object],
    ) -> None:
        with self.sessions.begin() as s:
            row = s.get(CoachingOutput, job_id)
            assert row and row.status == "running"
            row.output_json, row.error_code = output, error
            row.status = (
                "failed"
                if error
                else "insufficient_evidence"
                if output and output["status"] == "insufficient_evidence"
                else "done"
            )
            row.latency_ms, row.metrics_json, row.updated_at = (
                latency,
                metrics,
                utc_now(),
            )

    def invalidate(self, job_id: int) -> None:
        with self.sessions.begin() as s:
            s.execute(
                update(CoachingOutput)
                .where(
                    CoachingOutput.id == job_id,
                    CoachingOutput.status.in_(["done", "insufficient_evidence"]),
                )
                .values(
                    status="failed",
                    output_json=None,
                    error_code="INVALID_MODEL_OUTPUT",
                    updated_at=utc_now(),
                )
            )
