import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event, func, select

from chess_coach.application.sync_games import SyncGamesService
from chess_coach.domain.sync import Archive, SourceError, SyncAlreadyRunning
from chess_coach.infrastructure.chesscom.client import BASE_URL, ChessComClient
from chess_coach.infrastructure.persistence.models import (
    ArchiveSyncState,
    Game,
    ImportRejection,
    ImportRun,
    TrackedPlayer,
)
from chess_coach.infrastructure.persistence.sync_repository import SyncRepository

NOW = datetime(2026, 11, 7, tzinfo=UTC)


class FixtureAPI:
    def __init__(self):
        self.requests = []
        self.fail = None
        self.interrupt = False
        self.invalid = False
        self.extra = False
        self.not_modified = False
        self.raw = json.loads(
            (
                Path(__file__).parents[2] / "fixtures/chesscom/month_normal.json"
            ).read_text()
        )["games"][0]

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/testplayer"):
            return httpx.Response(200, json={"username": "TestPlayer"})
        if path.endswith("/archives"):
            return httpx.Response(
                200,
                json={
                    "archives": [
                        BASE_URL + "/player/testplayer/games/2026/09",
                        BASE_URL + "/player/testplayer/games/2026/10",
                    ]
                },
            )
        month = int(path[-2:])
        if month == 10:
            if self.interrupt:
                raise KeyboardInterrupt()
            if self.fail:
                return httpx.Response(self.fail)
            if self.not_modified and "If-None-Match" in request.headers:
                return httpx.Response(304)
        games = []
        for i in range(1, (4 if month == 9 else 5) + int(self.extra and month == 10)):
            raw = deepcopy(self.raw)
            number = month * 10 + i
            raw["uuid"] = f"00000000-0000-0000-0000-{number:012d}"
            raw["url"] = f"https://www.chess.com/game/live/{number}"
            raw["end_time"] = int(datetime(2026, month, 1, tzinfo=UTC).timestamp())
            games.append(raw)
        if self.invalid and month == 10:
            games[0]["white"]["result"] = "playing"
        return httpx.Response(200, json={"games": games}, headers={"ETag": '"v1"'})


@pytest.fixture
def setup_sync(sessions, tmp_path):
    source = FixtureAPI()
    api = ChessComClient(
        transport=httpx.MockTransport(source),
        sleep=lambda _: None,
        jitter=lambda: 0,
        clock=lambda: NOW,
    )
    store = SyncRepository(sessions, tmp_path / "test.db")
    yield source, store, SyncGamesService(api, store, lambda: NOW)
    api.close()


def count(sessions, model):
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_three_runs_and_immutable_existing_rows(setup_sync, sessions):
    source, store, service = setup_sync
    first = service.sync(" TestPlayer ")
    assert first.status == "COMPLETED" and first.games_inserted == 7
    with sessions() as session:
        original = [
            (g.id, g.created_at, g.raw_pgn) for g in session.scalars(select(Game))
        ]
    second = service.sync("testplayer")
    assert second.games_inserted == 0 and second.games_already_present == 4
    assert second.archives_skipped == 1 and second.archives_fetched == 1
    source.extra = True
    third = service.sync("TESTPLAYER")
    assert third.games_inserted == 1
    assert count(sessions, Game) == 8 and count(sessions, TrackedPlayer) == 1
    with sessions() as session:
        assert [
            (g.id, g.created_at, g.raw_pgn)
            for g in session.scalars(select(Game)).all()[:7]
        ] == original
        run = session.get(ImportRun, third.run_id)
        assert run.summary_json["games_inserted"] == 1
    assert all(c.status == "complete" for c in store.checkpoints("testplayer").values())
    forced = service.sync("testplayer", force=True)
    assert forced.archives_fetched == 2 and forced.games_inserted == 0


def test_partial_failure_retry_and_diagnostics(setup_sync, sessions):
    source, store, service = setup_sync
    source.fail = 500
    report = service.sync("testplayer")
    assert report.status == "PARTIAL" and report.archives_failed == 1
    assert count(sessions, Game) == 3
    assert store.checkpoints("testplayer")[Archive(2026, 10)].status == "failed"
    source.fail = None
    retry = service.sync("testplayer")
    assert retry.games_inserted == 4 and retry.archives_skipped == 1
    assert count(sessions, Game) == 7


def test_invalid_record_rejects_whole_month_preserves_raw_pgn(setup_sync, sessions):
    source, store, service = setup_sync
    source.invalid = True
    result = service.sync("testplayer")
    assert result.status == "PARTIAL" and result.games_failed == 4
    assert result.games_received == result.games_inserted + result.games_failed
    assert count(sessions, Game) == 3
    with sessions() as session:
        rejected = session.scalar(select(ImportRejection))
        assert rejected.raw_pgn == source.raw["pgn"]
    assert store.checkpoints("testplayer")[Archive(2026, 10)].etag is None


