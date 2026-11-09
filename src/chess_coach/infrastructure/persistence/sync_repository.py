"""SQLite synchronization transactions and local-process exclusion."""

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from chess_coach.application.errors import OperationError
from chess_coach.domain.sync import (
    Archive,
    Checkpoint,
    MonthResult,
    SyncAlreadyRunning,
    SyncReport,
)
from chess_coach.infrastructure.persistence.models import (
    ArchiveSyncState,
    Game,
    ImportRejection,
    ImportRun,
    Platform,
    RunStatus,
    TrackedPlayer,
)
from chess_coach.infrastructure.persistence.operations import ensure_idle, reserve


class SyncRepository:
    def __init__(self, sessions: sessionmaker[Session], database_path: Path):
        self.sessions = sessions
        self.lock_path = database_path.resolve().with_suffix(".sync.lock")

    @contextmanager
    def guard(self) -> Iterator[None]:
        # Kernel releases flock even on SIGKILL. Never unlink: that races waiters.
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SyncAlreadyRunning(
                    "SYNC_ALREADY_RUNNING: retry after the active local sync."
                ) from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def recover(self, now: datetime) -> None:
        # Only called while holding the database-wide kernel lock.
        with self.sessions.begin() as session:
            for run in session.scalars(
                select(ImportRun).where(ImportRun.status == RunStatus.RUNNING)
            ):
                successful = (run.summary_json or {}).get("archives_completed", 0)
                run.status = (
                    RunStatus.PARTIAL
                    if successful or run.games_inserted
                    else RunStatus.FAILED
                )
                run.finished_at = now
                run.error_message = (
                    "INTERRUPTED: recovered after previous process exited."
                )
                if run.summary_json:
                    previous_errors = run.summary_json.get("errors", [])
                    if not isinstance(previous_errors, list):
                        previous_errors = []
                    run.summary_json = {
                        **run.summary_json,
                        "status": "PARTIAL"
                        if run.status == RunStatus.PARTIAL
                        else "FAILED",
                        "errors": [*previous_errors, run.error_message],
                    }
            for state in session.scalars(
                select(ArchiveSyncState).where(ArchiveSyncState.status == "running")
            ):
                state.status = "failed"
                state.last_error = "INTERRUPTED: retry this archive."

    def checkpoints(self, username: str) -> dict[Archive, Checkpoint]:
        with self.sessions() as session:
            rows = session.scalars(
                select(ArchiveSyncState)
                .join(TrackedPlayer)
                .where(
                    TrackedPlayer.username == username,
                    TrackedPlayer.platform == Platform.CHESS_COM,
                )
            )
            return {
                Archive(row.year, row.month): Checkpoint(
                    row.status, row.etag, row.last_modified
                )
                for row in rows
            }

    def start(self, username: str, now: datetime) -> int:
        with self.sessions.begin() as session:
            reserve(session)
            ensure_idle(session)
            session.execute(
                insert(TrackedPlayer)
                .values(platform=Platform.CHESS_COM, username=username)
                .on_conflict_do_nothing(index_elements=["platform", "username"])
            )
            player = session.scalar(
                select(TrackedPlayer).where(
                    TrackedPlayer.username == username,
                    TrackedPlayer.platform == Platform.CHESS_COM,
                )
            )
            assert player is not None
            run = ImportRun(
                tracked_player_id=player.id, status=RunStatus.RUNNING, started_at=now
            )
            session.add(run)
            session.flush()
            return run.id

    def enqueue(self, player_id: int) -> int:
        with self.sessions.begin() as s:
            reserve(s)
            ensure_idle(s)
            if s.get(TrackedPlayer, player_id) is None:
                raise OperationError(
                    "PLAYER_NOT_CONFIGURED", "Configure a player first."
                )
            run = ImportRun(tracked_player_id=player_id, status=RunStatus.PENDING)
            s.add(run)
            s.flush()
            return run.id

    def next_pending(self) -> tuple[int, str] | None:
        with self.sessions() as s:
            row = s.execute(
                select(ImportRun.id, TrackedPlayer.username)
                .join(TrackedPlayer)
                .where(ImportRun.status == RunStatus.PENDING)
                .order_by(ImportRun.id)
                .limit(1)
            ).first()
            return (row[0], row[1]) if row else None

    def claim(self, run_id: int, now: datetime) -> None:
        with self.sessions.begin() as s:
            reserve(s)
            run = s.get(ImportRun, run_id)
            if run is None or run.status != RunStatus.PENDING:
                raise OperationError("SYNC_NOT_QUEUED", "Select a queued sync run.")
            run.status, run.started_at = RunStatus.RUNNING, now

    def progress(self, run_id: int) -> dict[str, object]:
        with self.sessions() as s:
            run = s.get(ImportRun, run_id)
            if run is None:
                raise OperationError(
                    "SYNC_RUN_NOT_FOUND", "The sync run was not found.", 404
                )
            summary = run.summary_json or {}
            failed = run.status in (RunStatus.FAILED, RunStatus.PARTIAL)
            return {
                "run_id": run.id,
                "status": {
                    RunStatus.PENDING: "queued",
                    RunStatus.RUNNING: "running",
                    RunStatus.SUCCEEDED: "completed",
                    RunStatus.FAILED: "failed",
                    RunStatus.PARTIAL: "failed",
                }[run.status],
                "partial": run.status == RunStatus.PARTIAL,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "progress": {
                    "archives_total": summary.get("archives_selected"),
                    "archives_processed": sum(
                        v
                        for key in (
                            "archives_completed",
                            "archives_failed",
                            "archives_skipped",
                        )
                        if isinstance((v := summary.get(key)), int)
                    ),
                    "games_seen": run.games_seen,
                    "games_inserted": run.games_inserted,
                    "games_existing": run.games_existing,
                    "games_failed": run.games_failed,
                    "games_skipped": run.games_skipped,
                },
                "error": {
                    "code": "SYNC_FAILED",
                    "message": "Sync did not finish successfully. Check backend logs and start another sync to resume archive checkpoints.",
                    "details": {},
                }
                if failed
                else None,
                "recoverable": failed or run.status == RunStatus.RUNNING,
            }

    @staticmethod
    def _state(session: Session, run: ImportRun, archive: Archive) -> ArchiveSyncState:
        state = session.scalar(
            select(ArchiveSyncState).where(
                ArchiveSyncState.tracked_player_id == run.tracked_player_id,
                ArchiveSyncState.year == archive.year,
                ArchiveSyncState.month == archive.month,
            )
        )
        if state is None:
            state = ArchiveSyncState(
                tracked_player_id=run.tracked_player_id,
                year=archive.year,
                month=archive.month,
            )
            session.add(state)
        return state

    def begin_archive(self, run_id: int, archive: Archive) -> None:
        with self.sessions.begin() as session:
            run = session.get(ImportRun, run_id)
            assert run is not None
            self._state(session, run, archive).status = "running"

    @staticmethod
    def _save_report(run: ImportRun, report: SyncReport) -> None:
        run.summary_json = asdict(report)
        run.archives_requested = report.archives_fetched
        run.games_seen = report.games_received
        run.games_inserted = report.games_inserted
        run.games_existing = report.games_already_present
        run.games_skipped = report.games_skipped_unsupported
        run.games_failed = report.games_failed

    def commit_archive(
        self,
        run_id: int,
        archive: Archive,
        result: MonthResult,
        report: SyncReport,
        now: datetime,
    ) -> None:
        with self.sessions.begin() as session:
            run = session.get(ImportRun, run_id)
            assert run is not None
            state = self._state(session, run, archive)
            if result.unchanged:
                if state.last_success_at is None:
                    raise ValueError("304 requires a successful checkpoint")
                report.archives_unchanged += 1
            else:
                for game in result.games:
                    statement = (
                        insert(Game)
                        .values(
                            **asdict(game),
                            tracked_player_id=run.tracked_player_id,
                            platform=Platform.CHESS_COM,
                        )
                        .on_conflict_do_nothing()
                        .returning(Game.id)
                    )
                    if session.scalar(statement) is None:
                        report.games_already_present += 1
                        existing = session.scalar(
                            select(Game).where(
                                Game.platform == Platform.CHESS_COM,
                                or_(
                                    Game.external_id == game.external_id,
                                    Game.canonical_hash == game.canonical_hash,
                                ),
                            )
                        )
                        # Backfill only matching immutable source records. Never
                        # attach evidence for a changed PGN to an older record.
                        if (
                            existing is not None
                            and existing.source_evidence is None
                            and existing.raw_pgn == game.raw_pgn
                        ):
                            existing.source_evidence = game.source_evidence
                    else:
                        report.games_inserted += 1
                state.etag, state.last_modified = result.etag, result.last_modified
                state.last_successful_game_count = result.received
            for rejected in result.rejections:
                session.add(
                    ImportRejection(
                        import_run_id=run_id,
                        year=archive.year,
                        month=archive.month,
                        record_index=rejected.index,
                        reason=rejected.reason,
                        raw_pgn=rejected.raw_pgn,
                    )
                )
            state.status = "complete"
            state.last_success_at = state.last_checked_at = now
            state.last_error = None
            report.archives_completed += 1
            self._save_report(run, report)

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
    ) -> None:
        with self.sessions.begin() as session:
            run = session.get(ImportRun, run_id)
            assert run is not None
            state = self._state(session, run, archive)
            state.status = "unavailable" if unavailable else "failed"
            state.last_checked_at, state.last_error = now, error
            if result:
                for rejected in result.rejections:
                    session.add(
                        ImportRejection(
                            import_run_id=run_id,
                            year=archive.year,
                            month=archive.month,
                            record_index=rejected.index,
                            reason=rejected.reason,
                            raw_pgn=rejected.raw_pgn,
                        )
                    )
            self._save_report(run, report)

    def finish(self, report: SyncReport, now: datetime) -> None:
        with self.sessions.begin() as session:
            run = session.get(ImportRun, report.run_id)
            assert run is not None
            run.status = {
                "COMPLETED": RunStatus.SUCCEEDED,
                "PARTIAL": RunStatus.PARTIAL,
                "FAILED": RunStatus.FAILED,
            }[report.status]
            run.finished_at = now
            run.error_message = "; ".join(report.errors) or None
            self._save_report(run, report)

    def diagnostics(self, username: str) -> dict[str, object]:
        """Read-only local health; never probes upstream or changes stale runs."""
        from sqlalchemy import func

        with self.sessions() as session:
            player = session.scalar(
                select(TrackedPlayer).where(
                    TrackedPlayer.username == username,
                    TrackedPlayer.platform == Platform.CHESS_COM,
                )
            )
            if player is None:
                return {"database": "ok", "player": username, "last_run": None}
            run = session.scalar(
                select(ImportRun)
                .where(ImportRun.tracked_player_id == player.id)
                .order_by(ImportRun.id.desc())
                .limit(1)
            )
            states = session.execute(
                select(ArchiveSyncState.status, func.count())
                .where(ArchiveSyncState.tracked_player_id == player.id)
                .group_by(ArchiveSyncState.status)
            ).all()
            games = session.scalar(
                select(func.count())
                .select_from(Game)
                .where(Game.tracked_player_id == player.id)
            )
            return {
                "database": "ok",
                "player": username,
                "games": games,
                "archive_states": dict(states),
                "last_run": run.summary_json if run else None,
                "last_error": run.error_message if run else None,
            }
