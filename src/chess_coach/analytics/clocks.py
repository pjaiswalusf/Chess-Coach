"""Own-clock state, explicit elapsed priority, and conservative missing values."""

import math
from dataclasses import dataclass

from chess_coach.analytics.feature_config import DEFAULT_CONFIG, FeatureConfig
from chess_coach.domain.game_records import ParsedGame, ParsedMove, PlayerColor


def valid_seconds(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) and value >= 0 else None


@dataclass
class ClockState:
    previous: dict[PlayerColor, float | None]
    base: float | None
    increment: float | None

    @classmethod
    def for_game(cls, game: ParsedGame) -> ClockState:
        base = valid_seconds(game.time_control.base_seconds)
        increment = valid_seconds(game.time_control.increment_seconds)
        return cls(
            {
                c: None
                if game.history_before_start_unknown
                or not any(
                    m.mover_color == c and m.clock_after_seconds is not None
                    for m in game.moves[:2]
                )
                else base
                for c in PlayerColor
            },
            base,
            increment,
        )

    def observe(
        self, move: ParsedMove, config: FeatureConfig = DEFAULT_CONFIG
    ) -> dict[str, object]:
        before = self.previous[move.mover_color]
        after = valid_seconds(move.clock_after_seconds)
        explicit = (
            valid_seconds(move.elapsed_seconds)
            if move.elapsed_source == "recorded"
            else None
        )
        diagnostics = []
        derived = None
        if before is not None and after is not None and self.increment is not None:
            derived = valid_seconds(before + self.increment - after)
            if derived is None:
                diagnostics.append("clock_inconsistent")
        if move.clock_after_seconds is not None and after is None:
            diagnostics.append("clock_invalid")
        used = explicit if explicit is not None else derived
        source = (
            "recorded"
            if explicit is not None
            else "estimated"
            if derived is not None
            else "unknown"
        )
        self.previous[move.mover_color] = after
        # V1 fast policy supports simple blitz/rapid controls by estimated duration.
        supported = (
            self.base is not None
            and self.increment is not None
            and 180 <= self.base + 40 * self.increment < 3600
        )
        quick = used <= config.fast_seconds if used is not None and supported else None
        pressure = (
            before <= max(config.pressure_seconds, config.pressure_fraction * self.base)
            if before is not None
            and self.base is not None
            and self.increment is not None
            else None
        )
        return {
            "time_used_seconds": used,
            "time_remaining_seconds": after,
            "clock_before_move_seconds": before,
            "elapsed_annotation_seconds": explicit,
            "time_source": source,
            "under_time_pressure": pressure,
            "move_played_quickly": quick,
            "diagnostics": tuple(diagnostics),
        }
