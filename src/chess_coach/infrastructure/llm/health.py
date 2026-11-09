"""Bounded local model inventory shared by coaching and diagnostics."""

import asyncio

import httpx

from chess_coach.config import Settings
from chess_coach.domain.coaching_models import LLMHealth

INVENTORY_TIMEOUT_SECONDS = 2.0


async def fetch_inventory(
    settings: Settings, transport: httpx.AsyncBaseTransport | None
) -> list[dict[str, object]]:
    url = f"{str(settings.ollama_host).rstrip('/')}/api/tags"
    async with (
        asyncio.timeout(INVENTORY_TIMEOUT_SECONDS),
        httpx.AsyncClient(
            trust_env=False, transport=transport, timeout=INVENTORY_TIMEOUT_SECONDS
        ) as client,
    ):
        response = await client.get(url)
        response.raise_for_status()
    models = response.json()["models"]
    if not isinstance(models, list) or any(
        not isinstance(model, dict)
        or not isinstance(model.get("name"), str)
        or not model["name"]
        for model in models
    ):
        raise ValueError("Invalid model inventory")
    return models


def local_model_digest(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> str | None:
    name = settings.ollama_model
    if ":" not in name:
        name += ":latest"
    for model in asyncio.run(fetch_inventory(settings, transport)):
        if model["name"] == name:
            digest = model.get("digest")
            if not isinstance(digest, str) or not digest:
                raise ValueError("Missing digest")
            if model.get("remote_host") or model.get("remote_model"):
                raise ValueError("Remote model")
            return digest
    return None


def check_health(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> LLMHealth:
    try:
        digest = local_model_digest(settings, transport)
    except httpx.HTTPError, TimeoutError:
        return LLMHealth(
            model=settings.ollama_model,
            server_reachable=False,
            model_installed=False,
            status="server_unavailable",
            message="Start Ollama locally, then retry coaching.",
        )
    except ValueError, KeyError, TypeError:
        return LLMHealth(
            model=settings.ollama_model,
            server_reachable=True,
            model_installed=False,
            status="check_failed",
            message="Check the local Ollama model inventory and configuration.",
        )
    if digest is None:
        return LLMHealth(
            model=settings.ollama_model,
            server_reachable=True,
            model_installed=False,
            status="model_missing",
            message="Configure an existing local Ollama model tag, then retry.",
        )
    return LLMHealth(
        model=settings.ollama_model,
        server_reachable=True,
        model_installed=True,
        status="ready",
        model_digest=digest,
        message="Local model installed; generation not tested.",
    )
