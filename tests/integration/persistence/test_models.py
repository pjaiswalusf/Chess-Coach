from datetime import UTC, datetime, timedelta, timezone

import chess
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session, sessionmaker

from chess_coach.infrastructure.persistence.models import (
    AnalysisRun,
    Game,
    GameAnalysisState,
    GameAnalysisStatus,
    GameResult,
    ImportRun,
    MoveAnalysis,
    Platform,
    PlayerColor,
    PositionCache,
    RunStatus,
    TrackedPlayer,
)

PLAYED_AT = datetime(2026, 1, 2, 12, tzinfo=UTC)


def game(player_id: int, **overrides: object) -> Game:
    values = {
        "tracked_player_id": player_id,
        "platform": Platform.CHESS_COM,
        "external_id": "abc123",
        "canonical_hash": "a" * 64,
        "raw_pgn": '[Result "1-0"]\n\n1. e4 e5 1-0',
        "played_at": PLAYED_AT,
        "white_username": "TestPlayer",
        "black_username": "Opponent",
        "player_color": PlayerColor.WHITE,
        "result": GameResult.WIN,
    }
    return Game(**(values | overrides))


def analysis_run(player_id: int, **overrides: object) -> AnalysisRun:
    values = {
        "tracked_player_id": player_id,
        "engine_version": "fixture-engine",
        "analysis_version": "1",
        "engine_config_hash": "c" * 64,
        "engine_config_json": {"threads": 4, "hash_mb": 512, "nodes": 50000, "multipv": 1},
        "draw_policy_version": "unclaimed-v1",
    }
    return AnalysisRun(**(values | overrides))


def cache(**overrides: object) -> PositionCache:
    values = {
        "fen": chess.STARTING_FEN,
        "initial_fen": chess.STARTING_FEN,
        "moves_uci_json": [],
        "history_hash": "h" * 64,
        "history_before_start_unknown": False,
        "engine_version": "fixture-engine",
        "analysis_version": "1",
        "config_hash": "c" * 64,
        "draw_policy_version": "unclaimed-v1",
        "score_cp_white": 25,
        "mate_distance_white": None,
        "best_move_uci": "e2e4",
        "pv_json": ["e2e4", "e7e5"],
        "depth": 12,
        "nodes": 50000,
    }
    return PositionCache(**(values | overrides))


def move(game_id: int, run_id: int, **overrides: object) -> MoveAnalysis:
    values = {
        "game_id": game_id,
        "analysis_run_id": run_id,
        "ply": 1,
        "move_number": 1,
        "mover": PlayerColor.WHITE,
        "fen_before": chess.STARTING_FEN,
        "played_move_uci": "e2e4",
        "played_move_san": "e4",
        "best_move_uci": "e2e4",
        "eval_before_cp_white": 25,
        "eval_after_cp_white": 25,
        "loss_cp": 0,
        "pv_json": ["e2e4", "e7e5"],
        "analysis_version": "1",
    }
    return MoveAnalysis(**(values | overrides))


@pytest.fixture
def game_and_run(sessions: sessionmaker[Session], player_id: int) -> tuple[int, int]:
    with sessions.begin() as session:
        stored_game, run = game(player_id), analysis_run(player_id)
        session.add_all([stored_game, run])
        session.flush()
        return stored_game.id, run.id


def test_create_tracked_player(sessions: sessionmaker[Session], player_id: int) -> None:
    with sessions() as session:
        player = session.get(TrackedPlayer, player_id)
        assert player is not None
        assert player.username == "testplayer"
        assert player.platform == Platform.CHESS_COM
        assert player.created_at.tzinfo == UTC


@pytest.mark.parametrize("username", ["testplayer", "TESTPLAYER"])
def test_duplicate_tracked_player_rejected(
    sessions: sessionmaker[Session], player_id: int, username: str
) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(TrackedPlayer(platform=Platform.CHESS_COM, username=username))
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(TrackedPlayer)) == 1


def test_create_game(sessions: sessionmaker[Session], player_id: int) -> None:
    original = game(player_id)
    with sessions.begin() as session:
        session.add(original)
    with sessions() as session:
        stored = session.get(Game, original.id)
        assert stored is not None
        assert stored.raw_pgn == original.raw_pgn
        assert stored.played_at == PLAYED_AT
        assert stored.white_rating is None
        assert stored.player_color == PlayerColor.WHITE
        assert stored.result == GameResult.WIN


