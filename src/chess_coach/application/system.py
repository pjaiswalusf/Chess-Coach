"""Collect dependency readiness without depending on integration implementations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DependencyStatus:
    state: Literal["available", "unavailable", "unknown"]
    detail: str
    code: str | None = None
    action: str | None = None


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


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Literal["pass", "warn", "fail", "skip"]
    required: bool
    message: str
    action: str | None = None
    code: str | None = None


def overall_status(
    checks: list[CheckResult],
) -> Literal["healthy", "degraded", "unavailable"]:
    if any(check.required and check.status == "fail" for check in checks):
        return "unavailable"
    if any(check.status != "pass" for check in checks):
        return "degraded"
    return "healthy"
