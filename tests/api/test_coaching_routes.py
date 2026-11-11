import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from chess_coach.api.dependencies import get_coaching_service
from chess_coach.application.coaching import CoachingProcessor, CoachingService
from chess_coach.application.errors import OperationError
from chess_coach.domain.coaching_models import LLMHealth
from chess_coach.infrastructure.persistence.coaching_repository import (
    CoachingRepository,
)
from chess_coach.infrastructure.persistence.models import MoveAnalysis, PositionCache
from chess_coach.infrastructure.persistence.query_repository import QueryRepository

PATH = "/api/v1/games/1/moves/1/explanation"
GAME_PATH = "/api/v1/games/1/coaching"
VALID = json.dumps({"status": "explained", "focus": "reply"})
UNSUPPORTED = json.dumps({"status": "explained", "focus": "mate"})


class FakeModel:
    def __init__(self):
        self.metrics = {}

    calls = 0
    raw = VALID
    error = None

    def generate(self, evidence, schema):
        self.calls += 1
        if self.error:
            raise OperationError(self.error, "Fixture failure")
        return self.raw


@pytest.fixture
def coaching(analyzed):
    client, sessions, store, _, settings, _, app = analyzed
    repo = CoachingRepository(QueryRepository(sessions, store))
    health = LLMHealth(
        status="ready",
        model=settings.ollama_model,
        model_digest="fixture-digest",
        server_reachable=True,
        model_installed=True,
        message="Fixture",
    )
    service = CoachingService(repo, settings, lambda: health)
    app.dependency_overrides[get_coaching_service] = lambda: service
    return client, repo, service, FakeModel()


def test_vertical_slice_cache_duplicate_and_offline(coaching):
    client, repo, service, model = coaching
    assert client.get(PATH).json()["status"] == "not_generated"
    first = client.post(PATH)
    assert first.status_code == 202
    identity = first.json()["job_id"]
    assert client.post(PATH).json()["job_id"] == identity
    row = repo.claim()
    CoachingProcessor(service, model).process(row)
    result = client.get(f"/api/v1/coaching-jobs/{identity}").json()
    assert result["status"] == "done" and result["coach"]["summary"]
    assert result["evidence"] == first.json()["evidence"]
    assert result["move_breakdown"] == first.json()["move_breakdown"]
    assert result["move_breakdown"]["played"]["san"].startswith("1. e4 ")
    assert (
        result["move_breakdown"]["played"]["key_fact"]
        in result["coach"]["what_went_wrong"]
    )
    assert "[[" not in result["coach"]["why_best_move_works"]
    service.health = lambda: LLMHealth(
        status="server_unavailable",
        model="fixture",
        server_reachable=False,
        model_installed=False,
        message="Start Ollama",
    )
    assert client.get(PATH).json()["cached"]
    assert client.post(PATH).json()["cached"]
    uncached = client.post("/api/v1/games/2/moves/1/explanation")
    assert (
        uncached.status_code == 503 and uncached.json()["code"] == "OLLAMA_UNAVAILABLE"
    )
    assert client.get("/api/v1/games/2/analysis").status_code == 200
    summary = client.get("/api/v1/analytics/summary")
    assert (
        summary.status_code == 200 and summary.json()["health"]["analyzed_games"] == 25
    )
    assert model.calls == 1


def test_game_coaching_is_read_only_until_requested_and_reuses_saved_results(coaching):
    client, repo, service, model = coaching
    initial = client.get(GAME_PATH).json()
    assert initial["status"] == "not_generated"
    assert repo.claim() is None
    (moment,) = initial["evidence"]["moments"]
    assert initial["game_review"][0]["played_fact"] == moment["played_fact"]
    assert initial["game_review"][0]["practice_tip"] is None
    queued = client.post(GAME_PATH)
    assert queued.status_code == 202
    job = queued.json()["job_id"]
    assert client.post(GAME_PATH).json()["job_id"] == job
    model.raw = json.dumps(
        {
            "status": "explained",
            "choices": [{"ply": moment["ply"], "focus": moment["allowed_focuses"][0]}],
        }
    )
    CoachingProcessor(service, model).process(repo.claim())
    result = client.get(f"/api/v1/coaching-jobs/{job}").json()
    assert result["status"] == "done"
    assert result["game_review"][0]["practice_tip"]
    assert result["game_review"][0]["move"] == moment["move"]
    saved = client.get(GAME_PATH).json()
    assert saved["cached"] and saved["game_review"] == result["game_review"]
    assert repo.claim() is None and model.calls == 1


