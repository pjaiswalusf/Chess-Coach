"""Short installation probe, independent of generation and application liveness."""

import httpx

from chess_coach.config import Settings
from chess_coach.domain.coaching_models import LLMHealth


def check_health(
    settings: Settings, transport: httpx.BaseTransport | None = None
) -> LLMHealth:
    reachable = False
    try:
        with httpx.Client(timeout=2, trust_env=False, transport=transport) as client:
            response = client.get(f"{str(settings.ollama_host).rstrip('/')}/api/tags")
            reachable = True
            response.raise_for_status()
            models = response.json()["models"]
            if not isinstance(models, list):
                raise TypeError("Invalid model inventory")
            for model in models:
                if model.get("name") == settings.ollama_model:
                    digest = model.get("digest")
                    if not isinstance(digest, str) or not digest:
                        raise ValueError("Missing digest")
                    # Remote aliases must never masquerade as installed local models.
                    if model.get("remote_host") or model.get("remote_model"):
                        raise ValueError("Remote model")
                    return LLMHealth(
                        model=settings.ollama_model,
                        server_reachable=True,
                        model_installed=True,
                        status="ready",
                        model_digest=digest,
                        message="Local model installed; generation not tested.",
                    )
            return LLMHealth(
                model=settings.ollama_model,
                server_reachable=True,
                model_installed=False,
                status="model_missing",
                message="Configure an existing local Ollama model tag, then retry.",
            )
    except httpx.TransportError:
        return LLMHealth(
            model=settings.ollama_model,
            server_reachable=False,
            model_installed=False,
            status="server_unavailable",
            message="Start Ollama locally, then retry coaching.",
        )
    except ValueError, KeyError, TypeError, AttributeError, httpx.HTTPStatusError:
        return LLMHealth(
            model=settings.ollama_model,
            server_reachable=reachable,
            model_installed=False,
            status="check_failed",
            message="Check the local Ollama model inventory and configuration.",
        )
