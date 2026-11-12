"""Keep score and PV from one complete UCI update, without sticky bound flags."""

from collections.abc import Iterable
from typing import overload

import chess
import chess.engine


class UnstableMultiPVError(chess.engine.EngineError):
    """Search ended without comparable lines consistent with its best move."""


class EvidenceProtocol(chess.engine.UciProtocol):
    require_final_rank_match = True

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
            return await self._analyse_ranked(
                board, limit, multipv, game, info, root_moves, options or {}
            )
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

    async def _analyse_ranked(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        multipv: int,
        game: object,
        info: chess.engine.Info,
        root_moves: Iterable[chess.Move] | None,
        options: chess.engine.ConfigMapping,
    ) -> list[chess.engine.InfoDict]:
        # A search can stop mid-iteration. Never compare lines from different
        # iterations or let a bound replace only the score of an earlier PV.
        expected = set(range(1, multipv + 1))
        latest: list[chess.engine.InfoDict] = []
        current: dict[int, chess.engine.InfoDict] = {}
        depth = None
        analysis = await self.analysis(
            board,
            limit,
            multipv=multipv,
            game=game,
            info=info,
            root_moves=root_moves,
            options=options,
        )
        with analysis:
            async for update in analysis:
                rank = update.get("multipv")
                iteration = update.get("depth")
                if rank not in expected or iteration is None or "score" not in update:
                    continue
                if depth != iteration or rank == 1:
                    current.clear()
                    depth = iteration
                if (
                    update.get("pv")
                    and not update.get("lowerbound")
                    and not update.get("upperbound")
                ):
                    current[rank] = update.copy()
                else:
                    current.pop(rank, None)
                if current.keys() == expected:
                    latest = [current[i] for i in range(1, multipv + 1)]
        best = await analysis.wait()
        if not latest or (
            self.require_final_rank_match and best.move != latest[0]["pv"][0]
        ):
            raise UnstableMultiPVError(
                "No complete unbounded MultiPV iteration matches the final best move"
            )
        return latest


class ReviewEvidenceProtocol(EvidenceProtocol):
    """Use the last complete ranking for short interactive searches."""

    require_final_rank_match = False
