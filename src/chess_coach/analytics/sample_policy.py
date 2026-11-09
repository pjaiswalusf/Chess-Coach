"""Versioned preliminary support heuristics, not statistical confidence."""

from chess_coach.analytics.contracts import (
    AnalyticsReport,
    EvidenceStatus,
    ReportStatus,
    Severity,
)

OVERALL_GAMES = 10
OPENING_GAMES = 10
PHASE_MOVES = 50
PHASE_GAMES = 5
CONTEXT_MOVES = 30
CONTEXT_GAMES = 10
CONVERSION_GAMES = 10
CONVERSION_STRENGTH_MIN_PERCENT = 80
CLOCK_COVERAGE = 0.8
CRITICAL_LOSS_CP = 150
ADVANTAGE_CP = 150
COLLAPSE_CP = 50


def support(moves: int, games: int, min_moves: int, min_games: int) -> EvidenceStatus:
    if not moves or not games:
        return EvidenceStatus.UNAVAILABLE
    return (
        EvidenceStatus.SUFFICIENT
        if moves >= min_moves and games >= min_games
        else EvidenceStatus.INSUFFICIENT
    )


def severity(loss: float | None) -> Severity | None:
    """CP-only categories; mate transitions remain unclassifiable in V1."""
    if loss is None:
        return None
    if loss >= CRITICAL_LOSS_CP:
        return Severity.CRITICAL
    if loss >= 80:
        return Severity.SIGNIFICANT
    if loss >= 30:
        return Severity.MINOR
    return Severity.NORMAL


def has_conversion_strength(report: AnalyticsReport | None) -> bool:
    if (
        report is None
        or report.status != ReportStatus.COMPLETE
        or not report.advantage_metrics
    ):
        return False
    conversion = report.advantage_metrics.conversion
    return (
        conversion.evidence_status == EvidenceStatus.SUFFICIENT
        and conversion.wins.per_100 is not None
        and conversion.wins.per_100 >= CONVERSION_STRENGTH_MIN_PERCENT
    )
