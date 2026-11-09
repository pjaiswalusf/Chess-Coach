"""Read metrics from existing analysis and coaching records."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from chess_coach.infrastructure.persistence.engine import create_readonly_engine
from chess_coach.infrastructure.persistence.models import AnalysisRun, CoachingOutput
from chess_coach.infrastructure.persistence.session import create_session_factory
from chess_coach.observability.metrics import (
    cache_hit_rate,
    games_per_hour,
    latency_p50,
    ratio,
)

COACHING_WINDOW_DAYS = 7


def system_metrics(path: Path) -> dict[str, object]:
    cutoff = datetime.now(UTC) - timedelta(days=COACHING_WINDOW_DAYS)
    engine = create_readonly_engine(path)
    try:
        with create_session_factory(engine)() as session:
            run = session.scalar(
                select(AnalysisRun)
                .where(AnalysisRun.finished_at.is_not(None))
                .order_by(AnalysisRun.finished_at.desc(), AnalysisRun.id.desc())
                .limit(1)
            )
            elapsed_seconds = (
                (run.finished_at - run.started_at).total_seconds()
                if run is not None and run.started_at and run.finished_at
                else 0
            )
            analysis = (
                None
                if run is None
                else {
                    "run_id": str(run.id),
                    "positions_per_second": ratio(
                        run.positions_analyzed, run.engine_seconds
                    ),
                    "cache_hit_rate": cache_hit_rate(run.cache_hits, run.cache_misses),
                    "duration_ms": run.active_duration_ms,
                    "games_per_hour": games_per_hour(
                        run.games_completed, elapsed_seconds
                    ),
                }
            )
            samples: list[int] = []
            schema_failures = schema_samples = failures = 0
            for data in session.scalars(
                select(CoachingOutput.metrics_json).where(
                    CoachingOutput.updated_at >= cutoff,
                    CoachingOutput.status.in_(
                        ("done", "failed", "insufficient_evidence")
                    ),
                    CoachingOutput.metrics_json.is_not(None),
                )
            ):
                if not data:
                    continue
                duration = data.get("request_duration_ms")
                finished = data.get("generation_finished_at")
                failed = data.get("generation_failed")
                if (
                    type(duration) is not int
                    or duration < 0
                    or not isinstance(finished, str)
                    or finished < cutoff.isoformat()
                    or not isinstance(failed, bool)
                ):
                    continue
                samples.append(duration)
                failures += failed
                first_valid = data.get("first_schema_valid")
                if isinstance(first_valid, bool):
                    schema_samples += 1
                    schema_failures += not first_valid
    finally:
        engine.dispose()
    return {
        "analysis": analysis,
        "coaching": {
            "window_days": COACHING_WINDOW_DAYS,
            "sample_count": len(samples),
            "latency_p50_ms": latency_p50(samples),
            "first_schema_failure_rate": ratio(100 * schema_failures, len(samples)),
            "first_schema_sample_count": schema_samples,
            "final_failure_rate": ratio(100 * failures, len(samples)),
        },
    }