def test_orphan_game_rejected(sessions: sessionmaker[Session]) -> None:
    with (
        pytest.raises(IntegrityError, match="FOREIGN KEY"),
        sessions.begin() as session,
    ):
        session.add(game(999999))


@pytest.mark.parametrize(
    "overrides",
    [
        {"canonical_hash": "b" * 64},  # same source ID, different hash
        {"platform": Platform.PGN, "external_id": None},  # same hash across sources
    ],
    ids=["external-id", "canonical-hash"],
)
def test_duplicate_game_rejected(
    sessions: sessionmaker[Session], player_id: int, overrides: dict[str, object]
) -> None:
    with sessions.begin() as session:
        session.add(game(player_id))
    with pytest.raises(IntegrityError, match="UNIQUE"), sessions.begin() as session:
        session.add(game(player_id, **overrides))
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Game)) == 1


def test_distinct_pgn_games_can_have_null_external_ids(
    sessions: sessionmaker[Session], player_id: int
) -> None:
    with sessions.begin() as session:
        session.add_all(
            [
                game(
                    player_id,
                    platform=Platform.PGN,
                    external_id=None,
                    canonical_hash=h * 64,
                )
                for h in ("a", "b")
            ]
        )
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Game)) == 2


def test_create_import_run(sessions: sessionmaker[Session], player_id: int) -> None:
    run = ImportRun(tracked_player_id=player_id)
    with sessions.begin() as session:
        session.add(run)
    with sessions() as session:
        stored = session.get(ImportRun, run.id)
        assert stored is not None
        assert stored.status == RunStatus.PENDING
        assert stored.started_at is None and stored.finished_at is None
        assert stored.games_seen == stored.games_inserted == stored.games_skipped == 0
    with sessions.begin() as session:
        session.execute(
            update(ImportRun)
            .where(ImportRun.id == run.id)
            .values(
                status=RunStatus.SUCCEEDED,
                started_at=PLAYED_AT,
                finished_at=PLAYED_AT + timedelta(minutes=1),
                games_seen=4,
                games_inserted=1,
                games_existing=1,
                games_skipped=1,
                games_failed=1,
            )
        )
    with sessions() as session:
        stored = session.get(ImportRun, run.id)
        assert stored.games_seen == (
            stored.games_inserted
            + stored.games_existing
            + stored.games_skipped
            + stored.games_failed
        )


def test_create_analysis_run(sessions: sessionmaker[Session], player_id: int) -> None:
    run = analysis_run(player_id)
    with sessions.begin() as session:
        session.add(run)
    with sessions() as session:
        stored = session.get(AnalysisRun, run.id)
        assert stored is not None
        assert stored.tracked_player_id == player_id
        assert stored.engine_config_json == run.engine_config_json
        assert stored.engine_config_json["nodes"] == 50000
        assert stored.draw_policy_version == "unclaimed-v1"
        assert stored.status == RunStatus.PENDING
        assert stored.finished_at is None
        assert stored.cache_hits == stored.cache_misses == stored.games_failed == 0


def test_game_analysis_state_unique_per_version(
    sessions: sessionmaker[Session], game_and_run: tuple[int, int]
) -> None:
    game_id, run_id = game_and_run
    with sessions.begin() as session:
        session.add(
            GameAnalysisState(
                game_id=game_id, analysis_run_id=run_id, analysis_version="1"
            )
        )
    with pytest.raises(IntegrityError, match="UNIQUE"), sessions.begin() as session:
        session.add(
            GameAnalysisState(
                game_id=game_id, analysis_run_id=run_id, analysis_version="1"
            )
        )
    with sessions.begin() as session:
        session.add(GameAnalysisState(game_id=game_id, analysis_version="2"))


