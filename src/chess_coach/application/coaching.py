"""Optional downstream coaching. Deterministic analysis is always read-only here."""

import json
import logging
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal, Protocol

import chess
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from structlog.contextvars import bound_contextvars

from chess_coach.analytics.contracts import (
    AnalyticsReport,
    ReportStatus,
    Weakness,
    coaching_report_hash,
)
from chess_coach.analytics.move_breakdown import build_move_breakdown
from chess_coach.application.coaching_evidence import EvidenceBuilder
from chess_coach.application.errors import OperationError
from chess_coach.config import Settings
from chess_coach.domain.analysis import fingerprint
from chess_coach.domain.coaching_models import (
    GameCoachingEvidence,
    GameMoment,
    GamePractice,
    GameReviewMoment,
    HistoricalExplanation,
    LLMHealth,
    MoveBreakdown,
    MoveCoachingEvidence,
    MoveExplanation,
    MovePractice,
    PracticeFocus,
)
from chess_coach.domain.feature_models import EvidenceModel
from chess_coach.domain.motif_models import (
    MOTIF_SCHEMA_VERSION,
    TAXONOMY_VERSION,
    ChessEvent,
    MotifEvidence,
    MotifPrediction,
)
from chess_coach.infrastructure.llm.client import generation_settings
from chess_coach.infrastructure.llm.motif_classifier import (
    MOTIF_PROMPT_VERSION,
    motif_input,
    validate_prediction,
)
from chess_coach.infrastructure.llm.prompts import (
    GAME_PRACTICE_PROMPT_VERSION,
    GAME_PRACTICE_SCHEMA_VERSION,
    HISTORICAL_EXPLANATION_PROMPT_VERSION,
    MOVE_EXPLANATION_PROMPT_VERSION,
    MOVE_PRACTICE_SCHEMA_VERSION,
    OUTPUT_SCHEMA_VERSION,
)
from chess_coach.infrastructure.llm.validation import validate_text
from chess_coach.infrastructure.persistence.coaching_repository import (
    CoachingRepository,
)
from chess_coach.infrastructure.persistence.models import CoachingOutput
from chess_coach.observability.logging import elapsed_ms

logger = logging.getLogger(__name__)


class CoachModel(Protocol):
    metrics: dict[str, object]

    def generate(self, evidence_json: str, schema: type[BaseModel]) -> str: ...


class HealthProbe(Protocol):
    def __call__(self) -> LLMHealth: ...


class HistoricalEvidence(EvidenceModel):
    schema_version: str = "historical-evidence-v1"
    # A canonical source report hash ties every statistic/reference to the full DTO.
    report_hash: str
    analytics_version: str
    policy_version: str
    ranker_version: str
    request: dict[str, object]
    total_games: int
    patterns: tuple[Weakness, ...] = Field(max_length=5)


CoachingEvidence = MoveCoachingEvidence | HistoricalEvidence | GameCoachingEvidence


class CoachingResponse(EvidenceModel):
    job_id: int | None = None
    status: str
    evidence: CoachingEvidence
    move_breakdown: MoveBreakdown | None = None
    game_review: tuple[GameReviewMoment, ...] = ()
    coach: MoveExplanation | HistoricalExplanation | None = None
    error_code: str | None = None
    message: str | None = None
    cached: bool = False
    model_digest: str | None = None
    attempt_count: int = 0


class MotifResponse(EvidenceModel):
    job_id: int | None = None
    status: str
    events: tuple[ChessEvent, ...]
    taxonomy_version: str = TAXONOMY_VERSION
    # The taxonomy is experimental pending the held-out release gate.
    motif: None = None
    error_code: str | None = None
    message: str | None = None
    cached: bool = False


class MotifHealth(EvidenceModel):
    status: Literal["ready", "degraded", "blocked"]
    database_ready: bool
    ollama: LLMHealth | None = None
    taxonomy_version: str = TAXONOMY_VERSION
    message: str


JobEvidence = CoachingEvidence | MotifEvidence


