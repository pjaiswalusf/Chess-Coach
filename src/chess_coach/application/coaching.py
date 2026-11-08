"""Optional downstream coaching. Deterministic analysis is always read-only here."""

import json
import logging
from time import perf_counter
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from chess_coach.analytics.contracts import AnalyticsReport, ReportStatus, Weakness
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
from chess_coach.infrastructure.llm.client import generation_settings
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


def historical_evidence(report: AnalyticsReport) -> HistoricalEvidence:
    # Category scores are not comparable. Preserve the rank within each category.
    patterns = tuple(
        w.model_copy(update={"source_moves": w.source_moves[:3]})
        for category in ("phase", "opening", "context")
        for w in report.ranked_weaknesses.get(category, ())
    )[:5]
    return HistoricalEvidence(
        report_hash=fingerprint(report.model_dump(mode="json")),
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

    def move(
        self, game: int, ply: int, generate: bool = False, profile: str | None = None
    ) -> CoachingResponse:
        return self.request(self.builder.move(game, ply, profile), generate)

    def history(
        self, report: AnalyticsReport, generate: bool = False
    ) -> CoachingResponse:
        evidence = historical_evidence(report)
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

    def request(
        self, evidence: MoveCoachingEvidence | HistoricalEvidence, generate: bool
    ) -> CoachingResponse:
        payload = evidence.model_dump(mode="json")
        config = generation_settings(self.settings)
        # Retrieval remains available offline. POST resolves the current digest when online.
        previous = self.store.find(
            fingerprint(payload),
            self.settings.ollama_model,
            config,
            MOVE_EXPLANATION_PROMPT_VERSION,
            OUTPUT_SCHEMA_VERSION,
        )
        if not generate:
            return (
                self.response(previous, evidence, cached=True)
                if previous
                else CoachingResponse(status="not_generated", evidence=evidence)
            )
        if previous and previous.status in {"done", "insufficient_evidence"}:
            try:
                self.response(previous, evidence, cached=True)
            except OperationError:
                self.store.invalidate(previous.id)
                previous = None
        health = self.health()
        if health.status != "ready":
            if previous and previous.status in {"done", "insufficient_evidence"}:
                return self.response(previous, evidence, cached=True)
            code = (
                "MODEL_NOT_INSTALLED"
                if health.status == "model_missing"
                else "OLLAMA_UNAVAILABLE"
            )
            raise OperationError(code, health.message, 503)
        assert health.model_digest
        row = self.store.enqueue(
            "move" if isinstance(evidence, MoveCoachingEvidence) else "historical",
            payload,
            self.settings.ollama_model,
            health.model_digest,
            config,
            MOVE_EXPLANATION_PROMPT_VERSION,
            OUTPUT_SCHEMA_VERSION,
        )
        return self.response(
            row, evidence, cached=row.status in {"done", "insufficient_evidence"}
        )

    def job(self, job_id: int) -> CoachingResponse:
        row = self.store.get(job_id)
        evidence = (
            MoveCoachingEvidence.model_validate(row.evidence_json)
            if row.output_type == "move"
            else HistoricalEvidence.model_validate(row.evidence_json)
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

    def process(self, row: CoachingOutput) -> None:
        started = perf_counter()
        output: dict[str, object] | None = None
        error: str | None = None
        try:
            evidence = (
                MoveCoachingEvidence.model_validate(row.evidence_json)
                if row.output_type == "move"
                else HistoricalEvidence.model_validate(row.evidence_json)
            )
            if (
                row.prompt_version != MOVE_EXPLANATION_PROMPT_VERSION
                or row.schema_version != OUTPUT_SCHEMA_VERSION
                or row.generation_json != generation_settings(self.service.settings)
                or row.model_name != self.service.settings.ollama_model
            ):
                raise OperationError(
                    "COACHING_CONFIG_CHANGED",
                    "Request coaching with the current configuration.",
                )
            if (
                isinstance(evidence, MoveCoachingEvidence)
                and self.service.builder.move(
                    evidence.game_id, evidence.ply, evidence.profile_hash
                )
                != evidence
            ):
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
            schema = (
                MoveExplanation if row.output_type == "move" else HistoricalExplanation
            )
            for attempt in range(2):
                self.service.store.attempt(row.id)
                try:
                    raw = self.model.generate(
                        json.dumps(
                            row.evidence_json, sort_keys=True, separators=(",", ":")
                        ),
                        schema,
                    )
                    validated = validated_output(raw, evidence)
                    if (
                        isinstance(evidence, MoveCoachingEvidence)
                        and self.service.builder.move(
                            evidence.game_id, evidence.ply, evidence.profile_hash
                        )
                        != evidence
                    ):
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
        self.service.store.finish(row.id, output, error, latency, self.model.metrics)
        logger.info(
            "coaching_finished",
            extra={
                "run_id": row.id,
                "error_code": error,
                "duration_seconds": latency / 1000,
            },
        )
