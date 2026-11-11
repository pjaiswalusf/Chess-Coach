from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from chess_coach.api.dependencies import (
    get_chesscom_verifier,
    get_query_service,
    get_system_status,
)
from chess_coach.application.analysis import AnalysisProcessor
from chess_coach.application.sync_games import SyncGamesService
from chess_coach.application.system import DependencyStatus, SystemStatus
from chess_coach.domain.sync import Archive, MonthResult, SourceError
from chess_coach.infrastructure.analysis_lock import worker_guard
from chess_coach.infrastructure.persistence.models import (
    AnalysisRun,
    Game,
    ImportRun,
)
from chess_coach.infrastructure.persistence.sync_repository import SyncRepository


def test_empty_player_games_and_analytics(api):
    client = api[0]
    assert client.get("/api/v1/player").json() == {"configured": False, "player": None}
    assert client.get("/api/v1/games").json() == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }
    assert client.post("/api/v1/sync-runs", json={}).status_code == 409
    assert client.get("/api/v1/sync-runs/latest-work").json() == {
        "sync_run_id": None,
        "analysis_run_id": None,
    }
    assert (
        client.post("/api/v1/analysis-runs", json={"scope": "pending"}).status_code
        == 409
    )
    for section in ("summary", "openings", "phases", "patterns"):
        body = client.get(f"/api/v1/analytics/{section}").json()
        assert body["status"] == "NO_GAMES" and body["selected_game_ids"] == []


def test_player_normalization_idempotence_switch_and_invalid_input(api):
    client, _sessions, *_ = api
    first = client.put("/api/v1/player", json={"username": "TestPlayer"})
    assert first.status_code == 200
    assert first.json()["player"]["username"] == "testplayer"
    assert (
        client.put("/api/v1/player", json={"username": "TESTPLAYER"}).json()
        == first.json()
    )
    assert (
        client.put("/api/v1/player", json={"username": "someone_else"}).status_code
        == 409
    )
    for username in (
        "",
        "https://chess.com/x",
        "../x",
        "x\ncontrol",
        "a" * 101,
        "x;pwd",
    ):
        assert (
            client.put("/api/v1/player", json={"username": username}).status_code == 422
        )
    assert (
        client.put(
            "/api/v1/player", json={"username": "x", "database_path": "/tmp/evil"}
        ).status_code
        == 422
    )


def test_first_browser_sync_rejects_missing_account_before_persisting_player(api):
    client, _, _, _, _, _, app = api

    def verify(username):
        if username == "not-found":
            raise SourceError("PLAYER_NOT_FOUND", "private upstream detail")
        return username

    app.dependency_overrides[get_chesscom_verifier] = lambda: verify
    bad = client.put("/api/v1/player", json={"username": "not-found", "verify": True})
    assert bad.status_code == 404
    assert bad.json()["code"] == "PLAYER_NOT_FOUND"
    assert "private upstream detail" not in bad.text
    assert client.get("/api/v1/player").json() == {"configured": False, "player": None}
    assert (
        client.put(
            "/api/v1/player", json={"username": "correct", "verify": True}
        ).status_code
        == 200
    )


