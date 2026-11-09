import shutil
import subprocess

import httpx

from chess_coach.application.system import DependencyStatus
from chess_coach.config import Settings
from chess_coach.infrastructure.llm.health import local_model_digest

STOCKFISH_PROBE_TIMEOUT_SECONDS = 2.0


def probe_stockfish(settings: Settings) -> DependencyStatus:
    executable = shutil.which(settings.stockfish_executable)
    if executable is None:
        return DependencyStatus(
            "unavailable",
            "Stockfish was not found. Install it or configure its executable.",
            "STOCKFISH_NOT_FOUND",
        )
    try:
        result = subprocess.run(
            [executable],
            input="uci\nisready\nquit\n",
            capture_output=True,
            text=True,
            timeout=STOCKFISH_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return DependencyStatus(
            "unavailable", "The Stockfish UCI check timed out.", "STOCKFISH_UCI_TIMEOUT"
        )
    except OSError, UnicodeError:
        return DependencyStatus(
            "unavailable",
            "Stockfish could not respond. Check its installation and retry.",
            "STOCKFISH_UCI_FAILED",
        )

    lines = result.stdout.splitlines()
    identifies_stockfish = any(
        line.lower().startswith("id name stockfish") for line in lines
    )
    if (
        result.returncode != 0
        or not identifies_stockfish
        or not {"uciok", "readyok"} <= set(lines)
    ):
        return DependencyStatus(
            "unavailable",
            "The configured executable did not complete the Stockfish UCI check.",
            "STOCKFISH_UCI_FAILED",
        )
    return DependencyStatus("available", "Stockfish responds to UCI commands.")


def probe_ollama(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[DependencyStatus, DependencyStatus]:
    unknown_model = DependencyStatus("unknown", "Model readiness could not be checked.")
    service = DependencyStatus("available", "Ollama is reachable.")
    try:
        digest = local_model_digest(settings, transport)
    except TimeoutError, httpx.TimeoutException:
        return DependencyStatus(
            "unavailable",
            "Ollama timed out. Check the service and retry.",
            "OLLAMA_TIMEOUT",
        ), unknown_model
    except httpx.HTTPError:
        return DependencyStatus(
            "unavailable",
            "Ollama is unavailable. Start it and check its address.",
            "OLLAMA_UNREACHABLE",
        ), unknown_model
    except ValueError, KeyError, TypeError:
        return service, DependencyStatus(
            "unknown",
            "Ollama returned an invalid local model inventory.",
            "OLLAMA_INVENTORY_INVALID",
            "Check the local Ollama model inventory and retry.",
        )
    if digest:
        return service, DependencyStatus(
            "available", "The configured model is installed."
        )
    return service, DependencyStatus(
        "unavailable",
        "The configured model is not installed.",
        "MODEL_NOT_INSTALLED",
    )