def test_game_coaching_rejects_model_reference_to_another_ply(coaching):
    client, repo, service, model = coaching
    job = client.post(GAME_PATH).json()["job_id"]
    model.raw = '{"status":"explained","choices":[{"ply":999,"focus":"reply"}]}'
    CoachingProcessor(service, model).process(repo.claim())
    result = client.get(f"/api/v1/coaching-jobs/{job}").json()
    assert result["status"] == "failed"
    assert result["error_code"] == "UNSUPPORTED_CLAIM"
    assert result["game_review"][0]["played_fact"]


@pytest.mark.parametrize(
    "raw,error",
    [
        ("not json", "INVALID_MODEL_OUTPUT"),
        ('{"status":"explained","score":99}', "INVALID_MODEL_OUTPUT"),
        (
            UNSUPPORTED,
            "UNSUPPORTED_CLAIM",
        ),
    ],
)
def test_invalid_output_never_success(coaching, raw, error):
    client, repo, service, model = coaching
    before = client.get("/api/v1/games/1/analysis").json()
    job = client.post(PATH).json()["job_id"]
    model.raw = raw
    CoachingProcessor(service, model).process(repo.claim())
    result = client.get(f"/api/v1/coaching-jobs/{job}").json()
    assert result["status"] == "failed" and result["coach"] is None
    assert result["error_code"] == error and model.calls == 2
    assert client.get("/api/v1/games/1/analysis").json() == before


def test_restart_and_failed_request_retry(coaching):
    client, repo, service, model = coaching
    job = client.post(PATH).json()["job_id"]
    assert repo.claim().status == "running"
    repo.recover()  # production caller owns kernel guard; simulate restart here
    row = repo.claim()
    model.error = "COACHING_TIMEOUT"
    CoachingProcessor(service, model).process(row)
    assert model.calls == 1 and repo.get(job).status == "failed"
    assert client.post(PATH).json()["job_id"] == job
    model.error = None
    CoachingProcessor(service, model).process(repo.claim())
    assert repo.get(job).status == "done"


def test_abstention_no_retry(coaching):
    client, repo, service, model = coaching
    job = client.post(PATH).json()["job_id"]
    model.raw = '{"status":"insufficient_evidence","focus":null}'
    CoachingProcessor(service, model).process(repo.claim())
    assert repo.get(job).status == "insufficient_evidence" and model.calls == 1


def test_errors_before_generation(coaching):
    client, _, service, model = coaching
    assert client.post("/api/v1/games/9999/moves/1/explanation").status_code == 404
    assert (
        client.post("/api/v1/games/1/moves/999/explanation").json()["code"]
        == "MOVE_NOT_FOUND"
    )
    assert client.post("/api/v1/games/1/moves/0/explanation").status_code == 422
    service.health = lambda: LLMHealth(
        status="model_missing",
        model="fixture",
        server_reachable=True,
        model_installed=False,
        message="Install the configured model",
    )
    assert client.post(PATH).json()["code"] == "MODEL_NOT_INSTALLED"
    assert model.calls == 0


def test_missing_analysis(seeded):
    client, *_ = seeded
    assert client.post(PATH).json()["code"] == "ANALYSIS_NOT_READY"


def test_digest_prompt_settings_and_evidence_cache_misses(coaching):
    client, repo, service, model = coaching
    first = client.post(PATH).json()["job_id"]
    CoachingProcessor(service, model).process(repo.claim())
    old = service.health()
    service.health = lambda: old.model_copy(update={"model_digest": "new-digest"})
    assert client.post(PATH).json()["job_id"] != first
    assert (
        repo.find("no-such-evidence", service.settings.ollama_model, {}, "new", "new")
        is None
    )
    service.settings = service.settings.model_copy(update={"llm_think": True})
    assert client.get(PATH).json()["status"] == "not_generated"


