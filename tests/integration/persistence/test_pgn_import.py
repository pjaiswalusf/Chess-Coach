"""File imports exercise the public CLI and migrated SQLite storage."""

import json

import pytest
from sqlalchemy import event, func, select

from chess_coach.cli import main
from chess_coach.infrastructure.persistence.models import (
    Game,
    ImportRejection,
    ImportRun,
)

PGN = '[White "TestPlayer"]\n[Black "Opponent"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n'


def invoke(paths):
    main(
        [
            "import-pgn",
            "--username",
            "testplayer",
            "--played-at",
            "2026-10-01T12:00:00Z",
            *map(str, paths),
        ]
    )


def test_file_import_identity_source_and_mixed_rejections(
    sessions, player_id, tmp_path, capsys
):
    valid = tmp_path / "valid.pgn"
    valid.write_bytes(PGN.replace("\n", "\r\n").encode())
    bad = tmp_path / "bad.pgn"
    bad.write_text(PGN.replace("e4", "e5"))
    other = tmp_path / "other.pgn"
    other.write_text(PGN.replace("e4 e5", "d4 d5"))
    with pytest.raises(SystemExit, match="1"):
        invoke([valid, bad, other])
    result = json.loads(capsys.readouterr().out)
    assert (result["inserted"], result["rejected"]) == (2, 1)
    variant = tmp_path / "variant.pgn"
    variant.write_text(
        '[Result "1-0"]\n[Black "Opponent"]\n[White "TestPlayer"]\n\n1. e4 {comment} e5 1-0\n'
    )
    for _ in range(10):
        invoke([variant])
        assert json.loads(capsys.readouterr().out)["existing"] == 1
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(Game)) == 2
        game = s.scalar(select(Game).order_by(Game.id))
        assert game.raw_pgn.encode() == valid.read_bytes()
        assert game.parse_status == "ready"
        assert game.parsed_metadata["completion_provenance"] == "pgn_declaration"
        assert game.source_evidence["import_run_id"] == result["run_id"]
        assert game.player_color == "white" and game.result == "win"
        rejection = s.scalar(select(ImportRejection))
        assert rejection.raw_pgn == bad.read_text()
        assert rejection.reason == "INVALID_MOVES"


def test_file_import_write_failure_is_atomic(
    sessions, player_id, engine, tmp_path, monkeypatch
):
    monkeypatch.setattr("chess_coach.cli.create_database_engine", lambda url: engine)
    valid = tmp_path / "valid.pgn"
    valid.write_text(PGN)

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO games"):
            raise RuntimeError("controlled storage failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="controlled storage failure"):
            invoke([valid])
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(Game)) == 0
        assert s.scalar(select(func.count()).select_from(ImportRun)) == 0
    invoke([valid])


@pytest.mark.parametrize(
    "body", [PGN.replace("1-0", "*"), PGN + PGN, PGN.replace("e4 e5", "e4 e5 2. Qh6")]
)
def test_file_import_rejects_unsafe_input(sessions, player_id, tmp_path, body):
    path = tmp_path / "unsafe.pgn"
    path.write_text(body)
    with pytest.raises(SystemExit, match="1"):
        invoke([path])
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(Game)) == 0
        assert s.scalar(select(ImportRejection.raw_pgn)) == body


def test_imported_game_is_analyzable_and_source_is_immutable(
    sessions, player_id, tmp_path
):
    from fixtures.reliability import FakeEngine

    from chess_coach.application.analysis import AnalysisProcessor, configured_profile
    from chess_coach.config import Settings
    from chess_coach.infrastructure.persistence.analysis_repository import (
        AnalysisRepository,
    )

    path = tmp_path / "game.pgn"
    path.write_text(PGN)
    invoke([path])
    settings = Settings(database_path=tmp_path / "test.db", _env_file=None)
    engine = FakeEngine()
    store = AnalysisRepository(sessions, settings.database_path)
    profile = configured_profile(settings, engine.engine_name)
    store.register(profile)
    run = store.create(player_id, profile)
    assert store.claim(profile) == run
    AnalysisProcessor(store, engine, settings).process(run)
    assert store.get(run).games_completed == 1
    with sessions() as s:
        game = s.scalar(select(Game))
        assert game.raw_pgn == PGN
        assert len(store.moves(game.id, profile.hash)) == 2
    calls = engine.calls
    again = store.create(player_id, profile)
    assert store.get(again).games_skipped == 1 and engine.calls == calls


@pytest.mark.parametrize(
    "case", ["missing", "oversize", "encoding", "player", "date", "busy"]
)
def test_import_preconditions_preserve_library(
    sessions, player_id, tmp_path, monkeypatch, case
):
    from chess_coach.infrastructure.persistence.models import RunStatus

    path = tmp_path / "game.pgn"
    path.write_text(PGN)
    args = [
        "import-pgn",
        "--username",
        "testplayer",
        "--played-at",
        "2026-10-01T12:00:00Z",
        str(path),
    ]
    if case == "missing":
        args[-1] = str(tmp_path / "missing.pgn")
    elif case == "oversize":
        monkeypatch.setenv("CHESS_COACH_PGN_MAX_BYTES", "10")
    elif case == "encoding":
        path.write_bytes(b"\xff")
    elif case == "player":
        args[2] = "another"
    elif case == "date":
        args[4] = "2026-10-01"
    else:
        with sessions.begin() as s:
            s.add(ImportRun(tracked_player_id=player_id, status=RunStatus.PENDING))
    with pytest.raises(SystemExit, match="1"):
        main(args)
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(Game)) == 0
        assert s.scalar(select(func.count()).select_from(ImportRun)) == (
            1 if case == "busy" else 0
        )
