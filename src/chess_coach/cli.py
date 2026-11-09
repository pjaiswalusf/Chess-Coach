"""Local API and completed-game import entry points."""

import argparse
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

import uvicorn
from sqlalchemy.exc import SQLAlchemyError

from chess_coach.application.errors import OperationError
from chess_coach.application.parse_imported_games import ParseImportedGames
from chess_coach.application.sync_games import SyncGamesService
from chess_coach.config import Settings
from chess_coach.domain.sync import (
    Archive,
    SourceError,
    SyncAlreadyRunning,
    normalize_username,
)
from chess_coach.infrastructure.chesscom.client import ChessComClient
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.parse_repository import ParseRepository
from chess_coach.infrastructure.persistence.session import create_session_factory
from chess_coach.infrastructure.persistence.sync_repository import SyncRepository
from chess_coach.infrastructure.pgn.parser import parse_game


@contextmanager
def _structured_events(name: str, level: str) -> Iterator[None]:
    from chess_coach.analysis_worker import JsonFormatter

    logger = logging.getLogger(name)
    previous_level = logger.level
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.setLevel(level)
    logger.addHandler(handler)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local post-game chess coach")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="Serve the local API (default)")
    sync = commands.add_parser(
        "sync", help="Import completed Chess.com monthly archives"
    )
    sync.add_argument("--username", required=True)
    sync.add_argument("--force", action="store_true")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument(
        "--month", help="Limit import to YYYY/MM, for controlled verification"
    )
    status = commands.add_parser(
        "sync-status", help="Read local import diagnostics without network"
    )
    status.add_argument("--username", required=True)
    validate = commands.add_parser(
        "parse-games", help="Validate locally stored completed-game PGNs"
    )
    validate.add_argument("--username", required=True)
    validate.add_argument(
        "--retry",
        action="store_true",
        help="Explicitly revalidate all stored games for this player",
    )
    commands.add_parser("doctor", help="Check Stockfish startup, analysis, and cleanup")
    worker = commands.add_parser(
        "analysis-worker", help="Run the single local analysis worker"
    )
    worker.add_argument(
        "--once", action="store_true", help="Process one pending run and exit"
    )
    worker.add_argument(
        "--with-coaching",
        action="store_true",
        help="Process queued coaching while no analysis is pending, using the same worker lock",
    )
    coaching_worker = commands.add_parser(
        "coaching-worker",
        help="Process persisted local coaching requests; stop the analysis worker first",
    )
    coaching_worker.add_argument("--once", action="store_true")
    sync_worker = commands.add_parser(
        "sync-worker", help="Process persisted sync requests"
    )
    sync_worker.add_argument("--once", action="store_true")
    features = commands.add_parser(
        "extract-features",
        help="Extract offline facts from completed games; no engine/model calls",
    )
    features.add_argument("--username", required=True)
    features.add_argument(
        "--profile", required=True, help="Existing analysis profile hash, or board-only"
    )
    analytics = commands.add_parser(
        "analytics-health",
        help="Read-only longitudinal report and readiness diagnostics",
    )
    analytics.add_argument("--player-id", type=int, required=True)
    analytics.add_argument("--profile", required=True)
    analytics.add_argument(
        "--window",
        default="all",
        choices=["all", "last_20", "last_50", "last_100", "date_range"],
    )
    analytics.add_argument("--start", help="Inclusive ISO timestamp with timezone")
    analytics.add_argument("--end", help="Exclusive ISO timestamp with timezone")
    training = commands.add_parser(
        "training", help="Generate puzzles from completed local analysis"
    )
    generate = training.add_subparsers(
        dest="training_command", required=True
    ).add_parser("generate")
    generate.add_argument("--player-id", type=int, required=True)
    generate.add_argument(
        "--profile", required=True, help="Completed analysis profile hash"
    )
    generate.add_argument("--after-move-id", type=int, default=0)
    generate.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command in (None, "serve"):
        with _structured_events("chess_coach.application.training", settings.log_level):
            uvicorn.run("chess_coach.api.app:app", host="127.0.0.1", port=8000)
        return
    if args.command == "coaching-worker":
        from chess_coach.coaching_worker import run_coaching_worker

        run_coaching_worker(settings, once=args.once)
        return
    if args.command == "sync-worker":
        from chess_coach.sync_worker import run_sync_worker

        run_sync_worker(settings, once=args.once)
        return
    if args.command == "analysis-worker":
        from chess_coach.analysis_worker import run_worker

        run_worker(settings, once=args.once, with_coaching=args.with_coaching)
        return
    if args.command == "doctor":
        from chess_coach.infrastructure.engine.diagnostics import diagnose

        raise SystemExit(diagnose(settings))
    engine = create_database_engine(settings.database_url)
    try:
        if args.command == "training":
            from chess_coach.application.generate_puzzles import (
                generate_puzzles,
                guard_idle,
            )
            from chess_coach.infrastructure.analysis_lock import worker_guard
            from chess_coach.infrastructure.engine.stockfish_adapter import (
                StockfishAdapter,
            )
            from chess_coach.infrastructure.persistence.training_repository import (
                TrainingRepository,
            )

            with (
                _structured_events(
                    "chess_coach.application.generate_puzzles", settings.log_level
                ),
                worker_guard(settings.database_path),
            ):
                training_store = TrainingRepository(create_session_factory(engine))
                guard_idle(training_store)
                verification_settings = settings.model_copy(
                    update={"stockfish_threads": settings.training_stockfish_threads}
                )
                training_report = generate_puzzles(
                    training_store,
                    StockfishAdapter(verification_settings),
                    verification_settings,
                    args.player_id,
                    args.profile,
                    args.after_move_id,
                    args.limit,
                )
            print(json.dumps(asdict(training_report), indent=2))
            if training_report.errors:
                raise SystemExit(1)
            return
        if args.command == "analytics-health":
            from chess_coach.analytics.contracts import AnalyticsRequest, ReportStatus
            from chess_coach.analytics.service import AnalyticsService
            from chess_coach.infrastructure.persistence.analytics_repository import (
                AnalyticsRepository,
            )

            report_analytics = AnalyticsService(
                AnalyticsRepository(create_session_factory(engine))
            ).build_report(
                AnalyticsRequest.model_validate(
                    {
                        "player_id": args.player_id,
                        "profile_hash": args.profile,
                        "window": args.window,
                        "start_date": args.start,
                        "end_date": args.end,
                    }
                )
            )
            print(report_analytics.model_dump_json(indent=2))
            if report_analytics.status == ReportStatus.DATA_ERROR:
                raise SystemExit(1)
            return
        if args.command == "extract-features":
            from chess_coach.application.features import ExtractFeatures
            from chess_coach.infrastructure.persistence.feature_repository import (
                FeatureRepository,
            )

            report_features = ExtractFeatures(
                FeatureRepository(create_session_factory(engine))
            ).run(args.username, args.profile)
            print(json.dumps(asdict(report_features), indent=2))
            if report_features.games_failed:
                raise SystemExit(1)
            return
        if args.command == "parse-games":
            report_parse = ParseImportedGames(
                ParseRepository(create_session_factory(engine), settings.database_path),
                parse_game,
                max_bytes=settings.pgn_max_bytes,
            ).run(args.username, retry=args.retry)
            print(json.dumps(asdict(report_parse), indent=2))
            return
        store = SyncRepository(create_session_factory(engine), settings.database_path)
        if args.command == "sync-status":
            print(
                json.dumps(
                    store.diagnostics(normalize_username(args.username)), indent=2
                )
            )
            return
        month = None
        if args.month:
            try:
                year, number = args.month.split("/")
                month = Archive(int(year), int(number))
            except ValueError:
                parser.error("--month must be YYYY/MM with a valid archive date")
        with ChessComClient() as provider:
            store = SyncRepository(
                create_session_factory(engine), settings.database_path
            )
            report = SyncGamesService(provider, store).sync(
                args.username, force=args.force, dry_run=args.dry_run, month=month
            )
        print(json.dumps(asdict(report), indent=2))
        if report.status in {"FAILED", "PARTIAL"}:
            raise SystemExit(1)
    except (SourceError, SyncAlreadyRunning, OperationError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}))
        raise SystemExit(1) from None
    except SQLAlchemyError:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "error": "DATABASE_ERROR: check database access and run uv run alembic upgrade head.",
                }
            )
        )
        raise SystemExit(1) from None
    finally:
        engine.dispose()