def test_database_failure_does_not_change_chess(coaching, monkeypatch):
    client, repo, service, model = coaching
    job = client.post(PATH).json()["job_id"]
    with repo.sessions() as s:
        before = [r.eval_after_cp_white for r in s.scalars(select(MoveAnalysis))]
        count = len(list(s.scalars(select(PositionCache))))

    def broken(*args):
        raise OperationalError("private", {}, Exception("disk full"))

    with monkeypatch.context() as m:
        m.setattr(repo, "finish", broken)
        with pytest.raises(OperationalError):
            CoachingProcessor(service, model).process(repo.claim())
    assert repo.get(job).status == "running"
    repo.recover()
    assert repo.get(job).status == "queued"
    with repo.sessions() as s:
        assert [
            r.eval_after_cp_white for r in s.scalars(select(MoveAnalysis))
        ] == before
        assert len(list(s.scalars(select(PositionCache)))) == count


def test_history_low_sample_and_get_read_only(coaching):
    client, _, _, model = coaching
    result = client.post("/api/v1/coaching/history")
    assert (
        result.status_code == 200 and result.json()["status"] == "insufficient_evidence"
    )
    assert client.get("/api/v1/coaching/history").json()["job_id"] is None
    assert model.calls == 0


def test_unsupported_focus_rejected_and_corrupt_cache_regenerates(coaching):
    from chess_coach.infrastructure.persistence.models import CoachingOutput

    client, repo, service, model = coaching
    job = client.post(PATH).json()["job_id"]
    model.raw = UNSUPPORTED
    CoachingProcessor(service, model).process(repo.claim())
    assert repo.get(job).status == "failed"
    assert repo.get(job).error_code == "UNSUPPORTED_CLAIM"
    client.post(PATH)
    model.raw = VALID
    CoachingProcessor(service, model).process(repo.claim())
    with repo.sessions.begin() as s:
        row = s.get(CoachingOutput, job)
        row.output_json = {"status": "explained", "summary": "corrupt"}
    assert client.get(PATH).json()["code"] == "INVALID_MODEL_OUTPUT"
    assert client.post(PATH).status_code == 202
    CoachingProcessor(service, model).process(repo.claim())
    assert client.get(PATH).json()["status"] == "done"


def test_source_change_during_generation_drops_output(coaching, monkeypatch):
    client, repo, service, model = coaching
    job = client.post(PATH).json()["job_id"]
    original = model.generate

    def generate(*args):
        raw = original(*args)

        def changed(*args):
            raise OperationError("EVIDENCE_INCOMPLETE", "Source changed")

        monkeypatch.setattr(service.builder, "move", changed)
        return raw

    monkeypatch.setattr(model, "generate", generate)
    CoachingProcessor(service, model).process(repo.claim())
    assert repo.get(job).status == "failed" and repo.get(job).output_json is None


def test_real_ollama_vertical_slice_opt_in(coaching):
    """Explicit opt-in: CHESS_COACH_REAL_OLLAMA=1 uv run pytest -k real_ollama."""
    import os
    from functools import partial

    from chess_coach.infrastructure.llm.client import OllamaCoach
    from chess_coach.infrastructure.llm.health import check_health

    if os.environ.get("CHESS_COACH_REAL_OLLAMA") != "1":
        pytest.skip("Set CHESS_COACH_REAL_OLLAMA=1 for actual local Qwen generation")
    client, repo, service, _ = coaching
    service.health = partial(check_health, service.settings)
    response = client.post(PATH)
    assert response.status_code == 202, response.text
    row = repo.claim()
    CoachingProcessor(service, OllamaCoach(service.settings)).process(row)
    result = client.get(f"/api/v1/coaching-jobs/{response.json()['job_id']}").json()
    assert result["status"] in {"done", "insufficient_evidence", "failed"}
    if result["status"] == "failed":
        assert result["coach"] is None and result["error_code"]
    else:
        assert result["coach"]
        assert client.get(PATH).json()["cached"]


