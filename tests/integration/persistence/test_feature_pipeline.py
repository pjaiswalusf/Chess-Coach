"""Migrated SQLite, existing engine evidence, failures and restart checkpoints."""

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import OperationalError
from test_analysis_pipeline import pipeline as analysis_pipeline
from test_analysis_pipeline import process, seed

from chess_coach.analytics.features import extract_game_features
from chess_coach.application.features import ExtractFeatures
from chess_coach.infrastructure.persistence.feature_repository import FeatureRepository
from chess_coach.infrastructure.persistence.models import (
    Game,
    MoveAnalysis,
    MoveFeature,
)
from chess_coach.infrastructure.pgn.parser import parse_game

pipeline = analysis_pipeline


def prepared(pipeline, sessions, player_id, count=1):
    ids = seed(sessions, player_id, count)
    run = pipeline[0].create(player_id, pipeline[3])
    process(pipeline, run)
    return ids, FeatureRepository(sessions), pipeline[3].hash


def test_roundtrip_idempotence_and_no_engine(
    pipeline, sessions, player_id, monkeypatch
):
    ids, store, profile = prepared(pipeline, sessions, player_id)
    calls = pipeline[1].calls
    monkeypatch.setattr(
        pipeline[1], "analyze", lambda *a, **k: pytest.fail("Engine called")
    )
    report = ExtractFeatures(store).run("testplayer", profile)
    assert (report.games_completed, report.valid_moves, report.games_failed) == (
        1,
        4,
        0,
    )
    snapshot = store.load(ids[0], profile)
    parsed = parse_game(snapshot.source.raw_pgn, "testplayer")
    assert store.get(snapshot) == extract_game_features(
        ids[0], parsed, snapshot.analyses
    )
    report = ExtractFeatures(store).run("testplayer", profile)
    assert report.games_skipped == 1 and pipeline[1].calls == calls
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(MoveFeature)) == 4
        assert s.scalar(select(func.count()).select_from(MoveAnalysis)) == 4


def test_board_only_and_profile_separation(pipeline, sessions, player_id):
    ids, store, profile = prepared(pipeline, sessions, player_id)
    service = ExtractFeatures(store)
    assert service.run("testplayer", "board-only").games_completed == 1
    f = store.get(store.load(ids[0], "board-only"))[0]
    assert f.engine_advantage_before is None
    assert service.run("testplayer", profile).games_completed == 1
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(MoveFeature)) == 8
    assert service.run("testplayer", "does-not-exist").reasons == {
        "ANALYSIS_NOT_READY": 1
    }


def test_interruption_resume_and_missing_row_repair(pipeline, sessions, player_id):
    ids, store, profile = prepared(pipeline, sessions, player_id, 3)

    def interrupt(game_id):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        ExtractFeatures(store, interrupt).run("testplayer", profile)
    assert len(store.get(store.load(ids[0], profile))) == 4
    report = ExtractFeatures(store).run("testplayer", profile)
    assert report.games_skipped == 1 and report.games_completed == 2
    with sessions.begin() as s:
        s.execute(
            delete(MoveFeature).where(
                MoveFeature.game_id == ids[0], MoveFeature.ply == 2
            )
        )
    report = ExtractFeatures(store).run("testplayer", profile)
    assert report.games_completed == 1 and report.games_skipped == 2
    assert len(store.get(store.load(ids[0], profile))) == 4


def test_atomic_rollback_and_failure_isolation(pipeline, sessions, player_id):
    ids, store, profile = prepared(pipeline, sessions, player_id, 2)
    bind = sessions.kw["bind"]
    inserts = 0

    def fail(connection, cursor, statement, parameters, context, executemany):
        nonlocal inserts
        if statement.startswith("INSERT INTO move_features"):
            inserts += 1
            if inserts == 2:
                raise OperationalError("injected", {}, Exception("disk"))

    event.listen(bind, "before_cursor_execute", fail)
    try:
        report = ExtractFeatures(store).run("testplayer", profile)
    finally:
        event.remove(bind, "before_cursor_execute", fail)
    assert report.games_failed == 1 and report.games_completed == 1
    assert store.get(store.load(ids[0], profile)) == []
    assert len(store.get(store.load(ids[1], profile))) == 4
    assert ExtractFeatures(store).run("testplayer", profile).games_completed == 1
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(MoveAnalysis)) == 8


def test_corrupt_analysis_fails_one_game_and_optional_missing_row(
    pipeline, sessions, player_id
):
    ids, store, profile = prepared(pipeline, sessions, player_id, 2)
    with sessions.begin() as s:
        s.scalar(
            select(MoveAnalysis).where(MoveAnalysis.game_id == ids[0])
        ).fen_before = "bad"
        s.execute(
            delete(MoveAnalysis).where(
                MoveAnalysis.game_id == ids[1], MoveAnalysis.ply == 2
            )
        )
    report = ExtractFeatures(store).run("testplayer", profile)
    assert report.reasons == {"ANALYSIS_ALIGNMENT_FAILED": 1}
    assert report.games_completed == 1
    fs = store.get(store.load(ids[1], profile))
    assert len(fs) == 4 and fs[1].engine_advantage_before is None


