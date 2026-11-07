import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from chess_coach.domain.sync import (
    Archive,
    Checkpoint,
    ExternalGame,
    Rejection,
    should_fetch,
)
from chess_coach.infrastructure.chesscom.client import BASE_URL, ChessComClient
from chess_coach.infrastructure.chesscom.exceptions import ChessComError
from chess_coach.infrastructure.chesscom.normalization import normalize_game

NOW = datetime(2026, 11, 7, tzinfo=UTC)
MONTH = Archive(2026, 10)


def record():
    return json.loads(
        (Path(__file__).parents[1] / "fixtures/chesscom/month_normal.json").read_text()
    )["games"][0]


def client(handler, **kwargs):
    return ChessComClient(
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        jitter=lambda: 0,
        clock=lambda: NOW,
        **kwargs,
    )


@pytest.mark.parametrize("status", [400, 404, 410, 301, 302, 403])
def test_permanent_errors_and_redirects_never_follow(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://evil.example/"})

    with client(handler) as api, pytest.raises(ChessComError):
        api.get_month_games("TestPlayer", MONTH)
    assert len(calls) == 1
    assert calls[0].url.host == "api.chess.com"
    assert calls[0].extensions["timeout"] == {
        "connect": 5,
        "read": 20,
        "write": 5,
        "pool": 5,
    }
    assert "local-chess-coach" in calls[0].headers["User-Agent"]


@pytest.mark.parametrize(
    "failure", [429, 500, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError]
)
def test_retries_bounded(failure):
    calls, delays = [], []

    def handler(request):
        calls.append(request)
        if isinstance(failure, int):
            return httpx.Response(failure)
        raise failure("simulated")

    with (
        ChessComClient(
            transport=httpx.MockTransport(handler),
            sleep=delays.append,
            jitter=lambda: 0,
        ) as api,
        pytest.raises(ChessComError),
    ):
        api.get_archives("testplayer")
    assert len(calls) == 3
    assert delays == [1, 2]


@pytest.mark.parametrize(
    "retry,expected",
    [
        ("2", [2, 2]),
        ("invalid", [1, 2]),
        ("9999", []),
        ("Sat, 07 Nov 2026 00:00:03 GMT", [3, 3]),
    ],
)
def test_retry_after(retry, expected):
    delays = []
    with (
        ChessComClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(429, headers={"Retry-After": retry})
            ),
            sleep=delays.append,
            jitter=lambda: 0,
            clock=lambda: NOW,
        ) as api,
        pytest.raises(ChessComError),
    ):
        api.get_archives("testplayer")
    assert delays == expected


@pytest.mark.parametrize("payload", [{}, {"games": None}, {"games": {}}, "html"])
def test_bad_envelope_not_empty(payload):
    def handler(_):
        return (
            httpx.Response(200, content=b"<html>")
            if payload == "html"
            else httpx.Response(200, json=payload)
        )

    with client(handler) as api, pytest.raises(ChessComError):
        api.get_month_games("testplayer", MONTH)


def test_valid_empty_and_conditional_month():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            304 if "If-None-Match" in request.headers else 200,
            json={"games": []},
            headers={"ETag": '"v1"'},
        )

    with client(handler) as api:
        result = api.get_month_games("testplayer", MONTH)
        assert result.received == 0 and result.etag == '"v1"'
        assert api.get_month_games(
            "testplayer", MONTH, Checkpoint("complete", '"v1"')
        ).unchanged
    assert len(requests) == 2


def test_304_without_checkpoint_retries_unconditionally_once():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(304)

    with client(handler) as api, pytest.raises(ChessComError, match="INVALID_304"):
        api.get_month_games("testplayer", MONTH)
    assert len(calls) == 2
    assert all("If-None-Match" not in r.headers for r in calls)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/2026/10",
        BASE_URL + "/player/other/games/2026/10",
        BASE_URL + "/player/testplayer/games/2026/13",
        BASE_URL + "/player/testplayer/games/2027/01",
        BASE_URL + "/player/testplayer/games/2026/10?x=1",
        2,
    ],
)
def test_discovery_rejects_untrusted_urls(url):
    with (
        client(lambda _: httpx.Response(200, json={"archives": [url]})) as api,
        pytest.raises(ChessComError),
    ):
        api.get_archives("testplayer")


def test_discovery_sorts_and_deduplicates():
    values = [
        BASE_URL + f"/player/testplayer/games/2026/{m}" for m in ["10", "09", "10"]
    ]
    with client(lambda _: httpx.Response(200, json={"archives": values})) as api:
        assert api.get_archives(" TestPlayer ") == [Archive(2026, 9), MONTH]


