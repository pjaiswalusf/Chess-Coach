from types import SimpleNamespace

import httpx
import pytest
from ollama import ResponseError

from chess_coach.application.errors import OperationError
from chess_coach.config import Settings
from chess_coach.domain.coaching_models import MovePractice
from chess_coach.infrastructure.llm.client import OllamaCoach


@pytest.mark.parametrize(
    "failure,code",
    [
        (httpx.ReadTimeout("timeout"), "COACHING_TIMEOUT"),
        (ConnectionError("offline"), "OLLAMA_UNAVAILABLE"),
        (ResponseError("missing", 404), "MODEL_NOT_INSTALLED"),
    ],
)
def test_adapter_errors_and_cleanup(monkeypatch, failure, code):
    closed = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False and kwargs["timeout"] == 90
            self._client = SimpleNamespace(close=lambda: closed.append(True))

        def chat(self, **kwargs):
            assert kwargs["stream"] is False
            assert kwargs["format"] == MovePractice.model_json_schema()
            raise failure

    monkeypatch.setattr("chess_coach.infrastructure.llm.client.Client", Client)
    with pytest.raises(OperationError) as error:
        OllamaCoach(Settings(_env_file=None)).generate("{}", MovePractice)
    assert error.value.code == code and closed == [True]