def job_evidence(row: CoachingOutput) -> JobEvidence:
    if row.output_type == "motif":
        return MotifEvidence.model_validate(row.evidence_json)
    if row.output_type == "move":
        return MoveCoachingEvidence.model_validate(row.evidence_json)
    if row.output_type == "game":
        return GameCoachingEvidence.model_validate(row.evidence_json)
    return HistoricalEvidence.model_validate(row.evidence_json)


def job_config(evidence: JobEvidence) -> tuple[str, str, str]:
    if isinstance(evidence, MotifEvidence):
        return "motif", MOTIF_PROMPT_VERSION, MOTIF_SCHEMA_VERSION
    if isinstance(evidence, MoveCoachingEvidence):
        return "move", MOVE_EXPLANATION_PROMPT_VERSION, MOVE_PRACTICE_SCHEMA_VERSION
    if isinstance(evidence, GameCoachingEvidence):
        return "game", GAME_PRACTICE_PROMPT_VERSION, GAME_PRACTICE_SCHEMA_VERSION
    return "historical", HISTORICAL_EXPLANATION_PROMPT_VERSION, OUTPUT_SCHEMA_VERSION


def historical_evidence(report: AnalyticsReport) -> HistoricalEvidence:
    # Category scores are not comparable. Preserve the rank within each category.
    patterns = tuple(
        w.model_copy(update={"source_moves": w.source_moves[:3]})
        for category in ("phase", "opening", "context")
        for w in report.ranked_weaknesses.get(category, ())
    )[:5]
    return HistoricalEvidence(
        report_hash=coaching_report_hash(report),
        analytics_version=report.analytics_version,
        policy_version=report.policy_version,
        ranker_version=report.ranker_version,
        request=report.request.model_dump(mode="json"),
        total_games=report.health.analyzed_games,
        patterns=patterns if report.status == ReportStatus.COMPLETE else (),
    )


def validated_output(
    raw: str, evidence: CoachingEvidence
) -> MovePractice | HistoricalExplanation | GamePractice:
    if isinstance(evidence, GameCoachingEvidence):
        review = GamePractice.model_validate_json(raw)
        allowed_by_ply = {
            moment.ply: moment.allowed_focuses for moment in evidence.moments
        }
        if len({choice.ply for choice in review.choices}) != len(review.choices) or any(
            choice.focus not in allowed_by_ply.get(choice.ply, ())
            for choice in review.choices
        ):
            raise OperationError(
                "UNSUPPORTED_CLAIM",
                "The model chose a moment or practice focus outside this game’s evidence.",
            )
        return review
    if isinstance(evidence, MoveCoachingEvidence):
        practice = MovePractice.model_validate_json(raw)
        allowed_focuses = _focuses(build_move_breakdown(evidence))
        if practice.focus is not None and practice.focus not in allowed_focuses:
            raise OperationError(
                "UNSUPPORTED_CLAIM",
                "The model chose a practice focus outside the saved observations.",
            )
        if practice.focus is None:
            specific = next(
                (focus for focus in allowed_focuses if focus != "reply"), None
            )
            if specific is not None:
                return MovePractice(status="explained", focus=specific)
        return practice
    output = HistoricalExplanation.model_validate_json(raw)
    allowed = [w.candidate_key for w in evidence.patterns]
    refs = [p.pattern_id for p in output.priorities]
    if (
        len(set(refs)) != len(refs)
        or any(r not in allowed for r in refs)
        or refs != [r for r in allowed if r in refs]
    ):
        raise OperationError(
            "UNSUPPORTED_CLAIM",
            "Historical advice must reference supplied patterns in order.",
        )
    validate_text(output)
    return output


