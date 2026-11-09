"""Non-destructive local diagnostics shared by doctor and FastAPI."""

import os
import shlex
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryFile
from typing import Literal

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from chess_coach.application.errors import OperationError
from chess_coach.application.system import CheckResult, DependencyStatus, SystemStatus
from chess_coach.config import Settings
from chess_coach.infrastructure.persistence.engine import create_readonly_engine
from chess_coach.infrastructure.persistence.models import Base
from chess_coach.infrastructure.system.probes import probe_ollama, probe_stockfish

MIGRATE = "Run uv run alembic upgrade head from the project directory."


def directory_check(settings: Settings) -> CheckResult:
    path = settings.database_path.parent
    try:
        with TemporaryFile(dir=path) as probe:
            probe.write(b"chess-coach")
            probe.seek(0)
            if probe.read() != b"chess-coach":
                raise OSError("Probe read failed")
        free_mb = shutil.disk_usage(path).free / 1024**2
    except OSError:
        return CheckResult(
            "data_directory",
            "fail",
            True,
            "The database directory is inaccessible.",
            "Create the configured directory or grant read and write access.",
            "DATA_DIRECTORY_UNAVAILABLE",
        )
    if free_mb < max(500, settings.analysis_min_free_mb):
        return CheckResult(
            "data_directory",
            "fail",
            True,
            "The database directory has too little free space.",
            "Free disk space and retry.",
            "DISK_SPACE_LOW",
        )
    if free_mb < 2000:
        return CheckResult(
            "data_directory",
            "warn",
            True,
            "Free disk space is below 2,000 MiB.",
            "Free disk space before a large import or analysis.",
            "DISK_SPACE_LOW",
        )
    return CheckResult(
        "data_directory",
        "pass",
        True,
        "The database directory is readable and writable.",
    )


def database_checks(path: Path, *, deep: bool = False) -> list[CheckResult]:
    database = CheckResult(
        "database", "pass", True, "The existing SQLite database is readable."
    )
    migrations = CheckResult("migrations", "skip", True, "Database access is required.")
    integrity = CheckResult(
        "database_integrity", "skip", True, "Database access is required."
    )
    if not path.is_file():
        database = CheckResult(
            "database",
            "fail",
            True,
            "The configured SQLite file does not exist.",
            MIGRATE,
            "DATABASE_MISSING",
        )
    elif not os.access(path, os.W_OK):
        database = CheckResult(
            "database",
            "fail",
            True,
            "The SQLite file is read-only for this process.",
            "Grant write access to the configured database file.",
            "DATABASE_READ_ONLY",
        )
    else:
        engine = create_readonly_engine(path)
        try:
            with engine.connect() as connection:
                # Reading sqlite_schema also detects a corrupt or locked database.
                tables = set(
                    connection.exec_driver_sql(
                        "SELECT name FROM sqlite_schema WHERE type = 'table'"
                    ).scalars()
                )
                try:
                    config = Config(
                        str(Path(__file__).resolve().parents[4] / "alembic.ini")
                    )
                    expected = set(ScriptDirectory.from_config(config).get_heads())
                    actual = set(
                        MigrationContext.configure(connection).get_current_heads()
                    )
                    if (
                        not expected
                        or actual != expected
                        or not Base.metadata.tables.keys() <= tables
                    ):
                        migrations = CheckResult(
                            "migrations",
                            "fail",
                            True,
                            "The database schema does not match the application.",
                            MIGRATE,
                            "MIGRATIONS_INCOMPATIBLE",
                        )
                    else:
                        migrations = CheckResult(
                            "migrations",
                            "pass",
                            True,
                            "The schema matches the application.",
                        )
                except SQLAlchemyError, CommandError, OSError:
                    migrations = CheckResult(
                        "migrations",
                        "fail",
                        True,
                        "The schema revision could not be verified.",
                        MIGRATE,
                        "MIGRATIONS_UNVERIFIED",
                    )
                if deep:
                    try:
                        pages = (
                            connection.exec_driver_sql("PRAGMA quick_check")
                            .scalars()
                            .all()
                        )
                        foreign_keys = connection.exec_driver_sql(
                            "PRAGMA foreign_key_check"
                        ).first()
                        ok = pages == ["ok"] and foreign_keys is None
                    except SQLAlchemyError:
                        ok = False
                    integrity = (
                        CheckResult(
                            "database_integrity",
                            "pass",
                            True,
                            "SQLite and foreign-key checks passed.",
                        )
                        if ok
                        else CheckResult(
                            "database_integrity",
                            "fail",
                            True,
                            "SQLite consistency or foreign-key verification failed.",
                            "Inspect a backup of the database before further writes.",
                            "DATABASE_INTEGRITY_FAILED",
                        )
                    )
        except SQLAlchemyError, OSError:
            database = CheckResult(
                "database",
                "fail",
                True,
                "The existing SQLite database could not be read.",
                "Check file access and retry when the database is unlocked.",
                "DATABASE_UNAVAILABLE",
            )
        finally:
            engine.dispose()
    return [database, migrations, integrity] if deep else [database, migrations]


