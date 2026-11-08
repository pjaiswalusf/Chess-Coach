"""Application operations consumed by the HTTP adapter."""

from chess_coach.analytics.contracts import AnalyticsReport, AnalyticsRequest
from chess_coach.analytics.service import AnalyticsService
from chess_coach.domain.sync import normalize_username
from chess_coach.infrastructure.persistence.query_repository import QueryRepository


class QueryService:
    def __init__(self, store: QueryRepository, analytics: AnalyticsService):
        self.store, self.analytics = store, analytics

    def player(self) -> dict[str, object]:
        return self.store.player()

    def set_player(self, username: str) -> dict[str, object]:
        return self.store.set_player(normalize_username(username))

    def games(
        self,
        limit: int,
        offset: int,
        time_class: str | None,
        color: str | None,
        status: str | None,
    ) -> dict[str, object]:
        return self.store.games(limit, offset, time_class, color, status)

    def game(self, game_id: int) -> dict[str, object]:
        return self.store.game(game_id)

    def game_analysis(self, game_id: int, profile: str | None) -> dict[str, object]:
        return self.store.game_analysis(game_id, profile)

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
