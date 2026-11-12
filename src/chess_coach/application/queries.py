"""Application operations consumed by the HTTP adapter."""

from collections.abc import Callable

import chess

from chess_coach.analytics.contracts import AnalyticsReport, AnalyticsRequest
from chess_coach.analytics.sample_policy import severity
from chess_coach.analytics.service import AnalyticsService
from chess_coach.application.errors import OperationError
from chess_coach.domain.sync import SourceError, normalize_username
from chess_coach.infrastructure.persistence.query_repository import QueryRepository


class QueryService:
    def __init__(
        self,
        store: QueryRepository,
        analytics: AnalyticsService,
        verify_player: Callable[[str], str] | None = None,
    ):
        self.store, self.analytics = store, analytics
        self.verify_player = verify_player

    def player(self) -> dict[str, object]:
        return self.store.player()

    def set_player(self, username: str, verify: bool = False) -> dict[str, object]:
        username = normalize_username(username)
        if verify and not self.store.player()["configured"]:
            try:
                if (
                    self.verify_player is None
                    or self.verify_player(username) != username
                ):
                    raise SourceError(
                        "PLAYER_MISMATCH", "Chess.com returned a different player."
                    )
            except SourceError as exc:
                if exc.code == "PLAYER_NOT_FOUND":
                    raise OperationError(
                        "PLAYER_NOT_FOUND",
                        "Chess.com could not find that username. Check the spelling and retry.",
                        404,
                    ) from None
                raise OperationError(
                    "CHESSCOM_UNAVAILABLE",
                    "Could not verify this username with Chess.com. Try again later.",
                    503,
                ) from None
        # The write still enforces single-player ownership if another tab configured first.
        return self.store.set_player(username)

    def games(
        self,
        limit: int,
        offset: int,
        time_class: str | None,
        color: str | None,
        status: str | None,
        result: str | None = None,
    ) -> dict[str, object]:
        return self.store.games(limit, offset, time_class, color, status, result)

    def game(self, game_id: int) -> dict[str, object]:
        return self.store.game(game_id)

    def game_analysis(self, game_id: int, profile: str | None) -> dict[str, object]:
        game, moves = self.store.game_analysis(game_id, profile)
        for move in moves:
            loss = move["loss_cp"]
            move["severity"] = severity(loss if isinstance(loss, int) else None)
        legal_moves_by_ply: list[list[str]] = []
        if isinstance(initial_fen := game["initial_fen"], str):
            board = chess.Board(initial_fen)
            for index in range(len(moves) + 1):
                legal_moves_by_ply.append(
                    []
                    if board.is_game_over(claim_draw=False)
                    else [move.uci() for move in board.legal_moves]
                )
                if index < len(moves):
                    board.push_uci(str(moves[index]["played_move_uci"]))
        return game | {"moves": moves, "legal_moves_by_ply": legal_moves_by_ply}

    def report(
        self, window: str, color: str, time_class: str, profile: str | None
    ) -> AnalyticsReport | None:
        if not self.store.player()["configured"]:
            return None
        profile = profile or self.store.profile()
        # No profile means no engine evidence; still report deterministic game outcomes.
        return self.analytics.build_report(
            AnalyticsRequest.model_validate(
                {
                    "player_id": self.store.player_id(),
                    "profile_hash": profile or "unavailable",
                    "window": window,
                    "color": None if color == "all" else color,
                    "time_class": None if time_class == "all" else time_class,
                }
            )
        )
