"""Wire application use cases to concrete local integrations."""

import shutil
from collections.abc import Iterator
from functools import partial
from typing import Annotated

from fastapi import Depends

from chess_coach.analytics.service import AnalyticsService
from chess_coach.application.analysis import AnalysisService
from chess_coach.application.jobs import JobService
from chess_coach.application.queries import QueryService
from chess_coach.application.system import (
    DependencyStatus,
    SystemStatus,
    collect_system_status,
)
from chess_coach.config import Settings, get_settings
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
)
from chess_coach.infrastructure.persistence.analytics_repository import (
    AnalyticsRepository,
)
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.query_repository import QueryRepository
from chess_coach.infrastructure.persistence.session import create_session_factory
from chess_coach.infrastructure.persistence.sync_repository import SyncRepository
from chess_coach.infrastructure.system.probes import probe_ollama


def get_system_status(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SystemStatus:
    return collect_system_status(
        lambda: (
            DependencyStatus(
                "unknown",
                "Executable found; run the analysis worker for verified engine readiness.",
            )
            if shutil.which(settings.stockfish_executable)
            else DependencyStatus(
                "unavailable", "Install Stockfish or configure its executable."
            )
        ),
        partial(probe_ollama, settings),
    )


def get_analysis_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[AnalysisService]:
    engine = create_database_engine(settings.database_url)
    try:
        yield AnalysisService(
            AnalysisRepository(create_session_factory(engine), settings.database_path)
        )
    finally:
        engine.dispose()


def get_query_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[QueryService]:
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        yield QueryService(
            QueryRepository(
                sessions, AnalysisRepository(sessions, settings.database_path)
            ),
            AnalyticsService(AnalyticsRepository(sessions)),
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
        engine = create_database_engine(settings.database_url, timeout_seconds=0.25)
        try:
            sessions = create_session_factory(engine)
            return QueryRepository(
                sessions, AnalysisRepository(sessions, settings.database_path)
            ).statistics()
        finally:
            engine.dispose()

    def worker() -> dict[str, object]:
        engine = create_database_engine(settings.database_url, timeout_seconds=0.25)
        try:
            return AnalysisRepository(create_session_factory(engine), settings.database_path).worker_status()
        finally:
            engine.dispose()

    return system_report(settings, status, statistics, worker)
