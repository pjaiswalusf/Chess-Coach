"""Real migrations and persisted evidence, fake engine only in fixture preparation."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select, text
from test_analysis_pipeline import pipeline as analysis_pipeline
from test_analysis_pipeline import seed
from test_feature_pipeline import prepared

from chess_coach.analytics.contracts import AnalyticsReport, AnalyticsRequest
from chess_coach.analytics.service import AnalyticsService
from chess_coach.application.features import ExtractFeatures
from chess_coach.cli import main
from chess_coach.domain.analysis import fingerprint
from chess_coach.infrastructure.persistence.analytics_repository import (
    AnalyticsRepository,
)
from chess_coach.infrastructure.persistence.feature_repository import FeatureRepository
from chess_coach.infrastructure.persistence.models import (
    AnalysisRun,
    Game,
    GameAnalysisState,
    MoveAnalysis,
    MoveFeature,
    PositionCache,
    TrackedPlayer,
)

pipeline = analysis_pipeline


def build(sessions, player_id, profile, **kwargs):
    return AnalyticsService(AnalyticsRepository(sessions)).build_report(
        AnalyticsRequest(player_id=player_id, profile_hash=profile, **kwargs)
    )


def dump(sessions):
    with sessions() as s:
        return {
            table: s.execute(text(f"SELECT * FROM {table}")).all()
            for table in [
                "games",
                "move_analyses",
                "move_features",
                "game_analysis_states",
                "position_cache",
                "analysis_runs",
            ]
        }


def test_real_snapshot_roundtrip_read_only_no_engine(
    pipeline, sessions, player_id, monkeypatch
):
    ids, _, profile = prepared(pipeline, sessions, player_id, 10)
    monkeypatch.setattr(
        pipeline[1], "analyze", lambda *a, **k: pytest.fail("engine called")
    )
    before = dump(sessions)
    report = build(sessions, player_id, profile)
    assert report.status == "COMPLETE", report.health
    assert report.health.analyzed_games == 10
    assert report.overall.moves.player_moves == 20
    assert report.overall.moves.comparable_moves == 20
    assert report.overall.moves.mean_loss_cp == 0
    assert report.overall.win_rate.per_100 == 100
    assert report.health.clock_data_coverage == 0
    assert report.health.integrity == "PASS"
    assert AnalyticsReport.model_validate_json(report.model_dump_json()) == report
    assert build(sessions, player_id, profile) == report
    assert dump(sessions) == before
    assert (
        sum(
            phase.summary.moves.player_moves
            for phase in report.phase_metrics
            if phase.key != "unclassified"
        )
        == 20
    )
    assert set(report.selected_game_ids) == set(ids)
    assert (
        ExtractFeatures(FeatureRepository(sessions))
        .run("testplayer", profile)
        .games_completed
        == 10
    )
    assert build(sessions, player_id, profile) == report


def test_last_twenty_before_analysis_filter_and_query_count(
    pipeline, sessions, player_id
):
    ids, _, profile = prepared(pipeline, sessions, player_id, 25)
    with sessions.begin() as s:
        for i, gid in enumerate(ids):
            s.get(Game, gid).played_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(
                days=i
            )
        for state in s.scalars(
            select(GameAnalysisState).where(GameAnalysisState.game_id.in_(ids[-2:]))
        ):
            state.status = "pending"
    statements = []

    def track(conn, cursor, statement, *args):
        statements.append(statement)

    engine = sessions.kw["bind"]
    event.listen(engine, "before_cursor_execute", track)
    try:
        report = build(sessions, player_id, profile, window="last_20")
    finally:
        event.remove(engine, "before_cursor_execute", track)
    assert report.status == "PARTIAL"
    assert report.selected_game_ids == tuple(reversed(ids[5:]))
    assert report.health.analysis_coverage == 0.9
    assert report.overall.games_played == 20
    assert report.health.analyzed_games == 18
    assert report.health.statuses == {"done": 18, "pending": 2}
    assert len(statements) <= 12, statements


def test_profile_isolation_missing_features_and_other_players(
    pipeline, sessions, player_id
):
    ids, _, profile = prepared(pipeline, sessions, player_id)
    report = build(sessions, player_id, profile)
    assert report.health.integrity == "PASS"
    assert any(
        m.key != "unclassified" and m.summary.moves.player_moves > 0
        for m in report.phase_metrics
    )
    assert build(sessions, player_id, "other").health.statuses == {"incompatible": 1}
    with sessions.begin() as s:
        p = TrackedPlayer(username="other", platform="pgn")
        s.add(p)
        s.flush()
        other = p.id
    assert build(sessions, other, profile).status == "NO_GAMES"
    with pytest.raises(ValueError, match="PLAYER_NOT_FOUND"):
        build(sessions, 9999, profile)
    with sessions.begin() as s:
        s.get(Game, ids[0]).parse_status = "incomplete"
    assert build(sessions, player_id, profile).status == "NO_GAMES"


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing", "MISSING_MOVE_ANALYSIS"),
        ("loss", "INVALID_LOSS"),
        ("negative", "INVALID_LOSS"),
        ("infinity", "INVALID_LOSS"),
        ("attribution", "PLAYER_ATTRIBUTION_INVALID"),
        ("version", "INCOMPATIBLE_ANALYSIS"),
        ("score", "ANALYSIS_SCORE_INVALID"),
        ("history", "POSITION_HISTORY_INVALID"),
        ("source", "ANALYSIS_SOURCE_CHANGED"),
        ("provenance", "ANALYSIS_PROVENANCE_MISSING"),
        ("profile", "INCOMPATIBLE_ANALYSIS"),
        ("position", "MISSING_POSITION_EVIDENCE"),
        ("severity", "SEVERITY_POLICY_MISMATCH"),
    ],
)
def test_corrupt_complete_evidence_blocks_report(
    pipeline, sessions, player_id, mutation, code
):
    _ids, _, profile = prepared(pipeline, sessions, player_id)
    with sessions.begin() as s:
        s.execute(text("PRAGMA ignore_check_constraints=ON"))
        row = s.scalar(select(MoveAnalysis).order_by(MoveAnalysis.ply))
        state = s.scalar(select(GameAnalysisState))
        if mutation == "missing":
            s.delete(row)
        elif mutation == "loss":
            row.loss_cp = 999
        elif mutation == "negative":
            row.loss_cp = -1
        elif mutation == "infinity":
            s.execute(
                text("UPDATE move_analyses SET loss_cp=:value"), {"value": float("inf")}
            )
        elif mutation == "attribution":
            row.mover = "black"
        elif mutation == "version":
            row.analysis_version = "bad"
        elif mutation == "score":
            row.eval_before_cp_white = 999
        elif mutation == "history":
            s.get(PositionCache, state.position_ids[0]).history_hash = "wrong"
        elif mutation == "source":
            state.source_hash = "wrong"
        elif mutation == "provenance":
            state.analysis_run_id = None
        elif mutation == "profile":
            s.get(AnalysisRun, state.analysis_run_id).engine_config_json = {
                "nodes": 999
            }
        elif mutation == "position":
            state.position_ids = []
        elif mutation == "severity":
            row.severity = "critical"
    # integrity_check detects intentional CHECK violations first.
    report = build(sessions, player_id, profile)
    assert report.status == "DATA_ERROR"
    assert code in [
        e.code for e in report.health.errors
    ] or "DATABASE_INTEGRITY_FAILED" in [e.code for e in report.health.errors]
    assert not report.ranked_weaknesses and report.overall is None


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("payload", "INVALID_STORED_EVIDENCE"),
        ("phase", "INVALID_STORED_EVIDENCE"),
        ("hash", "FEATURE_CONTENT_INVALID"),
        ("column", "FEATURE_CONTENT_INVALID"),
        ("missing", "FEATURE_SET_INVALID"),
    ],
)
def test_feature_snapshot_failures(pipeline, sessions, player_id, mutation, code):
    _, store, profile = prepared(pipeline, sessions, player_id)
    ExtractFeatures(store).run("testplayer", profile)
    with sessions.begin() as s:
        row = s.scalar(select(MoveFeature).order_by(MoveFeature.ply))
        if mutation == "payload":
            row.features_json = row.features_json | {"time_used_seconds": -2}
        elif mutation == "phase":
            row.features_json = row.features_json | {"phase": "imaginary"}
            row.content_hash = fingerprint(row.features_json)
        elif mutation == "hash":
            row.content_hash = "bad"
        elif mutation == "column":
            row.phase = "endgame"
        elif mutation == "missing":
            s.delete(row)
    report = build(sessions, player_id, profile)
    assert report.status == "DATA_ERROR"
    assert code in [e.code for e in report.health.errors]


def test_snapshot_isolation_while_worker_commits(pipeline, sessions, player_id):
    _ids, _, profile = prepared(pipeline, sessions, player_id)
    engine = sessions.kw["bind"]
    changed = False

    def after(conn, cursor, statement, *args):
        nonlocal changed
        if not changed and statement.startswith("SELECT games."):
            changed = True
            with sessions.begin() as writer:
                writer.scalar(select(GameAnalysisState)).status = "pending"

    event.listen(engine, "after_cursor_execute", after)
    try:
        report = build(sessions, player_id, profile)
    finally:
        event.remove(engine, "after_cursor_execute", after)
    assert changed
    assert report.health.statuses == {"done": 1}
    assert build(sessions, player_id, profile).health.statuses == {"pending": 1}


def test_cli_and_unknown_profile(pipeline, sessions, player_id, capsys):
    _, _, profile = prepared(pipeline, sessions, player_id)
    main(["analytics-health", "--player-id", str(player_id), "--profile", profile])
    assert json.loads(capsys.readouterr().out)["health"]["integrity"] == "PASS"
    with sessions.begin() as s:
        s.scalar(select(GameAnalysisState)).source_hash = "bad"
    with pytest.raises(SystemExit) as exc:
        main(["analytics-health", "--player-id", str(player_id), "--profile", profile])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "DATA_ERROR"


def test_unknown_time_class_filter_matches_null(pipeline, sessions, player_id):
    ids, _, profile = prepared(pipeline, sessions, player_id)
    with sessions.begin() as s:
        s.get(Game, ids[0]).time_class = None
    report = build(sessions, player_id, profile, time_class="UNKNOWN")
    assert report.selected_game_ids == tuple(ids)


def test_black_orientation_capture_response_and_clocks(pipeline, sessions, player_id):
    pgn = '[White "Opponent"]\n[Black "TestPlayer"]\n[Result "0-1"]\n[TimeControl "600+2"]\n\n1. e4 {[%clk 0:09:50]} d5 {[%clk 0:00:45]} 2. exd5 {[%clk 0:09:40]} Qxd5 {[%clk 0:00:30]} 3. Nc3 {[%clk 0:09:30]} Qe6+ {[%clk 0:00:20]} 4. Be2 {[%clk 0:09:20]} Nc6 {[%clk 0:00:10]} 0-1'
    ids = seed(sessions, player_id, pgn=pgn)
    with sessions.begin() as s:
        g = s.get(Game, ids[0])
        g.white_username, g.black_username = "Opponent", "TestPlayer"
        g.player_color, g.result, g.time_control = "black", "win", "600+2"
    from test_analysis_pipeline import process

    run = pipeline[0].create(player_id, pipeline[3])
    process(pipeline, run)
    profile = pipeline[3].hash
    ExtractFeatures(FeatureRepository(sessions)).run("testplayer", profile)
    dataset = AnalyticsRepository(sessions).load(
        AnalyticsRequest(player_id=player_id, profile_hash=profile)
    )
    assert not dataset.errors
    game = dataset.games[0]
    assert [m.ply for m in game.moves] == [2, 4, 6, 8]
    assert [m.before_cp for m in game.moves] == [-20, -60, -100, -140]
    assert [m.after_cp for m in game.moves] == [-40, -80, -120, -160]
    assert all(m.loss_cp == 20 for m in game.moves)
    assert [m.after_capture for m in game.moves] == [False, True, False, False]
    # First pre-move clock is 600, even though its post-move clock is only 45.
    assert [m.under_time_pressure for m in game.moves] == [False, True, True, True]
    report = build(sessions, player_id, profile)
    assert report.overall.moves.mean_loss_cp == 20
    assert report.overall.wins == 1
    capture = next(c for c in report.behavioral_metrics if c.key == "after_capture")
    assert capture.opportunities.player_moves == 1


def test_request_dates_color_version_and_failed_status(pipeline, sessions, player_id):
    ids, _, profile = prepared(pipeline, sessions, player_id, 2)
    start = datetime(2026, 2, 1, tzinfo=UTC)
    with sessions.begin() as s:
        s.get(Game, ids[0]).played_at = start
        s.get(Game, ids[1]).played_at = start + timedelta(days=1)
        s.scalar(
            select(GameAnalysisState).where(GameAnalysisState.game_id == ids[0])
        ).status = "failed"
    report = build(
        sessions,
        player_id,
        profile,
        window="date_range",
        start_date=start,
        end_date=start + timedelta(days=1),
        color="white",
    )
    assert report.selected_game_ids == (ids[0],)
    assert report.health.statuses == {"failed": 1}
    assert build(sessions, player_id, profile, color="black").status == "NO_GAMES"
    assert build(
        sessions, player_id, profile, analysis_version="other"
    ).health.statuses == {"incompatible": 2}


def test_white_check_and_capture_responses(pipeline, sessions, player_id):
    pgn = '[White "TestPlayer"]\n[Black "Opponent"]\n[Result "1-0"]\n\n1. e4 d5 2. exd5 Qxd5 3. Nc3 Qe6+ 4. Be2 Nc6 1-0'
    seed(sessions, player_id, pgn=pgn)
    from test_analysis_pipeline import process

    run = pipeline[0].create(player_id, pipeline[3])
    process(pipeline, run)
    report = build(sessions, player_id, pipeline[3].hash)
    context = {c.key: c for c in report.behavioral_metrics}
    assert context["in_check"].opportunities.player_moves == 1
    assert context["after_capture"].opportunities.player_moves == 1
    assert context["after_capture"].unknown_moves == 1
