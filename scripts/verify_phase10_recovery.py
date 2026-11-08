"""Opt-in real-engine SIGKILL/restart proof on a fresh copy of a benchmark DB.

uv run python scripts/verify_phase10_recovery.py /tmp/phase10-bench10.db /tmp/phase10-recovery.db
"""

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from chess_coach.analysis_worker import run_worker
from chess_coach.api.app import app
from chess_coach.api.dependencies import get_analysis_service
from chess_coach.application.analysis import (
    AnalysisProcessor,
    AnalysisService,
    configured_profile,
)
from chess_coach.config import Settings
from chess_coach.infrastructure.analysis_lock import worker_guard
from chess_coach.infrastructure.engine.stockfish_adapter import StockfishAdapter
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
)
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.models import MoveAnalysis
from chess_coach.infrastructure.persistence.session import create_session_factory


def connect(path):
    settings = Settings(database_path=path)
    db = create_database_engine(settings.database_url)
    return settings, db, AnalysisRepository(create_session_factory(db), path)


def crash_child(path):
    settings, db, store = connect(path)
    with worker_guard(path), StockfishAdapter(settings) as engine:
        profile = configured_profile(settings, engine.engine_name)
        store.register(profile)
        run_id = store.claim(profile)
        assert run_id is not None

        def checkpoint(kind, identity):
            if kind == "game" and store.get(run_id).games_completed == 3:
                os.kill(os.getpid(), signal.SIGKILL)

        AnalysisProcessor(store, engine, settings, checkpoint=checkpoint).process(
            run_id
        )
    db.dispose()


def main():
    if sys.argv[1] == "--crash-child":
        crash_child(Path(sys.argv[2]))
        return
    source, destination = map(Path, sys.argv[1:3])
    if destination.exists():
        raise SystemExit("Destination must be a new disposable test database")
    with (
        sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as src,
        sqlite3.connect(destination) as dst,
    ):
        src.backup(dst)
        for table in (
            "analysis_run_games",
            "move_analyses",
            "game_analysis_states",
            "position_cache",
            "analysis_runs",
            "analysis_worker_state",
        ):
            dst.execute(f"DELETE FROM {table}")
    settings, db, store = connect(destination)
    with StockfishAdapter(settings) as engine:
        profile = configured_profile(settings, engine.engine_name)
    run_id = store.create(1, profile)
    app.dependency_overrides[get_analysis_service] = lambda: AnalysisService(store)
    latencies = []
    child = subprocess.Popen(
        [sys.executable, __file__, "--crash-child", str(destination)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with TestClient(app) as client:
            while child.poll() is None:
                start = time.monotonic()
                response = client.get(f"/api/v1/analysis-runs/{run_id}")
                latencies.append(time.monotonic() - start)
                assert response.status_code == 200
                time.sleep(0.02)
        assert child.wait(timeout=10) == -signal.SIGKILL
        interrupted = store.get(run_id)
        assert interrupted.games_completed == 3 and interrupted.status == "running"
        with store.sessions() as session:
            rows_before = session.scalar(select(func.count()).select_from(MoveAnalysis))
        run_worker(settings, once=True)
        finished = store.get(run_id)
        assert finished.status == "done" and finished.games_completed == 10
        with store.sessions() as session:
            rows_after = session.scalar(select(func.count()).select_from(MoveAnalysis))
            duplicate = session.execute(
                select(
                    MoveAnalysis.game_id,
                    MoveAnalysis.ply,
                    MoveAnalysis.profile_hash,
                    func.count(),
                )
                .group_by(
                    MoveAnalysis.game_id, MoveAnalysis.ply, MoveAnalysis.profile_hash
                )
                .having(func.count() > 1)
            ).all()
            assert not duplicate
        second = store.create(1, profile)
        assert (
            store.get(second).games_skipped == 10
            and store.get(second).positions_analyzed == 0
        )
        report = {
            "hard_stop": "SIGKILL",
            "completed_before": 3,
            "move_rows_before": rows_before,
            "completed_after": finished.games_completed,
            "move_rows_after": rows_after,
            "duplicates": len(duplicate),
            "repeat_engine_calls": 0,
            "api_requests_during_analysis": len(latencies),
            "max_api_response_seconds": max(latencies),
        }
        Path(str(destination) + ".json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        app.dependency_overrides.clear()
        db.dispose()


if __name__ == "__main__":
    main()
