"""Public workflow and failure injection against real migrated SQLite."""

from dataclasses import asdict, replace

import chess
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select
from test_models import game

from chess_coach.api.app import app
from chess_coach.api.dependencies import get_analysis_service
from chess_coach.application.analysis import (
    AnalysisProcessor,
    AnalysisService,
    configured_profile,
)
from chess_coach.config import Settings
from chess_coach.domain.analysis import AnalysisRunStatus as Status
from chess_coach.domain.analysis import history_hash, transition
from chess_coach.domain.engine_types import EngineResult
from chess_coach.domain.game_records import PARSER_VERSION, ParseStatus
from chess_coach.infrastructure.analysis_lock import WorkerAlreadyRunning, worker_guard
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisError,
    AnalysisRepository,
)
from chess_coach.infrastructure.persistence.models import (
    Game,
    MoveAnalysis,
    PositionCache,
)
from chess_coach.infrastructure.pgn.parser import parse_game

PGN = '[White "TestPlayer"]\n[Black "Opponent"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0'


class FakeEngine:
    engine_name = "fixture-engine"
    calls = 0

    def start(self):
        pass

    def close(self):
        pass

    def analyze(self, board, **kwargs):
        self.calls += 1
        best = next(iter(board.legal_moves)).uci()
        return EngineResult(
            board.fen(),
            self.engine_name,
            20 * len(board.move_stack),
            None,
            None,
            best,
            (best,),
            4,
            100,
        )


@pytest.fixture
def pipeline(sessions, tmp_path):
    settings = Settings(database_path=tmp_path / "test.db", _env_file=None)
    store = AnalysisRepository(sessions, settings.database_path)
    engine = FakeEngine()
    profile = configured_profile(settings, engine.engine_name)
    store.register(profile)
    return store, engine, settings, profile


def seed(sessions, player_id, count=1, pgn=PGN):
    ids = []
    parsed = parse_game(pgn, "testplayer")
    metadata = asdict(parsed)
    del metadata["moves"]
    metadata["total_plies"] = parsed.total_plies
    with sessions.begin() as s:
        for i in range(count):
            g = game(
                player_id,
                platform="pgn",
                external_id=None,
                canonical_hash=f"{i:064x}",
                raw_pgn=pgn,
                parse_status=ParseStatus.READY,
                parser_version=PARSER_VERSION,
                chess_library_version=chess.__version__,
                parsed_metadata=metadata,
            )
            s.add(g)
            s.flush()
            ids.append(g.id)
    return ids


def process(pipeline, run_id):
    store, engine, settings, profile = pipeline
    assert store.claim(profile) == run_id
    AnalysisProcessor(store, engine, settings).process(run_id)


def test_complete_repeat_cache_and_profile_isolation(pipeline, sessions, player_id):
    store, engine, settings, profile = pipeline
    ids = seed(sessions, player_id, 2)
    run = store.create(player_id, profile)
    process(pipeline, run)
    result = store.get(run)
    assert result.status == Status.DONE
    assert (result.games_completed, result.cache_hits, engine.calls) == (2, 5, 5)
    assert len(store.moves(ids[0], profile.hash)) == 4
    losses = [m.loss_cp for m in store.moves(ids[0], profile.hash)]
    assert losses == [0, 20, 0, 20]
    second = store.create(player_id, profile)
    assert store.get(second).status == Status.DONE
    assert store.get(second).games_skipped == 2 and engine.calls == 5
    changed = replace(profile, config=profile.config | {"nodes": 20000})
    third = store.create(player_id, changed)
    assert store.get(third).games_skipped == 0
    assert store.claim(changed) == third
    AnalysisProcessor(store, engine, settings).process(third)
    assert engine.calls == 10
    assert len(store.moves(ids[0], profile.hash)) == 4
    assert len(store.moves(ids[0], changed.hash)) == 4


def test_empty_and_duplicate_run(pipeline, sessions, player_id):
    store, engine, _, profile = pipeline
    empty = store.create(player_id, profile)
    assert store.get(empty).status == Status.DONE and engine.calls == 0
    seed(sessions, player_id)
    run = store.create(player_id, profile)
    with pytest.raises(AnalysisError, match="active run"):
        store.create(player_id, profile)
    store.cancel(run)
    assert store.get(run).status == Status.CANCELLED
    with pytest.raises(AnalysisError):
        store.cancel(run)


def test_crash_preserves_commit_and_recovers_cached_positions(
    pipeline, sessions, player_id
):
    store, engine, settings, profile = pipeline
    ids = seed(sessions, player_id, 3)
    run = store.create(player_id, profile)
    assert store.claim(profile) == run

    def crash(kind, identity):
        if kind == "game":
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        AnalysisProcessor(store, engine, settings, checkpoint=crash).process(run)
    assert store.get(run).games_completed == 1
    assert len(store.moves(ids[0], profile.hash)) == 4
    with worker_guard(settings.database_path):
        store.recover(profile)
        process(pipeline, run)
    assert store.get(run).games_completed == 3
    assert engine.calls == 5
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(MoveAnalysis)) == 12


