import chess

from chess_coach.api.dependencies import get_variation_search
from chess_coach.domain.engine_types import EngineResult
from chess_coach.infrastructure.engine.exceptions import EngineUnavailableError

PATH = "/api/v1/games/1/review/variation"


def test_variation_replays_recorded_history_and_keeps_review_unchanged(analyzed):
    client, _, _, _, _, profile, app = analyzed
    history = []

    def search(board):
        history.extend(move.uci() for move in board.move_stack)
        best = "b8c6"
        return [
            EngineResult(board.fen(), "fixture", 42, None, None, best, (best,), 5, 100),
            EngineResult(
                board.fen(), "fixture", 65, None, None, "g8f6", ("g8f6",), 5, 100
            ),
        ]

    app.dependency_overrides[get_variation_search] = lambda: search
    body = {"profile_hash": profile.hash, "ply": 2, "line": ["f1c4"]}
    before = client.get("/api/v1/games/1/analysis").json()
    assert len(before["legal_moves_by_ply"]) == len(before["moves"]) + 1
    root = client.post(PATH, json=body | {"line": []})
    assert root.json()["legal_moves"] == before["legal_moves_by_ply"][2]
    response = client.post(PATH, json=body)
    assert response.status_code == 200
    position = response.json()
    assert position["san"] == "Bc4"
    assert position["side_to_move"] == "black"
    assert "b8c6" in position["legal_moves"]
    assert position["evaluation"] is None and history == []

    result = client.post(PATH, json=body | {"evaluate": True})
    assert result.status_code == 200
    assert history == ["e2e4", "e7e5", "f1c4"]
    assert result.json() == position | {
        "evaluation": {
            "cp": 42,
            "mate": None,
            "white_wins": None,
            "best_move": "b8c6",
            "continuation": "2...Nc6",
            "engine": "fixture",
            "alternatives": [
                {
                    "cp": 65,
                    "mate": None,
                    "white_wins": None,
                    "best_move": "g8f6",
                    "continuation": "2...Nf6",
                }
            ],
        }
    }
    assert client.get("/api/v1/games/1/analysis").json() == before


def test_variation_rejects_unavailable_game_and_illegal_moves(analyzed):
    client, _, _, _, _, profile, _ = analyzed
    body = {"profile_hash": profile.hash, "ply": 2, "line": ["f1f1"]}
    illegal = client.post(PATH, json=body)
    assert illegal.status_code == 422
    assert illegal.json()["code"] == "ILLEGAL_VARIATION_MOVE"
    assert client.post(PATH, json=body | {"ply": 5}).json()["code"] == "INVALID_BRANCH"
    assert client.post(PATH, json=body | {"profile_hash": "0" * 64}).status_code == 409
    assert client.post(PATH, json=body | {"fen": chess.STARTING_FEN}).status_code == 422
    assert client.post(PATH.replace("/1/", "/999/"), json=body).status_code == 404


def test_variation_requires_analyzed_game(seeded):
    client, _, _, _, _, profile, _ = seeded
    body = {"profile_hash": profile.hash, "ply": 0, "line": []}
    assert client.post(PATH, json=body).status_code == 409


def test_variation_repetition_and_engine_failure_are_independent(analyzed):
    client, _, _, _, _, profile, app = analyzed

    def search(_board):
        raise EngineUnavailableError("private path to Stockfish")

    app.dependency_overrides[get_variation_search] = lambda: search
    body = {"profile_hash": profile.hash, "ply": 0, "line": []}
    cycle = ["g1f3", "g8f6", "f3g1", "f6g8"]
    threefold = client.post(PATH, json=body | {"line": cycle * 2})
    assert threefold.status_code == 200
    assert threefold.json()["outcome"] is None
    failed = client.post(PATH, json=body | {"line": cycle * 2, "evaluate": True})
    assert failed.status_code == 503
    assert "private path" not in failed.text
    fivefold = client.post(PATH, json=body | {"line": cycle * 4, "evaluate": True})
    assert fivefold.status_code == 200
    assert fivefold.json()["outcome"] == "1/2-1/2"
    assert fivefold.json()["legal_moves"] == []
    assert fivefold.json()["evaluation"]["cp"] == 0
    assert fivefold.json()["evaluation"]["alternatives"] == []
    past_draw = client.post(PATH, json=body | {"line": cycle * 4 + ["e2e4"]})
    assert past_draw.status_code == 422
