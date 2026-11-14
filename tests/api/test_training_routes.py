from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import chess
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from chess_coach.api.app import create_app
from chess_coach.api.dependencies import get_system_status
from chess_coach.application.analysis import AnalysisProcessor
from chess_coach.application.generate_puzzles import generate_puzzles, reconstruct
from chess_coach.application.system import DependencyStatus, SystemStatus
from chess_coach.config import get_settings
from chess_coach.domain.engine_types import EngineResult
from chess_coach.domain.game_records import PARSER_VERSION
from chess_coach.domain.training import Rejected, Rejection
from chess_coach.infrastructure.engine.exceptions import EngineUnavailableError
from chess_coach.infrastructure.persistence.models import (
    Game,
    Puzzle,
    PuzzleAttempt,
    TrackedPlayer,
)
from chess_coach.infrastructure.persistence.training_repository import (
    TrainingRepository,
)
from chess_coach.infrastructure.pgn.parser import parse_game

PREFIX = "/api/v1/training"
PGN = '[White "TestPlayer"]\n[Black "Opponent"]\n[Result "1-0"]\n\n1. e4 d5 2. Nf3 dxe4 3. Nc3 1-0'


class VerificationEngine:
    engine_name = "training-fixture"

    def __init__(self):
        self.calls = 0
        self.closed = False

    def start(self):
        pass

    def close(self):
        self.closed = True

    def analyze_puzzle_candidate(self, board, *, nodes, multipv):
        self.calls += 1
        assert [move.uci() for move in board.move_stack] == ["e2e4", "d7d5"]
        assert multipv == 3
        assert nodes in (125_000, 500_000)
        return [
            EngineResult(
                board.fen(),
                self.engine_name,
                score,
                None,
                None,
                move,
                (move,),
                8,
                nodes,
            )
            for move, score in [("e4d5", 200), ("g1f3", 40), ("b1c3", 10)]
        ]


@pytest.fixture
def training_source(api, monkeypatch):
    _, sessions, store, source_engine, settings, profile, _ = api
    parsed = parse_game(PGN, "testplayer")
    metadata = asdict(parsed)
    del metadata["moves"]
    metadata["total_plies"] = parsed.total_plies
    with sessions.begin() as session:
        player = TrackedPlayer(username="testplayer", platform="chess.com")
        session.add(player)
        session.flush()
        player_id = player.id
        game = Game(
            tracked_player_id=player_id,
            platform="pgn",
            raw_pgn=PGN,
            canonical_hash="training-source",
            played_at=datetime(2026, 1, 1, tzinfo=UTC),
            white_username="TestPlayer",
            black_username="Opponent",
            player_color="white",
            result="win",
            time_class="rapid",
            time_control="600+5",
            parse_status="ready",
            parser_version=PARSER_VERSION,
            chess_library_version=chess.__version__,
            parsed_metadata=metadata,
        )
        session.add(game)

    def analysis(board, **_):
        best = next(iter(board.legal_moves)).uci()
        value = -170 if len(board.move_stack) == 3 else 0
        return EngineResult(
            board.fen(),
            source_engine.engine_name,
            value,
            None,
            None,
            best,
            (best,),
            5,
            100,
        )

    monkeypatch.setattr(source_engine, "analyze", analysis)
    run = store.create(player_id, profile)
    assert store.claim(profile) == run
    AnalysisProcessor(store, source_engine, settings).process(run)
    return player_id


@pytest.fixture
def practice(api, training_source):
    _, sessions, _, _, settings, profile, _ = api
    engine = VerificationEngine()
    repository = TrainingRepository(sessions)
    report = generate_puzzles(
        repository, engine, settings, training_source, profile.hash
    )
    assert (report.accepted, report.rejected, report.errors) == (1, 0, 0)
    assert engine.calls == 2 and engine.closed
    return api


def test_empty_queue_and_independent_health(api):
    client, _, _, _, _, _, app = api
    offline = DependencyStatus("unavailable", "Fixture offline")
    app.dependency_overrides[get_system_status] = lambda: SystemStatus(
        offline, offline, offline
    )
    assert client.get(PREFIX + "/next").json() == {
        "puzzle": None,
        "reason": "NO_PUZZLES_DUE",
    }
    stats = client.get(PREFIX + "/stats").json()
    assert stats["accuracy"] is None and stats["average_attempts"] is None
    health = client.get("/api/v1/system").json()["training"]
    assert health["practice_status"] == "ready"
    assert health["puzzles_due"] == 0
    # Simulate the engine availability check rather than depending on host installation.
    assert health["generation_status"] in ("verify_with_cli", "unavailable")


