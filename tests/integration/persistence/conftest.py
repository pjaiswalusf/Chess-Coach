from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from chess_coach.config import Settings
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.models import Platform, TrackedPlayer
from chess_coach.infrastructure.persistence.session import create_session_factory


@pytest.fixture
def migration_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("CHESS_COACH_DATABASE_PATH", str(tmp_path / "test.db"))
    return Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))


@pytest.fixture
def engine(migration_config: Config) -> Iterator[Engine]:
    # Every integrity test exercises the actual migration, never create_all().
    command.upgrade(migration_config, "head")
    engine = create_database_engine(Settings().database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def player_id(sessions: sessionmaker[Session]) -> int:
    with sessions.begin() as session:
        player = TrackedPlayer(platform=Platform.CHESS_COM, username="TestPlayer")
        session.add(player)
        session.flush()
        return player.id