_PRACTICE: dict[PracticeFocus, tuple[str, str]] = {
    "reply": (
        "Start with the opponent’s strongest saved reply.",
        "Play that reply on the board. What changes, and what would you play next?",
    ),
    "material": (
        "Follow the captures before judging the exchange.",
        "Replay the highlighted capture or attack. What can each side take back?",
    ),
    "check": (
        "Look at checks and the legal replies they leave.",
        "Find the highlighted check on the board. Can the king move, can the check be blocked, or can the checking piece be captured?",
    ),
    "mate": (
        "Check for mating moves on both sides before committing.",
        "Replay the highlighted checkmate. What covers each escape square, and what prevents a block or capture?",
    ),
    "promotion": (
        "Calculate the pawn’s route and the reply after promotion.",
        "Play the promotion in the saved line. What can the new piece do, and how can the opponent respond?",
    ),
    "castling": (
        "Compare the king’s safety before and after castling.",
        "Replay the castling move. Which squares now protect the king, and where can the rook play?",
    ),
}


def _focuses(
    breakdown: MoveBreakdown, *, include_best: bool = False
) -> list[PracticeFocus]:
    if breakdown.alternative is None and not include_best:
        return []
    cues = (
        breakdown.played.cue,
        breakdown.alternative.cue if breakdown.alternative else "",
    )
    choices: list[PracticeFocus] = (
        [] if breakdown.played.cue == "ends the game" else ["reply"]
    )
    if any("checkmate" in cue for cue in cues):
        choices.append("mate")
    if any("gives check" in cue for cue in cues):
        choices.append("check")
    if any(cue.startswith(("captures", "attacks")) for cue in cues):
        choices.append("material")
    if any(cue.startswith("promotes") for cue in cues):
        choices.append("promotion")
    if "castles" in cues:
        choices.append("castling")
    return choices


def move_prompt_payload(evidence: MoveCoachingEvidence) -> str:
    breakdown = build_move_breakdown(evidence)
    return json.dumps(
        {
            "played_line_observation": breakdown.played.cue,
            "alternative_observation": breakdown.alternative.cue
            if breakdown.alternative
            else None,
            "allowed_focuses": _focuses(breakdown),
        }
    )


def game_review_moments(
    evidence: GameCoachingEvidence, practice: GamePractice | None = None
) -> tuple[GameReviewMoment, ...]:
    moments = {moment.ply: moment for moment in evidence.moments}
    ordered = (
        [
            (moments[choice.ply], _PRACTICE[choice.focus][1])
            for choice in practice.choices
        ]
        if practice
        else [(moment, None) for moment in evidence.moments]
    )
    return tuple(
        GameReviewMoment(
            ply=moment.ply,
            move=moment.move,
            played_fact=moment.played_fact,
            alternative_fact=moment.alternative_fact,
            practice_tip=tip,
        )
        for moment, tip in ordered
    )


