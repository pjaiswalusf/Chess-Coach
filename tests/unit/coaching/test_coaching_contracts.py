import chess
import httpx
import pytest
from pydantic import ValidationError

from chess_coach.application.coaching import validated_output
from chess_coach.application.errors import OperationError
from chess_coach.config import Settings
from chess_coach.domain.coaching_models import (
    EngineScore,
    HistoricalExplanation,
    MoveCoachingEvidence,
    MovePractice,
)
from chess_coach.infrastructure.llm.health import check_health
from chess_coach.infrastructure.llm.validation import validate_text


@pytest.fixture
def evidence():
    return MoveCoachingEvidence(
        game_id=1,
        ply=1,
        player_color="white",
        phase="opening",
        fen_before=chess.STARTING_FEN,
        initial_fen=chess.STARTING_FEN,
        history_uci=(),
        history_before_start_unknown=False,
        played_move_uci="e2e4",
        best_move_uci="d2d4",
        best_line_uci=("d2d4", "d7d5"),
        played_refutation_uci=("e7e5",),
        before=EngineScore(cp_white=50),
        after=EngineScore(cp_white=20),
        loss_cp=30,
        completion_provenance="pgn_declaration",
        source_hash="source",
        profile_hash="profile",
        engine_version="fixture",
        analysis_version="single-v1",
        draw_policy="automatic-only-v1",
        feature_version=1,
    )


def test_white_and_unknowns(evidence):
    assert evidence.loss_cp == 30
    assert (
        evidence.player_rating is None and evidence.historical_theme_frequency is None
    )
    with pytest.raises(ValidationError):
        evidence.loss_cp = 90


def test_black_perspective(evidence):
    board = chess.Board()
    board.push_uci("e2e4")
    changed = evidence.model_dump() | {
        "ply": 2,
        "player_color": "black",
        "fen_before": board.fen(),
        "history_uci": ("e2e4",),
        "played_move_uci": "e7e5",
        "best_move_uci": "c7c5",
        "best_line_uci": ("c7c5",),
        "played_refutation_uci": ("g1f3",),
        "before": {"cp_white": -50},
        "after": {"cp_white": 20},
        "loss_cp": 70,
    }
    assert MoveCoachingEvidence.model_validate(changed).loss_cp == 70
    with pytest.raises(ValidationError):
        MoveCoachingEvidence.model_validate(changed | {"loss_cp": 0})


@pytest.mark.parametrize(
    "field,value",
    [
        ("fen_before", "bad"),
        ("initial_fen", "8/8/8/8/8/8/8/8 w - - 0 1"),
        ("played_move_uci", "e2e5"),
        ("best_move_uci", "e2e5"),
        ("best_line_uci", ("d2d4", "d7d4")),
        ("played_refutation_uci", ("d2d4",)),
        ("played_refutation_uci", ()),
        ("loss_cp", -1),
        ("loss_cp", True),
        ("player_color", "black"),
        ("before", {"cp_white": 0, "mate_white": 1}),
    ],
)
def test_invalid_evidence(evidence, field, value):
    with pytest.raises(ValidationError):
        MoveCoachingEvidence.model_validate(evidence.model_dump() | {field: value})


@pytest.mark.parametrize(
    "score",
    [
        {},
        {"mate_white": 0},
        {"mate_white": -2, "mate_winner": True},
        {"cp_white": True},
    ],
)
def test_invalid_score(score):
    with pytest.raises(ValidationError):
        EngineScore.model_validate(score)


def test_mate_zero():
    assert EngineScore(mate_white=0, mate_winner=False).mate_white == 0


def test_move_model_can_only_select_supported_practice(evidence):
    assert (
        validated_output('{"status":"explained","focus":"reply"}', evidence).status
        == "explained"
    )
    assert (
        validated_output(
            '{"status":"insufficient_evidence","focus":null}', evidence
        ).status
        == "insufficient_evidence"
    )
    with pytest.raises(OperationError, match="outside the saved observations"):
        validated_output('{"status":"explained","focus":"mate"}', evidence)
    for payload in (
        {"status": "explained", "focus": None},
        {
            "status": "explained",
            "focus": "reply",
            "summary": "Your king is checkmated.",
        },
        {"status": "explained", "focus": "invented"},
        {"status": "insufficient_evidence", "focus": "reply"},
    ):
        with pytest.raises(ValidationError):
            MovePractice.model_validate(payload)


@pytest.mark.parametrize(
    "text",
    [
        "You lose 43% of games.",
        "Play Nf3.",
        "This wins three pawns.",
        "You made eleven mistakes.",
        "You lost twenty games.",
        "Your rating will rise a thousand points.",
        "You miss a tactic a dozen times.",
        "<script>alert()</script>",
    ],
)
def test_historical_text_still_rejects_detectable_claims(text):
    with pytest.raises(OperationError, match="prohibited"):
        validate_text(
            HistoricalExplanation(status="insufficient_evidence", summary=text)
        )


@pytest.mark.parametrize(
    "body,status",
    [
        ({"models": []}, "model_missing"),
        ({"models": [{"name": "qwen3.5:4b-q4_K_M", "digest": "abc"}]}, "ready"),
        (
            {
                "models": [
                    {
                        "name": "qwen3.5:4b-q4_K_M",
                        "digest": "abc",
                        "remote_host": "cloud",
                    }
                ]
            },
            "check_failed",
        ),
        ({"invalid": []}, "check_failed"),
    ],
)
def test_health_never_generates(body, status):
    def handler(request):
        assert request.method == "GET" and request.url.path == "/api/tags"
        return httpx.Response(200, json=body)

    assert (
        check_health(Settings(_env_file=None), httpx.MockTransport(handler)).status
        == status
    )


def test_offline_health():
    def offline(request):
        raise httpx.ConnectError("offline")

    assert (
        check_health(Settings(_env_file=None), httpx.MockTransport(offline)).status
        == "server_unavailable"
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"ollama_host": "https://example.com"},
        {"ollama_model": "qwen-cloud"},
        {"llm_keep_alive": "-1"},
    ],
)
def test_local_configuration(settings):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **settings)


def test_explanation_cannot_claim_an_alternative_to_the_same_best_move(evidence):
    same = MoveCoachingEvidence.model_validate(
        evidence.model_dump()
        | {
            "best_move_uci": "e2e4",
            "best_line_uci": ("e2e4", "e7e5"),
        }
    )
    with pytest.raises(OperationError, match="outside the saved observations"):
        validated_output('{"status":"explained","focus":"reply"}', same)
    assert (
        validated_output('{"status":"insufficient_evidence","focus":null}', same).status
        == "insufficient_evidence"
    )


def test_same_best_move_abstains_without_model_or_cache(evidence):
    from unittest.mock import Mock

    from chess_coach.application.coaching import CoachingService

    same = MoveCoachingEvidence.model_validate(
        evidence.model_dump()
        | {
            "best_move_uci": "e2e4",
            "best_line_uci": ("e2e4", "e7e5"),
        }
    )
    store, health = Mock(), Mock()
    service = CoachingService(store, Settings(_env_file=None), health)
    for generate in (False, True):
        response = service.request(same, generate)
        assert response.status == "insufficient_evidence"
        assert response.evidence == same
        assert response.coach.status == "insufficient_evidence"
    assert not store.mock_calls
    health.assert_not_called()
