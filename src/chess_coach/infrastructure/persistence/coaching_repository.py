"""Short independent transactions for coaching evidence and durable job state."""

from sqlalchemy import select, update

from chess_coach.analytics.phases import classify_phase
from chess_coach.application.errors import OperationError
from chess_coach.domain.analysis import fingerprint
from chess_coach.domain.coaching_models import EngineScore, MoveCoachingEvidence
from chess_coach.domain.feature_models import FEATURE_EXTRACTOR_VERSION
from chess_coach.infrastructure.persistence.analysis_repository import (
    profile_of,
    source_hash,
)
from chess_coach.infrastructure.persistence.models import (
    AnalysisRun,
    CoachingOutput,
    Game,
    GameAnalysisState,
    MoveAnalysis,
    PositionCache,
    utc_now,
)
from chess_coach.infrastructure.persistence.query_repository import QueryRepository


class CoachingRepository:
    def __init__(self, queries: QueryRepository):
        self.queries = queries
        self.sessions = queries.sessions

    def move_evidence(
        self, game_id: int, ply: int, profile: str | None = None
    ) -> MoveCoachingEvidence:
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
                run is None
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
            assert state.position_ids and row.best_move_uci
            before = s.get(PositionCache, state.position_ids[ply - 1])
            after = s.get(PositionCache, state.position_ids[ply])
            assert before and after
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
            return MoveCoachingEvidence(
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
            s.execute(update(CoachingOutput).where(
                CoachingOutput.id == job_id,
                CoachingOutput.status.in_(["done", "insufficient_evidence"]),
            ).values(status="failed", output_json=None, error_code="INVALID_MODEL_OUTPUT", updated_at=utc_now()))
