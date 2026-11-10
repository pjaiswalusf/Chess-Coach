"""Opt-in real engine benchmark using declared-complete PGNs in an isolated DB.

uv run python scripts/benchmark_phase10.py --games 10 --database /tmp/phase10-bench10.db
No network; no modifications to the source database.
"""

import argparse
import json
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import chess
from alembic import command
from alembic.config import Config

from chess_coach.analysis_worker import run_worker
from chess_coach.application.analysis import configured_profile
from chess_coach.config import Settings
from chess_coach.domain.analysis import fingerprint
from chess_coach.domain.game_records import PARSER_VERSION
from chess_coach.infrastructure.engine.stockfish_adapter import StockfishAdapter
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
)
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.models import Game, TrackedPlayer
from chess_coach.infrastructure.persistence.session import create_session_factory
from chess_coach.infrastructure.pgn.parser import parse_game

parser = argparse.ArgumentParser()
parser.add_argument("--games", type=int, required=True)
parser.add_argument("--prepare-only", action="store_true")
parser.add_argument("--database", type=Path, required=True)
source_group = parser.add_mutually_exclusive_group()
source_group.add_argument("--source", type=Path, default=Path("data/phase10-before.db"))
source_group.add_argument("--fixtures", action="store_true")
parser.add_argument(
    "--cache-from", type=Path, help="Seed only the position cache from a prior run"
)
args = parser.parse_args()
if args.database.exists():
    raise SystemExit("Use a new isolated database path")
os.environ["CHESS_COACH_DATABASE_PATH"] = str(args.database)
command.upgrade(Config("alembic.ini"), "head")
settings = Settings(database_path=args.database)
db = create_database_engine(settings.database_url)
sessions = create_session_factory(db)
store = AnalysisRepository(sessions, args.database)
if args.fixtures:
    fixtures = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pgn"
    records = [
        ((fixtures / f"{name}.pgn").read_text(), "Pratik")
        for name in (
            "white_win",
            "black_win",
            "checkmate",
            "draw",
            "timeout",
            "clocks",
            "custom",
        )
    ]
else:
    with sqlite3.connect(f"file:{args.source.resolve()}?mode=ro", uri=True) as source:
        records = source.execute(
            "SELECT g.raw_pgn, p.username FROM games g JOIN tracked_players p ON p.id=g.tracked_player_id ORDER BY g.id"
        ).fetchall()
accepted = []
for raw, username in records:
    try:
        parsed = parse_game(raw, username)
    except ValueError:
        continue
    accepted.append((raw, parsed))
    if len(accepted) == args.games:
        break
if len(accepted) != args.games:
    raise SystemExit("Not enough valid completed PGNs")
with sessions.begin() as session:
    player = TrackedPlayer(platform="pgn", username="benchmark")
    session.add(player)
    session.flush()
    player_id = player.id
    # Use actual White usernames: worker revalidates membership against tracked player.
    player.username = accepted[0][1].tracked_player
    for raw, parsed in accepted:
        if player.username.casefold() not in (
            parsed.white_username.casefold(),
            parsed.black_username.casefold(),
        ):
            raise SystemExit("Select games belonging to one player")
        metadata = asdict(parsed)
        del metadata["moves"]
        metadata["total_plies"] = parsed.total_plies
        session.add(
            Game(
                tracked_player_id=player_id,
                platform="pgn",
                canonical_hash=fingerprint(raw),
                raw_pgn=raw,
                played_at=datetime.now(UTC),
                white_username=parsed.white_username,
                black_username=parsed.black_username,
                player_color=parsed.player_color,
                result=parsed.player_result,
                parse_status="ready",
                parser_version=PARSER_VERSION,
                chess_library_version=chess.__version__,
                parsed_metadata=metadata,
            )
        )
if args.cache_from:
    # Both files must use the current migration schema. The source is read-only.
    with (
        closing(sqlite3.connect(args.database.resolve().as_uri(), uri=True)) as target,
        target,
    ):
        target.execute(
            "ATTACH DATABASE ? AS cache_source",
            (f"{args.cache_from.resolve().as_uri()}?mode=ro",),
        )
        target.execute(
            "INSERT INTO position_cache SELECT * FROM cache_source.position_cache"
        )
if args.prepare_only:
    db.dispose()
    raise SystemExit(0)
with StockfishAdapter(settings) as engine:
    profile = configured_profile(settings, engine.engine_name)
run_id = store.create(player_id, profile)
begin = time.monotonic()
run_worker(settings, once=True)
elapsed = time.monotonic() - begin
run = store.get(run_id)
second = store.create(player_id, profile)
report = {
    key: getattr(run, key)
    for key in (
        "status",
        "games_total",
        "games_completed",
        "games_failed",
        "positions_analyzed",
        "cache_hits",
        "cache_misses",
        "terminal_positions",
        "engine_seconds",
    )
}
report.update(
    engine=profile.engine,
    config=profile.config,
    wall_seconds=elapsed,
    total_plies=sum(p.total_plies for _, p in accepted),
    min_plies=min(p.total_plies for _, p in accepted),
    max_plies=max(p.total_plies for _, p in accepted),
    repeat_skipped=store.get(second).games_skipped,
    repeat_engine_calls=store.get(second).positions_analyzed,
)
Path(str(args.database) + ".json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
db.dispose()
