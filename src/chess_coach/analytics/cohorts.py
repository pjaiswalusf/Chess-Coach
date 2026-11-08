"""Selection policy shared by adapters and pure fixture tests."""

from chess_coach.analytics.contracts import AnalyticsRequest, GameEvidence, WindowType

LIMITS = {WindowType.LAST_20: 20, WindowType.LAST_50: 50, WindowType.LAST_100: 100}


def select_cohort(
    games: tuple[GameEvidence, ...], request: AnalyticsRequest
) -> tuple[GameEvidence, ...]:
    eligible = [
        g
        for g in games
        if (request.color is None or g.color == request.color)
        and (request.time_class is None or g.time_class == request.time_class)
        and (request.start_date is None or g.played_at >= request.start_date)
        and (request.end_date is None or g.played_at < request.end_date)
    ]
    eligible.sort(key=lambda g: (g.played_at, g.game_id), reverse=True)
    return tuple(eligible[: LIMITS.get(request.window)])