def test_partial_position_crash_then_resume(pipeline, sessions, player_id):
    store, engine, settings, profile = pipeline
    seed(sessions, player_id)
    run = store.create(player_id, profile)
    store.claim(profile)

    def crash(kind, identity):
        if kind == "position" and identity == 1:
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        AnalysisProcessor(store, engine, settings, checkpoint=crash).process(run)
    assert engine.calls == 2 and store.get(run).games_completed == 0
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(MoveAnalysis)) == 0
    store.recover(profile)
    process(pipeline, run)
    assert engine.calls == 5 and store.get(run).cache_hits == 2


def test_bad_game_does_not_abort_batch(pipeline, sessions, player_id):
    store, _engine, _, profile = pipeline
    ids = seed(sessions, player_id, 3)
    with sessions.begin() as s:
        s.get(Game, ids[1]).raw_pgn = PGN.replace("e4", "e5")
    run = store.create(player_id, profile)
    process(pipeline, run)
    result = store.get(run)
    assert result.status == Status.COMPLETED_WITH_ERRORS
    assert (result.games_completed, result.games_failed) == (2, 1)
    assert store.members(run)[1].error_code == "INVALID_GAME"
    detail = AnalysisService(store).detail(run)
    assert detail["progress_percent"] == 100
    assert detail["successful_percent"] == 200 / 3


def test_missing_move_makes_done_game_eligible(pipeline, sessions, player_id):
    store, _, _, profile = pipeline
    ids = seed(sessions, player_id)
    run = store.create(player_id, profile)
    process(pipeline, run)
    with sessions.begin() as s:
        s.execute(
            delete(MoveAnalysis).where(
                MoveAnalysis.game_id == ids[0], MoveAnalysis.ply == 2
            )
        )
    retry = store.create(player_id, profile)
    assert store.get(retry).games_skipped == 0
    process(pipeline, retry)
    assert len(store.moves(ids[0], profile.hash)) == 4


def test_cancel_at_position_boundary_and_new_run(pipeline, sessions, player_id):
    store, engine, settings, profile = pipeline
    seed(sessions, player_id)
    run = store.create(player_id, profile)
    store.claim(profile)

    def cancel(kind, identity):
        if kind == "position":
            store.cancel(run)

    AnalysisProcessor(store, engine, settings, checkpoint=cancel).process(run)
    assert store.get(run).status == Status.CANCELLED
    assert store.get(run).games_completed == 0 and engine.calls == 1
    retry = store.create(player_id, profile)
    process(pipeline, retry)
    assert engine.calls == 5 and store.get(retry).status == Status.DONE


def test_finalization_failure_rolls_back_all_moves(pipeline, sessions, player_id):
    store, _, settings, profile = pipeline
    seed(sessions, player_id)
    run = store.create(player_id, profile)
    store.claim(profile)
    bind = sessions.kw["bind"]

    def reject(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO move_analyses"):
            raise RuntimeError("injected insert failure")

    event.listen(bind, "before_cursor_execute", reject)
    try:
        with pytest.raises(RuntimeError):
            AnalysisProcessor(store, pipeline[1], settings).process(run)
    finally:
        event.remove(bind, "before_cursor_execute", reject)
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(MoveAnalysis)) == 0
        assert s.scalar(select(func.count()).select_from(PositionCache)) == 5
        assert store.get(run).games_completed == 0
    store.recover(profile)
    process(pipeline, run)
    assert store.get(run).status == Status.DONE


def test_mate_zero_winner_and_no_cp_conversion(pipeline, sessions, player_id):
    store, engine, _, profile = pipeline
    pgn = PGN.split("\n\n")[0].replace("1-0", "0-1") + "\n\n1. f3 e5 2. g4 Qh4# 0-1"
    ids = seed(sessions, player_id, pgn=pgn)
    run = store.create(player_id, profile)
    process(pipeline, run)
    last = store.moves(ids[0], profile.hash)[-1]
    assert last.mate_after_white == 0 and last.mate_after_winner is False
    assert last.loss_cp is None and engine.calls == 4
    assert store.get(run).terminal_positions == 1


