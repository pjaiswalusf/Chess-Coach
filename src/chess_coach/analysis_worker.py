"""Dedicated local process. Own the kernel lock before engine startup/recovery."""

import logging
import shutil
import signal
from threading import Event, Thread

from sqlalchemy.exc import OperationalError

from chess_coach.application.analysis import AnalysisProcessor, configured_profile
from chess_coach.config import Settings
from chess_coach.infrastructure.analysis_lock import worker_guard
from chess_coach.infrastructure.engine.stockfish_adapter import StockfishAdapter
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
)
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.session import create_session_factory
from chess_coach.infrastructure.system.diagnostics import database_checks
from chess_coach.observability.logging import configure_logging


def run_worker(
    settings: Settings, *, once: bool = False, with_coaching: bool = False
) -> None:
    if with_coaching and settings.llm_keep_alive != "0":
        raise ValueError("Set CHESS_COACH_LLM_KEEP_ALIVE=0 for the combined worker.")
    configure_logging(settings.log_level)
    for check in database_checks(settings.database_path):
        if check.status == "fail":
            logging.getLogger(__name__).error(
                "analysis_worker_unavailable", extra={"error_code": check.code}
            )
            raise SystemExit(f"{check.message} {check.action or ''}")
    stop, pulse_stop = Event(), Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set())
        for sig in (signal.SIGINT, signal.SIGTERM)
    }
    db = create_database_engine(settings.database_url)
    store = AnalysisRepository(create_session_factory(db), settings.database_path)
    try:
        with worker_guard(settings.database_path), StockfishAdapter(settings) as engine:
            profile = configured_profile(settings, engine.engine_name)
            store.register(profile)
            store.recover(profile)
            coaching = None
            if with_coaching:
                from chess_coach.coaching_worker import make_coaching_processor

                coaching = make_coaching_processor(store, settings)
                coaching.service.store.recover()

            def heartbeat() -> None:
                while not pulse_stop.wait(5):
                    try:
                        store.heartbeat()
                    except OperationalError:
                        logging.getLogger(__name__).exception(
                            "heartbeat_database_error"
                        )

            pulse = Thread(target=heartbeat, daemon=True)
            pulse.start()
            try:
                processor = AnalysisProcessor(store, engine, settings, stop)
                failures = 0
                while not stop.is_set():
                    try:
                        if (
                            shutil.disk_usage(
                                settings.database_path.resolve().parent
                            ).free
                            < settings.analysis_min_free_mb * 1024 * 1024
                        ):
                            raise OSError(
                                "DISK_SPACE_LOW: free disk space before restarting worker"
                            )
                        run_id = store.claim(profile)
                        if run_id is not None:
                            processor.process(run_id)
                        elif coaching is not None:
                            row = coaching.service.store.claim()
                            if row is not None:
                                # Keep the same kernel guard, without retaining Stockfish memory
                                # while Ollama loads the model. Restart on the next engine run.
                                engine.close()
                                coaching.process(row)
                        failures = 0
                        if once:
                            break
                        stop.wait(2)
                    except OperationalError:
                        failures += 1
                        if failures >= 3:
                            raise
                        stop.wait(failures)
                        store.recover(profile)
                        if coaching is not None:
                            coaching.service.store.recover()
            finally:
                pulse_stop.set()
                pulse.join(timeout=10)
                store.register(profile, "stopped")
    finally:
        db.dispose()
        for sig, old in previous.items():
            signal.signal(sig, old)


if __name__ == "__main__":
    run_worker(Settings())
