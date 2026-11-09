"""Shared stderr logging for the API, CLI and durable workers."""

import logging
import os
import re
import sys
from pathlib import Path
from time import perf_counter
from traceback import walk_tb
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars

SAFE_FIELDS = frozenset(
    [
        "request_id",
        "run_id",
        "game_id",
        "puzzle_id",
        "tracked_player_id",
        "ply",
        "component",
        "duration_ms",
        "engine_duration_ms",
        "error_code",
        "error_type",
        "status",
        "http_status",
        "operation",
        "cache_type",
        "cache_hits",
        "cache_misses",
        "game_count",
        "games_inserted",
        "games_existing",
        "games_completed",
        "positions_analyzed",
        "terminal_positions",
        "engine_version",
        "model",
        "schema_valid",
        "attempt_count",
        "next_review_at",
    ]
)
EVENT = re.compile(r"[a-z][a-z0-9_]{0,79}")


def elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


def safe_fields(
    _: Any, __: str, event: structlog.types.EventDict
) -> structlog.types.EventDict:
    record = event["_record"]
    fields = {
        key: str(value) if key.endswith("_id") else value
        for key in SAFE_FIELDS
        if (value := event.get(key, getattr(record, key, None))) is not None
    }
    fields.setdefault("component", record.name.split(".")[-1])
    name = event["event"]
    # Application calls use literal event names and pass data in named fields.
    fields["event"] = name if EVENT.fullmatch(name) else "application_event"
    fields["level"] = record.levelname.lower()
    exception = event.get("exc_info")
    if isinstance(exception, tuple) and exception[0]:
        fields["error_type"] = exception[0].__name__
        fields["frames"] = [
            f"{Path(frame.f_code.co_filename).name}:{line}:{frame.f_code.co_name}"
            for frame, line in walk_tb(exception[2])
        ]
    return fields


class JsonHandler(logging.Handler):
    """Write to the current stderr without retaining a closed capture stream."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            print(self.format(record), file=sys.stderr, flush=True)
        except OSError, ValueError:
            # Logging must not fail the operation or echo an unsanitized LogRecord.
            return


def _logger_factory(name: str = "chess_coach") -> logging.Logger:
    return logging.getLogger(name)


def configure_logging(level: str | None = None) -> None:
    logger = logging.getLogger("chess_coach")
    selected = (level or os.environ.get("CHESS_COACH_LOG_LEVEL") or "INFO").upper()
    logger.setLevel(logging.getLevelNamesMapping().get(selected, logging.INFO))
    logger.propagate = False
    for handler in tuple(logger.handlers):
        if isinstance(handler, JsonHandler):
            logger.removeHandler(handler)
            handler.close()
    handler = JsonHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            use_get_message=False,
            processors=[
                merge_contextvars,
                safe_fields,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.processors.JSONRenderer(default=str),
            ],
        )
    )
    logger.addHandler(handler)
    for name in ("chess.engine", "httpx", "httpcore"):
        # These libraries can emit raw board positions, engine output and URLs.
        transport_logger = logging.getLogger(name)
        transport_logger.handlers[:] = [logging.NullHandler()]
        transport_logger.propagate = False
    structlog.configure(
        processors=[structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=_logger_factory,
        wrapper_class=structlog.stdlib.BoundLogger,
    )
