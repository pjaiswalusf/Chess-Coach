"""Every API contract test uses an isolated, migrated database and fake integrations."""

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import chess
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from chess_coach.api.app import create_app
from chess_coach.api.dependencies import get_system_status
from chess_coach.application.analysis import AnalysisProcessor, configured_profile
from chess_coach.application.system import DependencyStatus, SystemStatus
from chess_coach.config import Settings, get_settings
from chess_coach.domain.engine_types import EngineResult
from chess_coach.domain.game_records import PARSER_VERSION
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
)
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.models import Game, Platform, TrackedPlayer
from chess_coach.infrastructure.persistence.session import create_session_factory
from chess_coach.infrastructure.pgn.parser import parse_game

PGN = '[White "TestPlayer"]\n[Black "Opponent"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0'


class FakeEngine:
    engine_name = "fixture-engine"
    calls = 0

    def start(self):
        pass

    def close(self):
        pass

    def analyze(self, board, **kwargs):
        self.calls += 1
        best = next(iter(board.legal_moves)).uci()
        return EngineResult(
            board.fen(),
            self.engine_name,
            20 * len(board.move_stack),
            None,
            None,
            best,
            (best,),
            4,
            100,
        )


@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / "api.db", _env_file=None)
    monkeypatch.setenv("CHESS_COACH_DATABASE_PATH", str(settings.database_path))
    command.upgrade(
        Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head"
    )
    db = create_database_engine(settings.database_url)
    sessions = create_session_factory(db)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    ready = DependencyStatus("available", "Fixture dependency")
    app.dependency_overrides[get_system_status] = lambda: SystemStatus(
        ready, ready, ready
    )
    store = AnalysisRepository(sessions, settings.database_path)
    engine = FakeEngine()
    profile = configured_profile(settings, engine.engine_name)
    store.register(profile)
    with TestClient(
        app, base_url="http://127.0.0.1", raise_server_exceptions=False
    ) as client:
        yield client, sessions, store, engine, settings, profile, app
    db.dispose()


@pytest.fixture
def seeded(api):
    client, sessions, _store, _engine, _settings, _profile, _app = api
    player_id = client.put("/api/v1/player", json={"username": "TestPlayer"}).json()[
        "player"
    ]["id"]
    parsed = parse_game(PGN, "testplayer")
    metadata = asdict(parsed)
    del metadata["moves"]
    metadata["total_plies"] = parsed.total_plies
    with sessions.begin() as s:
        for i in range(25):
            s.add(
                Game(
                    tracked_player_id=player_id,
                    platform=Platform.PGN,
                    canonical_hash=f"{i:064x}",
                    raw_pgn=PGN,
                    played_at=datetime(2026, 1, 1, tzinfo=UTC),
                    white_username="TestPlayer",
                    black_username="Opponent",
                    player_color="white",
                    result="win",
                    time_class="rapid",
                    parse_status="ready",
                    parser_version=PARSER_VERSION,
                    chess_library_version=chess.__version__,
                    parsed_metadata=metadata,
                )
            )
    return api


@pytest.fixture
def analyzed(seeded):
    _, sessions, store, engine, settings, profile, _ = seeded
    with sessions() as s:
        player_id = s.query(TrackedPlayer).one().id
    run = store.create(player_id, profile)
    assert store.claim(profile) == run
    AnalysisProcessor(store, engine, settings).process(run)
    return seeded