def test_per_game_resume_state_survives_new_sessions(
    sessions: sessionmaker[Session], player_id: int
) -> None:
    with sessions.begin() as session:
        run = analysis_run(player_id, status=RunStatus.RUNNING)
        session.add(run)
        session.flush()
        for index, status in enumerate(GameAnalysisStatus):
            stored_game = game(
                player_id, external_id=str(index), canonical_hash=str(index) * 64
            )
            session.add(stored_game)
            session.flush()
            session.add(
                GameAnalysisState(
                    game_id=stored_game.id,
                    analysis_run_id=run.id,
                    analysis_version="1",
                    status=status,
                )
            )
    with sessions() as session:
        unfinished = session.scalars(
            select(GameAnalysisState).where(
                GameAnalysisState.status != GameAnalysisStatus.DONE
            )
        ).all()
        assert {state.status for state in unfinished} == {
            GameAnalysisStatus.PENDING,
            GameAnalysisStatus.RUNNING,
            GameAnalysisStatus.FAILED,
        }
        assert all(state.analysis_run_id == run.id for state in unfinished)


def test_create_position_cache(sessions: sessionmaker[Session]) -> None:
    entry = cache()
    with sessions.begin() as session:
        session.add(entry)
    with sessions() as session:
        stored = session.get(PositionCache, entry.id)
        assert stored is not None
        assert stored.pv_json == ["e2e4", "e7e5"]
        assert stored.score_cp_white == 25 and stored.mate_distance_white is None
        assert stored.created_at.tzinfo == UTC


def test_duplicate_cache_rejected(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        session.add(cache())
    with pytest.raises(IntegrityError, match="UNIQUE"), sessions.begin() as session:
        session.add(cache())


@pytest.mark.parametrize(
    "overrides",
    [
        {"history_hash": "other-history"},
        {"history_before_start_unknown": True},
        {"engine_version": "other-engine"},
        {"analysis_version": "2"},
        {"config_hash": "different-budget"},
        {"draw_policy_version": "unclaimed-v2"},
    ],
)
def test_same_fen_can_store_incompatible_analysis(
    sessions: sessionmaker[Session], overrides: dict[str, object]
) -> None:
    # Synthetic identities: generating hashes/replaying PGN belongs to later phases.
    with sessions.begin() as session:
        session.add_all([cache(), cache(**overrides)])
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(PositionCache)) == 2


def test_create_move_analysis(
    sessions: sessionmaker[Session], game_and_run: tuple[int, int]
) -> None:
    entry = move(*game_and_run)
    with sessions.begin() as session:
        session.add(entry)
    with sessions() as session:
        stored = session.get(MoveAnalysis, entry.id)
        assert stored is not None
        assert stored.analysis_run_id == game_and_run[1]
        assert stored.move_number == (stored.ply + 1) // 2
        assert stored.mover == PlayerColor.WHITE
        assert stored.phase is None and stored.severity is None
        assert stored.eval_before_cp_white == stored.eval_after_cp_white == 25


def test_duplicate_move_analysis_rejected(
    sessions: sessionmaker[Session], game_and_run: tuple[int, int]
) -> None:
    with sessions.begin() as session:
        session.add(move(*game_and_run))
    with pytest.raises(IntegrityError, match="UNIQUE"), sessions.begin() as session:
        session.add(move(*game_and_run))
    with sessions.begin() as session:
        session.add(move(*game_and_run, ply=2, mover=PlayerColor.BLACK))


def test_game_delete_cascades_only_dependent_analysis(
    sessions: sessionmaker[Session], game_and_run: tuple[int, int], player_id: int
) -> None:
    game_id, run_id = game_and_run
    with sessions.begin() as session:
        session.add_all(
            [
                move(game_id, run_id),
                cache(),
                GameAnalysisState(
                    game_id=game_id, analysis_version="1", analysis_run_id=run_id
                ),
            ]
        )
    with sessions.begin() as session:
        session.execute(delete(Game).where(Game.id == game_id))
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(MoveAnalysis)) == 0
        assert session.scalar(select(func.count()).select_from(GameAnalysisState)) == 0
        assert session.get(AnalysisRun, run_id) is not None
        assert session.get(TrackedPlayer, player_id) is not None
        assert session.scalar(select(func.count()).select_from(PositionCache)) == 1


def test_player_and_run_deletion_are_restricted(
    sessions: sessionmaker[Session], game_and_run: tuple[int, int], player_id: int
) -> None:
    with sessions.begin() as session:
        session.add(move(*game_and_run))
    for model, identity in [(TrackedPlayer, player_id), (AnalysisRun, game_and_run[1])]:
        with (
            pytest.raises(IntegrityError, match="FOREIGN KEY"),
            sessions.begin() as session,
        ):
            session.execute(delete(model).where(model.id == identity))


