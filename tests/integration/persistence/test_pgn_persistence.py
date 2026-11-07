from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import event, func, select

from chess_coach.application.parse_imported_games import ParseImportedGames
from chess_coach.domain.game_records import ParseStatus
from chess_coach.domain.sync import SyncAlreadyRunning
from chess_coach.infrastructure.persistence.models import Game, Platform
from chess_coach.infrastructure.persistence.parse_repository import ParseRepository
from chess_coach.infrastructure.pgn.parser import parse_game

NOW = datetime(2026, 11, 7, tzinfo=UTC)
FIXTURES = Path(__file__).parents[2] / "fixtures/pgn"


def add_game(
    sessions, player_id, name="white_win", *, platform=Platform.PGN, evidence=None
):
    raw = (FIXTURES / f"{name}.pgn").read_text().replace("Pratik", "TestPlayer")
    with sessions.begin() as session:
        index = session.scalar(select(func.count()).select_from(Game)) + 1
        game = Game(
            tracked_player_id=player_id,
            platform=platform,
            external_id=str(index),
            canonical_hash=f"{index:064d}",
            raw_pgn=raw,
            played_at=NOW,
            white_username="TestPlayer",
            black_username="Opponent",
            player_color="white",
            result="unknown",
            source_evidence=evidence,
            eco_url="https://source.example/opening",
        )
        session.add(game)
        session.flush()
        return game.id, raw


@pytest.fixture
def store(sessions, tmp_path):
    return ParseRepository(sessions, tmp_path / "test.db")


def service(store, parser=parse_game):
    return ParseImportedGames(store, parser, clock=lambda: NOW)


def test_mixed_batch_idempotent_and_explicit_retry(sessions, player_id, store):
    first, _ = add_game(sessions, player_id)
    bad, raw = add_game(sessions, player_id, "illegal")
    last, _ = add_game(sessions, player_id, "clocks")
    report = service(store).run(" TESTPLAYER ")
    assert (report.games_attempted, report.ready, report.parse_failed) == (3, 2, 1)
    assert report.reasons == {"INVALID_MOVES": 1} and report.clock_coverage_games == 1
    assert store.eligible_ids() == [first, last]
    assert service(store).run("testplayer").games_attempted == 0
    assert service(store).run("testplayer", retry=True).games_attempted == 3
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Game)) == 3
        rejected = session.get(Game, bad)
        assert rejected.raw_pgn == raw and rejected.parse_reason == "INVALID_MOVES"
        assert rejected.parser_version == 1 and rejected.parse_attempted_at == NOW
        assert rejected.parsed_metadata is None
        ready = session.get(Game, first)
        assert ready.result == "win" and ready.player_color == "white"
        assert ready.eco_url == "https://source.example/opening"
        assert ready.parsed_metadata["total_plies"] == 6
        assert ready.parsed_metadata["completion_provenance"] == "pgn_declaration"
        assert "moves" not in ready.parsed_metadata


