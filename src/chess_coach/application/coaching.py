"""Optional downstream coaching. Deterministic analysis is always read-only here."""

import json
import logging
from time import perf_counter
from typing import Literal, Protocol

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from chess_coach.analytics.contracts import (
    AnalyticsReport,
    ReportStatus,
    Weakness,
    coaching_report_hash,
)
from chess_coach.application.coaching_evidence import EvidenceBuilder
from chess_coach.application.errors import OperationError
from chess_coach.config import Settings
from chess_coach.domain.analysis import fingerprint
from chess_coach.domain.coaching_models import (
    HistoricalExplanation,
    LLMHealth,
    MoveCoachingEvidence,
    MoveExplanation,
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
    MOVE_EXPLANATION_PROMPT_VERSION,
    OUTPUT_SCHEMA_VERSION,
)
from chess_coach.infrastructure.llm.validation import (
    validate_chess_claims,
    validate_text,
)
from chess_coach.infrastructure.persistence.coaching_repository import (
    CoachingRepository,
)
from chess_coach.infrastructure.persistence.models import CoachingOutput

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


class CoachingResponse(EvidenceModel):
    job_id: int | None = None
    status: str
    evidence: MoveCoachingEvidence | HistoricalEvidence
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


JobEvidence = MoveCoachingEvidence | HistoricalEvidence | MotifEvidence


def job_evidence(row: CoachingOutput) -> JobEvidence:
    if row.output_type == "motif":
        return MotifEvidence.model_validate(row.evidence_json)
    if row.output_type == "move":
        return MoveCoachingEvidence.model_validate(row.evidence_json)
    return HistoricalEvidence.model_validate(row.evidence_json)


def job_config(evidence: JobEvidence) -> tuple[str, str, str]:
    if isinstance(evidence, MotifEvidence):
        return "motif", MOTIF_PROMPT_VERSION, MOTIF_SCHEMA_VERSION
    kind = "move" if isinstance(evidence, MoveCoachingEvidence) else "historical"
    return kind, MOVE_EXPLANATION_PROMPT_VERSION, OUTPUT_SCHEMA_VERSION


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
    raw: str, evidence: MoveCoachingEvidence | HistoricalEvidence
) -> MoveExplanation | HistoricalExplanation:
    output: MoveExplanation | HistoricalExplanation
    if isinstance(evidence, MoveCoachingEvidence):
        output = MoveExplanation.model_validate_json(raw)
        validate_chess_claims(output, evidence)
    else:
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

    def request(
        self, evidence: MoveCoachingEvidence | HistoricalEvidence, generate: bool
    ) -> CoachingResponse:
        row = self.request_row(evidence, generate)
        return (
            self.response(
                row,
                evidence,
                cached=not generate or row.status in {"done", "insufficient_evidence"},
            )
            if row
            else CoachingResponse(status="not_generated", evidence=evidence)
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
        return self.response(row, evidence)

    @staticmethod
    def response(
        row: CoachingOutput,
        evidence: MoveCoachingEvidence | HistoricalEvidence,
        cached: bool = False,
    ) -> CoachingResponse:
        output = None
        if row.status in {"done", "insufficient_evidence"}:
            try:
                output = validated_output(json.dumps(row.output_json), evidence)
            except ValueError, OperationError:
                raise OperationError(
                    "INVALID_MODEL_OUTPUT",
                    "Stored coaching failed validation; regenerate it.",
                ) from None
        return CoachingResponse(
            job_id=row.id,
            status=row.status,
            evidence=evidence,
            coach=output,
            error_code=row.error_code,
            cached=cached,
            model_digest=row.model_digest,
            attempt_count=row.attempt_count,
            message="Coaching failed. Check Ollama and the local coaching worker, then retry."
            if row.status == "failed"
            else "Start the local coaching worker if this request remains queued."
            if row.status == "queued"
            else None,
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
        return True

    def process(self, row: CoachingOutput) -> None:
        started = perf_counter()
        output: dict[str, object] | None = None
        error: str | None = None
        metrics: dict[str, object] = {}
        try:
            evidence = job_evidence(row)
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
            schema: type[BaseModel]
            if isinstance(evidence, MotifEvidence):
                schema, payload = MotifPrediction, motif_input(evidence)
            else:
                schema = (
                    MoveExplanation
                    if isinstance(evidence, MoveCoachingEvidence)
                    else HistoricalExplanation
                )
                payload = json.dumps(
                    row.evidence_json, sort_keys=True, separators=(",", ":")
                )
            for attempt in range(2):
                self.service.store.attempt(row.id)
                try:
                    raw = self.model.generate(payload, schema)
                    metrics = self.model.metrics
                    validated = (
                        validate_prediction(raw, evidence)
                        if isinstance(evidence, MotifEvidence)
                        else validated_output(raw, evidence)
                    )
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
                except OperationError as exc:
                    error = exc.code
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
        except OperationError as exc:
            error = exc.code
        except ValueError:
            error = "EVIDENCE_INCOMPLETE"
        except SQLAlchemyError:
            logger.exception("coaching_database_error", extra={"run_id": row.id})
            raise
        except Exception:
            logger.exception("coaching_unexpected_failure", extra={"run_id": row.id})
            error = "COACHING_FAILED"
        latency = round((perf_counter() - started) * 1000)
        self.service.store.finish(row.id, output, error, latency, metrics)
        logger.info(
            "coaching_finished",
            extra={
                "run_id": row.id,
                "error_code": error,
                "duration_seconds": latency / 1000,
            },
        )
