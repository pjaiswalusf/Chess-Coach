"""Integrity, completeness and availability are independent health dimensions."""

from collections import Counter
from math import isfinite

from chess_coach.analytics.contracts import (
    AnalyticsHealthReport,
    Diagnostic,
    EvidenceDataset,
)
from chess_coach.analytics.metrics import player_moves
from chess_coach.analytics.sample_policy import CLOCK_COVERAGE, severity


def check_analytics_health(dataset: EvidenceDataset) -> AnalyticsHealthReport:
    games = dataset.games
    errors = list(dataset.errors)
    warnings = list(dataset.warnings)
    seen_games = set()
    for g in games:
        if g.game_id in seen_games:
            errors.append(Diagnostic(code="DUPLICATE_GAME", game_id=g.game_id))
        seen_games.add(g.game_id)
        seen = set()
        if g.analysis_status == "done" and len(g.moves) != g.expected_player_moves:
            errors.append(Diagnostic(code="MISSING_MOVE_ANALYSIS", game_id=g.game_id))
        for m in g.moves:
            if m.ply in seen:
                errors.append(
                    Diagnostic(code="DUPLICATE_MOVE_ANALYSIS", game_id=g.game_id)
                )
            seen.add(m.ply)
            if m.loss_cp is not None and (not isfinite(m.loss_cp) or m.loss_cp < 0):
                errors.append(Diagnostic(code="INVALID_LOSS", game_id=g.game_id))
            elif m.severity != severity(m.loss_cp):
                errors.append(
                    Diagnostic(code="SEVERITY_POLICY_MISMATCH", game_id=g.game_id)
                )
            if m.game_id != g.game_id or m.mover != g.color:
                errors.append(
                    Diagnostic(code="PLAYER_ATTRIBUTION_INVALID", game_id=g.game_id)
                )
    moves = player_moves(games)
    expected = sum(g.expected_player_moves for g in games)
    complete = sum(g.analysis_status == "done" for g in games)
    clocks = sum(m.under_time_pressure is not None for m in moves)
    if complete < len(games):
        warnings.append(Diagnostic(code="ANALYSIS_PARTIAL"))
    if not moves or clocks / len(moves) < CLOCK_COVERAGE:
        warnings.append(Diagnostic(code="CLOCK_DATA_LIMITED"))
    if any(g.eco == "UNKNOWN" for g in games):
        warnings.append(Diagnostic(code="OPENING_UNKNOWN"))
    if not dataset.database_integrity:
        errors.append(Diagnostic(code="DATABASE_INTEGRITY_FAILED"))
    if not dataset.foreign_keys:
        errors.append(Diagnostic(code="FOREIGN_KEY_FAILED"))
    return AnalyticsHealthReport(
        integrity="FAIL" if errors else "PASS",
        database_integrity=dataset.database_integrity,
        foreign_keys=dataset.foreign_keys,
        selected_games=len(games),
        analyzed_games=complete,
        analysis_coverage=complete / len(games) if games else None,
        statuses=dict(sorted(Counter(g.analysis_status for g in games).items())),
        selected_player_moves=expected,
        analyzed_player_moves=len(moves),
        move_evidence_coverage=len(moves) / expected if expected else None,
        clock_data_coverage=clocks / len(moves) if moves else None,
        opening_data_coverage=sum(g.eco != "UNKNOWN" for g in games) / len(games)
        if games
        else None,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )
