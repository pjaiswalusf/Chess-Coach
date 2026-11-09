"""Versioned review intervals, measured in UTC days."""

from datetime import UTC, datetime, timedelta

SCHEDULER_VERSION = 1
CORRECT_INTERVALS = (3, 7, 14, 30)


def schedule(now: datetime, streak: int, correct: bool) -> tuple[int, datetime]:
    if now.utcoffset() is None or type(streak) is not int or streak < 0:
        raise ValueError(
            "Review scheduling requires an aware time and a nonnegative streak."
        )
    if not correct:
        return 0, now.astimezone(UTC) + timedelta(days=1)
    days = CORRECT_INTERVALS[min(streak, len(CORRECT_INTERVALS) - 1)]
    return streak + 1, now.astimezone(UTC) + timedelta(days=days)
