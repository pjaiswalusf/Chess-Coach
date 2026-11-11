"""Serve the real API and job processors with offline adapters for Playwright."""

import json
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

import chess
import httpx
import uvicorn
from alembic import command
from alembic.config import Config
from reliability import FakeEngine

from chess_coach.api import dependencies
from chess_coach.api.app import create_app
from chess_coach.application.analysis import AnalysisProcessor, configured_profile
from chess_coach.application.coaching import CoachingProcessor, CoachingService
from chess_coach.application.generate_puzzles import generate_puzzles
from chess_coach.application.parse_imported_games import ParseImportedGames
from chess_coach.application.sync_games import SyncGamesService
from chess_coach.application.system import DependencyStatus
from chess_coach.config import Settings, get_settings
from chess_coach.domain.coaching_models import GamePractice, LLMHealth, MovePractice
from chess_coach.infrastructure.analysis_lock import worker_guard
from chess_coach.infrastructure.chesscom.client import BASE_URL, ChessComClient
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
)
from chess_coach.infrastructure.persistence.coaching_repository import (
    CoachingRepository,
)
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.parse_repository import ParseRepository
from chess_coach.infrastructure.persistence.query_repository import QueryRepository
from chess_coach.infrastructure.persistence.session import create_session_factory
from chess_coach.infrastructure.persistence.sync_repository import SyncRepository
from chess_coach.infrastructure.persistence.training_repository import (
    TrainingRepository,
)
from chess_coach.infrastructure.pgn.parser import parse_game

