"""Serial archive orchestration; adapters own HTTP and SQL."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from copy import deepcopy
from datetime import UTC, datetime
from typing import Protocol

from chess_coach.domain.sync import (
    Archive,
    Checkpoint,
    MonthResult,
    SourceError,
    SyncReport,
    normalize_username,
    should_fetch,
)

logger = logging.getLogger(__name__)


class GameProvider(Protocol):
    def get_player(self, username: str) -> str: ...
    def get_archives(self, username: str) -> list[Archive]: ...
    def get_month_games(
        self, username: str, archive: Archive, checkpoint: Checkpoint | None = None
    ) -> MonthResult: ...


class SyncStore(Protocol):
    def guard(self) -> AbstractContextManager[None]: ...
    def recover(self, now: datetime) -> None: ...
    def checkpoints(self, username: str) -> dict[Archive, Checkpoint]: ...
    def start(self, username: str, now: datetime) -> int: ...
    def begin_archive(self, run_id: int, archive: Archive) -> None: ...
    def commit_archive(
        self,
        run_id: int,
        archive: Archive,
        result: MonthResult,
        report: SyncReport,
        now: datetime,
    ) -> None: ...
    def fail_archive(
        self,
        run_id: int,
        archive: Archive,
        error: str,
        report: SyncReport,
        now: datetime,
        *,
        unavailable: bool = False,
        result: MonthResult | None = None,
    ) -> None: ...
    def finish(self, report: SyncReport, now: datetime) -> None: ...


class SyncGamesService:
    def __init__(
        self,
        provider: GameProvider,
        store: SyncStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.provider, self.store, self.clock = provider, store, clock

    def sync(
        self,
        username: str,
        *,
        force: bool = False,
        dry_run: bool = False,
        month: Archive | None = None,
    ) -> SyncReport:
        username = normalize_username(username)
        with self.store.guard():
            if not dry_run:
                self.store.recover(self.clock())
            # No player/run creation when the public identity cannot be verified.
            self.provider.get_player(username)
            report = SyncReport()
            if not dry_run:
                report.run_id = self.store.start(username, self.clock())
            try:
                archives = self.provider.get_archives(username)
                report.archives_discovered = len(archives)
                if month is not None:
                    if month not in archives:
                        raise SourceError(
                            "ARCHIVE_NOT_LISTED",
                            "Choose a month from archive discovery.",
                        )
                    archives = [month]
                checkpoints = self.store.checkpoints(username)
                now = self.clock()
                selected = [
                    a
                    for a in archives
                    if should_fetch(a, checkpoints.get(a), now, force)
                ]
                report.archives_selected = len(archives)
                report.planned_archives = [a.key for a in selected]
                report.archives_skipped = len(archives) - len(selected)
                unavailable = [
                    a
                    for a in archives
                    if a not in selected and checkpoints[a].status == "unavailable"
                ]
                for archive in unavailable:
                    report.errors.append(
                        f"{archive.key}: UNAVAILABLE; review source and use --force to retry."
                    )
                if dry_run:
                    report.status = "DRY_RUN"
                    return report
                assert report.run_id is not None
                completed = report.archives_skipped - len(unavailable)
                for archive in selected:
                    self.store.begin_archive(report.run_id, archive)
                    report.archives_fetched += 1
                    result = None
                    before = deepcopy(report)
                    try:
                        result = self.provider.get_month_games(
                            username, archive, checkpoints.get(archive)
                        )
                        report.games_received += result.received
                        report.games_skipped_unsupported += sum(
                            r.unsupported for r in result.rejections
                        )
                        if any(not r.unsupported for r in result.rejections):
                            raise SourceError(
                                "INVALID_RECORDS",
                                "Archive rejected atomically; inspect import_rejections and retry.",
                            )
                        # Mutations to report are restored if the transaction fails.
                        self.store.commit_archive(
                            report.run_id, archive, result, report, self.clock()
                        )
                        completed += 1
                    except Exception as exc:
                        report = before
                        if result:
                            report.games_received += result.received
                            skipped = sum(r.unsupported for r in result.rejections)
                            report.games_skipped_unsupported += skipped
                            report.games_failed += result.received - skipped
                        report.archives_failed += 1
                        error = (
                            str(exc)
                            if isinstance(exc, SourceError)
                            else "PERSISTENCE_FAILURE: inspect backend logs and retry."
                        )
                        if not isinstance(exc, SourceError):
                            logger.exception(
                                "archive_import_failed",
                                extra={"run_id": report.run_id, "archive": archive.key},
                            )
                        report.errors.append(f"{archive.key}: {error}")
                        assert report.run_id is not None
                        self.store.fail_archive(
                            report.run_id,
                            archive,
                            error,
                            report,
                            self.clock(),
                            unavailable=isinstance(exc, SourceError)
                            and exc.unavailable,
                            result=result,
                        )
                    logger.info(
                        "archive_processed",
                        extra={"run_id": report.run_id, "archive": archive.key},
                    )
                report.status = (
                    "COMPLETED"
                    if not report.errors
                    else "PARTIAL"
                    if completed
                    else "FAILED"
                )
            except Exception as exc:
                report.status = "FAILED"
                report.errors.append(
                    str(exc)
                    if isinstance(exc, SourceError)
                    else "SYNC_FAILURE: inspect backend logs and retry."
                )
                if not isinstance(exc, SourceError):
                    logger.exception("sync_failed", extra={"run_id": report.run_id})
            if not dry_run:
                self.store.finish(report, self.clock())
            return report