def test_interrupted_run_recovered_without_reimporting_committed_month(
    setup_sync, sessions
):
    source, _store, service = setup_sync
    source.interrupt = True
    with pytest.raises(KeyboardInterrupt):
        service.sync("testplayer")
    assert count(sessions, Game) == 3
    source.interrupt = False
    result = service.sync("testplayer")
    assert result.games_inserted == 4 and result.archives_skipped == 1
    with sessions() as session:
        runs = session.scalars(select(ImportRun).order_by(ImportRun.id)).all()
        assert runs[0].status == "partial" and "INTERRUPTED" in runs[0].error_message
        assert runs[1].status == "succeeded"


def test_atomic_transaction_failure_restores_counters(setup_sync, sessions, engine):
    _source, store, service = setup_sync

    def fail_insert(connection, cursor, statement, parameters, context, executemany):
        if (
            statement.startswith("INSERT INTO games")
            and "uuid:00000000-0000-0000-0000-000000000102" in parameters
        ):
            raise RuntimeError("simulated disk error")

    event.listen(engine, "before_cursor_execute", fail_insert)
    try:
        report = service.sync("testplayer")
    finally:
        event.remove(engine, "before_cursor_execute", fail_insert)
    assert (
        report.status == "PARTIAL"
        and report.games_inserted == 3
        and report.games_failed == 4
    )
    assert count(sessions, Game) == 3
    assert store.checkpoints("testplayer")[Archive(2026, 10)].etag is None
    assert service.sync("testplayer").games_inserted == 4


def test_dry_run_no_database_changes(setup_sync, sessions):
    source, _store, service = setup_sync
    report = service.sync("testplayer", dry_run=True)
    assert report.status == "DRY_RUN" and report.planned_archives == [
        "2026/09",
        "2026/10",
    ]
    assert len(source.requests) == 2
    for model in (TrackedPlayer, Game, ImportRun, ArchiveSyncState):
        assert count(sessions, model) == 0


def test_simultaneous_sync_guard(setup_sync, sessions, tmp_path):
    source, _store, service = setup_sync
    other = SyncRepository(sessions, tmp_path / "test.db")
    with other.guard(), pytest.raises(SyncAlreadyRunning):
        service.sync("testplayer")
    assert not source.requests
    assert service.sync("testplayer").status == "COMPLETED"


def test_304_preserves_data_and_validators(setup_sync, sessions):
    source, store, service = setup_sync
    service.sync("testplayer")
    source.not_modified = True
    report = service.sync("testplayer")
    assert report.archives_unchanged == 1 and report.games_received == 0
    assert count(sessions, Game) == 7
    assert store.checkpoints("testplayer")[Archive(2026, 10)].etag == '"v1"'


def test_unavailable_needs_deliberate_retry(setup_sync):
    source, _store, service = setup_sync
    source.fail = 410
    assert service.sync("testplayer").status == "PARTIAL"
    source.fail = None
    report = service.sync("testplayer")
    assert report.status == "PARTIAL" and report.archives_fetched == 0
    assert service.sync("testplayer", force=True).status == "COMPLETED"


def test_unknown_profile_does_not_create_player(sessions, tmp_path):
    with ChessComClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(404))
    ) as api:
        service = SyncGamesService(api, SyncRepository(sessions, tmp_path / "test.db"))
        with pytest.raises(SourceError, match="PLAYER_NOT_FOUND"):
            service.sync("missing")
    assert count(sessions, TrackedPlayer) == 0
    assert count(sessions, ImportRun) == 0


def test_interrupted_refresh_with_no_new_rows_is_partial(setup_sync, sessions):
    source, _store, service = setup_sync
    service.sync("testplayer")
    source.interrupt = True
    with pytest.raises(KeyboardInterrupt):
        service.sync("testplayer", force=True)
    source.interrupt = False
    service.sync("testplayer")
    with sessions() as session:
        run = session.get(ImportRun, 2)
        assert run.games_inserted == 0
        assert run.status == "partial"
        assert run.summary_json["archives_completed"] == 1


