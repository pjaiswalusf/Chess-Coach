from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from chess_coach.analytics.cohorts import select_cohort
from chess_coach.analytics.contracts import AnalyticsRequest, WindowType


def request(**kwargs):
    return AnalyticsRequest(player_id=1, profile_hash="fixture", **kwargs)


@pytest.mark.parametrize(
    "window,n", [("last_20", 20), ("last_50", 50), ("last_100", 100), ("all", 105)]
)
def test_windows_and_pending_membership(factory, window, n):
    games = tuple(
        factory(i, status="pending" if i > 103 else "done") for i in range(1, 106)
    )
    selected = select_cohort(games, request(window=window))
    assert [g.game_id for g in selected] == list(range(105, 105 - n, -1))
    assert len([g for g in selected if g.analysis_status == "pending"]) == 2


def test_partial_twenty_fixture(factory):
    games = tuple(
        factory(i, status="pending" if i >= 24 else "done") for i in range(1, 26)
    )
    selected = select_cohort(games, request(window="last_20"))
    assert [g.game_id for g in selected] == list(range(25, 5, -1))
    assert sum(g.analysis_status == "done" for g in selected) == 18


def test_date_boundaries_filters_and_ties(factory):
    start = datetime(2026, 1, 2, tzinfo=UTC)
    end = start + timedelta(days=2)
    selected = select_cohort(
        tuple(factory(i) for i in range(1, 5)),
        request(window=WindowType.DATE_RANGE, start_date=start, end_date=end),
    )
    assert [g.game_id for g in selected] == [2, 1]
    games = tuple(
        factory(i).model_copy(update={"played_at": start}) for i in range(1, 4)
    )
    assert [g.game_id for g in select_cohort(games, request())] == [3, 2, 1]
    assert select_cohort(games, request(color="black")) == ()
    assert select_cohort(games, request(time_class="rapid")) == ()


@pytest.mark.parametrize(
    "fields",
    [
        {"window": "bad"},
        {"window": "date_range"},
        {"window": "date_range", "start_date": "2026-01-01", "end_date": "2026-01-02"},
        {
            "window": "date_range",
            "start_date": "2026-01-02T00:00:00Z",
            "end_date": "2026-01-01T00:00:00Z",
        },
        {"start_date": "2026-01-01T00:00:00Z"},
    ],
)
def test_invalid_request(fields):
    with pytest.raises(ValidationError):
        request(**fields)


def test_offset_dates_normalized():
    r = request(
        window="date_range",
        start_date="2026-01-01T05:30:00+05:30",
        end_date="2026-01-02T05:30:00+05:30",
    )
    assert r.start_date == datetime(2026, 1, 1, tzinfo=UTC)
