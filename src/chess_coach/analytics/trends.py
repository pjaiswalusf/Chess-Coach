"""Descriptive comparisons within the same color and exact clock control."""

from collections import defaultdict

from chess_coach.analytics.contracts import GameEvidence, RecentTrend, TrendPeriod
from chess_coach.analytics.metrics import move_metrics, player_moves
from chess_coach.domain.game_records import PlayerColor

GAMES_PER_PERIOD = 10
MIN_CLASSIFIABLE_MOVES = 50


def recent_trends(games: tuple[GameEvidence, ...]) -> tuple[RecentTrend, ...]:
    grouped: dict[tuple[PlayerColor, str, str], list[GameEvidence]] = defaultdict(list)
    for game in sorted(games, key=lambda g: (g.played_at, g.game_id), reverse=True):
        if game.time_class in {
            "bullet",
            "blitz",
            "rapid",
            "daily",
        } and game.time_control.strip().lower() not in {"", "-", "?", "unknown"}:
            grouped[game.color, game.time_class, game.time_control].append(game)

    def period(group: tuple[GameEvidence, ...]) -> TrendPeriod | None:
        if len(group) != GAMES_PER_PERIOD or any(
            g.analysis_status != "done"
            or not any(m.severity is not None for m in g.moves)
            for g in group
        ):
            return None
        errors = move_metrics(player_moves(group)).critical
        if errors.denominator < MIN_CLASSIFIABLE_MOVES:
            return None
        return TrendPeriod(
            first_game_at=group[-1].played_at,
            last_game_at=group[0].played_at,
            game_ids=tuple(g.game_id for g in group),
            critical=errors,
        )

    output = []
    for (color, time_class, time_control), group in sorted(grouped.items()):
        recent = period(tuple(group[:GAMES_PER_PERIOD]))
        earlier = period(tuple(group[GAMES_PER_PERIOD : 2 * GAMES_PER_PERIOD]))
        if earlier and recent:
            # Compare exact rate ratios without rounding to display precision.
            before = earlier.critical.numerator * recent.critical.denominator
            after = recent.critical.numerator * earlier.critical.denominator
            output.append(
                RecentTrend(
                    color=color,
                    time_class=time_class,
                    time_control=time_control,
                    earlier=earlier,
                    recent=recent,
                    direction="lower"
                    if after < before
                    else "higher"
                    if after > before
                    else "unchanged",
                )
            )
    return tuple(output)