def test_interruption_recovered_and_completed_games_untouched(
    sessions, player_id, store
):
    first, _ = add_game(sessions, player_id)
    second, _ = add_game(sessions, player_id)
    calls = 0

    def interrupt(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt()
        # Parsing runs outside any SQL transaction/session.
        assert (
            not store.sessions.kw["bind"].pool.checkedout()
            if hasattr(store.sessions.kw["bind"].pool, "checkedout")
            else True
        )
        return parse_game(*args, **kwargs)

    with pytest.raises(KeyboardInterrupt):
        service(store, interrupt).run("testplayer")
    assert store.eligible_ids() == [first]
    with sessions() as session:
        assert session.get(Game, second).parse_status == "parsing"
    result = service(store).run("testplayer")
    assert result.recovered == result.games_attempted == result.ready == 1
    assert store.eligible_ids() == [first, second]


def test_failed_commit_rolls_back_metadata_then_recovers(
    sessions, player_id, store, engine
):
    game_id, raw = add_game(sessions, player_id)
    service(store).run("testplayer")
    with sessions() as session:
        original = session.get(Game, game_id).parsed_metadata

    def fail_commit(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE games") and "parser_version" in statement:
            raise RuntimeError("simulated write failure")
        if statement.startswith("UPDATE games") and "ready" in parameters:
            raise RuntimeError("simulated write failure")

    event.listen(engine, "before_cursor_execute", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="simulated write failure"):
            service(store).run("testplayer", retry=True)
    finally:
        event.remove(engine, "before_cursor_execute", fail_commit)
    with sessions() as session:
        row = session.get(Game, game_id)
        assert row.parse_status == "parsing"
        assert row.parsed_metadata == original and row.raw_pgn == raw
    assert store.eligible_ids() == []
    assert service(store).run("testplayer").ready == 1


def evidence(**kwargs):
    return {
        "end_time": 1700000000,
        "white_result": "win",
        "black_result": "resigned",
        "result": "1-0",
        "rules": "chess",
        "final_fen": None,
        **kwargs,
    }


@pytest.mark.parametrize(
    "source,reason",
    [
        (None, "SOURCE_EVIDENCE_MISSING"),
        (evidence(end_time=None), "SOURCE_EVIDENCE_MISSING"),
        (evidence(black_result="playing"), "SOURCE_EVIDENCE_MISSING"),
        (evidence(rules="chess960"), "UNSUPPORTED_VARIANT"),
        (evidence(result="0-1"), "RESULT_MISMATCH"),
        (evidence(final_fen="invalid"), "FINAL_POSITION_MISMATCH"),
    ],
)
def test_source_evidence_required(sessions, player_id, store, source, reason):
    game_id, raw = add_game(
        sessions, player_id, platform=Platform.CHESS_COM, evidence=source
    )
    report = service(store).run("testplayer")
    assert report.reasons == {reason: 1}
    assert store.eligible_ids() == []
    with sessions() as session:
        assert session.get(Game, game_id).raw_pgn == raw


def test_source_provenance_and_mismatch(sessions, player_id, store):
    game_id, _ = add_game(
        sessions, player_id, platform=Platform.CHESS_COM, evidence=evidence()
    )
    assert service(store).run("testplayer").ready == 1
    with sessions.begin() as session:
        row = session.get(Game, game_id)
        assert row.parsed_metadata["completion_provenance"] == "chesscom_archive"
        row.black_username = "AnotherPlayer"
    assert service(store).run("testplayer", retry=True).reasons == {
        "SOURCE_METADATA_MISMATCH": 1
    }
    assert store.eligible_ids() == []


def test_unexpected_errors_surface_and_are_not_silently_retried(
    sessions, player_id, store, caplog
):
    game_id, _ = add_game(sessions, player_id)

    def broken(*args, **kwargs):
        raise RuntimeError("parser programming error")

    caplog.set_level("INFO")
    with pytest.raises(RuntimeError):
        service(store, broken).run("testplayer")
    with sessions() as session:
        row = session.get(Game, game_id)
        assert row.parse_reason == "UNEXPECTED_PARSE_ERROR"
    assert "unexpected_parse_error" in caplog.text
    summary = next(
        record.summary
        for record in caplog.records
        if record.message == "pgn_validation_summary"
    )
    assert (
        summary["games_attempted"]
        == summary["parse_failed"]
        == summary["unexpected_errors"]
        == 1
    )
    assert summary["reasons"] == {"UNEXPECTED_PARSE_ERROR": 1}
    assert service(store).run("testplayer").games_attempted == 0
    assert service(store).run("testplayer", retry=True).ready == 1


def test_exclusion_and_version_eligibility(sessions, player_id, store):
    game_id, _ = add_game(sessions, player_id)
    with store.guard(), pytest.raises(SyncAlreadyRunning):
        service(store).run("testplayer")
    service(store).run("testplayer")
    with sessions.begin() as session:
        session.get(Game, game_id).parser_version = 0
    assert store.eligible_ids() == []
    service(store).run("testplayer", retry=True)
    with sessions.begin() as session:
        session.get(Game, game_id).parse_status = ParseStatus.INCOMPLETE
    assert store.eligible_ids() == []


def test_parse_cli_uses_real_database_and_prints_summary(
    sessions, player_id, store, capsys
):
    import json

    from chess_coach.cli import main

    add_game(sessions, player_id)
    add_game(sessions, player_id, "illegal")
    main(["parse-games", "--username", "testplayer"])
    report = json.loads(capsys.readouterr().out)
    assert report["games_attempted"] == 2
    assert report["ready"] == report["parse_failed"] == 1
    main(["parse-games", "--username", "testplayer", "--retry"])
    assert json.loads(capsys.readouterr().out)["games_attempted"] == 2
