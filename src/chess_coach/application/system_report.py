"""Read-only system report with independent dependency failure handling."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from chess_coach.application.system import SystemStatus
from chess_coach.config import Settings


def system_report(
    settings: Settings,
    status: SystemStatus,
    statistics: Callable[[], dict[str, int]],
    worker: Callable[[], dict[str, object]] | None = None,
) -> dict[str, object]:
    try:
        counts = statistics()
        database = "available"
        engine = worker() if worker is not None else {}
    except SQLAlchemyError, OSError:
        logging.getLogger(__name__).exception("system_database_unavailable")
        counts = None
        database = "unavailable"
        engine = {}
    stockfish = "available" if engine.get("available") else status.stockfish.state
    return {
        "status": "unavailable"
        if database != "available"
        else "healthy"
        if stockfish == "available"
        and all(s.state == "available" for s in (status.ollama, status.ollama_model))
        else "degraded",
        "components": {
            "database": {"status": database},
            "stockfish": {"status": stockfish, "version": engine.get("engine_version")},
            "ollama": {"status": status.ollama.state, "model": settings.ollama_model},
        },
        "statistics": counts,
        "checked_at": datetime.now(UTC),
    }
