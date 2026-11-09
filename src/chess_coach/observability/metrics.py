"""Metric formulas for persisted local operation samples."""

from collections.abc import Sequence
from statistics import median


def ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


def cache_hit_rate(hits: int, misses: int) -> float | None:
    return ratio(100 * hits, hits + misses)


def games_per_hour(games: int, elapsed_seconds: float) -> float | None:
    return ratio(3600 * games, elapsed_seconds)


def latency_p50(samples: Sequence[int]) -> float | None:
    return float(median(samples)) if samples else None