@pytest.mark.parametrize(
    "username", ["../test", "a/b", "a?b", "a\nb", "", "https://evil"]
)
def test_unsafe_username_never_requests(username):
    with (
        client(lambda _: pytest.fail("network must not be called")) as api,
        pytest.raises(ValueError),
    ):
        api.get_player(username)


def test_profile_identity_and_not_found():
    with client(lambda _: httpx.Response(200, json={"username": "TestPlayer"})) as api:
        assert api.get_player(" TESTPLAYER ") == "testplayer"
    with (
        client(lambda _: httpx.Response(404)) as api,
        pytest.raises(ChessComError, match="PLAYER_NOT_FOUND"),
    ):
        api.get_player("testplayer")
    with (
        client(lambda _: httpx.Response(200, json={"username": "other"})) as api,
        pytest.raises(ChessComError, match="PLAYER_MISMATCH"),
    ):
        api.get_player("testplayer")


def test_normalization_optional_fields_orientation_and_fallback():
    raw = record()
    game = normalize_game(raw, "testplayer", 0, NOW)
    assert isinstance(game, ExternalGame)
    assert game.player_color == "white" and game.result == "win"
    assert game.raw_pgn == raw["pgn"] and game.black_rating is None
    assert game.played_at.tzinfo == UTC
    black = normalize_game(raw, "opponent", 0, NOW)
    assert black.player_color == "black" and black.result == "loss"
    del raw["uuid"]
    fallback = normalize_game(raw, "testplayer", 0, NOW)
    assert fallback.canonical_hash == game.canonical_hash
    assert fallback.external_id.startswith("url:")


@pytest.mark.parametrize(
    "field,value",
    [
        ("pgn", ""),
        ("pgn", None),
        ("end_time", -1),
        ("end_time", True),
        ("end_time", 9999999999999999),
        ("white", {}),
        ("uuid", "bad"),
        ("url", "https://evil"),
    ],
)
def test_invalid_records(field, value):
    raw = record()
    raw[field] = value
    result = normalize_game(raw, "testplayer", 0, NOW)
    assert isinstance(result, Rejection) and not result.unsupported


def test_variants_and_incomplete_results():
    raw = record()
    raw["rules"] = "chess960"
    assert normalize_game(raw, "testplayer", 0, NOW).unsupported
    raw["rules"] = "chess"
    raw["white"]["result"] = "playing"
    assert isinstance(normalize_game(raw, "testplayer", 0, NOW), Rejection)
    raw["white"]["result"] = raw["black"]["result"] = "agreed"
    raw["pgn"] = raw["pgn"].replace("1-0", "1/2-1/2")
    assert normalize_game(raw, "testplayer", 0, NOW).result == "draw"


@pytest.mark.parametrize(
    "archive,status,force,expected",
    [
        (Archive(2026, 9), "complete", False, False),
        (MONTH, "complete", False, True),
        (Archive(2026, 11), "complete", False, True),
        (Archive(2025, 1), "failed", False, True),
        (Archive(2025, 1), "running", False, True),
        (Archive(2025, 1), "unavailable", False, False),
        (Archive(2025, 1), "unavailable", True, True),
        (Archive(2025, 1), "complete", True, True),
    ],
)
def test_archive_planner(archive, status, force, expected):
    assert should_fetch(archive, Checkpoint(status), NOW, force) is expected
    assert should_fetch(archive, None, NOW)


def test_previous_month_at_year_boundary():
    assert should_fetch(
        Archive(2025, 12), Checkpoint("complete"), datetime(2026, 1, 1, tzinfo=UTC)
    )


def test_identity_presence_transitions_never_create_incompatible_accepted_keys():
    raw = record()
    del raw["url"]
    assert isinstance(normalize_game(raw, "testplayer", 0, NOW), Rejection)
    raw = record()
    both = normalize_game(raw, "testplayer", 0, NOW)
    del raw["uuid"]
    fallback = normalize_game(raw, "testplayer", 0, NOW)
    assert both.canonical_hash == fallback.canonical_hash


@pytest.mark.parametrize(
    "pgn", ["<html>failure</html>", '[Result "*"]\n\n*', '[Result "0-1"]\n\n0-1']
)
def test_unusable_or_conflicting_pgn_rejected(pgn):
    raw = record()
    raw["pgn"] = pgn
    result = normalize_game(raw, "testplayer", 0, NOW)
    assert isinstance(result, Rejection) and result.reason == "INVALID_PGN_RESULT"


def test_archive_month_does_not_require_end_time_in_same_utc_month():
    raw = record()
    raw["end_time"] = int(datetime(2026, 11, 1, 1, tzinfo=UTC).timestamp())
    with client(lambda _: httpx.Response(200, json={"games": [raw]})) as api:
        result = api.get_month_games("testplayer", MONTH)
    assert len(result.games) == 1 and result.rejections == []
    assert result.games[0].played_at.month == 11
