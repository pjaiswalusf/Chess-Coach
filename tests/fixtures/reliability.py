"""Deterministic engine used at the application boundary in offline tests."""

from typing import Self

import chess

from chess_coach.domain.engine_types import EngineResult


class FakeEngine:
    engine_name = "fixture-engine"
    calls = 0

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *args):
        self.close()

    def start(self):
        pass

    def close(self):
        pass

    def analyze(self, board: chess.Board, **kwargs) -> EngineResult:
        self.calls += 1
        best = next(iter(board.legal_moves)).uci()
        return EngineResult(
            board.fen(),
            self.engine_name,
            20 * len(board.move_stack),
            None,
            None,
            best,
            (best,),
            4,
            100,
        )
