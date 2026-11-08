"""V1 policies. Changes to these defaults require a feature-version bump."""

from dataclasses import dataclass

PIECE_VALUES = {1: 1, 2: 3, 3: 3, 4: 5, 5: 9}


@dataclass(frozen=True)
class FeatureConfig:
    endgame_material: int = 14
    opening_last_move: int = 10
    advantage_cp: int = 150
    lost_advantage_cp: int = 50
    fast_seconds: float = 3.0
    pressure_seconds: float = 30.0
    pressure_fraction: float = 0.1


DEFAULT_CONFIG = FeatureConfig()
