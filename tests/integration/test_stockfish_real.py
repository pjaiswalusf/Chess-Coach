import chess
import pytest

from chess_coach.config import Settings
from chess_coach.infrastructure.engine.stockfish_adapter import StockfishAdapter

pytestmark = pytest.mark.engine
MATE = "r1bqkbnr/p1pp1ppp/1pn5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 2 4"


def test_real_engine_contracts():
    adapter = StockfishAdapter(Settings(_env_file=None))
    with adapter:
        assert adapter.check_health()
        owned = adapter._engine
        assert owned is not None
        for board in [chess.Board(), chess.Board(MATE), chess.Board(MATE).mirror()]:
            assert board.is_valid()
            original = board.fen(), list(board.move_stack)
            result = adapter.analyze(board, nodes=100_000)
            assert result.depth and result.nodes
            assert result.best_move_uci == result.pv_uci[0]
            replay = board.copy(stack=True)
            for uci in result.pv_uci:
                replay.push_uci(uci)
            assert (board.fen(), board.move_stack) == original
            if board.fullmove_number == 4:
                assert result.mate_white == (1 if board.turn else -1)
                assert result.mate_winner == board.turn
        # Broad orientation, avoiding exact engine-dependent centipawns.
        advantage = chess.Board()
        advantage.remove_piece_at(chess.D8)
        for board, sign in [(advantage, 1), (advantage.mirror(), -1)]:
            assert board.is_valid()
            result = adapter.analyze(board, nodes=100_000)
            assert result.score_cp_white is not None
            assert sign * result.score_cp_white > 300
        for _ in range(5):
            adapter.analyze(chess.Board())
        assert adapter._engine is owned
    assert owned.returncode.result(timeout=5) == 0
    adapter.close()


def test_real_exception_cleanup():
    adapter = StockfishAdapter(Settings(_env_file=None))
    with pytest.raises(RuntimeError), adapter:
        owned = adapter._engine
        raise RuntimeError("caller failure")
    assert owned is not None
    owned.returncode.result(timeout=5)


def test_real_puzzle_multipv_preserves_history_and_ranks():
    from chess_coach.domain.training import verify_solution

    board = chess.Board()
    for uci in ("e2e4", "e7e5", "f1c4", "b8c6", "d1f3", "b7b6"):
        board.push_uci(uci)
    original = board.fen(), board.move_stack.copy()
    with StockfishAdapter(Settings(_env_file=None)) as adapter:
        lines = adapter.analyze_puzzle_candidate(board, nodes=200_000, multipv=3)
        solution = verify_solution(board, "g1e2", lines, adapter.engine_name)
        assert solution.move_uci == "f3f7"
        assert solution.theme == "forced_mate"
    assert (board.fen(), board.move_stack) == original