class CoachingService:
    def __init__(
        self, store: CoachingRepository, settings: Settings, health: HealthProbe
    ):
        self.store, self.settings, self.health = store, settings, health
        self.builder = EvidenceBuilder(store)

    def motif_health(self) -> MotifHealth:
        if not self.store.motif_schema_ready():
            return MotifHealth(
                status="blocked",
                database_ready=False,
                message="Check the database path and apply migrations before retrying.",
            )
        llm = self.health()
        return MotifHealth(
            status="ready" if llm.status == "ready" else "degraded",
            database_ready=True,
            ollama=llm,
            message=llm.message,
        )

    def move(
        self, game: int, ply: int, generate: bool = False, profile: str | None = None
    ) -> CoachingResponse:
        return self.request(self.builder.move(game, ply, profile), generate)

    def game_evidence(self, game: int, profile: str | None) -> GameCoachingEvidence:
        try:
            resolved, identity, moves = self.store.game_moments(game, profile)
            moments = []
            for move in moves:
                board = chess.Board(move.fen_before)
                san = board.san(chess.Move.from_uci(move.played_move_uci))
                dots = "." if board.turn == chess.WHITE else "..."
                breakdown = build_move_breakdown(move)
                moments.append(
                    GameMoment(
                        ply=move.ply,
                        move=f"{board.fullmove_number}{dots} {san}",
                        played_fact=breakdown.played.key_fact,
                        alternative_fact=breakdown.alternative.key_fact
                        if breakdown.alternative
                        else None,
                        allowed_focuses=tuple(
                            focus
                            for focus in _focuses(breakdown, include_best=True)
                            if focus != "reply" or move.played_refutation_uci
                        ),
                    )
                )
            return GameCoachingEvidence(
                game_id=game,
                profile_hash=resolved,
                source_hash=identity,
                moments=tuple(moments),
            )
        except OperationError:
            raise
        except ValueError:
            raise OperationError(
                "EVIDENCE_INCOMPLETE",
                "Complete compatible engine analysis before retrying.",
            ) from None

    def game(
        self, game: int, generate: bool = False, profile: str | None = None
    ) -> CoachingResponse:
        evidence = self.game_evidence(game, profile)
        if not any(moment.allowed_focuses for moment in evidence.moments):
            return CoachingResponse(
                status="insufficient_evidence",
                evidence=evidence,
                game_review=game_review_moments(evidence),
            )
        return self.request(evidence, generate)

    def history(
        self,
        report: AnalyticsReport,
        generate: bool = False,
        expected_report_hash: str | None = None,
    ) -> CoachingResponse:
        evidence = historical_evidence(report)
        if (
            generate
            and expected_report_hash is not None
            and expected_report_hash != evidence.report_hash
        ):
            raise OperationError(
                "COACHING_REPORT_CHANGED",
                "The historical evidence changed. Refresh the report before generating coaching.",
            )
        if not evidence.patterns:
            return CoachingResponse(
                status="insufficient_evidence",
                evidence=evidence,
                coach=HistoricalExplanation(
                    status="insufficient_evidence",
                    summary="There is insufficient supported historical evidence for coaching.",
                ),
            )
        return self.request(evidence, generate)

    def motif(
        self, game: int, ply: int, generate: bool = False, profile: str | None = None
    ) -> MotifResponse:
        evidence = self.builder.motif(game, ply, profile)
        if not evidence.events:
            return MotifResponse(status="insufficient_evidence", events=())
        if generate:
            self.store.record_events(evidence)
        row = self.request_row(evidence, generate)
        if row and not self.valid_cached_output(row, evidence):
            return MotifResponse(
                job_id=row.id,
                status="failed",
                events=evidence.events,
                error_code="INVALID_MODEL_OUTPUT",
                message="Stored motif failed validation. Request it again to regenerate.",
            )
        return MotifResponse(
            job_id=row.id if row else None,
            status=row.status if row else "not_generated",
            events=evidence.events,
            error_code=row.error_code if row else None,
            message=(
                "Check the local coaching worker and Ollama, then retry."
                if row and row.status == "failed"
                else None
            ),
            cached=bool(row and row.status in {"done", "insufficient_evidence"}),
        )

    def request(self, evidence: CoachingEvidence, generate: bool) -> CoachingResponse:
        if (
            isinstance(evidence, MoveCoachingEvidence)
            and evidence.played_move_uci == evidence.best_move_uci
        ):
            breakdown = build_move_breakdown(evidence)
            return CoachingResponse(
                status="insufficient_evidence",
                evidence=evidence,
                move_breakdown=breakdown,
                coach=MoveExplanation(
                    status="insufficient_evidence", summary=breakdown.assessment
                ),
            )
        row = self.request_row(evidence, generate)
        return (
            self.response(
                row,
                evidence,
                cached=not generate or row.status in {"done", "insufficient_evidence"},
            )
            if row
            else CoachingResponse(
                status="not_generated",
                evidence=evidence,
                move_breakdown=build_move_breakdown(evidence)
                if isinstance(evidence, MoveCoachingEvidence)
                else None,
                game_review=game_review_moments(evidence)
                if isinstance(evidence, GameCoachingEvidence)
                else (),
            )
        )

    @staticmethod
    def valid_cached_output(row: CoachingOutput, evidence: JobEvidence) -> bool:
        if row.status not in {"done", "insufficient_evidence"}:
            return True
        try:
            raw = json.dumps(row.output_json)
            output = (
                validate_prediction(raw, evidence)
                if isinstance(evidence, MotifEvidence)
                else validated_output(raw, evidence)
            )
            return (output.status == "insufficient_evidence") == (
                row.status == "insufficient_evidence"
            )
        except ValueError:
            return False

    def request_row(
        self, evidence: JobEvidence, generate: bool
    ) -> CoachingOutput | None:
        kind, prompt, schema = job_config(evidence)
        payload = evidence.model_dump(mode="json")
        config = generation_settings(self.settings)
        evidence_hash = fingerprint(payload)
        # Retrieval remains available offline. POST resolves the current digest when online.
        model = self.settings.ollama_model
        if not generate:
            return self.store.find(evidence_hash, model, config, prompt, schema)
        health = self.health()
        if health.status != "ready":
            previous = self.store.find(evidence_hash, model, config, prompt, schema)
            if (
                previous
                and previous.status in {"done", "insufficient_evidence"}
                and self.valid_cached_output(previous, evidence)
            ):
                return previous
            code = (
                "MODEL_NOT_INSTALLED"
                if health.status == "model_missing"
                else "OLLAMA_UNAVAILABLE"
            )
            raise OperationError(code, health.message, 503)
        assert health.model_digest
        previous = self.store.find(
            evidence_hash, model, config, prompt, schema, digest=health.model_digest
        )
        if previous and not self.valid_cached_output(previous, evidence):
            self.store.invalidate(previous.id)
        return self.store.enqueue(
            kind,
            payload,
            model,
            health.model_digest,
            config,
            prompt,
            schema,
        )

    def job(self, job_id: int) -> CoachingResponse:
        row = self.store.get(job_id)
        if row.output_type == "motif":
            raise OperationError(
                "COACHING_NOT_FOUND", "Read motif status from the completed move.", 404
            )
        evidence = job_evidence(row)
        assert not isinstance(evidence, MotifEvidence)
        if (
            isinstance(evidence, MoveCoachingEvidence)
            and row.schema_version != MOVE_PRACTICE_SCHEMA_VERSION
        ):
            raise OperationError(
                "COACHING_CONFIG_CHANGED",
                "Reopen this move to see its current coaching breakdown.",
            )
        # Verify current source before exposing a stored move result.
        if (
            isinstance(evidence, MoveCoachingEvidence)
            and self.builder.move(evidence.game_id, evidence.ply, evidence.profile_hash)
            != evidence
        ):
            raise OperationError(
                "EVIDENCE_INCOMPLETE",
                "The stored evidence changed; request coaching again.",
            )
        if (
            isinstance(evidence, GameCoachingEvidence)
            and self.game_evidence(evidence.game_id, evidence.profile_hash) != evidence
        ):
            raise OperationError(
                "EVIDENCE_INCOMPLETE",
                "The stored game evidence changed. Reopen Game Review.",
            )
        return self.response(row, evidence)

    @staticmethod
    def response(
        row: CoachingOutput,
        evidence: CoachingEvidence,
        cached: bool = False,
    ) -> CoachingResponse:
        output: MoveExplanation | HistoricalExplanation | None = None
        game_practice = None
        breakdown = (
            build_move_breakdown(evidence)
            if isinstance(evidence, MoveCoachingEvidence)
            else None
        )
        if row.status in {"done", "insufficient_evidence"}:
            try:
                validated = validated_output(json.dumps(row.output_json), evidence)
            except ValueError, OperationError:
                raise OperationError(
                    "INVALID_MODEL_OUTPUT",
                    "Stored coaching failed validation; regenerate it.",
                ) from None
            if isinstance(validated, HistoricalExplanation):
                output = validated
            elif isinstance(validated, GamePractice):
                game_practice = validated
            elif validated.focus is not None:
                assert breakdown and breakdown.alternative
                lesson, tip = _PRACTICE[validated.focus]
                output = MoveExplanation(
                    status="explained",
                    summary=breakdown.assessment,
                    what_went_wrong=breakdown.played.key_fact,
                    why_best_move_works=breakdown.alternative.key_fact,
                    lesson=lesson,
                    practice_tip=tip,
                )
            else:
                assert breakdown
                output = MoveExplanation(
                    status="insufficient_evidence", summary=breakdown.assessment
                )
        return CoachingResponse(
            job_id=row.id,
            status=row.status,
            evidence=evidence,
            move_breakdown=breakdown,
            game_review=game_review_moments(evidence, game_practice)
            if isinstance(evidence, GameCoachingEvidence)
            else (),
            coach=output,
            error_code=row.error_code,
            cached=cached,
            model_digest=row.model_digest,
            attempt_count=row.attempt_count,
            message="The local model’s notes failed the evidence checks. The Stockfish breakdown is available above."
            if breakdown is not None
            and row.status == "failed"
            and row.error_code in {"UNSUPPORTED_CLAIM", "FACT_CONTRADICTION"}
            else "Coaching failed. Check Ollama and the local coaching worker, then retry."
            if row.status == "failed"
            else "Start the local coaching worker if this request remains queued."
            if row.status == "queued"
            else None,
        )


