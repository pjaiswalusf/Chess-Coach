import asyncio
from unittest.mock import AsyncMock

import chess
import chess.engine
import pytest

from chess_coach.infrastructure.engine.protocol import (
    EvidenceProtocol,
    UnstableMultiPVError,
)


def test_score_and_pv_are_from_same_unbounded_update():
    async def run():
        stream = chess.engine.AnalysisResult()
        bound = {
            "score": chess.engine.PovScore(chess.engine.Cp(60), chess.WHITE),
            "pv": [chess.Move.from_uci("d2d4")],
            "lowerbound": True,
            "depth": 4,
        }
        exact = {
            "score": chess.engine.PovScore(chess.engine.Cp(25), chess.WHITE),
            "pv": [chess.Move.from_uci("e2e4")],
            "depth": 5,
            "nodes": 100,
        }
        stream.post(bound)
        stream.post(exact)
        stream.post({**bound, "depth": 6})
        stream.post({"nodes": 200})
        stream.set_finished(chess.engine.BestMove(chess.Move.from_uci("e2e4"), None))
        protocol = EvidenceProtocol()
        protocol.analysis = AsyncMock(return_value=stream)
        assert (
            await protocol.analyse(chess.Board(), chess.engine.Limit(nodes=100))
            == exact
        )

    asyncio.run(run())


def test_bound_only_search_is_rejected():
    async def run():
        stream = chess.engine.AnalysisResult()
        stream.post(
            {
                "score": chess.engine.PovScore(chess.engine.Cp(60), chess.WHITE),
                "pv": [chess.Move.from_uci("d2d4")],
                "upperbound": True,
            }
        )
        stream.set_finished(chess.engine.BestMove(chess.Move.from_uci("d2d4"), None))
        protocol = EvidenceProtocol()
        protocol.analysis = AsyncMock(return_value=stream)
        with pytest.raises(chess.engine.EngineError, match="unbounded"):
            await protocol.analyse(chess.Board(), chess.engine.Limit(nodes=100))

    asyncio.run(run())


def test_interrupted_stream_does_not_return_partial_success():
    async def run():
        stream = chess.engine.AnalysisResult()
        stream.post(
            {
                "score": chess.engine.PovScore(chess.engine.Cp(25), chess.WHITE),
                "pv": [chess.Move.from_uci("e2e4")],
            }
        )
        stream.set_exception(chess.engine.EngineTerminatedError("test crash"))
        protocol = EvidenceProtocol()
        protocol.analysis = AsyncMock(return_value=stream)
        with pytest.raises(chess.engine.EngineTerminatedError):
            await protocol.analyse(chess.Board(), chess.engine.Limit(nodes=100))

    asyncio.run(run())


@pytest.mark.parametrize("final_move", ["e2e4", "d2d4"])
def test_multipv_keeps_only_complete_unbounded_iterations(final_move):
    async def run():
        stream = chess.engine.AnalysisResult()
        for depth, rank, move, bound in [
            (9, 1, "e2e4", False),
            (9, 2, "d2d4", False),
            (10, 1, "d2d4", False),
            (10, 2, "e2e4", True),
            (11, 1, "d2d4", False),
        ]:
            stream.post(
                {
                    "score": chess.engine.PovScore(
                        chess.engine.Cp(60 - rank), chess.WHITE
                    ),
                    "pv": [chess.Move.from_uci(move)],
                    "depth": depth,
                    "multipv": rank,
                    "upperbound": bound,
                }
            )
        stream.set_finished(
            chess.engine.BestMove(chess.Move.from_uci(final_move), None)
        )
        protocol = EvidenceProtocol()
        protocol.analysis = AsyncMock(return_value=stream)
        if final_move != "e2e4":
            with pytest.raises(UnstableMultiPVError):
                await protocol.analyse(
                    chess.Board(), chess.engine.Limit(nodes=100), multipv=2
                )
            return
        lines = await protocol.analyse(
            chess.Board(), chess.engine.Limit(nodes=100), multipv=2
        )
        assert [(row["depth"], row["pv"][0].uci()) for row in lines] == [
            (9, "e2e4"),
            (9, "d2d4"),
        ]

    asyncio.run(run())
