"""Serial archive orchestration; adapters own HTTP and SQL."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from copy import deepcopy
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol

from structlog.contextvars import bound_contextvars

from chess_coach.domain.sync import (
    Archive,
    Checkpoint,
    MonthResult,
    SourceError,
    SyncReport,
    normalize_username,
    should_fetch,
)
from chess_coach.observability.logging import elapsed_ms

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
    def claim(self, run_id: int, now: datetime) -> None: ...
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
    def finish(self, report: SyncReport, now: datetime, duration_ms: int) -> None: ...


class SyncGamesService:
    def __init__(
        self,
        provider: GameProvider,
        store: SyncStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        prepare_games: Callable[[str], object] | None = None,
    ):
        self.provider, self.store, self.clock = provider, store, clock
        self.prepare_games = prepare_games

    def sync(
        self,
        username: str,
        *,
        force: bool = False,
        dry_run: bool = False,
        month: Archive | None = None,
        queued_run_id: int | None = None,
    ) -> SyncReport:
        started = perf_counter()
        username = normalize_username(username)
        with self.store.guard():
            if not dry_run:
                self.store.recover(self.clock())
            # No player/run creation when the public identity cannot be verified.
            if queued_run_id is None:
                try:
                    self.provider.get_player(username)
                except SourceError as exc:
                    logger.warning(
                        "sync_preflight_failed",
                        extra={
                            "component": "sync",
                            "error_code": exc.code,
                            "duration_ms": elapsed_ms(started),
                        },
                    )
                    raise
            report = SyncReport()
            if not dry_run:
                if queued_run_id is None:
                    report.run_id = self.store.start(username, self.clock())
                else:
                    self.store.claim(queued_run_id, self.clock())
                    report.run_id = queued_run_id
            error_code = None
            if report.run_id is not None:
                logger.info(
                    "sync_started", extra={"run_id": report.run_id, "component": "sync"}
                )
            try:
                if queued_run_id is not None:
                    self.provider.get_player(username)
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
                    error_code = "ARCHIVE_UNAVAILABLE"
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
                        with bound_contextvars(
                            run_id=str(report.run_id), component="sync"
                        ):
                            self.store.commit_archive(
                                report.run_id, archive, result, report, self.clock()
                            )
                        completed += 1
                    except Exception as exc:
                        error_code = (
                            exc.code
                            if isinstance(exc, SourceError)
                            else "PERSISTENCE_FAILURE"
                        )
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
                if self.prepare_games is not None:
                    self.prepare_games(username)
            except Exception as exc:
                report.status = "FAILED"
                error_code = (
                    exc.code if isinstance(exc, SourceError) else "SYNC_FAILURE"
                )
                report.errors.append(
                    str(exc)
                    if isinstance(exc, SourceError)
                    else "SYNC_FAILURE: inspect backend logs and retry."
                )
                if not isinstance(exc, SourceError):
                    logger.exception(
                        "sync_processing_error",
                        extra={"run_id": report.run_id, "error_code": error_code},
                    )
            if not dry_run:
                duration = elapsed_ms(started)
                context = {
                    "run_id": report.run_id,
                    "component": "sync",
                    "duration_ms": duration,
                    "games_inserted": report.games_inserted,
                    "games_existing": report.games_already_present,
                }
                try:
                    self.store.finish(report, self.clock(), duration)
                except Exception:
                    logger.exception(
                        "sync_failed",
                        extra={
                            **context,
                            "status": "FAILED",
                            "error_code": "PERSISTENCE_FAILURE",
                        },
                    )
                    raise
                event = (
                    "sync_finished" if report.status == "COMPLETED" else "sync_failed"
                )
                logger.log(
                    logging.INFO if report.status == "COMPLETED" else logging.WARNING,
                    event,
                    extra={
                        **context,
                        "status": report.status,
                        "error_code": error_code,
                    },
                )
            return report
