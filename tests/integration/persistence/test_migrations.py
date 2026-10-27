from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Engine, inspect

from chess_coach.config import Settings
from chess_coach.infrastructure.persistence.base import Base
from chess_coach.infrastructure.persistence.engine import create_database_engine

EXPECTED_TABLES = {
    "tracked_players",
    "games",
    "import_runs",
    "analysis_runs",
    "game_analysis_states",
    "position_cache",
    "move_analyses",
    "alembic_version",
}


def test_migrations_build_empty_database(migration_config: Config) -> None:
    path = Settings().database_path
    assert not path.exists()
    command.upgrade(migration_config, "head")
    engine = create_database_engine(Settings().database_url)
    try:
        assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == (
                ScriptDirectory.from_config(migration_config).get_current_head()
            )
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


def test_alembic_schema_matches_models(
    engine: Engine, migration_config: Config
) -> None:
    command.check(migration_config)
    # Alembic does not reliably compare CHECK constraints; inspect them explicitly.
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        actual = {
            item["name"]: " ".join(item["sqltext"].split())
            for item in inspector.get_check_constraints(table.name)
        }
        expected = {
            str(constraint.name): " ".join(
                str(
                    constraint.sqltext.compile(
                        dialect=engine.dialect,
                        compile_kwargs={"literal_binds": True, "include_table": False},
                    )
                ).split()
            )
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert actual == expected
        assert all(c["name"] for c in inspector.get_foreign_keys(table.name))
        assert all(c["name"] for c in inspector.get_unique_constraints(table.name))


def test_migration_downgrade_and_reupgrade(
    engine: Engine, migration_config: Config
) -> None:
    command.downgrade(migration_config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    command.upgrade(migration_config, "head")
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    command.check(migration_config)
