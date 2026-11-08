"""Serial local sync queue; archive checkpoints survive worker restarts."""

import logging
import signal
from datetime import UTC, datetime
from threading import Event

from chess_coach.application.parse_imported_games import ParseImportedGames
from chess_coach.application.sync_games import SyncGamesService
from chess_coach.config import Settings
from chess_coach.domain.sync import SyncAlreadyRunning
from chess_coach.infrastructure.chesscom.client import ChessComClient
from chess_coach.infrastructure.persistence.engine import create_database_engine
from chess_coach.infrastructure.persistence.parse_repository import ParseRepository
from chess_coach.infrastructure.persistence.session import create_session_factory
from chess_coach.infrastructure.persistence.sync_repository import SyncRepository
from chess_coach.infrastructure.pgn.parser import parse_game


def run_sync_worker(settings: Settings, *, once: bool = False) -> None:
    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set())
        for sig in (signal.SIGINT, signal.SIGTERM)
    }
    db = create_database_engine(settings.database_url)
    store = SyncRepository(create_session_factory(db), settings.database_path)
    prepare = ParseImportedGames(
        ParseRepository(store.sessions, settings.database_path, lock_already_held=True),
        parse_game,
        max_bytes=settings.pgn_max_bytes,
    )
    try:
        # Recover before polling, even if there are no queued jobs yet.
        with store.guard():
            store.recover(datetime.now(UTC))
        with ChessComClient() as provider:
            while not stop.is_set():
                pending = store.next_pending()
                if pending:
                    try:
                        SyncGamesService(
                            provider, store, prepare_games=prepare.run
                        ).sync(pending[1], queued_run_id=pending[0])
                    except SyncAlreadyRunning:
                        logging.getLogger(__name__).warning("sync_worker_busy")
                if once:
                    break
                stop.wait(2)
    finally:
        db.dispose()
        for sig, old in previous.items():
            signal.signal(sig, old)
