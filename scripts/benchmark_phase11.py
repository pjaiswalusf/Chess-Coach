"""Measure existing real engine evidence in an isolated backup; no engine calls.

uv run python scripts/benchmark_phase11.py --source /tmp/phase10-bench30.db \
  --database /tmp/phase11-bench.db --output docs/benchmarks/phase11.json
"""

import argparse
import json
import os
import socket
import sqlite3
import subprocess
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from alembic import command
from alembic.config import Config

from chess_coach.application.features import ExtractFeatures
from chess_coach.config import Settings
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.feature_repository import FeatureRepository
from chess_coach.infrastructure.persistence.session import create_session_factory

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--database", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if args.database.exists():
    raise SystemExit("Use a new destination database; source is never modified.")
with (
    sqlite3.connect(f"file:{args.source.resolve()}?mode=ro", uri=True) as source,
    sqlite3.connect(args.database) as destination,
):
    source.backup(destination)
os.environ["CHESS_COACH_DATABASE_PATH"] = str(args.database)
command.upgrade(Config("alembic.ini"), "head")
settings = Settings(database_path=args.database)
engine = create_database_engine(settings.database_url)
store = FeatureRepository(create_session_factory(engine))
with sqlite3.connect(args.database) as c:
    profiles = c.execute(
        "SELECT DISTINCT p.username,s.profile_hash FROM game_analysis_states s JOIN games g ON g.id=s.game_id JOIN tracked_players p ON p.id=g.tracked_player_id WHERE s.status='done'"
    ).fetchall()
if len(profiles) != 1:
    raise SystemExit(
        "Select a source corpus with one player/profile for comparable measurements."
    )
username, profile = profiles[0]
try:
    with (
        patch.object(
            subprocess, "Popen", side_effect=AssertionError("No subprocess allowed")
        ),
        patch.object(
            socket, "socket", side_effect=AssertionError("No network allowed")
        ),
    ):
        start = perf_counter()
        report = ExtractFeatures(store).run(username, profile)
        wall = perf_counter() - start
        repeat = ExtractFeatures(store).run(username, profile)
        all_features = []
        games = []
        for game_id in store.candidates(username):
            fs = store.get(store.load(game_id, profile))
            all_features.extend(fs)
            games.append(
                {
                    "game_id": game_id,
                    "plies": len(fs),
                    "phases": dict(Counter(f.phase for f in fs)),
                }
            )
    n = len(all_features)
    output = {
        "sample_policy": f"All {len(games)} unique games in the supplied existing analyzed corpus. Completion provenance is revalidated per game. No new engine analysis.",
        "report": asdict(report),
        "wall_seconds": wall,
        "features_per_extraction_second": n / report.extraction_seconds
        if report.extraction_seconds
        else None,
        "missing_clock_percent": 100 * report.missing_clocks / n if n else None,
        "missing_evaluation_percent": 100 * report.missing_evaluations / n
        if n
        else None,
        "phase_counts": dict(Counter(f.phase for f in all_features)),
        "flag_counts": {
            field: sum(getattr(f, field) is True for f in all_features)
            for field in [
                "played_is_capture",
                "played_gives_check",
                "played_is_castling",
                "queen_moved_early",
                "advantage_lost",
            ]
        },
        "repeat": asdict(repeat),
        "games": games,
        "subprocess_and_network_calls": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k != "games"}, indent=2))
finally:
    engine.dispose()