def test_cross_process_lock_released_after_kill(setup_sync):
    import subprocess
    import sys

    _source, store, service = setup_sync
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl,sys; f=open(sys.argv[1], 'a'); fcntl.flock(f, fcntl.LOCK_EX); print('ready', flush=True); sys.stdin.read()",
            str(store.lock_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(SyncAlreadyRunning):
            service.sync("testplayer")
    finally:
        process.kill()
        process.communicate(timeout=5)
    assert service.sync("testplayer").status == "COMPLETED"


def test_scoped_import_and_local_diagnostics(setup_sync, sessions):
    source, store, service = setup_sync
    assert store.diagnostics("missing")["last_run"] is None
    report = service.sync("testplayer", month=Archive(2026, 9))
    assert report.archives_selected == 1 and report.games_inserted == 3
    requests_before = len(source.requests)
    result = store.diagnostics("testplayer")
    assert result["database"] == "ok" and result["games"] == 3
    assert result["archive_states"] == {"complete": 1}
    assert len(source.requests) == requests_before
    assert service.sync("testplayer", month=Archive(2025, 1)).status == "FAILED"


def test_archive_discovery_failure_is_persisted(sessions, tmp_path):
    def handler(request):
        return httpx.Response(
            200,
            json={"username": "testplayer"}
            if request.url.path.endswith("/testplayer")
            else {},
        )

    with ChessComClient(transport=httpx.MockTransport(handler)) as api:
        service = SyncGamesService(api, SyncRepository(sessions, tmp_path / "test.db"))
        report = service.sync("testplayer")
    assert report.status == "FAILED" and "INVALID_SCHEMA" in report.errors[0]
    with sessions() as session:
        assert session.get(ImportRun, report.run_id).status == "failed"


def test_unsupported_records_are_counted_and_preserved(sessions, tmp_path):
    source = FixtureAPI()
    source.raw["rules"] = "chess960"
    with ChessComClient(
        transport=httpx.MockTransport(source), clock=lambda: NOW
    ) as api:
        service = SyncGamesService(
            api, SyncRepository(sessions, tmp_path / "test.db"), lambda: NOW
        )
        report = service.sync("testplayer")
    assert report.status == "COMPLETED"
    assert report.games_received == report.games_skipped_unsupported == 7
    assert report.games_inserted == report.games_failed == 0
    assert count(sessions, Game) == 0
    assert count(sessions, ImportRejection) == 7


def test_previous_errors_survive_recovery(setup_sync, sessions):
    source, store, service = setup_sync
    source.interrupt = True
    with pytest.raises(KeyboardInterrupt):
        service.sync("testplayer")
    with sessions.begin() as session:
        run = session.scalar(select(ImportRun))
        run.summary_json = {**run.summary_json, "errors": ["prior diagnostic"]}
    with store.guard():
        store.recover(NOW)
    with sessions() as session:
        run = session.scalar(select(ImportRun))
        assert run.summary_json["errors"][0] == "prior diagnostic"
        assert "INTERRUPTED" in run.summary_json["errors"][1]


def test_source_evidence_backfill_keeps_pgn_immutable(setup_sync, sessions):
    source, _store, service = setup_sync
    service.sync("testplayer")
    with sessions.begin() as session:
        first = session.scalar(select(Game).order_by(Game.id))
        first_id, raw = first.id, first.raw_pgn
        assert first.source_evidence["white_result"] == "win"
        first.source_evidence = None
    service.sync("testplayer", force=True)
    with sessions() as session:
        first = session.get(Game, first_id)
        assert first.source_evidence["end_time"] > 0
        assert first.raw_pgn == raw
    with sessions.begin() as session:
        session.get(Game, first_id).source_evidence = None
    source.raw["pgn"] += "\n{changed source}"
    service.sync("testplayer", force=True)
    with sessions() as session:
        first = session.get(Game, first_id)
        assert first.source_evidence is None and first.raw_pgn == raw


def test_sync_events_use_persisted_ids_and_exclude_source_payload(
    setup_sync, sessions, capsys
):
    from chess_coach.observability.logging import configure_logging

    source, _, service = setup_sync
    source.fail = 500
    source.raw["pgn"] = source.raw["pgn"].replace(
        "[Event ", '[Site "PRIVATE_TEST_USERNAME_123"]\n[Event ', 1
    )
    configure_logging("DEBUG")
    report = service.sync("testplayer")
    output = capsys.readouterr().err
    assert "PRIVATE_TEST_USERNAME_123" not in output
    assert "testplayer" not in output.lower()
    events = [json.loads(line) for line in output.splitlines()]
    boundaries = [
        event
        for event in events
        if event["event"] in {"sync_started", "sync_finished", "sync_failed"}
    ]
    assert [event["event"] for event in boundaries] == ["sync_started", "sync_failed"]
    assert all(event["run_id"] == str(report.run_id) for event in events)
    with sessions() as session:
        run = session.get(ImportRun, report.run_id)
        assert run.duration_ms == boundaries[-1]["duration_ms"]
        assert run.games_inserted == boundaries[-1]["games_inserted"]
        assert run.games_inserted == sum(
            event["event"] == "game_inserted" for event in events
        )


def test_sync_preflight_failure_does_not_log_or_return_username(
    setup_sync, sessions, capsys
):
    from chess_coach.observability.logging import configure_logging

    _, store, _ = setup_sync
    configure_logging()
    with ChessComClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(403))
    ) as provider, pytest.raises(SourceError) as error:
        SyncGamesService(provider, store).sync("private-test-player")
    assert "private-test-player" not in str(error.value)
    event = json.loads(capsys.readouterr().err)
    assert event["event"] == "sync_preflight_failed"
    assert event["error_code"] == "HTTP_ERROR"
    assert "private-test-player" not in json.dumps(event)
    assert count(sessions, ImportRun) == 0
