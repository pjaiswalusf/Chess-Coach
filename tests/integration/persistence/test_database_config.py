from pathlib import Path

import pytest
from sqlalchemy import URL

from chess_coach.config import Settings
from chess_coach.infrastructure.persistence.engine import create_database_engine


@pytest.mark.parametrize(
    ("pragma", "expected"),
    [("foreign_keys", 1), ("journal_mode", "wal"), ("busy_timeout", 5000)],
)
def test_sqlite_configuration_on_every_connection(
    tmp_path: Path, pragma: str, expected: int | str
) -> None:
    settings = Settings(database_path=tmp_path / "nested" / "test.db")
    engine = create_database_engine(settings.database_url)
    try:
        # Simultaneous checkouts force two distinct physical connections.
        with engine.connect() as first, engine.connect() as second:
            for connection in (first, second):
                assert (
                    connection.exec_driver_sql(f"PRAGMA {pragma}").scalar() == expected
                )
    finally:
        engine.dispose()


def test_memory_database_is_not_silently_used() -> None:
    with pytest.raises(ValueError, match="file-based"):
        create_database_engine(URL.create("sqlite", database=":memory:"))
