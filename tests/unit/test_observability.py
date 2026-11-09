import json
import logging
from datetime import datetime

from structlog.contextvars import bound_contextvars

from chess_coach.observability.logging import configure_logging
from chess_coach.observability.metrics import (
    cache_hit_rate,
    games_per_hour,
    latency_p50,
    ratio,
)


def test_one_safe_json_event_per_log_after_reconfiguration(capsys):
    configure_logging()
    configure_logging()
    log = logging.getLogger("chess_coach.observability.test")
    with bound_contextvars(request_id="request", run_id="12"):
        try:
            raise ValueError("SECRET_TEST_PROMPT_456")
        except ValueError:
            log.exception(
                "operation_failed",
                extra={
                    "error_code": "TEST_FAILURE",
                    "pgn": "PRIVATE_TEST_USERNAME_123",
                },
            )
    log.info("scope_ended")
    logging.getLogger("chess.engine").warning("SECRET_TEST_PROMPT_456")
    logging.getLogger("httpx").warning("PRIVATE_TEST_USERNAME_123")
    raw = capsys.readouterr().err
    assert "SECRET_TEST_PROMPT_456" not in raw
    assert "PRIVATE_TEST_USERNAME_123" not in raw
    failure, outside = map(json.loads, raw.splitlines())
    assert failure["event"] == "operation_failed"
    assert failure["request_id"] == "request"
    assert failure["run_id"] == "12"
    assert failure["error_type"] == "ValueError"
    assert failure["frames"]
    assert failure["level"] == "error"
    assert failure["timestamp"].endswith("Z")
    assert datetime.fromisoformat(failure["timestamp"]).utcoffset().total_seconds() == 0
    assert "request_id" not in outside
    assert "run_id" not in outside


def test_metrics_formulas_and_missing_samples():
    assert cache_hit_rate(80, 20) == 80
    assert cache_hit_rate(0, 0) is None
    assert ratio(500, 10) == 50
    assert ratio(0, 10) == 0
    assert games_per_hour(60, 1800) == 120
    assert ratio(100 * 2, 100) == 2
    assert latency_p50([]) is None
    assert latency_p50([200, 100, 300, 500]) == 250


def test_unnamed_structlog_emits_json_to_stderr(capsys):
    import structlog

    configure_logging()
    structlog.get_logger().info("diagnostic_smoke_test", component="system")
    event = json.loads(capsys.readouterr().err)
    assert event["event"] == "diagnostic_smoke_test"
    assert event["component"] == "system"