def test_generate_is_idempotent_without_starting_engine_again(
    practice, training_source
):
    client, sessions, _, _, settings, profile, _ = practice
    engine = VerificationEngine()
    report = generate_puzzles(
        TrainingRepository(sessions), engine, settings, training_source, profile.hash
    )
    assert (report.accepted, report.already_existing, report.errors) == (0, 1, 0)
    assert engine.calls == 0 and not engine.closed
    puzzle = client.get(PREFIX + "/next").json()["puzzle"]
    assert puzzle["side_to_move"] == "white"
    assert (
        puzzle["fen"] == "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    )
    assert set(puzzle) == {
        "id",
        "fen",
        "side_to_move",
        "theme",
        "difficulty",
        "attempt_count",
        "legal_moves",
        "solver_moves",
    }
    with sessions() as session:
        stored = session.get(Puzzle, puzzle["id"])
        assert stored.source_ply == 3
        assert stored.solution_uci == "e4d5"
        assert stored.verification_json["deep"][0]["score_cp_white"] == 200


def test_analysis_worker_retries_a_saved_puzzle_scan(api, training_source, monkeypatch):
    from chess_coach import analysis_worker

    client, sessions, _, _, settings, profile, _ = api
    verification = VerificationEngine()
    settings = settings.model_copy(update={"training_candidate_limit": 1})
    repository = TrainingRepository(sessions)
    assert repository.next_scan().puzzle_cursor == 0

    class AnalysisEngine(VerificationEngine):
        engine_name = profile.engine

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    offline = True

    def start():
        if offline:
            raise EngineUnavailableError("fixture offline")

    verification.start = start
    monkeypatch.setattr(
        analysis_worker,
        "StockfishAdapter",
        lambda config: AnalysisEngine() if config is settings else verification,
    )
    analysis_worker.run_worker(settings, once=True)
    assert repository.next_scan().puzzle_cursor == 0
    assert client.get(PREFIX + "/next").json()["puzzle"] is None

    offline = False
    analysis_worker.run_worker(settings, once=True)
    puzzle = client.get(PREFIX + "/next").json()["puzzle"]
    assert puzzle["attempt_count"] == 0
    assert repository.next_scan().puzzle_cursor > 0
    analysis_worker.run_worker(settings, once=True)
    assert repository.next_scan() is None
    assert client.get(PREFIX + "/stats").json()["puzzles_total"] == 1
    assert verification.calls == 2


@pytest.mark.parametrize("last_move, correct", [("d5c6", True), ("d5d6", False)])
def test_full_puzzle_attempt_is_graded_once(practice, last_move, correct):
    client, sessions, *_ = practice
    with sessions.begin() as session:
        stored = session.scalar(select(Puzzle))
        stored.solution_pv_json = ["e4d5", "b8c6", "d5c6", "b7c6"]
        stored.solve_plies = 4
    puzzle = client.get(PREFIX + "/next").json()["puzzle"]
    assert puzzle["solver_moves"] == 2
    path = f"{PREFIX}/{puzzle['id']}/play"
    assert client.post(attempt_path(client), json=answer("e4d5")).status_code == 422
    first = {"submission_id": str(uuid4()), "moves": ["e4d5"]}
    step = client.post(path, json=first).json()
    assert step["result"] is None and step["continuation"]["reply_san"] == "Nc6"
    assert "d5c6" in step["continuation"]["legal_moves"]
    assert client.post(path, json=first).json() == step
    assert client.get(PREFIX + "/stats").json()["attempts_total"] == 0
    finish = {"submission_id": str(uuid4()), "moves": ["e4d5", last_move]}
    result = client.post(path, json=finish).json()
    assert result["continuation"] is None and result["result"]["correct"] is correct
    assert client.post(path, json=finish).json() == result
    assert client.get(PREFIX + "/stats").json()["attempts_total"] == 1


@pytest.mark.parametrize("corruption", ["position", "turn", "source"])
def test_reconstruction_refuses_corrupt_evidence(api, training_source, corruption):
    _, sessions, _, _, settings, profile, _ = api
    store = TrainingRepository(sessions)
    username, (candidate,) = store.candidates(training_source, profile.hash, 0, 30)
    game, move, _, _ = candidate
    if corruption == "turn":
        move.mover = "black"
        expected = Rejection.WRONG_PLAYER_TURN
    elif corruption == "position":
        move.fen_before = "invalid"
        expected = Rejection.INVALID_POSITION
    else:
        game.raw_pgn = "broken PGN"
        expected = Rejection.MISSING_ANALYSIS
    with pytest.raises(Rejected, match=expected):
        reconstruct(candidate, username, settings.pgn_max_bytes)


def test_engine_unavailable_preserves_existing_practice(
    practice, training_source, monkeypatch
):
    client, sessions, _, _, settings, profile, _ = practice
    with sessions.begin() as session:
        stored = session.scalar(select(Puzzle))
        stored.source_ply = 4
    engine = VerificationEngine()

    def unavailable():
        raise EngineUnavailableError("fixture offline")

    monkeypatch.setattr(engine, "start", unavailable)
    report = generate_puzzles(
        TrainingRepository(sessions), engine, settings, training_source, profile.hash
    )
    assert report.errors == 1 and report.retry_from_move_id == 0
    puzzle = client.get(PREFIX + "/next").json()["puzzle"]
    response = client.post(f"{PREFIX}/{puzzle['id']}/attempts", json=answer("e4d5"))
    assert response.status_code == 200 and response.json()["correct"]


def answer(move):
    return {"submission_id": str(uuid4()), "move_uci": move}


def attempt_path(client):
    return f"{PREFIX}/{client.get(PREFIX + '/next').json()['puzzle']['id']}/attempts"


def test_wrong_answer_retry_restart_and_statistics(practice):
    client, sessions, _, _, settings, _, _ = practice
    path = attempt_path(client)
    body = answer("g1f3")
    response = client.post(path, json=body)
    assert response.status_code == 200
    result = response.json()
    assert not result["correct"] and result["solution_san"] == "exd5"
    attempted = datetime.fromisoformat(result["attempted_at"])
    assert datetime.fromisoformat(result["next_review_at"]) == attempted + timedelta(
        days=1
    )
    restarted = create_app()
    restarted.dependency_overrides[get_settings] = lambda: settings
    with TestClient(restarted, base_url="http://127.0.0.1") as other:
        assert other.post(path, json=body).json() == result
        conflict = other.post(path, json={**body, "move_uci": "e4d5"})
        assert (
            conflict.status_code == 409
            and conflict.json()["code"] == "SUBMISSION_ID_CONFLICT"
        )
        assert other.post(path, json=answer("g1f3")).json()["code"] == "PUZZLE_NOT_DUE"
        assert other.get(PREFIX + "/next").json()["puzzle"] is None
        stats = other.get(PREFIX + "/stats").json()
        assert (
            stats["attempts_total"]
            == stats["incorrect_attempts"]
            == stats["puzzles_attempted"]
            == 1
        )
        assert stats["accuracy"] == 0 and stats["average_attempts"] == 1
        assert stats["themes"][0]["attempts"] == 1
        (cohort,) = other.get(PREFIX + "/progress").json()["cohorts"]
        assert cohort["before"]["game_ids"] == [result["source_game_id"]]
        assert cohort["after"]["game_ids"] == []
        assert cohort["change_per_100"] is None
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(PuzzleAttempt)) == 1
        stored = session.scalar(select(Puzzle))
        assert stored.attempt_count == 1 and stored.correct_streak == 0
        assert stored.next_review_at == datetime.fromisoformat(result["next_review_at"])