def test_stale_source_rejected_and_changed_snapshot_preserved(
    pipeline, sessions, player_id
):
    ids, store, profile = prepared(pipeline, sessions, player_id)
    ExtractFeatures(store).run("testplayer", profile)
    old = store.load(ids[0], profile)
    with sessions.begin() as s:
        row = s.scalar(
            select(MoveAnalysis).where(
                MoveAnalysis.game_id == ids[0], MoveAnalysis.ply == 1
            )
        )
        row.eval_before_cp_white = 200
    new = store.load(ids[0], profile)
    assert new.input_hash != old.input_hash
    assert ExtractFeatures(store).run("testplayer", profile).games_completed == 1
    assert len(store.get(old)) == 4 and len(store.get(new)) == 4
    with pytest.raises(ValueError, match="FEATURE_INPUT_CHANGED"):
        store.save(old, store.get(old))
    with sessions.begin() as s:
        s.get(Game, ids[0]).raw_pgn += "\n{changed}"
    assert ExtractFeatures(store).run("testplayer", profile).reasons == {
        "ANALYSIS_NOT_READY": 1
    }


def test_invalid_feature_payload_rebuilt(pipeline, sessions, player_id):
    ids, store, profile = prepared(pipeline, sessions, player_id)
    ExtractFeatures(store).run("testplayer", profile)
    with sessions.begin() as s:
        row = s.scalar(select(MoveFeature))
        row.features_json = row.features_json | {"time_used_seconds": -10}
    assert ExtractFeatures(store).run("testplayer", profile).games_completed == 1
    assert len(store.get(store.load(ids[0], profile))) == 4


def test_source_completion_enforced(sessions, player_id):
    ids = seed(sessions, player_id, 2)
    with sessions.begin() as s:
        s.get(Game, ids[0]).raw_pgn = s.get(Game, ids[0]).raw_pgn.replace("1-0", "*")
        s.get(Game, ids[1]).platform = "chess.com"
    report = ExtractFeatures(FeatureRepository(sessions)).run(
        "testplayer", "board-only"
    )
    assert report.games_failed == 2 and report.games_completed == 0


def test_concurrent_finalizers(pipeline, sessions, player_id):
    from concurrent.futures import ThreadPoolExecutor

    ids, store, profile = prepared(pipeline, sessions, player_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(
            pool.map(
                lambda _: ExtractFeatures(store).run("testplayer", profile), range(2)
            )
        )
    assert all(r.games_failed == 0 for r in reports)
    assert len(store.get(store.load(ids[0], profile))) == 4


def test_truncated_set_cannot_replace_committed_features(pipeline, sessions, player_id):
    ids, store, profile = prepared(pipeline, sessions, player_id)
    ExtractFeatures(store).run("testplayer", profile)
    snapshot = store.load(ids[0], profile)
    original = store.get(snapshot)
    for partial in [[], original[:2]]:
        with pytest.raises(ValueError, match="FEATURE_SET_INVALID"):
            store.save(snapshot, partial)
        assert store.get(snapshot) == original


def test_version_change_preserves_prior_snapshot(
    pipeline, sessions, player_id, monkeypatch
):
    import chess_coach.infrastructure.persistence.feature_repository as repository

    ids, store, profile = prepared(pipeline, sessions, player_id)
    ExtractFeatures(store).run("testplayer", profile)
    snapshot_v1 = store.load(ids[0], profile)
    fs = store.get(snapshot_v1)
    monkeypatch.setattr(repository, "FEATURE_EXTRACTOR_VERSION", 2)
    snapshot_v2 = store.load(ids[0], profile)
    assert snapshot_v2.input_hash != snapshot_v1.input_hash
    store.save(snapshot_v2, [f.model_copy(update={"feature_version": 2}) for f in fs])
    assert all(f.feature_version == 2 for f in store.get(snapshot_v2))
    monkeypatch.setattr(repository, "FEATURE_EXTRACTOR_VERSION", 1)
    assert store.get(snapshot_v1) == fs


def test_cli_offline_features(sessions, player_id, capsys):
    import json

    from chess_coach.cli import main

    seed(sessions, player_id)
    main(["extract-features", "--username", "testplayer", "--profile", "board-only"])
    assert json.loads(capsys.readouterr().out)["games_completed"] == 1
    with pytest.raises(SystemExit) as exc:
        main(["extract-features", "--username", "testplayer", "--profile", "invalid"])
    assert exc.value.code == 1