def test_result_filter_and_rating_use_tracked_player_perspective(seeded):
    client, sessions, *_ = seeded
    with sessions.begin() as session:
        game = session.get(Game, 1)
        game.player_color, game.result = "black", "loss"
        game.white_rating, game.black_rating = 1800, 1400
    page = client.get("/api/v1/games?result=loss&player_color=black&limit=1").json()
    assert page["total"] == 1
    (item,) = page["items"]
    assert (
        item["id"],
        item["result"],
        item["player_rating"],
        item["critical_errors"],
    ) == (1, "loss", 1400, None)


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "limit=abc",
        "player_color=purple",
        "time_class=fast",
        "analysis_status=bogus",
    ],
)
def test_invalid_pagination_and_filters(api, query):
    response = api[0].get("/api/v1/games?" + query)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_pagination_order_detail_and_pending(seeded):
    client, _, _, engine, *_ = seeded
    first = client.get("/api/v1/games").json()
    second = client.get("/api/v1/games?offset=20").json()
    assert (first["total"], len(first["items"]), len(second["items"])) == (25, 20, 5)
    assert [g["id"] for g in first["items"] + second["items"]] == list(range(25, 0, -1))
    assert "raw_pgn" not in first["items"][0]
    assert client.get("/api/v1/games?player_color=black").json()["total"] == 0
    assert (
        client.get("/api/v1/games/1").json()["completion_provenance"]
        == "pgn_declaration"
    )
    analysis = client.get("/api/v1/games/1/analysis").json()
    assert analysis["status"] == "pending" and analysis["moves"] == []
    assert engine.calls == 0


@pytest.mark.parametrize(
    "path,status",
    [
        ("/games/999", 404),
        ("/games/-1", 422),
        ("/games/no", 422),
        ("/games/999/analysis", 404),
        ("/sync-runs/999", 404),
        ("/sync-runs/-1", 422),
        ("/analysis-runs/999", 404),
        ("/analysis-runs/0", 422),
    ],
)
def test_missing_and_invalid_resources(api, path, status):
    response = api[0].get("/api/v1" + path)
    assert response.status_code == status
    assert set(response.json()) == {"code", "message", "details"}


def test_analysis_evidence_and_analytics_match_existing_service(analyzed):
    client, _, _, engine, _, profile, _app = analyzed
    before = engine.calls
    latest = client.get("/api/v1/sync-runs/latest-work").json()
    assert latest["sync_run_id"] is None
    progress = client.get(
        f"/api/v1/analysis-runs/{latest['analysis_run_id']}/progress"
    ).json()
    assert progress["games_completed"] == 25
    assert progress["games_remaining"] == 0
    assert "games" not in progress
    result = client.get("/api/v1/games/1/analysis").json()
    assert result["status"] == "completed"
    assert [m["ply"] for m in result["moves"]] == [1, 2, 3, 4]
    import chess

    board = chess.Board()
    assert result["initial_fen"] == board.fen()
    for move in result["moves"]:
        assert move["fen_before"] == board.fen()
        assert move["pv_san"] == board.variation_san(
            [chess.Move.from_uci(uci) for uci in move["pv_json"]]
        )
        board.push_san(move["played_move_san"])
        assert move["fen_after"] == board.fen()
        assert move["severity"] == "normal"
        assert move["rating"] == "book"
    assert client.get("/api/v1/games").json()["items"][0]["critical_errors"] == 0
    assert [m["eval_before_cp_white"] for m in result["moves"]] == [0, 20, 40, 60]
    assert [m["loss_cp"] for m in result["moves"]] == [0, 20, 0, 20]
    assert all(m["mate_before_white"] is None for m in result["moves"])
    assert engine.calls == before
    # Compare each HTTP projection with the existing deterministic application service.
    from chess_coach.analytics.contracts import AnalyticsRequest
    from chess_coach.analytics.service import AnalyticsService
    from chess_coach.infrastructure.persistence.analytics_repository import (
        AnalyticsRepository,
    )

    report = AnalyticsService(AnalyticsRepository(analyzed[1])).build_report(
        AnalyticsRequest(player_id=1, profile_hash=profile.hash, window="last_50")
    )
    summary = client.get("/api/v1/analytics/summary").json()
    assert summary["metrics"] == report.overall.model_dump(mode="json")
    for endpoint, field in [
        ("openings", "opening_metrics"),
        ("phases", "phase_metrics"),
    ]:
        body = client.get("/api/v1/analytics/" + endpoint).json()
        assert body["items"] == [
            s.model_dump(mode="json") for s in getattr(report, field)
        ]
        assert body["selected_game_ids"] == summary["selected_game_ids"]
    opening = next(
        item
        for item in client.get("/api/v1/analytics/phases").json()["items"]
        if item["key"] == "opening"
    )
    assert opening["evidence_status"] == "sufficient"
    assert opening["summary"]["moves"]["classifiable_moves"] == 50
    assert (
        client.get("/api/v1/analytics/patterns").json()["patterns"]
        == report.model_dump(mode="json")["ranked_weaknesses"]
    )
    assert (
        client.get("/api/v1/analytics/summary?color=black").json()["metrics"][
            "games_played"
        ]
        == 0
    )