PLAYER = "testplayer"
ARCHIVE = f"{BASE_URL}/player/{PLAYER}/games/2026/10"
NOW = datetime(2026, 11, 7, tzinfo=UTC)
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def source(directory: Path, request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url == f"{BASE_URL}/player/{PLAYER}":
        return httpx.Response(200, json={"username": PLAYER})
    if url.endswith("/archives"):
        return httpx.Response(200, json={"archives": [ARCHIVE]})
    assert url == ARCHIVE
    if (directory / "timeout").exists():
        raise httpx.ReadTimeout("Fixture source unavailable", request=request)
    if (directory / "rate-limit").exists():
        return httpx.Response(429, headers={"Retry-After": "2"})
    games = []
    for i in range(1, 15):
        opponent = f"Fixture_{i:02}"
        moves = "1. e4 e5 2. Bc4 Nc6 3. Qf3 b6 4. Ne2" if i != 14 else "1. e4 e5 2. Qh6"
        games.append(
            {
                "rules": "chess",
                "url": f"https://www.chess.com/game/live/{i}",
                "end_time": 1790812800 + i,
                "time_class": "rapid",
                "time_control": "600",
                "white": {"username": PLAYER, "result": "win"},
                "black": {"username": opponent, "result": "resigned"},
                "pgn": f'[White "{PLAYER}"]\n[Black "{opponent}"]\n[Result "1-0"]\n\n{moves} 1-0',
            }
        )
    return httpx.Response(200, json={"games": games})


class WorkflowEngine(FakeEngine):
    def analyze(self, board, **kwargs):
        result = super().analyze(board, **kwargs)
        ply = len(board.move_stack)
        best = "f3h5" if ply == 6 else result.best_move_uci
        return replace(
            result,
            score_cp_white={6: 350, 7: -150}.get(ply, 0),
            best_move_uci=best,
            pv_uci=(best,),
        )

    def analyze_puzzle_candidate(self, board, *, nodes, multipv):
        result = self.analyze(board)
        mate = board.parse_uci("f3f7")
        assert board.gives_check(mate)
        alternatives = [move.uci() for move in board.legal_moves if move != mate][
            : multipv - 1
        ]
        return [
            replace(
                result,
                score_cp_white=None,
                mate_white=1,
                mate_winner=chess.WHITE,
                best_move_uci=mate.uci(),
                pv_uci=(mate.uci(),),
            ),
            *(
                replace(
                    result, score_cp_white=-index * 20, best_move_uci=uci, pv_uci=(uci,)
                )
                for index, uci in enumerate(alternatives)
            ),
        ]


class WorkflowModel:
    def __init__(self):
        self.metrics = {}

    def generate(self, evidence_json, schema):
        if schema is MovePractice:
            return MovePractice(status="explained", focus="reply").model_dump_json()
        evidence = json.loads(evidence_json)
        if schema is GamePractice:
            return json.dumps(
                {
                    "status": "explained",
                    "choices": [
                        {
                            "ply": evidence[0]["ply"],
                            "focus": evidence[0]["allowed_focuses"][0],
                        }
                    ],
                }
            )
        return json.dumps(
            {
                "status": "explained",
                "summary": "Review your opening decisions before moving.",
                "priorities": [
                    {
                        "pattern_id": evidence["patterns"][0]["candidate_key"],
                        "explanation": "The opening evidence contains recurring critical errors.",
                        "practice_tip": "Check forcing moves before choosing a candidate.",
                    }
                ],
            }
        )


def main(directory: Path, port: int) -> None:
    if directory.resolve() != Path.cwd() or not directory.name.startswith(
        "chess-coach-e2e-"
    ):
        raise SystemExit("Run the fixture API from its dedicated test directory.")
    database = directory / "workflow.db"
    os.environ["CHESS_COACH_DATABASE_PATH"] = str(database)
    get_settings.cache_clear()
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    settings = Settings(database_path=database, _env_file=None)
    db = create_database_engine(settings.database_url)
    sessions = create_session_factory(db)
    analysis = AnalysisRepository(sessions, database)
    sync = SyncRepository(sessions, database)
    parse = ParseImportedGames(
        ParseRepository(sessions, database, lock_already_held=True), parse_game
    )
    provider = ChessComClient(
        transport=httpx.MockTransport(lambda request: source(directory, request)),
        sleep=lambda _: None,
        clock=lambda: NOW,
    )

    def health():
        offline = (directory / "ollama-down").exists()
        return LLMHealth(
            status="server_unavailable" if offline else "ready",
            model=settings.ollama_model,
            model_digest=None if offline else "fixture-model",
            server_reachable=not offline,
            model_installed=not offline,
            message="Start Ollama and retry." if offline else "Fixture ready.",
        )

    coaching = CoachingService(
        CoachingRepository(QueryRepository(sessions, analysis)), settings, health
    )
    engine = WorkflowEngine()
    profile = configured_profile(settings, engine.engine_name)
    stop, started = Event(), Event()

    def checkpoint(kind, position):
        if (
            kind == "position"
            and position == 1
            and not (directory / "continue-analysis").exists()
        ):
            (directory / "analysis-paused").touch()
            while not (directory / "continue-analysis").exists() and not stop.wait(
                0.02
            ):
                pass

    def work():
        sync_service = SyncGamesService(provider, sync, prepare_games=parse.run)
        processor = AnalysisProcessor(analysis, engine, settings, stop, checkpoint)
        coaching_processor = CoachingProcessor(coaching, WorkflowModel())
        with worker_guard(database):
            analysis.register(profile)
            analysis.recover(profile)
            started.set()
            try:
                while not stop.is_set():
                    if pending := sync.next_pending():
                        sync_service.sync(pending[1], queued_run_id=pending[0])
                    elif (run_id := analysis.claim(profile)) is not None:
                        processor.process(run_id)
                        run = analysis.get(run_id)
                        if run.status == "done":
                            generate_puzzles(
                                TrainingRepository(sessions),
                                engine,
                                settings,
                                run.tracked_player_id,
                                profile.hash,
                                limit=1,
                            )
                    elif (job := coaching.store.claim()) is not None:
                        coaching_processor.process(job)
                    else:
                        stop.wait(0.03)
            finally:
                analysis.register(profile, "stopped")

    @asynccontextmanager
    async def lifespan(_app):
        worker = Thread(target=work)
        worker.start()
        try:
            assert started.wait(5), "Fixture job worker did not start"
            yield
        finally:
            stop.set()
            worker.join(timeout=5)
            assert not worker.is_alive()

    ready = DependencyStatus("available", "Fixture ready")
    dependencies.probe_stockfish = lambda _: ready
    dependencies.probe_ollama = lambda _: (
        (ready, ready)
        if health().status == "ready"
        else (
            DependencyStatus("unavailable", "Fixture offline"),
            DependencyStatus("unknown", "Fixture offline"),
        )
    )
    app = create_app()
    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def identify_fixture(request, call_next):
        response = await call_next(request)
        response.headers["X-Chess-Coach-Fixture"] = directory.name
        return response

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[dependencies.get_chesscom_verifier] = lambda: (
        provider.get_player
    )
    app.dependency_overrides[dependencies.get_llm_health] = health
    app.dependency_overrides[dependencies.get_coaching_service] = lambda: coaching
    try:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            workers=1,
            proxy_headers=False,
            access_log=False,
        )
    finally:
        provider.close()
        db.dispose()


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[2]))
