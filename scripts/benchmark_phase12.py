"""Offline report benchmark on an isolated SQLite backup.

Optional --scale-games replicates source records for a labelled load test, never
for evidence-quality evaluation. It does not claim new independent game samples.
"""

import argparse
import json
import logging
import os
import socket
import sqlite3
import subprocess
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from chess_coach.analytics.contracts import AnalyticsRequest
from chess_coach.analytics.service import AnalyticsService
from chess_coach.application.features import ExtractFeatures
from chess_coach.config import Settings
from chess_coach.domain.analysis import fingerprint
from chess_coach.infrastructure.persistence.analytics_repository import (
    AnalyticsRepository,
)
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.feature_repository import FeatureRepository
from chess_coach.infrastructure.persistence.models import (
    Game,
    GameAnalysisState,
    MoveAnalysis,
    TrackedPlayer,
)
from chess_coach.infrastructure.persistence.session import create_session_factory


class Measurements(logging.Handler):
    def __init__(self):
        super().__init__()
        self.samples: list[dict[str, float]] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.msg == "analytics_report":
            self.samples.append(
                {
                    key: getattr(record, key)
                    for key in (
                        "retrieval_seconds",
                        "validation_seconds",
                        "aggregation_seconds",
                        "ranking_seconds",
                        "total_seconds",
                    )
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scale-games", type=int)
    args = parser.parse_args()
    if (
        not args.source.is_file()
        or args.database.exists()
        or args.source.resolve() == args.database.resolve()
    ):
        raise SystemExit("Use an existing source and a new isolated destination.")
    with (
        sqlite3.connect(
            args.source.resolve().as_uri() + "?mode=ro", uri=True
        ) as source,
        sqlite3.connect(args.database) as destination,
    ):
        source.backup(destination)
    os.environ["CHESS_COACH_DATABASE_PATH"] = str(args.database)
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_database_engine(Settings(database_path=args.database).database_url)
    sessions = create_session_factory(engine)
    logger = logging.getLogger("chess_coach.analytics.service")
    measurements = Measurements()
    logger.setLevel(logging.INFO)
    logger.addHandler(measurements)
    try:
        with sessions() as s:
            profiles = list(
                s.execute(
                    select(Game.tracked_player_id, GameAnalysisState.profile_hash)
                    .join(GameAnalysisState)
                    .where(GameAnalysisState.status == "done")
                    .distinct()
                )
            )
            if len(profiles) != 1:
                raise SystemExit("Supply one completed player/profile corpus.")
            player_id, profile = profiles[0]
            username = s.get(TrackedPlayer, player_id).username
            original_games = list(
                s.scalars(
                    select(Game)
                    .where(Game.tracked_player_id == player_id)
                    .order_by(Game.id)
                )
            )
        # Copy persisted evidence only in this disposable load-test database.
        if args.scale_games:
            if args.scale_games < len(original_games):
                raise SystemExit("Scale count must be at least the source count.")
            with sessions.begin() as s:
                for i in range(len(original_games), args.scale_games):
                    original = original_games[i % len(original_games)]
                    values = {
                        c.name: getattr(original, c.name)
                        for c in Game.__table__.columns
                        if c.name != "id"
                    }
                    values.update(
                        canonical_hash=fingerprint(["phase12-load-test", i]),
                        external_id=None,
                    )
                    game = Game(**values)
                    s.add(game)
                    s.flush()
                    state = s.scalar(
                        select(GameAnalysisState).where(
                            GameAnalysisState.game_id == original.id,
                            GameAnalysisState.profile_hash == profile,
                        )
                    )
                    s.add(
                        GameAnalysisState(
                            **{
                                c.name: game.id
                                if c.name == "game_id"
                                else getattr(state, c.name)
                                for c in GameAnalysisState.__table__.columns
                                if c.name != "id"
                            }
                        )
                    )
                    for row in s.scalars(
                        select(MoveAnalysis).where(
                            MoveAnalysis.game_id == original.id,
                            MoveAnalysis.profile_hash == profile,
                        )
                    ):
                        s.add(
                            MoveAnalysis(
                                **{
                                    c.name: game.id
                                    if c.name == "game_id"
                                    else getattr(row, c.name)
                                    for c in MoveAnalysis.__table__.columns
                                    if c.name != "id"
                                }
                            )
                        )
        with (
            patch.object(
                subprocess, "Popen", side_effect=AssertionError("No subprocess")
            ),
            patch.object(socket, "socket", side_effect=AssertionError("No network")),
        ):
            prepared = ExtractFeatures(FeatureRepository(sessions)).run(
                username, profile
            )
            if prepared.games_failed:
                raise SystemExit(f"Feature preparation failed: {prepared.reasons}")
            service = AnalyticsService(AnalyticsRepository(sessions))
            request = AnalyticsRequest(player_id=player_id, profile_hash=profile)
            start = perf_counter()
            first = service.build_report(request)
            first_wall = perf_counter() - start
            second = service.build_report(request)
            if first != second:
                raise SystemExit("Report changed without a data change")
            if first.status == "DATA_ERROR":
                raise SystemExit(first.health.model_dump_json())
        output = {
            "sample_policy": "Synthetic load test: replicated source records; not independent historical evidence."
            if args.scale_games
            else "All unique source games with existing engine evidence; no new analysis.",
            "independent_source_games": len(original_games),
            "selected_games": first.health.selected_games,
            "analyzed_games": first.health.analyzed_games,
            "player_moves": first.health.analyzed_player_moves,
            "report_status": first.status,
            "first_wall_seconds": first_wall,
            "timings": measurements.samples,
            "deterministic_repeat": True,
            "subprocess_and_network_calls": 0,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2) + "\n")
        print(json.dumps(output, indent=2))
    finally:
        logger.removeHandler(measurements)
        engine.dispose()


if __name__ == "__main__":
    main()
