"""Versioned preliminary support heuristics, not statistical confidence."""

from chess_coach.analytics.contracts import EvidenceStatus, Severity

OVERALL_GAMES = 10
OPENING_GAMES = 10
PHASE_MOVES = 50
PHASE_GAMES = 5
CONTEXT_MOVES = 30
CONTEXT_GAMES = 10
CONVERSION_GAMES = 10
CLOCK_COVERAGE = 0.8
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
    if loss >= 150:
        return Severity.CRITICAL
    if loss >= 80:
        return Severity.SIGNIFICANT
    if loss >= 30:
        return Severity.MINOR
    return Severity.NORMAL
