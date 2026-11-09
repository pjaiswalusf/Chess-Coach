"""Wire application use cases to concrete local integrations."""

from collections.abc import Callable, Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from threading import Lock
from time import monotonic
from typing import Annotated

import httpx
from fastapi import Depends
from sqlalchemy import Engine

from chess_coach.analytics.service import AnalyticsService
from chess_coach.api.schemas.contracts import SystemResponse
from chess_coach.api.schemas.system import ComponentHealth, SystemMetrics
from chess_coach.application.analysis import AnalysisService
from chess_coach.application.coaching import CoachingService
from chess_coach.application.errors import OperationError
from chess_coach.application.jobs import JobService
from chess_coach.application.queries import QueryService
from chess_coach.application.system import (
    CheckResult,
    SystemStatus,
    collect_system_status,
    overall_status,
)
from chess_coach.application.training import TrainingService, practice_counts
from chess_coach.config import Settings, get_settings
from chess_coach.domain.coaching_models import LLMHealth
from chess_coach.infrastructure.analysis_lock import worker_is_locked
from chess_coach.infrastructure.chesscom.client import ChessComClient
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
)
from chess_coach.infrastructure.persistence.analytics_repository import (
    AnalyticsRepository,
)
from chess_coach.infrastructure.persistence.engine import (
    create_database_engine,
    create_readonly_engine,
)
from chess_coach.infrastructure.persistence.query_repository import QueryRepository
from chess_coach.infrastructure.persistence.session import create_session_factory
from chess_coach.infrastructure.persistence.sync_repository import SyncRepository
from chess_coach.infrastructure.persistence.system_metrics import system_metrics
from chess_coach.infrastructure.persistence.training_repository import (
    TrainingRepository,
)
from chess_coach.infrastructure.system.diagnostics import (
    core_checks,
    database_checks,
    diagnose,
    require_current_database,
)
from chess_coach.infrastructure.system.probes import probe_ollama, probe_stockfish

_probe_lock = Lock()
_probe_cache: tuple[tuple[str, str, str], float, SystemStatus] | None = None


