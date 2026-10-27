import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry


def create_database_engine(database_url: URL) -> Engine:
    """Create the local file database engine; schema creation belongs to Alembic."""
    if database_url.get_backend_name() != "sqlite" or database_url.database in (
        None,
        "",
        ":memory:",
    ):
        raise ValueError("A file-based SQLite database URL is required.")
    Path(database_url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        database_url, connect_args={"timeout": 5.0, "autocommit": False}
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
                cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            connection.autocommit = previous

    return engine
