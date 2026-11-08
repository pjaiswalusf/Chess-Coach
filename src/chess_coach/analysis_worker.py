"""Dedicated local process. Own the kernel lock before engine startup/recovery."""

import json
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


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, object] = {
            "event": record.getMessage(),
            "level": record.levelname,
        }
        for name in (
            "run_id",
            "game_id",
            "error_code",
            "operation",
            "duration_seconds",
        ):
            if hasattr(record, name):
                data[name] = getattr(record, name)
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data)


def run_worker(settings: Settings, *, once: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.getLogger("chess_coach").addHandler(handler)
    logging.getLogger("chess_coach").setLevel(settings.log_level)
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
            finally:
                pulse_stop.set()
                pulse.join(timeout=10)
                store.register(profile, "stopped")
    finally:
        db.dispose()
        for sig, old in previous.items():
            signal.signal(sig, old)
        logging.getLogger("chess_coach").removeHandler(handler)


if __name__ == "__main__":
    run_worker(Settings())