def test_malformed_illegal_missing_retired_and_cross_site(practice):
    client, sessions, *_ = practice
    path = attempt_path(client)
    assert client.post(path, json=answer("not-uci")).status_code == 422
    illegal = client.post(path, json=answer("a2a5"))
    assert illegal.status_code == 422 and illegal.json()["code"] == "ILLEGAL_MOVE"
    assert (
        client.post(
            path, json=answer("e4d5"), headers={"Origin": "https://example.com"}
        ).status_code
        == 403
    )
    assert client.post(PREFIX + "/999/attempts", json=answer("e4d5")).status_code == 404
    with sessions.begin() as session:
        session.scalar(select(Puzzle)).status = "retired"
    assert client.post(path, json=answer("e4d5")).json()["code"] == "PUZZLE_RETIRED"
    assert client.get(PREFIX + "/next").json()["puzzle"] is None
    assert client.get(PREFIX + "/stats").json()["attempts_total"] == 0


def test_concurrent_due_submissions_only_accept_one(practice):
    client, sessions, *_ = practice
    path = attempt_path(client)
    gate = Barrier(2, timeout=5)

    def submit():
        gate.wait()
        return client.post(path, json=answer("e4d5"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(submit), pool.submit(submit)]
        responses = sorted(
            (result.result() for result in results), key=lambda r: r.status_code
        )
    first, second = responses
    assert first.status_code == 200 and first.json()["correct"]
    assert datetime.fromisoformat(
        first.json()["next_review_at"]
    ) - datetime.fromisoformat(first.json()["attempted_at"]) == timedelta(days=3)
    assert second.status_code == 409
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(PuzzleAttempt)) == 1
        assert session.scalar(select(Puzzle)).correct_streak == 1


