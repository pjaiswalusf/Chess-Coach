"""Local Ollama structured adapter with finite transport and token budgets."""

import json

import httpx
from ollama import Client, ResponseError
from pydantic import BaseModel

from chess_coach.application.errors import OperationError
from chess_coach.config import Settings
from chess_coach.domain.motif_models import MotifPrediction
from chess_coach.infrastructure.llm.motif_classifier import MOTIF_SYSTEM_PROMPT
from chess_coach.infrastructure.llm.prompts import SYSTEM_PROMPT


def generation_settings(settings: Settings) -> dict[str, object]:
    return {
        "temperature": 0,
        "num_ctx": settings.llm_context_tokens,
        "num_predict": settings.llm_output_tokens,
        "keep_alive": settings.llm_keep_alive,
        "think": settings.llm_think,
        "timeout": settings.llm_timeout_seconds,
    }


class OllamaCoach:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.metrics: dict[str, object] = {}

    def generate(self, evidence_json: str, schema: type[BaseModel]) -> str:
        # Full legal history remains in persisted identity/replay evidence. The
        # model receives only the compact current-position evidence it explains.
        payload = json.loads(evidence_json)
        if isinstance(payload, dict):
            payload = {k: v for k, v in payload.items() if k not in {
                "initial_fen", "history_uci", "source_hash", "profile_hash", "report_hash"
            }}
        evidence_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(evidence_json.encode()) > 10_000:
            raise OperationError(
                "EVIDENCE_INCOMPLETE",
                "The coaching evidence exceeds the local context limit.",
            )
        self.metrics = {}
        try:
            # Explicit client ownership prevents connection leaks across jobs.
            client = Client(
                host=str(self.settings.ollama_host),
                timeout=self.settings.llm_timeout_seconds,
                trust_env=False,
            )
            # Ollama's SDK owns an httpx client; close it even on failures.
            try:
                response = client.chat(
                    model=self.settings.ollama_model,
                    messages=[
                        {
                            "role": "system",
                            "content": MOTIF_SYSTEM_PROMPT
                            if schema is MotifPrediction
                            else SYSTEM_PROMPT,
                        },
                        {"role": "user", "content": evidence_json},
                    ],
                    format=schema.model_json_schema(),
                    stream=False,
                    options={
                        "temperature": 0,
                        "num_ctx": self.settings.llm_context_tokens,
                        "num_predict": self.settings.llm_output_tokens,
                    },
                    think=self.settings.llm_think,
                    keep_alive=self.settings.llm_keep_alive,
                )
            finally:
                client._client.close()
            self.metrics = {
                k: getattr(response, k)
                for k in (
                    "total_duration",
                    "load_duration",
                    "prompt_eval_count",
                    "eval_count",
                )
            }
            content = response.message.content
            if not response.done or not content or len(content) > 10_000:
                raise OperationError(
                    "INVALID_MODEL_OUTPUT",
                    "The model returned incomplete output. Retry coaching.",
                )
            return content
        except httpx.TimeoutException:
            raise OperationError(
                "COACHING_TIMEOUT",
                "Local generation timed out. Retry with Ollama available.",
                503,
            ) from None
        except httpx.TransportError, ConnectionError:
            raise OperationError(
                "OLLAMA_UNAVAILABLE", "Start Ollama locally and retry coaching.", 503
            ) from None
        except ResponseError as exc:
            code = (
                "MODEL_NOT_INSTALLED"
                if exc.status_code == 404
                else "MODEL_REQUEST_INVALID"
                if exc.status_code == 400
                else "OLLAMA_UNAVAILABLE"
            )
            raise OperationError(
                code, "Check the configured local Ollama model, then retry.", 503
            ) from None
