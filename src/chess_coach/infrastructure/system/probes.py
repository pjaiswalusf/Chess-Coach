import shutil
import subprocess

import httpx

from chess_coach.application.system import DependencyStatus
from chess_coach.config import Settings


def probe_stockfish(settings: Settings) -> DependencyStatus:
    executable = shutil.which(settings.stockfish_executable)
    if executable is None:
        return DependencyStatus(
            "unavailable",
            "Stockfish was not found. Install it or configure its executable.",
        )
    try:
        result = subprocess.run(
            [executable],
            input="uci\nisready\nquit\n",
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired, UnicodeError:
        return DependencyStatus(
            "unavailable",
            "Stockfish could not respond. Check its installation and retry.",
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
        )
    return DependencyStatus("available", "Stockfish responds to UCI commands.")


def probe_ollama(settings: Settings) -> tuple[DependencyStatus, DependencyStatus]:
    url = f"{str(settings.ollama_host).rstrip('/')}/api/tags"
    unknown_model = DependencyStatus("unknown", "Model readiness could not be checked.")
    try:
        response = httpx.get(url, timeout=1.0)
        response.raise_for_status()
    except httpx.TimeoutException:
        return (
            DependencyStatus(
                "unavailable", "Ollama timed out. Check the service and retry."
            ),
            unknown_model,
        )
    except httpx.HTTPError:
        return (
            DependencyStatus(
                "unavailable", "Ollama is unavailable. Start it and check its address."
            ),
            unknown_model,
        )

    service = DependencyStatus("available", "Ollama is reachable.")
    try:
        payload = response.json()
        models = payload["models"]
        if not isinstance(models, list) or any(
            not isinstance(model, dict) or not isinstance(model.get("name"), str)
            for model in models
        ):
            raise ValueError("Invalid model list")
    except ValueError, KeyError, TypeError:
        return service, DependencyStatus(
            "unknown",
            "Ollama returned an invalid model list. Check the service and retry.",
        )

    model_name = settings.ollama_model
    if ":" not in model_name:
        model_name += ":latest"
    if any(model["name"] == model_name for model in models):
        return service, DependencyStatus(
            "available", "The configured model is installed."
        )
    return service, DependencyStatus(
        "unavailable",
        "The configured model is not installed. Pull it with Ollama and retry.",
    )
