import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry


def create_database_engine(
    database_url: URL, *, timeout_seconds: float = 5.0
) -> Engine:
    """Create the local file database engine; schema creation belongs to Alembic."""
    if database_url.get_backend_name() != "sqlite" or database_url.database in (
        None,
        "",
        ":memory:",
    ):
        raise ValueError("A file-based SQLite database URL is required.")
    Path(database_url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        database_url,
        hide_parameters=True,
        connect_args={"timeout": timeout_seconds, "autocommit": False},
    )

    @event.listens_for(engine, "connect")
    def configure_connection(
        connection: sqlite3.Connection, connection_record: ConnectionPoolEntry
    ) -> None:
        # PRAGMAs must run outside a transaction, including Python 3.14's
        # non-legacy transaction mode used above.
        previous = connection.autocommit
        connection.autocommit = True
        try:
            with closing(connection.cursor()) as cursor:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute(f"PRAGMA busy_timeout={int(timeout_seconds * 1000)}")
        finally:
            connection.autocommit = previous

    return engine


def create_readonly_engine(database_path: Path) -> Engine:
    """Read an existing SQLite file without provisioning or setting journal mode."""
    url = URL.create(
        "sqlite+pysqlite",
        database=database_path.resolve().as_uri(),
        query={"mode": "ro", "uri": "true"},
    )
    return create_engine(url, hide_parameters=True, connect_args={"timeout": 1.0})
