"""Fixed-position development diagnostic; never accepts live game input."""

import chess

from chess_coach.config import Settings
from chess_coach.infrastructure.engine.exceptions import ChessEngineError
from chess_coach.infrastructure.engine.stockfish_adapter import StockfishAdapter


def diagnose(settings: Settings) -> int:
    print("CHESS ENGINE DIAGNOSTIC")
    try:
        with StockfishAdapter(settings) as adapter:
            print(f"UCI initialization: PASS ({adapter.engine_name})")
            print(f"Threads: {settings.stockfish_threads}; Hash: {settings.stockfish_hash_mb} MB")
            if not adapter.check_health():
                raise ChessEngineError("Engine ping failed; check executable")
            print("Engine ping: PASS")
            result = adapter.analyze(chess.Board())
            print(f"Sample analysis / best move / full PV: PASS ({result.best_move_uci})")
        print("Engine cleanup: PASS\nOVERALL: PASS")
        return 0
    except (ChessEngineError, ValueError) as exc:
        print(f"OVERALL: FAIL\n{exc}")
        return 1