def _generation_request(
    row: CoachingOutput, evidence: JobEvidence
) -> tuple[type[BaseModel], str]:
    if isinstance(evidence, MotifEvidence):
        return MotifPrediction, motif_input(evidence)
    if isinstance(evidence, MoveCoachingEvidence):
        return MovePractice, move_prompt_payload(evidence)
    if isinstance(evidence, GameCoachingEvidence):
        return GamePractice, json.dumps(
            [
                moment.model_dump(mode="json", exclude={"move"})
                for moment in evidence.moments
                if moment.allowed_focuses
            ]
        )
    return HistoricalExplanation, json.dumps(
        row.evidence_json, sort_keys=True, separators=(",", ":")
    )


class CoachingProcessor:
    def __init__(self, service: CoachingService, model: CoachModel):
        self.service, self.model = service, model

    def current(self, evidence: JobEvidence) -> bool:
        if isinstance(evidence, MotifEvidence):
            move = evidence.move
            return (
                bool(evidence.events)
                and self.service.builder.motif(
                    move.game_id, move.ply, move.profile_hash
                )
                == evidence
            )
        if isinstance(evidence, MoveCoachingEvidence):
            return (
                self.service.builder.move(
                    evidence.game_id, evidence.ply, evidence.profile_hash
                )
                == evidence
            )
        if isinstance(evidence, GameCoachingEvidence):
            return (
                self.service.game_evidence(evidence.game_id, evidence.profile_hash)
                == evidence
            )
        return True

    def process(self, row: CoachingOutput) -> None:
        with bound_contextvars(
            run_id=str(row.id), component="coaching", model=row.model_name
        ):
            started = perf_counter()
            logger.info("llm_generation_started")
            try:
                self._process(row, started)
            except SQLAlchemyError:
                logger.exception(
                    "llm_generation_failed",
                    extra={
                        "error_code": "DATABASE_UNAVAILABLE",
                        "duration_ms": elapsed_ms(started),
                    },
                )
                raise

    def _check_generation_inputs(
        self, row: CoachingOutput, evidence: JobEvidence
    ) -> None:
        _, prompt, schema_version = job_config(evidence)
        if (
            row.prompt_version != prompt
            or row.schema_version != schema_version
            or row.generation_json != generation_settings(self.service.settings)
            or row.model_name != self.service.settings.ollama_model
        ):
            raise OperationError(
                "COACHING_CONFIG_CHANGED",
                "Request coaching with the current configuration.",
            )
        if not self.current(evidence):
            raise OperationError(
                "EVIDENCE_INCOMPLETE",
                "The game evidence changed; request coaching again.",
            )
        health = self.service.health()
        if health.status != "ready":
            raise OperationError(
                "MODEL_NOT_INSTALLED"
                if health.status == "model_missing"
                else "OLLAMA_UNAVAILABLE",
                health.message,
            )
        if health.model_digest != row.model_digest:
            raise OperationError(
                "MODEL_CHANGED",
                "The installed model changed; request coaching again.",
            )

    def _process(self, row: CoachingOutput, started: float) -> None:
        output: dict[str, object] | None = None
        error: str | None = None
        metrics: dict[str, object] = {}
        request_seconds = 0.0
        attempt_count = 0
        first_schema_valid: bool | None = None
        schema_valid: bool | None = None
        try:
            evidence = job_evidence(row)
            self._check_generation_inputs(row, evidence)
            schema, payload = _generation_request(row, evidence)
            for attempt in range(2):
                self.service.store.attempt(row.id)
                attempt_count += 1
                schema_valid = None
                try:
                    requested = perf_counter()
                    try:
                        raw = self.model.generate(payload, schema)
                    finally:
                        request_seconds += perf_counter() - requested
                    metrics = self.model.metrics
                    validated = (
                        validate_prediction(raw, evidence)
                        if isinstance(evidence, MotifEvidence)
                        else validated_output(raw, evidence)
                    )
                    schema_valid = True
                    if not self.current(evidence):
                        raise OperationError(
                            "EVIDENCE_INCOMPLETE",
                            "Game evidence changed during generation; retry coaching.",
                        )
                    output = validated.model_dump(mode="json")
                    error = None
                    break
                except ValidationError:
                    error = "INVALID_MODEL_OUTPUT"
                    schema_valid = False
                except OperationError as exc:
                    error = exc.code
                    if error == "INVALID_MODEL_OUTPUT":
                        schema_valid = False
                    elif error in {"UNSUPPORTED_CLAIM", "FACT_CONTRADICTION"}:
                        schema_valid = True
                    if isinstance(evidence, MotifEvidence) and error in {
                        "UNSUPPORTED_CLAIM",
                        "FACT_CONTRADICTION",
                    }:
                        break
                    if error not in {
                        "INVALID_MODEL_OUTPUT",
                        "UNSUPPORTED_CLAIM",
                        "FACT_CONTRADICTION",
                        "OLLAMA_UNAVAILABLE",
                    }:
                        break
                finally:
                    if attempt == 0:
                        first_schema_valid = schema_valid
        except OperationError as exc:
            error = exc.code
        except ValueError:
            error = "EVIDENCE_INCOMPLETE"
        except SQLAlchemyError:
            raise
        except Exception:
            logger.exception("coaching_unexpected_failure", extra={"run_id": row.id})
            error = "COACHING_FAILED"
        latency = elapsed_ms(started)
        diagnostic_code = (
            {
                "COACHING_TIMEOUT": "MODEL_REQUEST_TIMEOUT",
                "OLLAMA_UNAVAILABLE": "OLLAMA_UNREACHABLE",
                "INVALID_MODEL_OUTPUT": "MODEL_SCHEMA_INVALID",
                "UNSUPPORTED_CLAIM": "MODEL_FACTUAL_VALIDATION_FAILED",
                "FACT_CONTRADICTION": "MODEL_FACTUAL_VALIDATION_FAILED",
            }.get(error, error)
            if error
            else None
        )
        measured_ms = round(request_seconds * 1000) if attempt_count else None
        self.service.store.finish(
            row.id,
            output,
            error,
            latency,
            {
                **metrics,
                "request_duration_ms": measured_ms,
                "first_schema_valid": first_schema_valid,
                "schema_valid": schema_valid,
                "attempt_count": attempt_count,
                "generation_failed": error is not None,
                "generation_finished_at": datetime.now(UTC).isoformat(),
                "diagnostic_code": diagnostic_code,
            },
        )
        logger.log(
            logging.WARNING if error else logging.INFO,
            "llm_generation_failed" if error else "llm_generation_finished",
            extra={
                "error_code": diagnostic_code,
                "duration_ms": measured_ms if measured_ms is not None else latency,
                "schema_valid": schema_valid,
                "attempt_count": attempt_count,
            },
        )
