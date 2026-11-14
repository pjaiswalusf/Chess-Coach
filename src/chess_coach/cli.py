"""Local API and completed-game import entry points."""

import argparse
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import uvicorn
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

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
from chess_coach.observability.logging import configure_logging


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local post-game chess coach")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="Serve the local API (default)")
    pgn_import = commands.add_parser(
        "import-pgn", help="Import completed single-game UTF-8 PGN files"
    )
    pgn_import.add_argument("--username", required=True)
    pgn_import.add_argument(
        "--played-at",
        required=True,
        type=datetime.fromisoformat,
        help="Actual game time as an ISO timestamp with timezone; applies to all files",
    )
    pgn_import.add_argument("files", nargs="+", type=Path)
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
    doctor = commands.add_parser("doctor", help="Check local application dependencies")
    doctor.add_argument(
        "--deep", action="store_true", help="Scan SQLite integrity and foreign keys"
    )
    doctor.add_argument(
        "--strict",
        action="store_true",
        help="Fail when optional checks warn or are skipped",
    )
    commands.add_parser(
        "engine-check", help="Run the fixed-position Stockfish verification"
    )
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
    return parser


def _run_doctor(args: argparse.Namespace) -> None:
    from chess_coach.application.system import overall_status
    from chess_coach.infrastructure.system.diagnostics import diagnose

    configure_logging()
    try:
        checks = diagnose(Settings, deep=args.deep)
    except Exception:
        logging.getLogger(__name__).exception(
            "doctor_failed", extra={"error_code": "DIAGNOSTICS_FAILED"}
        )
        print("Diagnostics could not finish. Check backend logs and retry.")
        raise SystemExit(2) from None
    labels = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}
    print("Chess Coach — Diagnostics")
    for check in checks:
        print(
            f"{labels[check.status]:4}  {check.name.replace('_', ' ').capitalize()}: {check.message}"
        )
        if check.action:
            print(f"      {check.action}")
    overall = overall_status(checks)
    print(f"Overall status: {overall.upper()}")
    if overall != "unavailable":
        print(
            "Available: stored games, historical analysis, deterministic analytics, and stored training."
        )
        states = {check.name: check.status for check in checks}
        if states.get("stockfish") == "pass":
            print("Stockfish is ready. Start the analysis worker to run new analysis.")
        else:
            print("Unavailable: new Stockfish analysis.")
        coaching_ready = states.get("ollama") == states.get("ollama_model") == "pass"
        print(
            f"{'Available' if coaching_ready else 'Unavailable'}: new LLM explanations."
        )
    if overall == "unavailable" or (args.strict and overall != "healthy"):
        raise SystemExit(1)


def _import_pgn(
    args: argparse.Namespace, sessions: sessionmaker[Session], settings: Settings
) -> None:
    from chess_coach.application.import_pgn import import_files
    from chess_coach.infrastructure.persistence.pgn_repository import (
        PGNRepository,
    )

    imported = import_files(
        PGNRepository(sessions),
        args.files,
        args.username,
        args.played_at,
        settings.pgn_max_bytes,
    )
    print(json.dumps(imported, indent=2))
    if imported["rejected"]:
        raise SystemExit(1)


def _training(
    args: argparse.Namespace, sessions: sessionmaker[Session], settings: Settings
) -> None:
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

    with worker_guard(settings.database_path):
        training_store = TrainingRepository(sessions)
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


def _analytics_health(
    args: argparse.Namespace, sessions: sessionmaker[Session]
) -> None:
    from chess_coach.analytics.contracts import AnalyticsRequest, ReportStatus
    from chess_coach.analytics.service import AnalyticsService
    from chess_coach.infrastructure.persistence.analytics_repository import (
        AnalyticsRepository,
    )

    report_analytics = AnalyticsService(AnalyticsRepository(sessions)).build_report(
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


def _extract_features(
    args: argparse.Namespace, sessions: sessionmaker[Session]
) -> None:
    from chess_coach.application.features import ExtractFeatures
    from chess_coach.infrastructure.persistence.feature_repository import (
        FeatureRepository,
    )

    report_features = ExtractFeatures(FeatureRepository(sessions)).run(
        args.username, args.profile
    )
    print(json.dumps(asdict(report_features), indent=2))
    if report_features.games_failed:
        raise SystemExit(1)


def _parse_games(
    args: argparse.Namespace, sessions: sessionmaker[Session], settings: Settings
) -> None:
    report_parse = ParseImportedGames(
        ParseRepository(sessions, settings.database_path),
        parse_game,
        max_bytes=settings.pgn_max_bytes,
    ).run(args.username, retry=args.retry)
    print(json.dumps(asdict(report_parse), indent=2))


def _sync_or_show_status(
    args: argparse.Namespace,
    sessions: sessionmaker[Session],
    settings: Settings,
    parser: argparse.ArgumentParser,
) -> None:
    store = SyncRepository(sessions, settings.database_path)
    if args.command == "sync-status":
        print(
            json.dumps(store.diagnostics(normalize_username(args.username)), indent=2)
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
        prepare = ParseImportedGames(
            ParseRepository(
                store.sessions, settings.database_path, lock_already_held=True
            ),
            parse_game,
            max_bytes=settings.pgn_max_bytes,
        )
        report = SyncGamesService(provider, store, prepare_games=prepare.run).sync(
            args.username, force=args.force, dry_run=args.dry_run, month=month
        )
    print(json.dumps(asdict(report), indent=2))
    if report.status in {"FAILED", "PARTIAL"}:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        _run_doctor(args)
        return
    if args.command in (None, "serve"):
        uvicorn.run(
            "chess_coach.api.app:app", host="127.0.0.1", port=8000, access_log=False
        )
        return
    settings = Settings()
    configure_logging(settings.log_level)
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
    if args.command == "engine-check":
        from chess_coach.infrastructure.engine.diagnostics import (
            diagnose as diagnose_engine,
        )

        raise SystemExit(diagnose_engine(settings))
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        match args.command:
            case "import-pgn":
                _import_pgn(args, sessions, settings)
            case "training":
                _training(args, sessions, settings)
            case "analytics-health":
                _analytics_health(args, sessions)
            case "extract-features":
                _extract_features(args, sessions)
            case "parse-games":
                _parse_games(args, sessions, settings)
            case _:
                _sync_or_show_status(args, sessions, settings, parser)
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
