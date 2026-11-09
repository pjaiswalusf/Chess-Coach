"""One read-only orchestration path; adapters supply a consistent evidence snapshot."""

import logging
from time import perf_counter
from typing import Protocol

from chess_coach.analytics import patterns
from chess_coach.analytics.contracts import (
    AnalyticsReport,
    AnalyticsRequest,
    EvidenceDataset,
    ReportStatus,
)
from chess_coach.analytics.health import check_analytics_health
from chess_coach.analytics.metrics import summarize
from chess_coach.analytics.sample_policy import OVERALL_GAMES
from chess_coach.analytics.trends import recent_trends

logger = logging.getLogger(__name__)


class AnalyticsSource(Protocol):
    def load(self, request: AnalyticsRequest) -> EvidenceDataset: ...


class AnalyticsService:
    def __init__(self, repository: AnalyticsSource):
        self.repository = repository

    def build_report(self, request: AnalyticsRequest) -> AnalyticsReport:
        request = AnalyticsRequest.model_validate(request.model_dump())
        start = perf_counter()
        dataset = self.repository.load(request)
        loaded = perf_counter()
        health = check_analytics_health(dataset)
        games = dataset.games
        if health.integrity == "FAIL":
            return AnalyticsReport(
                request=request,
                status=ReportStatus.DATA_ERROR,
                selected_game_ids=tuple(g.game_id for g in games),
                health=health,
            )
        status = (
            ReportStatus.NO_GAMES
            if not games
            else ReportStatus.PARTIAL
            if health.analyzed_games < len(games)
            else ReportStatus.INSUFFICIENT_DATA
            if len(games) < OVERALL_GAMES
            else ReportStatus.COMPLETE
        )
        validated = perf_counter()
        overall = summarize(games)
        phase = patterns.segments(games, "phase")
        color = patterns.segments(games, "color")
        time_control = patterns.segments(games, "time_control")
        opening = patterns.segments(games, "eco")
        behavioral = patterns.contexts(games, health.clock_data_coverage)
        advantage = patterns.advantages(games)
        aggregated = perf_counter()
        rankings = (
            patterns.rank_candidates(games, phase, opening, behavioral)
            if status == ReportStatus.COMPLETE
            else {}
        )
        ranked = perf_counter()
        report = AnalyticsReport(
            request=request,
            status=status,
            selected_game_ids=tuple(g.game_id for g in games),
            health=health,
            analyzed_move_refs=tuple(
                sorted((m.game_id, m.ply) for g in games for m in g.moves)
            ),
            overall=overall,
            phase_metrics=phase,
            color_metrics=color,
            time_control_metrics=time_control,
            opening_metrics=opening,
            behavioral_metrics=behavioral,
            advantage_metrics=advantage,
            recent_trends=recent_trends(games),
            castling_metrics=patterns.castling(games),
            ranked_weaknesses=rankings,
        )
        logger.info(
            "analytics_report",
            extra={
                "player_id": request.player_id,
                "selected_games": len(games),
                "retrieval_seconds": dataset.retrieval_seconds or loaded - start,
                "validation_seconds": dataset.validation_seconds + validated - loaded,
                "aggregation_seconds": aggregated - validated,
                "ranking_seconds": ranked - aggregated,
                "total_seconds": perf_counter() - start,
                "report_status": status.value,
            },
        )
        return report
