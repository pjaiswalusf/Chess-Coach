"""Create and verify a SQLite snapshot of the configured Chess Coach database."""

import argparse
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import ValidationError

from chess_coach.config import Settings


def backup(source: Path, directory: Path) -> Path:
    with closing(
        sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    ) as src:
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%SZ")
        with NamedTemporaryFile(
            dir=directory,
            prefix=f"chess-coach-{timestamp}-",
            suffix=".db",
            delete=False,
        ) as file:
            snapshot = Path(file.name)
        try:
            with closing(sqlite3.connect(snapshot)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("SQLite integrity check failed.")
        except Exception, KeyboardInterrupt:
            snapshot.unlink(missing_ok=True)
            raise
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("backups"))
    args = parser.parse_args()
    try:
        snapshot = backup(Settings().database_path, args.directory)
    except OSError, RuntimeError, ValidationError, sqlite3.Error:
        print(
            "Backup failed. Check the configured SQLite path and backup directory, "
            "then stop the app and retry.",
            file=sys.stderr,
        )
        return 1
    print(f"Verified SQLite backup: {snapshot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
