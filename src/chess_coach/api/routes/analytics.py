"""Fixed report projections; all chess metrics come from AnalyticsService."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from chess_coach.analytics.contracts import ReportStatus, coaching_report_hash
from chess_coach.analytics.sample_policy import has_conversion_strength
from chess_coach.api.dependencies import get_query_service
from chess_coach.api.schemas.contracts import (
    AnalyticsFilters,
    OverviewResponse,
    PatternsResponse,
    SegmentsResponse,
    SummaryResponse,
)
from chess_coach.application.queries import QueryService

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])
Service = Annotated[QueryService, Depends(get_query_service)]
Filters = Annotated[AnalyticsFilters, Query()]


def projection(
    service: QueryService, filters: AnalyticsFilters, section: str
) -> dict[str, object]:
    report = service.report(
        filters.window, filters.color, filters.time_class, filters.profile_hash
    )
    common: dict[str, object] = {
        "filters": filters,
        "profile_hash": report.request.profile_hash
        if report and report.request.profile_hash != "unavailable"
        else None,
        "status": report.status if report else ReportStatus.NO_GAMES,
        "selected_game_ids": report.selected_game_ids if report else (),
        "health": report.health if report else None,
    }
    if section == "summary":
        return common | {"metrics": report.overall if report else None}
    conversion = (
        report.advantage_metrics.conversion
        if report and report.advantage_metrics
        else None
    )
    progress = {
        "conversion": conversion,
        "conversion_strength": has_conversion_strength(report),
        "recent_trends": report.recent_trends if report else (),
    }
    if section == "overview":
        return (
            common
            | progress
            | {
                "metrics": report.overall if report else None,
                "phases": report.phase_metrics if report else (),
                "openings": report.opening_metrics if report else (),
                "patterns": report.ranked_weaknesses if report else {},
            }
        )
    if section == "patterns":
        return (
            common
            | progress
            | {
                "patterns": report.ranked_weaknesses if report else {},
                "contexts": report.behavioral_metrics if report else (),
                "report_hash": coaching_report_hash(report) if report else None,
                "priority": service.coach_priority(report),
            }
        )
    return common | {
        "items": (
            report.opening_metrics if section == "openings" else report.phase_metrics
        )
        if report
        else ()
    }


@router.get(
    "/overview",
    response_model=OverviewResponse,
    summary="Read one consistent analytics snapshot for the dashboard",
)
def overview(service: Service, filters: Filters) -> dict[str, object]:
    return projection(service, filters, "overview")


@router.get(
    "/summary",
    response_model=SummaryResponse,
    summary="Read deterministic results, loss metrics, and coverage",
)
def summary(service: Service, filters: Filters) -> dict[str, object]:
    return projection(service, filters, "summary")


@router.get(
    "/openings",
    response_model=SegmentsResponse,
    summary="Read opening cohorts and evidence sufficiency",
)
def openings(service: Service, filters: Filters) -> dict[str, object]:
    return projection(service, filters, "openings")


@router.get(
    "/phases",
    response_model=SegmentsResponse,
    summary="Read persisted phase evidence aggregates",
)
def phases(service: Service, filters: Filters) -> dict[str, object]:
    return projection(service, filters, "phases")


@router.get(
    "/patterns",
    response_model=PatternsResponse,
    summary="Read ranked weaknesses and source move references",
)
def patterns(service: Service, filters: Filters) -> dict[str, object]:
    return projection(service, filters, "patterns")
