"""Durable single local coaching consumer, using the existing kernel worker guard."""

import signal
from functools import partial
from threading import Event

from chess_coach.application.coaching import CoachingProcessor, CoachingService
from chess_coach.config import Settings
from chess_coach.infrastructure.analysis_lock import WorkerAlreadyRunning, worker_guard
from chess_coach.infrastructure.llm.client import OllamaCoach
from chess_coach.infrastructure.llm.health import check_health
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
)
from chess_coach.infrastructure.persistence.coaching_repository import (
    CoachingRepository,
)
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.query_repository import QueryRepository
from chess_coach.infrastructure.persistence.session import create_session_factory
from chess_coach.observability.logging import configure_logging


def make_coaching_processor(
    analysis: AnalysisRepository, settings: Settings
) -> CoachingProcessor:
    store = CoachingRepository(QueryRepository(analysis.sessions, analysis))
    service = CoachingService(store, settings, partial(check_health, settings))
    return CoachingProcessor(service, OllamaCoach(settings))


def run_coaching_worker(settings: Settings, *, once: bool = False) -> None:
    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set())
        for sig in (signal.SIGINT, signal.SIGTERM)
    }
    db = create_database_engine(settings.database_url)
    processor = make_coaching_processor(
        AnalysisRepository(create_session_factory(db), settings.database_path), settings
    )
    store = processor.service.store
    configure_logging(settings.log_level)
    try:
        # Separate consumer, same SQLite queue/OS-lock pattern. Holding this guard also
        # excludes Stockfish work, so the two memory-heavy workloads cannot overlap.
        with worker_guard(settings.database_path):
            store.recover()
            while not stop.is_set():
                row = store.claim()
                if row:
                    processor.process(row)
                if once:
                    break
                stop.wait(2)
    except WorkerAlreadyRunning:
        raise ValueError(
            "Stop the analysis worker before starting the coaching worker."
        ) from None
    finally:
        db.dispose()
        for sig, old in previous.items():
            signal.signal(sig, old)
