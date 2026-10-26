"""Collect dependency readiness without depending on integration implementations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DependencyStatus:
    state: Literal["available", "unavailable", "unknown"]
    detail: str


@dataclass(frozen=True)
class SystemStatus:
    stockfish: DependencyStatus
    ollama: DependencyStatus
    ollama_model: DependencyStatus


def collect_system_status(
    stockfish_probe: Callable[[], DependencyStatus],
    ollama_probe: Callable[[], tuple[DependencyStatus, DependencyStatus]],
) -> SystemStatus:
    stockfish = stockfish_probe()
    ollama, model = ollama_probe()
    return SystemStatus(stockfish=stockfish, ollama=ollama, ollama_model=model)
