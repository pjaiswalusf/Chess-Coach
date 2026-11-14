"""Read-only system report with independent dependency failure handling."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from chess_coach.application.system import SystemStatus
from chess_coach.config import Settings
from chess_coach.domain.analysis import ANALYSIS_VERSION


def system_report(
    settings: Settings,
    status: SystemStatus,
    statistics: Callable[[], dict[str, int]] | None,
    worker: Callable[[], dict[str, object]] | None = None,
    training: Callable[[], tuple[int, int, bool]] | None = None,
) -> dict[str, object]:
    try:
        counts = statistics() if statistics else None
        database = "available" if counts is not None else "unavailable"
        engine = worker() if worker is not None else {}
    except SQLAlchemyError, OSError:
        logging.getLogger(__name__).exception("system_database_unavailable")
        counts = None
        database = "unavailable"
        engine = {}
    stockfish = status.stockfish.state
    training_status: dict[str, object] | None = None
    if training is not None:
        try:
            total, due, worker_owns_engine = training()
        except SQLAlchemyError, OSError:
            logging.getLogger(__name__).exception("training_database_unavailable")
            training_status = {
                "practice_status": "unavailable",
                "generation_status": "unavailable",
                "detail": "Check database access and run uv run alembic upgrade head.",
            }
        else:
            if stockfish == "unavailable":
                generation_status = "unavailable"
                detail = "Install Stockfish to generate new puzzles."
            elif worker_owns_engine or (counts and counts.get("active_analysis_runs")):
                generation_status = "busy"
                detail = "The local analysis worker scans newly analyzed games for puzzles automatically."
            else:
                generation_status = "verify_with_cli"
                detail = "Start the local analysis worker to process queued analysis and puzzle scans."
            training_status = {
                "practice_status": "ready",
                "generation_status": generation_status,
                "detail": detail,
                "puzzles_total": total,
                "puzzles_due": due,
            }
    return {
        "status": "unavailable"
        if database != "available"
        else "healthy"
        if stockfish == "available"
        and all(s.state == "available" for s in (status.ollama, status.ollama_model))
        else "degraded",
        "components": {
            "database": {"status": database},
            "chesscom": {"status": "not_checked"},
            "stockfish": {"status": stockfish, "version": engine.get("engine_version")},
            "ollama": {
                "status": status.ollama.state,
                "model": settings.ollama_model,
                "model_status": status.ollama_model.state,
            },
        },
        "statistics": counts,
        "training": training_status,
        "checked_at": datetime.now(UTC),
        "analysis_version": ANALYSIS_VERSION,
    }