def test_prompt_evidence_excludes_imported_prose(coaching):
    client, repo, service, model = coaching
    client.post(PATH)
    captured = []
    original = model.generate

    def generate(evidence, schema):
        captured.append(json.loads(evidence))
        return original(evidence, schema)

    model.generate = generate
    CoachingProcessor(service, model).process(repo.claim())
    assert captured
    assert all(
        key not in captured[0]
        for key in ("raw_pgn", "opening_name", "white_username", "comments")
    )
    assert captured[0] == {
        "played_line_observation": "quiet move",
        "alternative_observation": "quiet move",
        "allowed_focuses": ["reply"],
    }


def test_prompt_version_change_misses_existing_success(coaching, monkeypatch):
    client, repo, service, model = coaching
    first = client.post(PATH).json()["job_id"]
    CoachingProcessor(service, model).process(repo.claim())
    monkeypatch.setattr(
        "chess_coach.application.coaching.MOVE_EXPLANATION_PROMPT_VERSION",
        "next-version",
    )
    assert client.get(PATH).json()["status"] == "not_generated"
    assert client.post(PATH).json()["job_id"] != first


def test_changed_history_report_cannot_admit_generation(coaching):
    client, repo, service, _ = coaching

    def unexpected_health():
        pytest.fail("Stale admission must reject before probing Ollama")

    service.health = unexpected_health
    response = client.post(
        "/api/v1/coaching/history",
        params={"window": "last_20", "expected_report_hash": "b" * 64},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "COACHING_REPORT_CHANGED"
    assert repo.claim() is None


def test_combined_worker_releases_stockfish_before_processing_coaching(
    coaching, monkeypatch
):
    from chess_coach import analysis_worker, coaching_worker

    client, _, service, model = coaching
    active = False

    class FixtureStockfish:
        engine_name = "fixture-engine"

        def __init__(self, settings):
            pass

        def __enter__(self):
            nonlocal active
            active = True
            return self

        def close(self):
            nonlocal active
            active = False

        def __exit__(self, *_):
            self.close()

    generate = model.generate

    def check_engine_released(*args):
        assert not active
        return generate(*args)

    model.generate = check_engine_released
    monkeypatch.setattr(analysis_worker, "StockfishAdapter", FixtureStockfish)
    monkeypatch.setattr(
        coaching_worker,
        "make_coaching_processor",
        lambda *_: CoachingProcessor(service, model),
    )
    job = client.post(PATH).json()["job_id"]
    analysis_worker.run_worker(service.settings, once=True, with_coaching=True)
    assert client.get(f"/api/v1/coaching-jobs/{job}").json()["status"] == "done"
    assert model.calls == 1


@pytest.mark.parametrize(
    ("raw", "code", "first_rate"),
    [
        ("SECRET_TEST_PROMPT_456", "MODEL_SCHEMA_INVALID", 100),
        (
            UNSUPPORTED,
            "MODEL_FACTUAL_VALIDATION_FAILED",
            0,
        ),
    ],
)
def test_coaching_metrics_and_private_failure_logs(
    coaching, capsys, raw, code, first_rate
):
    from chess_coach.observability.logging import configure_logging

    client, repo, service, model = coaching
    configure_logging()
    job = client.post(PATH).json()["job_id"]
    model.raw = raw
    CoachingProcessor(service, model).process(repo.claim())
    raw_log = capsys.readouterr().err
    assert "SECRET_TEST_PROMPT_456" not in raw_log
    events = [json.loads(line) for line in raw_log.splitlines()]
    assert [event["event"] for event in events] == [
        "llm_generation_started",
        "llm_generation_failed",
    ]
    assert all(
        event["run_id"] == str(job) and "request_id" not in event for event in events
    )
    assert events[-1]["error_code"] == code
    assert events[-1]["schema_valid"] is (first_rate == 0)
    measured = client.get("/api/v1/system/metrics").json()
    assert measured["analysis"]["positions_per_second"] > 0
    assert measured["analysis"]["duration_ms"] >= 0
    assert measured["coaching"]["sample_count"] == 1
    assert measured["coaching"]["first_schema_failure_rate"] == first_rate
    assert measured["coaching"]["final_failure_rate"] == 100
