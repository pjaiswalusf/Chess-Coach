"""Wire application use cases to concrete local integrations."""

from collections.abc import Iterator
from functools import partial
from typing import Annotated

from fastapi import Depends

from chess_coach.application.analysis import AnalysisService
from chess_coach.application.system import SystemStatus, collect_system_status
from chess_coach.config import Settings, get_settings
from chess_coach.infrastructure.system.probes import probe_ollama, probe_stockfish


def get_system_status(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SystemStatus:
    return collect_system_status(
        partial(probe_stockfish, settings), partial(probe_ollama, settings)
    )


def get_analysis_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[AnalysisService]:
    from chess_coach.infrastructure.persistence.analysis_repository import (
        AnalysisRepository,
    )
    from chess_coach.infrastructure.persistence.engine import create_database_engine
    from chess_coach.infrastructure.persistence.session import create_session_factory

    engine = create_database_engine(settings.database_url)
    try:
        yield AnalysisService(
            AnalysisRepository(create_session_factory(engine), settings.database_path)
        )
    finally:
        engine.dispose()
