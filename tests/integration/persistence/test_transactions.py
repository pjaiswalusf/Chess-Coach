import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from test_models import game

from chess_coach.infrastructure.persistence.models import Game, Platform, TrackedPlayer


def test_transaction_rolls_back(sessions: sessionmaker[Session]) -> None:
    with (
        pytest.raises(RuntimeError, match="simulated failure"),
        sessions.begin() as session,
    ):
        player = TrackedPlayer(platform=Platform.CHESS_COM, username="temporary")
        session.add(player)
        session.flush()
        session.add(game(player.id))
        session.flush()  # Both writes reached SQLite before the failure.
        raise RuntimeError("simulated failure")
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(TrackedPlayer)) == 0
        assert session.scalar(select(func.count()).select_from(Game)) == 0


def test_failed_transaction_preserves_existing_data_and_allows_retry(
    sessions: sessionmaker[Session], player_id: int
) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(game(player_id))
        session.flush()
        session.add(game(player_id, canonical_hash="b" * 64))
        session.flush()
    with sessions() as session:
        assert session.get(TrackedPlayer, player_id) is not None
        assert session.scalar(select(func.count()).select_from(Game)) == 0
    with sessions.begin() as session:
        session.add(game(player_id))
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Game)) == 1


def test_plain_session_without_commit_does_not_persist(
    sessions: sessionmaker[Session],
) -> None:
    with sessions() as session:
        session.add(TrackedPlayer(platform=Platform.PGN, username="temporary"))
        session.flush()
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(TrackedPlayer)) == 0
