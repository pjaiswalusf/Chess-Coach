"""Wire application use cases to concrete local integrations."""

from functools import partial
from typing import Annotated

from fastapi import Depends

from chess_coach.application.system import SystemStatus, collect_system_status
from chess_coach.config import Settings, get_settings
from chess_coach.infrastructure.system.probes import probe_ollama, probe_stockfish


def get_system_status(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SystemStatus:
    return collect_system_status(
        partial(probe_stockfish, settings), partial(probe_ollama, settings)
    )
