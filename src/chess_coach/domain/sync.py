"""Typed contracts for completed-game synchronization."""

import re
from dataclasses import dataclass, field
from datetime import datetime


def normalize_username(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{1,100}", value):
        raise ValueError("Use a Chess.com username containing letters, digits, _ or -.")
    return value


@dataclass(frozen=True, order=True)
class Archive:
    year: int
    month: int

    def __post_init__(self) -> None:
        if not 2007 <= self.year <= 9999 or not 1 <= self.month <= 12:
            raise ValueError("Invalid archive year/month.")

    @property
    def key(self) -> str:
        return f"{self.year:04d}/{self.month:02d}"


@dataclass(frozen=True)
class ExternalGame:
    external_id: str
    canonical_hash: str
    raw_pgn: str
    played_at: datetime
    white_username: str
    black_username: str
    white_rating: int | None
    black_rating: int | None
    player_color: str
    result: str
    time_control: str | None
    time_class: str | None
    eco_url: str | None
    source_url: str | None
    source_evidence: dict[str, object] | None = None


@dataclass(frozen=True)
class Rejection:
    index: int
    reason: str
    raw_pgn: str | None
    unsupported: bool = False


@dataclass(frozen=True)
class MonthResult:
    games: list[ExternalGame] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    received: int = 0
    unchanged: bool = False
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class Checkpoint:
    status: str
    etag: str | None = None
    last_modified: str | None = None


@dataclass
class SyncReport:
    run_id: int | None = None
    status: str = "RUNNING"
    archives_discovered: int = 0
    archives_selected: int = 0
    archives_completed: int = 0
    archives_fetched: int = 0
    archives_skipped: int = 0
    archives_unchanged: int = 0
    archives_failed: int = 0
    games_received: int = 0
    games_inserted: int = 0
    games_already_present: int = 0
    games_skipped_unsupported: int = 0
    games_failed: int = 0
    planned_archives: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def should_fetch(
    archive: Archive, checkpoint: Checkpoint | None, now: datetime, force: bool = False
) -> bool:
    if force or checkpoint is None:
        return True
    if checkpoint.status == "unavailable":
        return False
    if checkpoint.status != "complete":
        return True
    current = now.year * 12 + now.month
    return archive.year * 12 + archive.month >= current - 1


class SyncAlreadyRunning(Exception):
    pass


class SourceError(Exception):
    def __init__(self, code: str, message: str, *, unavailable: bool = False):
        self.code = code
        self.unavailable = unavailable
        super().__init__(f"{code}: {message}")
