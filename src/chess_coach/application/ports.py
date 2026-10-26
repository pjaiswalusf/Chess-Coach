from collections.abc import Sequence
from typing import Protocol

from chess_coach.domain.models import (
    CoachResponse,
    EngineAnalysis,
    ExternalGame,
)


class GameProvider(Protocol):
    """Source of external chess games."""

    def fetch_games(self, username: str) -> Sequence[ExternalGame]: ...


class GameRepository(Protocol):
    """Persistence boundary for imported games."""

    def exists(self, external_id: str) -> bool: ...

    def save(self, game: ExternalGame) -> None: ...


class AnalysisRepository(Protocol):
    """Persistence boundary for chess analysis results."""

    def get_cached_position(
        self,
        fen: str,
        engine_version: str,
        config_hash: str,
    ) -> EngineAnalysis | None: ...

    def save_position_analysis(
        self,
        fen: str,
        engine_version: str,
        config_hash: str,
        analysis: EngineAnalysis,
    ) -> None: ...


class ChessEngine(Protocol):
    """Boundary around deterministic chess-engine analysis."""

    def analyze(self, fen: str) -> EngineAnalysis: ...


class CoachModel(Protocol):
    """Boundary around the local language model."""

    def explain(self, evidence: str) -> CoachResponse: ...
