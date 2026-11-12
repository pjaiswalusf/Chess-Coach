from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import chess
import chess.engine
import chess.variant
import pytest

from chess_coach.config import Settings
from chess_coach.infrastructure.engine.exceptions import (
    EngineAnalysisError,
    EngineUnavailableError,
    InvalidPositionError,
)
from chess_coach.infrastructure.engine.stockfish_adapter import StockfishAdapter


@pytest.fixture
def setup_engine(monkeypatch):
    engine = Mock()
    engine.id = {"name": "Fake Stockfish"}
    engine.options = {"Threads": None, "Hash": None}
    engine.returncode = Future()
    engine.returncode.set_result(0)
    engine.analyse.return_value = {
        "score": chess.engine.PovScore(chess.engine.Cp(25), chess.WHITE),
        "pv": [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")],
        "depth": 5, "nodes": 100,
    }
    monkeypatch.setattr("shutil.which", lambda _: "/fake/stockfish")
    spawn = Mock(return_value=engine)
    monkeypatch.setattr(chess.engine.SimpleEngine, "popen", spawn)
    return StockfishAdapter(Settings(_env_file=None)), engine, spawn


def test_reuse_history_and_cleanup(setup_engine):
    adapter, engine, spawn = setup_engine
    board = chess.Board()
    board.push_uci("g1f3")
    board.push_uci("g8f6")
    history = list(board.move_stack)
    with adapter:
        for _ in range(10):
            result = adapter.analyze(board, game="game-1")
            assert result.score_cp_white == 25
        assert adapter.check_health()
        sent = engine.analyse.call_args.args[0]
        assert sent is not board and sent.move_stack == history
        assert engine.analyse.call_args.kwargs["game"] == "game-1"
    assert board.move_stack == history
    spawn.assert_called_once()
    engine.quit.assert_called_once()
    adapter.close()
    assert not adapter.check_health()


@pytest.mark.parametrize("budget", [0, -1, True, "100", 10_000_001])
def test_invalid_budget(setup_engine, budget):
    adapter, engine, spawn = setup_engine
    with pytest.raises(ValueError):
        adapter.analyze(chess.Board(), nodes=budget)
    spawn.assert_not_called()
    engine.analyse.assert_not_called()


@pytest.mark.parametrize("board", [chess.Board(None), chess.Board(chess960=True),
                                      chess.variant.AtomicBoard(), "bad"])
def test_invalid_position(setup_engine, board):
    adapter, _, spawn = setup_engine
    with pytest.raises(InvalidPositionError):
        adapter.analyze(board)
    spawn.assert_not_called()


@pytest.mark.parametrize("failure", [TimeoutError(), chess.engine.EngineTerminatedError()])
def test_failure_and_explicit_recovery(setup_engine, failure):
    adapter, engine, spawn = setup_engine
    adapter.start()
    engine.analyse.side_effect = failure
    with pytest.raises(EngineAnalysisError):
        adapter.analyze(chess.Board())
    assert not adapter.check_health()
    engine.close.assert_called_once()
    with pytest.raises(EngineUnavailableError):
        adapter.analyze(chess.Board())
    engine.analyse.side_effect = None
    with adapter:
        assert adapter.analyze(chess.Board()).best_move_uci == "e2e4"
    assert spawn.call_count == 2


@pytest.mark.parametrize("change", [
    {"score": None}, {"pv": []}, {"lowerbound": True},
    {"pv": [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e2e3")]},
    {"nodes": -1},
])
def test_malformed_result(setup_engine, change):
    adapter, engine, _ = setup_engine
    engine.analyse.return_value.update(change)
    with adapter, pytest.raises(EngineAnalysisError):
        adapter.analyze(chess.Board())


def test_missing_binary(setup_engine, monkeypatch):
    adapter, _, spawn = setup_engine
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(EngineUnavailableError):
        adapter.start()
    spawn.assert_not_called()


def test_startup_and_context_failures(setup_engine):
    adapter, engine, _ = setup_engine
    engine.configure.side_effect = chess.engine.EngineError("bad config")
    with pytest.raises(EngineUnavailableError):
        adapter.start()
    engine.close.assert_called_once()
    engine.configure.side_effect = None
    with pytest.raises(RuntimeError), adapter:
        raise RuntimeError("caller failed")
    assert not adapter.check_health()


def test_terminal_draw_and_mate(setup_engine):
    adapter, engine, _ = setup_engine
    mate = chess.Board()
    for san in ["f3", "e5", "g4", "Qh4#"]:
        mate.push_san(san)
    with adapter:
        result = adapter.analyze(mate)
        assert result.mate_white == 0 and result.mate_winner is chess.BLACK
        assert result.score_cp_white is None and result.best_move_uci is None
        draw = chess.Board("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1")
        assert draw.is_stalemate()
        assert adapter.analyze(draw).score_cp_white == 0
    engine.analyse.assert_not_called()


def test_engine_line_stops_at_automatic_draw_without_changing_root_score(setup_engine):
    adapter, engine, _ = setup_engine
    board = chess.Board("4k3/8/8/8/8/8/4b3/4K3 w - - 0 1")
    # Add material so the starting position is playable. Capturing the
    # bishop then leaves the kings and a single knight.
    board.set_piece_at(chess.A1, chess.Piece(chess.KNIGHT, chess.WHITE))
    engine.analyse.return_value.update(
        score=chess.engine.PovScore(chess.engine.Cp(-6), chess.WHITE),
        pv=[chess.Move.from_uci(uci) for uci in ("e1e2", "e8d8")],
    )
    with adapter:
        result = adapter.analyze(board)
    assert result.pv_uci == ("e1e2",)
    assert result.score_cp_white == -6


def test_serialization(setup_engine):
    adapter, engine, _ = setup_engine
    entered, release, second = Event(), Event(), Event()
    info = engine.analyse.return_value
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return info
    engine.analyse.side_effect = blocked
    def health():
        second.set()
        return adapter.check_health()
    with adapter, ThreadPoolExecutor(2) as pool:
        analysis = pool.submit(adapter.analyze, chess.Board())
        assert entered.wait(5)
        ping = pool.submit(health)
        assert second.wait(5)
        assert engine.ping.call_count == 1
        release.set()
        analysis.result(5)
        assert ping.result(5)


def test_claimable_draw_not_assumed_claimed(setup_engine):
    adapter, engine, _ = setup_engine
    board = chess.Board()
    cycle = ["g1f3", "g8f6", "f3g1", "f6g8"]
    for uci in cycle * 2:
        board.push_uci(uci)
    assert board.can_claim_threefold_repetition()
    with adapter:
        assert adapter.analyze(board).best_move_uci is not None
        for uci in cycle * 2:
            board.push_uci(uci)
        assert board.is_fivefold_repetition()
        assert adapter.analyze(board).score_cp_white == 0
    engine.analyse.assert_called_once()


def test_illegal_history_rejected(setup_engine):
    adapter, engine, _ = setup_engine
    board = chess.Board()
    board.push(chess.Move.null())
    with pytest.raises(InvalidPositionError):
        adapter.analyze(board)
    engine.analyse.assert_not_called()


def test_health_failure_and_shutdown_timeout(setup_engine):
    adapter, engine, _ = setup_engine
    adapter.start()
    engine.ping.side_effect = TimeoutError()
    assert not adapter.check_health()
    engine.close.assert_called_once()
    engine.ping.side_effect = None
    adapter.start()
    engine.quit.side_effect = TimeoutError()
    with pytest.raises(EngineAnalysisError):
        adapter.close()
    assert engine.close.call_count == 2


@pytest.mark.parametrize("trigger", ["analysis", "close"])
def test_unconfirmed_exit_blocks_reuse_until_cleanup(setup_engine, trigger):
    adapter, engine, spawn = setup_engine
    adapter.start()
    engine.returncode = Mock()
    engine.returncode.result.side_effect = TimeoutError()
    if trigger == "analysis":
        engine.analyse.side_effect = TimeoutError()
        with pytest.raises(EngineAnalysisError):
            adapter.analyze(chess.Board())
    else:
        with pytest.raises(EngineAnalysisError):
            adapter.close()
    assert not adapter.check_health()
    with pytest.raises(EngineUnavailableError):
        adapter.start()
    with pytest.raises(EngineUnavailableError):
        adapter.analyze(chess.Board())
    spawn.assert_called_once()
    engine.returncode.result.side_effect = None
    adapter.close()
    engine.analyse.side_effect = None
    with adapter:
        assert adapter.check_health()
    assert spawn.call_count == 2
