"""Keep score and PV from one complete UCI update, without sticky bound flags."""

from collections.abc import Iterable
from typing import overload

import chess
import chess.engine


class EvidenceProtocol(chess.engine.UciProtocol):
    @overload
    async def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: None = None,
        game: object = None,
        info: chess.engine.Info = chess.engine.INFO_ALL,
        root_moves: Iterable[chess.Move] | None = None,
        options: chess.engine.ConfigMapping | None = None,
    ) -> chess.engine.InfoDict: ...

    @overload
    async def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int,
        game: object = None,
        info: chess.engine.Info = chess.engine.INFO_ALL,
        root_moves: Iterable[chess.Move] | None = None,
        options: chess.engine.ConfigMapping | None = None,
    ) -> list[chess.engine.InfoDict]: ...

    @overload
    async def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int | None = None,
        game: object = None,
        info: chess.engine.Info = chess.engine.INFO_ALL,
        root_moves: Iterable[chess.Move] | None = None,
        options: chess.engine.ConfigMapping | None = None,
    ) -> chess.engine.InfoDict | list[chess.engine.InfoDict]: ...

    async def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int | None = None,
        game: object = None,
        info: chess.engine.Info = chess.engine.INFO_ALL,
        root_moves: Iterable[chess.Move] | None = None,
        options: chess.engine.ConfigMapping | None = None,
    ) -> chess.engine.InfoDict | list[chess.engine.InfoDict]:
        if multipv is not None:
            raise chess.engine.EngineError("Evidence analysis supports single PV only")
        analysis = await self.analysis(
            board,
            limit,
            game=game,
            info=info,
            root_moves=root_moves,
            options=options or {},
        )
        latest: chess.engine.InfoDict = {}
        with analysis:
            async for update in analysis:
                if (
                    "score" in update
                    and update.get("pv")
                    and not update.get("lowerbound")
                    and not update.get("upperbound")
                ):
                    latest = update.copy()
        if not latest:
            raise chess.engine.EngineError(
                "Engine returned no complete unbounded evaluation"
            )
        return latest