@pytest.mark.parametrize("section", ["summary", "openings", "phases", "patterns"])
@pytest.mark.parametrize(
    "query",
    ["window=date_range", "color=purple", "time_class=fast", "profile_hash=bad"],
)
def test_analytics_shared_validation(api, section, query):
    assert api[0].get(f"/api/v1/analytics/{section}?{query}").status_code == 422


class Provider:
    def get_player(self, username):
        return username

    def get_archives(self, username):
        return [Archive(2026, 1)]

    def get_month_games(self, username, archive, checkpoint=None):
        return MonthResult()


def test_sync_persistence_worker_transitions_and_restart(api):
    client, sessions, _, _, settings, _, app = api
    client.put("/api/v1/player", json={"username": "testplayer"})
    accepted = client.post("/api/v1/sync-runs", json={})
    assert accepted.status_code == 202
    run = accepted.json()["run_id"]
    store = SyncRepository(sessions, settings.database_path)
    assert client.get(f"/api/v1/sync-runs/{run}").json()["status"] == "queued"
    assert client.get("/api/v1/sync-runs/latest-work").json() == {
        "sync_run_id": run,
        "analysis_run_id": None,
    }
    assert client.post("/api/v1/sync-runs", json={}).status_code == 409
    assert client.put("/api/v1/player", json={"username": "other"}).status_code == 409
    SyncGamesService(Provider(), store).sync("testplayer", queued_run_id=run)
    with TestClient(app, base_url="http://127.0.0.1") as restarted:
        result = restarted.get(f"/api/v1/sync-runs/{run}").json()
        assert result["status"] == "completed"
        assert (
            result["progress"]["archives_total"]
            == result["progress"]["archives_processed"]
            == 1
        )
    next_id = store.enqueue(1)
    store.claim(next_id, datetime.now(UTC))
    assert client.get(f"/api/v1/sync-runs/{next_id}").json()["status"] == "running"
    with store.guard():
        store.recover(datetime.now(UTC))
    assert client.get(f"/api/v1/sync-runs/{next_id}").json()["recoverable"] is True
    assert client.get(f"/api/v1/sync-runs/{next_id}").json()["status"] == "failed"
    assert client.post("/api/v1/sync-runs", json={}).status_code == 202


def test_sync_source_failure_is_persisted_without_exception_text(api):
    client, sessions, _, _, settings, *_ = api
    client.put("/api/v1/player", json={"username": "testplayer"})
    run = client.post("/api/v1/sync-runs", json={}).json()["run_id"]

    class Failing(Provider):
        def get_player(self, username):
            raise SourceError("SOURCE_DOWN", "/private/secret")

    SyncGamesService(Failing(), SyncRepository(sessions, settings.database_path)).sync(
        "testplayer", queued_run_id=run
    )
    response = client.get(f"/api/v1/sync-runs/{run}")
    assert response.json()["status"] == "failed"
    assert "/private/secret" not in response.text