def test_history_and_profile_cache_misses(pipeline, sessions, player_id):
    store, _, _, profile = pipeline
    seed(sessions, player_id)
    run = store.create(player_id, profile)
    process(pipeline, run)
    board = chess.Board()
    assert store.cached(board, False, profile) is not None
    assert store.cached(board, True, profile) is None
    assert store.cached(board, False, replace(profile, engine="new-engine")) is None
    for move in ["g1f3", "g8f6", "f3g1", "f6g8"]:
        board.push_uci(move)
    bare = chess.Board(board.fen())
    assert history_hash(bare, False) != history_hash(board, False)
    assert store.cached(board, False, profile) is None


def test_api_start_progress_conflict_cancel_and_restart(pipeline, sessions, player_id):
    store, _, settings, _profile = pipeline
    seed(sessions, player_id)
    app.dependency_overrides[get_analysis_service] = lambda: AnalysisService(store)
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            assert (
                client.post(
                    "/api/v1/analysis-runs", json={"tracked_player_id": player_id}
                ).status_code
                == 503
            )
            with worker_guard(settings.database_path):
                response = client.post(
                    "/api/v1/analysis-runs", json={"tracked_player_id": player_id}
                )
                assert response.status_code == 202
                run = response.json()["id"]
                assert response.json()["status"] == "queued"
                assert (
                    client.post(
                        "/api/v1/analysis-runs", json={"tracked_player_id": player_id}
                    ).status_code
                    == 409
                )
                process(pipeline, run)
                response = client.get(f"/api/v1/analysis-runs/{run}")
                assert response.json()["progress_percent"] == 100
                assert client.get("/health").status_code == 200
            with TestClient(app, base_url="http://127.0.0.1") as restarted:
                data = restarted.get(f"/api/v1/analysis-runs/{run}").json()
                assert (
                    data["status"] == "completed" and data["worker_available"] is False
                )
                assert restarted.get("/api/v1/analysis-runs/99999").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_single_worker_guard(pipeline):
    _, _, settings, _ = pipeline
    with (
        worker_guard(settings.database_path),
        pytest.raises(WorkerAlreadyRunning),
        worker_guard(settings.database_path),
    ):
        pytest.fail("second owner")
    with worker_guard(settings.database_path):
        pass


def test_transitions():
    for final in set(Status) - {Status.PENDING, Status.RUNNING}:
        with pytest.raises(ValueError):
            transition(final, Status.RUNNING)
    transition(Status.PENDING, Status.RUNNING)
    transition(Status.RUNNING, Status.COMPLETED_WITH_ERRORS)


def test_invalid_engine_pv_rejected_without_completion(pipeline, sessions, player_id):
    store, engine, _settings, profile = pipeline
    seed(sessions, player_id)
    original = engine.analyze
    engine.analyze = lambda board, **kwargs: replace(
        original(board), best_move_uci="e2e5", pv_uci=("e2e5",)
    )
    run = store.create(player_id, profile)
    process(pipeline, run)
    assert store.get(run).status == Status.COMPLETED_WITH_ERRORS
    assert store.members(run)[0].error_code == "ENGINE_INVALID_RESULT"
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(PositionCache)) == 0
        assert s.scalar(select(func.count()).select_from(MoveAnalysis)) == 0


def test_cache_corruption_is_not_silently_reused(pipeline, sessions, player_id):
    store, _, _, profile = pipeline
    seed(sessions, player_id)
    run = store.create(player_id, profile)
    process(pipeline, run)
    with sessions.begin() as s:
        row = s.scalar(select(PositionCache).order_by(PositionCache.id))
        row.pv_json = ["e2e5"]
    retry = store.create(player_id, profile)
    assert store.get(retry).games_skipped == 0
    process(pipeline, retry)
    assert store.get(retry).status == Status.COMPLETED_WITH_ERRORS
    assert store.members(retry)[0].error_code == "ENGINE_INVALID_RESULT"


def test_recovery_mismatch_preserves_prior_evidence(pipeline, sessions, player_id):
    store, _, _, profile = pipeline
    seed(sessions, player_id)
    run = store.create(player_id, profile)
    store.claim(profile)
    store.recover(replace(profile, engine="different"))
    assert store.get(run).status == Status.FAILED
    assert store.get(run).error_code == "ANALYSIS_PROFILE_MISMATCH"


def test_source_changes_and_membership_snapshot(pipeline, sessions, player_id):
    store, _, _, profile = pipeline
    ids = seed(sessions, player_id)
    run = store.create(player_id, profile)
    with sessions.begin() as s:
        g = s.get(Game, ids[0])
        g.raw_pgn += "\n{changed}"
        s.add(game(player_id, canonical_hash="z" * 64, external_id="later"))
    process(pipeline, run)
    assert store.get(run).games_total == 1
    assert store.get(run).games_failed == 1
    assert len(store.members(run)) == 1