def test_schedule_write_failure_rolls_back_insert(practice):
    client, sessions, *_ = practice
    path = attempt_path(client)
    bind = sessions.kw["bind"]

    def fail(_conn, _cursor, statement, *_):
        if statement.startswith("UPDATE puzzles SET"):
            raise RuntimeError("fixture write failure after attempt INSERT")

    event.listen(bind, "before_cursor_execute", fail)
    try:
        # The API builds its own engine. Install the injection on its session factory.
        from chess_coach.api.dependencies import get_training_service
        from chess_coach.application.training import TrainingService

        app = practice[-1]
        app.dependency_overrides[get_training_service] = lambda: TrainingService(
            TrainingRepository(sessions)
        )
        assert client.post(path, json=answer("e4d5")).status_code == 500
    finally:
        event.remove(bind, "before_cursor_execute", fail)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(PuzzleAttempt)) == 0
        puzzle = session.scalar(select(Puzzle))
        assert puzzle.attempt_count == puzzle.correct_streak == 0
        assert puzzle.next_review_at == puzzle.created_at


def test_transfer_keeps_comparable_periods_and_drops_incomplete_analysis(
    practice, training_source
):
    from sqlalchemy import delete

    from chess_coach.infrastructure.persistence.models import MoveAnalysis

    client, sessions, store, engine, settings, profile, _ = practice
    attempt = client.post(attempt_path(client), json=answer("e4d5")).json()
    boundary = datetime.fromisoformat(attempt["attempted_at"])
    with sessions.begin() as session:
        source = session.get(Game, attempt["source_game_id"])
        values = {
            column.name: getattr(source, column.name)
            for column in Game.__table__.columns
            if column.name
            not in {"id", "canonical_hash", "played_at", "time_class", "time_control"}
        }
        before = [(boundary - timedelta(days=1), "rapid", "600+5")] * 33
        after = [(boundary + timedelta(days=1), "rapid", "600+5")] * 34
        other = [
            (boundary, "rapid", "600+5"),
            (boundary + timedelta(days=1), "rapid", "900+10"),
            (boundary + timedelta(days=1), "blitz", "180+2"),
        ]
        for index, (played, category, control) in enumerate(before + after + other):
            session.add(
                Game(
                    **values,
                    canonical_hash=f"transfer-{index}",
                    played_at=played,
                    time_class=category,
                    time_control=control,
                )
            )
    run = store.create(training_source, profile)
    assert store.claim(profile) == run
    AnalysisProcessor(store, engine, settings).process(run)

    def cohorts():
        data = client.get(PREFIX + "/progress").json()
        return {
            (cohort["time_class"], cohort["time_control"]): cohort
            for cohort in data["cohorts"]
        }

    groups = cohorts()
    rapid = groups["rapid", "600+5"]
    for period in ("before", "after"):
        assert len(rapid[period]["game_ids"]) == 34
        assert rapid[period]["moves"] == 102
        assert rapid[period]["critical_errors"] == 34
        assert rapid[period]["errors_per_100"] == pytest.approx(100 / 3)
    assert rapid["change_per_100"] == 0
    assert groups["blitz", "180+2"]["change_per_100"] is None
    assert groups["rapid", "900+10"]["change_per_100"] is None

    with sessions.begin() as session:
        session.execute(
            delete(MoveAnalysis).where(
                MoveAnalysis.game_id == rapid["after"]["game_ids"][0],
                MoveAnalysis.ply == 3,
            )
        )
    damaged = cohorts()["rapid", "600+5"]
    assert damaged["after"]["moves"] == 99
    assert damaged["after"]["critical_errors"] == 33
    assert damaged["change_per_100"] is None