def test_cross_operation_double_submission_persists_one_run(seeded):
    _client, sessions, _store, _, settings, _profile, app = seeded
    barrier = Barrier(2)

    def submit(path):
        with TestClient(app, base_url="http://127.0.0.1") as concurrent:
            barrier.wait()
            return concurrent.post(path, json={}).status_code

    with (
        worker_guard(settings.database_path),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        outcomes = list(
            pool.map(submit, ["/api/v1/sync-runs", "/api/v1/analysis-runs"])
        )
    assert sorted(outcomes) == [202, 409]
    with sessions() as s:
        assert (
            s.scalar(select(func.count()).select_from(ImportRun))
            + s.scalar(select(func.count()).select_from(AnalysisRun))
        ) == 1


@pytest.mark.parametrize("kind", ["sync", "analysis"])
def test_same_operation_double_submission(seeded, kind):
    _, sessions, _, _, settings, _, app = seeded
    barrier = Barrier(2)

    def submit(_):
        with TestClient(app, base_url="http://127.0.0.1") as concurrent:
            barrier.wait(timeout=5)
            return concurrent.post(f"/api/v1/{kind}-runs", json={})

    with (
        worker_guard(settings.database_path),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = sorted(
            pool.map(submit, range(2)), key=lambda response: response.status_code
        )
    assert [response.status_code for response in results] == [202, 409]
    assert results[1].json()["code"] == f"{kind.upper()}_ALREADY_RUNNING"
    with sessions() as s:
        table = ImportRun if kind == "sync" else AnalysisRun
        assert s.scalar(select(func.count()).select_from(table)) == 1


def test_analysis_pending_request_completes_and_no_work_avoids_engine(seeded):
    client, _, store, engine, settings, profile, _ = seeded
    with worker_guard(settings.database_path):
        result = client.post("/api/v1/analysis-runs", json={"scope": "pending"})
        assert result.status_code == 202
        run = result.json()["run_id"]
        assert client.post("/api/v1/sync-runs", json={}).status_code == 409
        assert store.claim(profile) == run
        AnalysisProcessor(store, engine, settings).process(run)
        assert (
            client.get(f"/api/v1/analysis-runs/{run}").json()["status"] == "completed"
        )
        calls = engine.calls
        repeat = client.post("/api/v1/analysis-runs", json={})
        assert repeat.status_code == 202 and repeat.json()["status"] == "completed"
        assert repeat.json()["games_skipped"] == 25 and engine.calls == calls
    assert (
        client.post("/api/v1/analysis-runs", json={"threads": 999}).status_code == 422
    )


def test_analysis_rejects_unsupported_version_and_malformed_json(api):
    client, *_ = api
    for response in (
        client.post("/api/v1/analysis-runs", json={"analysis_version": "unknown"}),
        client.post(
            "/api/v1/analysis-runs",
            content="{",
            headers={"Content-Type": "application/json"},
        ),
    ):
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert "Traceback" not in response.text


@pytest.mark.parametrize("failed", ["database", "stockfish", "ollama"])
def test_system_partial_failure(api, failed, monkeypatch):
    client, _, _, _, _, _, app = api
    ready = DependencyStatus("available", "Ready")
    down = DependencyStatus("unavailable", "Unavailable")
    app.dependency_overrides[get_system_status] = lambda: SystemStatus(
        down if failed == "stockfish" else ready,
        down if failed == "ollama" else ready,
        ready,
    )
    if failed == "database":
        from sqlalchemy.exc import OperationalError

        from chess_coach.infrastructure.persistence.query_repository import (
            QueryRepository,
        )

        def unavailable(self):
            raise OperationalError("select", {}, Exception("private path"))

        monkeypatch.setattr(QueryRepository, "statistics", unavailable)
    result = client.get("/api/v1/system")
    assert result.status_code == 200
    assert result.json()["status"] == (
        "unavailable" if failed == "database" else "degraded"
    )
    assert result.json()["components"][failed]["status"] == "unavailable"
    assert (result.json()["statistics"] is None) == (failed == "database")
    assert client.get("/health").json() == {"status": "ok"}


def test_system_counts_completed_profiles(analyzed):
    result = analyzed[0].get("/api/v1/system")
    assert result.json()["statistics"] == {
        "games_stored": 25,
        "games_analyzed": 25,
        "pending_games": 0,
        "positions_cached": 5,
        "active_sync_runs": 0,
        "active_analysis_runs": 0,
        "active_coaching_jobs": 0,
    }


def test_security_errors_and_unexpected_exception(api):
    client, _, _, _, _, _, app = api
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    for headers in (
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
    ):
        response = client.put("/api/v1/player", json={"username": "x"}, headers=headers)
        assert response.status_code == 403
    assert (
        client.put(
            "/api/v1/player",
            content="username=x",
            headers={"Content-Type": "text/plain"},
        ).status_code
        == 422
    )

    def broken():
        raise RuntimeError("/private/path/secret.db")

    app.dependency_overrides[get_query_service] = broken
    result = client.get("/api/v1/player")
    assert result.status_code == 500 and result.json()["code"] == "INTERNAL_ERROR"
    assert "/private" not in result.text


def test_database_failure_does_not_accept_run(api, monkeypatch):
    from sqlalchemy.exc import OperationalError

    client, sessions, *_ = api
    client.put("/api/v1/player", json={"username": "testplayer"})

    def fail(*args):
        raise OperationalError("insert", {}, Exception("/private/db"))

    monkeypatch.setattr(SyncRepository, "enqueue", fail)
    result = client.post("/api/v1/sync-runs", json={})
    assert result.status_code == 503 and result.json()["code"] == "DATABASE_UNAVAILABLE"
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(ImportRun)) == 0


def test_openapi_has_explicit_success_and_error_contracts(api):
    client = api[0]
    schema = client.get("/openapi.json").json()
    for operations in schema["paths"].values():
        for operation in operations.values():
            assert operation["summary"]
            assert operation["responses"]["422"]["content"]["application/json"][
                "schema"
            ]["$ref"].endswith("/ErrorResponse")
            success = operation["responses"].get(
                "202", operation["responses"].get("200")
            )
            assert success["content"]["application/json"]["schema"]
    assert client.get("/docs").status_code == 200


def test_mate_evidence_is_separate_from_centipawns(seeded):
    from dataclasses import asdict

    import chess

    from chess_coach.infrastructure.pgn.parser import parse_game

    client, sessions, store, engine, settings, profile, _ = seeded
    pgn = '[White "TestPlayer"]\n[Black "Opponent"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1'
    parsed = parse_game(pgn, "testplayer")
    metadata = asdict(parsed)
    del metadata["moves"]
    metadata["total_plies"] = parsed.total_plies
    with sessions.begin() as s:
        game = s.get(Game, 1)
        game.raw_pgn, game.result, game.parsed_metadata = pgn, "loss", metadata
    run = store.create(1, profile)
    assert store.claim(profile) == run
    AnalysisProcessor(store, engine, settings).process(run)
    result = client.get("/api/v1/games/1/analysis").json()
    assert result["status"] == "completed"
    terminal = result["moves"][-1]
    assert terminal["mate_after_white"] == 0 and terminal["mate_after_winner"] is False
    assert terminal["eval_after_cp_white"] is None and terminal["loss_cp"] is None
    assert (
        chess.Move.from_uci(terminal["played_move_uci"])
        in chess.Board(terminal["fen_before"]).legal_moves
    )


def test_analysis_interrupted_state_is_recovered_without_losing_work(seeded):
    client, _sessions, store, _, settings, profile, _ = seeded
    run = store.create(1, profile)
    assert store.claim(profile) == run
    store.begin_game(run, 1)
    assert client.get(f"/api/v1/analysis-runs/{run}").json()["status"] == "running"
    with worker_guard(settings.database_path):
        store.recover(profile)
    assert client.get(f"/api/v1/analysis-runs/{run}").json()["status"] == "queued"
    assert store.members(run)[0].status == "pending"
    assert store.claim(profile) == run
    store.fail_game(run, 1, "ENGINE_UNAVAILABLE")
    store.finish(run, "ENGINE_UNAVAILABLE")
    failed = client.get(f"/api/v1/analysis-runs/{run}").json()
    assert failed["status"] == "failed" and failed["games_failed"] == 1
    assert failed["error_code"] == "ENGINE_UNAVAILABLE"


def test_sync_prepares_games_before_publishing_completion(seeded):
    from chess_coach.application.parse_imported_games import ParseImportedGames
    from chess_coach.infrastructure.persistence.parse_repository import ParseRepository
    from chess_coach.infrastructure.pgn.parser import parse_game

    client, sessions, _, _, settings, *_ = seeded
    with sessions.begin() as s:
        s.get(Game, 1).parse_status = "pending"
    run = client.post("/api/v1/sync-runs", json={}).json()["run_id"]
    parser = ParseImportedGames(
        ParseRepository(sessions, settings.database_path, lock_already_held=True),
        parse_game,
    )

    def prepare(username):
        assert client.get(f"/api/v1/sync-runs/{run}").json()["status"] == "running"
        return parser.run(username)

    SyncGamesService(
        Provider(),
        SyncRepository(sessions, settings.database_path),
        prepare_games=prepare,
    ).sync("testplayer", queued_run_id=run)
    assert client.get(f"/api/v1/sync-runs/{run}").json()["status"] == "completed"
    with sessions() as s:
        assert s.get(Game, 1).parse_status == "ready"


def test_game_pending_filter_includes_explicit_pending_states(seeded):
    from chess_coach.domain.analysis import ANALYSIS_VERSION
    from chess_coach.infrastructure.persistence.models import GameAnalysisState

    client, sessions, _, _, _, profile, _ = seeded
    with sessions.begin() as s:
        s.add(
            GameAnalysisState(
                game_id=1,
                profile_hash=profile.hash,
                analysis_version=ANALYSIS_VERSION,
                status="pending",
            )
        )
    result = client.get("/api/v1/games?analysis_status=pending").json()
    assert result["total"] == 25


def test_analysis_rejects_cross_profile_provenance_and_invalid_scores(analyzed):
    from dataclasses import replace

    from chess_coach.infrastructure.persistence.models import (
        GameAnalysisState,
        MoveAnalysis,
    )

    client, sessions, store, engine, settings, profile, _ = analyzed
    changed = replace(profile, config=profile.config | {"nodes": 20000})
    run_b = store.create(1, changed)
    assert store.claim(changed) == run_b
    AnalysisProcessor(store, engine, settings).process(run_b)
    with sessions.begin() as s:
        state_a = s.scalar(
            select(GameAnalysisState).where(
                GameAnalysisState.game_id == 1,
                GameAnalysisState.profile_hash == profile.hash,
            )
        )
        state_a.analysis_run_id = run_b
        move_a = s.scalar(
            select(MoveAnalysis).where(
                MoveAnalysis.game_id == 1,
                MoveAnalysis.profile_hash == profile.hash,
                MoveAnalysis.ply == 1,
            )
        )
        move_a.eval_before_cp_white = 99999
    result = client.get("/api/v1/games/1/analysis?profile_hash=" + profile.hash).json()
    assert result["status"] == "incompatible" and result["moves"] == []
    assert (
        client.get("/api/v1/games/1/analysis?profile_hash=" + changed.hash).json()[
            "status"
        ]
        == "completed"
    )


def test_completed_filter_uses_persisted_status_while_evidence_read_validates_source(
    analyzed,
):
    client, sessions, *_ = analyzed
    with sessions.begin() as s:
        s.get(Game, 1).raw_pgn += "\n{changed source}"
    page = client.get("/api/v1/games?analysis_status=completed&limit=100").json()
    assert page["total"] == 25 and all(
        g["analysis_status"] == "completed" for g in page["items"]
    )
    assert client.get("/api/v1/games/1/analysis").json()["status"] == "incompatible"
