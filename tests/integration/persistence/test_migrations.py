from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Engine, inspect

from chess_coach.config import Settings
from chess_coach.infrastructure.persistence.base import Base
from chess_coach.infrastructure.persistence.engine import create_database_engine

EXPECTED_TABLES = {
    "archive_sync_state",
    "import_rejections",
    "tracked_players",
    "games",
    "import_runs",
    "analysis_runs",
    "analysis_run_games",
    "analysis_worker_state",
    "game_analysis_states",
    "position_cache",
    "move_analyses",
    "move_features",
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


def test_phase8_upgrade_preserves_phase7_game(migration_config: Config) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import MetaData, Table, select

    command.upgrade(migration_config, "c7a001")
    engine = create_database_engine(Settings().database_url)
    raw_pgn = '[White "TestPlayer"]\n[Black "Opponent"]\n[Result "1-0"]\n\n1. e4 e5 1-0'
    try:
        metadata = MetaData()
        players = Table("tracked_players", metadata, autoload_with=engine)
        games = Table("games", metadata, autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(
                players.insert().values(
                    id=1,
                    platform="chess.com",
                    username="testplayer",
                    created_at=datetime(2026, 11, 7, tzinfo=UTC),
                )
            )
            connection.execute(
                games.insert().values(
                    id=1,
                    tracked_player_id=1,
                    platform="chess.com",
                    external_id="old-game",
                    canonical_hash="a" * 64,
                    raw_pgn=raw_pgn,
                    played_at=datetime(2026, 11, 7, tzinfo=UTC),
                    white_username="TestPlayer",
                    black_username="Opponent",
                    player_color="white",
                    result="win",
                    created_at=datetime(2026, 11, 7, tzinfo=UTC),
                )
            )
        command.upgrade(migration_config, "head")
        upgraded = Table("games", MetaData(), autoload_with=engine)
        with engine.connect() as connection:
            row = connection.execute(select(upgraded)).mappings().one()
            assert row["id"] == 1 and row["raw_pgn"] == raw_pgn
            assert (
                row["external_id"] == "old-game" and row["canonical_hash"] == "a" * 64
            )
            assert row["parse_status"] == "pending"
            assert row["source_evidence"] is None and row["parsed_metadata"] is None
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


def test_phase10_upgrade_preserves_legacy_analysis(migration_config: Config) -> None:
    """Referenced parent-table rebuild retains legacy evidence and maps statuses."""
    from datetime import UTC, datetime

    from sqlalchemy import MetaData, Table, select

    command.upgrade(migration_config, "c8a001")
    engine = create_database_engine(Settings().database_url)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    now = datetime.now(UTC)
    try:
        with engine.begin() as c:
            c.execute(
                metadata.tables["tracked_players"]
                .insert()
                .values(id=1, platform="pgn", username="a", created_at=now)
            )
            c.execute(
                metadata.tables["games"]
                .insert()
                .values(
                    id=1,
                    tracked_player_id=1,
                    platform="pgn",
                    canonical_hash="a" * 64,
                    raw_pgn="preserved",
                    played_at=now,
                    white_username="a",
                    black_username="b",
                    player_color="white",
                    result="win",
                    created_at=now,
                )
            )
            c.execute(
                metadata.tables["analysis_runs"]
                .insert()
                .values(
                    id=1,
                    tracked_player_id=1,
                    status="succeeded",
                    engine_version="old",
                    analysis_version="1",
                    engine_config_hash="x" * 64,
                    engine_config_json={},
                    draw_policy_version="old",
                    games_total=1,
                    games_completed=1,
                    games_failed=0,
                    positions_analyzed=0,
                    cache_hits=0,
                    cache_misses=0,
                    error_count=0,
                )
            )
            c.execute(
                metadata.tables["game_analysis_states"]
                .insert()
                .values(
                    id=1,
                    game_id=1,
                    analysis_run_id=1,
                    analysis_version="1",
                    status="done",
                )
            )
        command.upgrade(migration_config, "head")
        runs = Table("analysis_runs", MetaData(), autoload_with=engine)
        states = Table("game_analysis_states", MetaData(), autoload_with=engine)
        with engine.connect() as c:
            row = c.execute(select(runs)).mappings().one()
            assert row["status"] == "done" and row["profile_hash"] == "legacy"
            assert c.execute(select(states.c.analysis_run_id)).scalar() == 1
            assert c.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()