@pytest.mark.parametrize(
    "overrides",
    [
        {"ply": 0},
        {"move_number": 0},
        {"mover": "green"},
        {"loss_cp": -1},
        {"mate_before_white": 3},
        {"mate_after_white": -2},
        {"eval_before_cp_white": None},
        {"phase": "invalid"},
        {"severity": "invalid"},
    ],
)
def test_move_invariants_rejected(
    sessions: sessionmaker[Session],
    game_and_run: tuple[int, int],
    overrides: dict[str, object],
) -> None:
    with pytest.raises(IntegrityError, match="CHECK"), sessions.begin() as session:
        session.add(move(*game_and_run, **overrides))


@pytest.mark.parametrize(
    "field",
    [
        "archives_requested",
        "games_seen",
        "games_inserted",
        "games_existing",
        "games_skipped",
        "games_failed",
    ],
)
def test_import_counts_cannot_be_negative(
    sessions: sessionmaker[Session], player_id: int, field: str
) -> None:
    with pytest.raises(IntegrityError, match="CHECK"), sessions.begin() as session:
        session.add(ImportRun(tracked_player_id=player_id, **{field: -1}))


@pytest.mark.parametrize(
    "field",
    [
        "games_total",
        "games_completed",
        "games_failed",
        "positions_analyzed",
        "cache_hits",
        "cache_misses",
        "error_count",
    ],
)
def test_analysis_counts_cannot_be_negative(
    sessions: sessionmaker[Session], player_id: int, field: str
) -> None:
    with pytest.raises(IntegrityError, match="CHECK"), sessions.begin() as session:
        session.add(analysis_run(player_id, **{field: -1}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"mate_distance_white": 3},
        {"score_cp_white": None},
        {"depth": -1},
        {"nodes": -1},
    ],
)
def test_cache_invariants_rejected(
    sessions: sessionmaker[Session], overrides: dict[str, object]
) -> None:
    with pytest.raises(IntegrityError, match="CHECK"), sessions.begin() as session:
        session.add(cache(**overrides))


@pytest.mark.parametrize("model", [ImportRun, AnalysisRun, GameAnalysisState])
def test_invalid_status_rejected(
    sessions: sessionmaker[Session],
    player_id: int,
    game_and_run: tuple[int, int],
    model: type,
) -> None:
    if model is ImportRun:
        entry = ImportRun(tracked_player_id=player_id, status="invalid")
    elif model is AnalysisRun:
        entry = analysis_run(player_id, status="invalid")
    else:
        entry = GameAnalysisState(
            game_id=game_and_run[0], analysis_version="1", status="invalid"
        )
    with pytest.raises(IntegrityError, match="CHECK"), sessions.begin() as session:
        session.add(entry)


def test_invalid_player_color_rejected(
    sessions: sessionmaker[Session], player_id: int
) -> None:
    with pytest.raises(IntegrityError, match="CHECK"), sessions.begin() as session:
        session.add(game(player_id, player_color="green"))


def test_mate_is_separate_and_loss_can_be_unknown(
    sessions: sessionmaker[Session], game_and_run: tuple[int, int]
) -> None:
    with sessions.begin() as session:
        session.add(cache(score_cp_white=None, mate_distance_white=-2))
        session.add(
            move(
                *game_and_run,
                eval_after_cp_white=None,
                mate_after_white=-2,
                loss_cp=None,
            )
        )
    with sessions() as session:
        stored = session.scalar(select(MoveAnalysis))
        assert stored.eval_after_cp_white is None and stored.mate_after_white == -2
        assert stored.loss_cp is None


def test_timestamps_normalize_to_utc(
    sessions: sessionmaker[Session], player_id: int
) -> None:
    offset = timezone(timedelta(hours=5, minutes=30))
    entry = game(player_id, played_at=PLAYED_AT.astimezone(offset))
    with sessions.begin() as session:
        session.add(entry)
    with sessions() as session:
        stored = session.get(Game, entry.id)
        assert stored.played_at == PLAYED_AT
        assert stored.played_at.tzinfo == UTC


def test_naive_timestamps_rejected(
    sessions: sessionmaker[Session], player_id: int
) -> None:
    with pytest.raises(StatementError, match="timezone"), sessions.begin() as session:
        session.add(game(player_id, played_at=PLAYED_AT.replace(tzinfo=None)))