def core_checks(
    load_settings: Callable[[], Settings],
    *,
    deep: bool = False,
) -> tuple[Settings | None, list[CheckResult]]:
    try:
        settings = load_settings()
    except ValidationError, OSError:
        return None, [
            CheckResult(
                "configuration",
                "fail",
                True,
                "Application settings could not be loaded.",
                "Check the CHESS_COACH settings against .env.example.",
                "CONFIG_INVALID",
            )
        ]
    if (sys.version_info.major, sys.version_info.minor) < (3, 14):
        return None, [
            CheckResult(
                "configuration",
                "fail",
                True,
                "Python 3.14 or newer is required.",
                "Run the application through uv.",
                "PYTHON_VERSION_UNSUPPORTED",
            )
        ]
    return settings, [
        CheckResult(
            "configuration",
            "pass",
            True,
            f"Settings loaded with Python {sys.version.split()[0]}.",
        ),
        directory_check(settings),
        *database_checks(settings.database_path, deep=deep),
    ]


def diagnose(
    load_settings: Callable[[], Settings],
    *,
    deep: bool = False,
    probe_optional: Callable[[Settings], SystemStatus] | None = None,
) -> list[CheckResult]:
    settings, checks = core_checks(load_settings, deep=deep)
    if settings is None:
        return checks
    if probe_optional is None:
        engine = probe_stockfish(settings)
        ollama, model = probe_ollama(settings)
        optional = SystemStatus(engine, ollama, model)
    else:
        optional = probe_optional(settings)

    def check(name: str, dependency: DependencyStatus) -> CheckResult:
        states: dict[str, Literal["pass", "warn", "skip"]] = {
            "available": "pass",
            "unavailable": "warn",
            "unknown": "skip",
        }
        state = (
            "warn"
            if dependency.state == "unknown" and dependency.code
            else states[dependency.state]
        )
        actions = {
            "stockfish": "Install Stockfish or check the configured executable.",
            "ollama": "Start Ollama locally and check its configured address.",
            "ollama_model": f"Run ollama pull {shlex.quote(settings.ollama_model)}, then refresh.",
        }
        return CheckResult(
            name,
            state,
            False,
            dependency.detail,
            dependency.action or (actions[name] if state == "warn" else None),
            dependency.code
            or (f"{name.upper()}_UNAVAILABLE" if state == "warn" else None),
        )

    return checks + [
        check("stockfish", optional.stockfish),
        check("ollama", optional.ollama),
        check("ollama_model", optional.ollama_model),
    ]


def require_current_database(path: Path) -> None:
    for check in database_checks(path):
        if check.status == "fail":
            raise OperationError(
                check.code or "DATABASE_UNAVAILABLE", check.action or check.message, 503
            )
