"""Local API and completed-game import entry points."""

import argparse
import json
from dataclasses import asdict

import uvicorn
from sqlalchemy.exc import SQLAlchemyError

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
    args = parser.parse_args(argv)
    if args.command in (None, "serve"):
        uvicorn.run("chess_coach.api.app:app", host="127.0.0.1", port=8000)
        return
    settings = Settings()
    if args.command == "analysis-worker":
        from chess_coach.analysis_worker import run_worker

        run_worker(settings, once=args.once)
        return
    if args.command == "doctor":
        from chess_coach.infrastructure.engine.diagnostics import diagnose

        raise SystemExit(diagnose(settings))
    engine = create_database_engine(settings.database_url)
    try:
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
    except (SourceError, SyncAlreadyRunning, ValueError) as exc:
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