def get_system_status(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SystemStatus:
    global _probe_cache
    key = (
        settings.stockfish_executable,
        str(settings.ollama_host),
        settings.ollama_model,
    )
    with _probe_lock:
        if _probe_cache and _probe_cache[0] == key and monotonic() < _probe_cache[1]:
            return _probe_cache[2]
        status = collect_system_status(
            partial(probe_stockfish, settings), partial(probe_ollama, settings)
        )
        _probe_cache = key, monotonic() + 5, status
        return status


def get_readiness_failure() -> str | None:
    _, checks = core_checks(get_settings)
    return next(
        (check.code for check in checks if check.required and check.status == "fail"),
        None,
    )


def _open_database(settings: Settings) -> Engine:
    try:
        return create_database_engine(settings.database_url)
    except OSError as exc:
        raise OperationError(
            "DATABASE_UNAVAILABLE",
            "Check access to the configured database directory.",
            503,
        ) from exc


def get_analysis_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[AnalysisService]:
    engine = _open_database(settings)
    try:
        yield AnalysisService(
            AnalysisRepository(create_session_factory(engine), settings.database_path)
        )
    finally:
        engine.dispose()


def get_chesscom_verifier() -> Callable[[str], str]:
    def verify(username: str) -> str:
        with ChessComClient(timeout=httpx.Timeout(3.0), attempts=1) as client:
            return client.get_player(username)

    return verify


def get_query_service(
    settings: Annotated[Settings, Depends(get_settings)],
    verify_player: Annotated[Callable[[str], str], Depends(get_chesscom_verifier)],
) -> Iterator[QueryService]:
    engine = _open_database(settings)
    sessions = create_session_factory(engine)
    try:
        yield QueryService(
            QueryRepository(
                sessions, AnalysisRepository(sessions, settings.database_path)
            ),
            AnalyticsService(AnalyticsRepository(sessions)),
            verify_player,
        )
    finally:
        engine.dispose()


def get_job_service(
    settings: Annotated[Settings, Depends(get_settings)],
    queries: Annotated[QueryService, Depends(get_query_service)],
) -> JobService:
    return JobService(
        queries.store,
        SyncRepository(queries.store.sessions, settings.database_path),
    )


def get_system_report(
    settings: Annotated[Settings, Depends(get_settings)],
    status: Annotated[SystemStatus, Depends(get_system_status)],
) -> dict[str, object]:
    from chess_coach.application.system_report import system_report

    def statistics() -> dict[str, int]:
        engine = create_readonly_engine(settings.database_path)
        try:
            sessions = create_session_factory(engine)
            return QueryRepository(
                sessions, AnalysisRepository(sessions, settings.database_path)
            ).statistics()
        finally:
            engine.dispose()

    def worker() -> dict[str, object]:
        engine = create_readonly_engine(settings.database_path)
        try:
            return AnalysisRepository(
                create_session_factory(engine), settings.database_path
            ).worker_status()
        finally:
            engine.dispose()

    def training() -> tuple[int, int, bool]:
        engine = create_readonly_engine(settings.database_path)
        try:
            total, due = practice_counts(
                TrainingRepository(create_session_factory(engine))
            )
            return total, due, worker_is_locked(settings.database_path)
        finally:
            engine.dispose()

    if any(check.status == "fail" for check in database_checks(settings.database_path)):
        return system_report(settings, status, None)
    return system_report(settings, status, statistics, worker, training)


def get_coaching_service(
    settings: Annotated[Settings, Depends(get_settings)],
    queries: Annotated[QueryService, Depends(get_query_service)],
) -> CoachingService:
    from chess_coach.application.coaching import CoachingService
    from chess_coach.infrastructure.llm.health import check_health
    from chess_coach.infrastructure.persistence.coaching_repository import (
        CoachingRepository,
    )

    return CoachingService(
        CoachingRepository(queries.store), settings, partial(check_health, settings)
    )


def get_llm_health(settings: Annotated[Settings, Depends(get_settings)]) -> LLMHealth:
    from chess_coach.infrastructure.llm.health import check_health

    return check_health(settings)


def get_training_service(
    queries: Annotated[QueryService, Depends(get_query_service)],
) -> TrainingService:
    return TrainingService(TrainingRepository(queries.store.sessions))


def get_component_health() -> ComponentHealth:
    optional: SystemStatus | None = None

    def probe(settings: Settings) -> SystemStatus:
        nonlocal optional
        optional = collect_system_status(
            partial(probe_stockfish, settings), partial(probe_ollama, settings)
        )
        return optional

    checks = diagnose(get_settings, probe_optional=probe)
    status = overall_status(checks)
    report = None
    model = None
    if optional is not None:
        settings = get_settings()
        model = settings.ollama_model
    if optional is not None and status != "unavailable":
        report = SystemResponse.model_validate(get_system_report(settings, optional))
        if report.status == "unavailable":
            checks = [
                CheckResult(
                    "database",
                    "fail",
                    True,
                    "Application data could not be read.",
                    "Check database access and retry.",
                    "DATABASE_UNAVAILABLE",
                )
                if check.name == "database"
                else check
                for check in checks
            ]
            status = "unavailable"
    return ComponentHealth.model_validate(
        {
            "overall": status,
            "components": {check.name: asdict(check) for check in checks},
            "checked_at": datetime.now(UTC),
            "statistics": report.statistics if report else None,
            "training": report.training if report else None,
            "analysis_version": report.analysis_version if report else None,
            "engine_version": report.components.stockfish.version if report else None,
            "model": model,
        }
    )


def get_system_metrics(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SystemMetrics:
    require_current_database(settings.database_path)
    return SystemMetrics.model_validate(system_metrics(settings.database_path))