def test_ineligible_games_reported_without_engine_work(pipeline, sessions, player_id):
    store, engine, _, profile = pipeline
    ids = seed(sessions, player_id)
    with sessions.begin() as s:
        s.get(Game, ids[0]).parse_status = ParseStatus.PARSE_FAILED
    run = store.create(player_id, profile)
    assert store.get(run).games_excluded == 1
    assert store.get(run).games_total == 0 and engine.calls == 0


def test_engine_failure_retries_once_then_fails_run(pipeline, sessions, player_id):
    from chess_coach.infrastructure.engine.exceptions import EngineAnalysisError

    store, engine, _, profile = pipeline
    seed(sessions, player_id)
    attempts = []

    def broken(board, **kwargs):
        attempts.append(1)
        raise EngineAnalysisError("hung")

    engine.analyze = broken
    run = store.create(player_id, profile)
    process(pipeline, run)
    assert len(attempts) == 2
    assert store.get(run).status == Status.FAILED
    assert store.get(run).error_code == "ENGINE_UNAVAILABLE"


def test_graceful_shutdown_leaves_recoverable_run(pipeline, sessions, player_id):
    from threading import Event

    store, engine, settings, profile = pipeline
    seed(sessions, player_id)
    run = store.create(player_id, profile)
    store.claim(profile)
    stop = Event()

    def shutdown(kind, identity):
        stop.set()

    AnalysisProcessor(store, engine, settings, stop, shutdown).process(run)
    assert store.get(run).status == Status.RUNNING
    store.recover(profile)
    process(pipeline, run)
    assert store.get(run).status == Status.DONE and engine.calls == 5


def test_missing_final_position_never_finalizes(pipeline, sessions, player_id):
    store, _engine, _settings, profile = pipeline
    ids = seed(sessions, player_id)
    run = store.create(player_id, profile)
    store.claim(profile)
    store.begin_game(run, ids[0])
    parsed = parse_game(PGN, "testplayer")
    with pytest.raises(ValueError, match="Missing required positions"):
        store.finalize(run, ids[0], parsed, profile, [])
    assert store.get(run).games_completed == 0


def test_database_errors_are_safe_api_responses(pipeline):
    from sqlalchemy.exc import OperationalError

    def broken():
        raise OperationalError("private-sql", {}, Exception("secret-path"))

    app.dependency_overrides[get_analysis_service] = broken
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            response = client.get("/api/v1/analysis-runs")
            assert response.status_code == 503
            assert response.json()["code"] == "DATABASE_UNAVAILABLE"
            assert (
                "secret-path" not in response.text
                and "private-sql" not in response.text
            )
    finally:
        app.dependency_overrides.clear()


def test_concurrent_submission_has_one_winner(pipeline, sessions, player_id):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    store, _, _, profile = pipeline
    seed(sessions, player_id)
    gate = Barrier(2)

    def submit():
        gate.wait()
        try:
            return store.create(player_id, profile)
        except AnalysisError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert sum(isinstance(result, int) for result in results) == 1
    assert results.count("ANALYSIS_ALREADY_RUNNING") == 1


def test_cross_origin_mutation_rejected(pipeline):
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post(
            "/api/v1/analysis-runs/1/cancel",
            headers={"origin": "https://untrusted.example"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "ORIGIN_NOT_ALLOWED"


def test_worker_lifecycle_closes_engine_and_releases_lock(
    pipeline, monkeypatch, sessions, player_id
):
    import chess_coach.analysis_worker as worker_module

    store, _, settings, profile = pipeline
    seed(sessions, player_id)
    run = store.create(player_id, profile)
    instances = []

    class ContextEngine(FakeEngine):
        closed = False

        def __init__(self, settings):
            instances.append(self)

        def __enter__(self):
            self.start()
            return self

        def __exit__(self, *args):
            self.closed = True

    monkeypatch.setattr(worker_module, "StockfishAdapter", ContextEngine)
    worker_module.run_worker(settings, once=True)
    assert store.get(run).status == Status.DONE
    assert instances[0].closed
    assert store.worker_status()["available"] is False
    with worker_guard(settings.database_path):
        pass


def test_worker_disk_preflight_closes_without_claiming(
    pipeline, monkeypatch, sessions, player_id
):
    from collections import namedtuple

    import chess_coach.analysis_worker as worker_module

    store, _, settings, profile = pipeline
    seed(sessions, player_id)
    run = store.create(player_id, profile)
    closed = []

    class ContextEngine(FakeEngine):
        def __init__(self, settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(True)

    monkeypatch.setattr(worker_module, "StockfishAdapter", ContextEngine)
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(
        worker_module.shutil, "disk_usage", lambda _: Usage(100, 100, 0)
    )
    with pytest.raises(OSError, match="DISK_SPACE_LOW"):
        worker_module.run_worker(settings, once=True)
    assert closed == [True]
    assert store.get(run).status == Status.PENDING
