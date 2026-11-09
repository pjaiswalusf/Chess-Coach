"""Serial, bounded PubAPI client. No database or active-game endpoints."""

import random
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Self

import httpx

from chess_coach.domain.sync import (
    Archive,
    Checkpoint,
    ExternalGame,
    MonthResult,
    normalize_username,
)
from chess_coach.infrastructure.chesscom.exceptions import ChessComError
from chess_coach.infrastructure.chesscom.normalization import normalize_game

BASE_URL = "https://api.chess.com/pub"
TIMEOUT = httpx.Timeout(connect=5, read=20, write=5, pool=5)
USER_AGENT = "local-chess-coach/0.1 (github.com/pratikjaiswal49/Chess-Coach)"


class ChessComClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout = TIMEOUT,
        attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._http = httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
            trust_env=False,
        )
        self._sleep, self._jitter, self._clock = sleep, jitter, clock
        self._attempts = attempts

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        for attempt in range(self._attempts):
            delay = 2**attempt + self._jitter()
            try:
                response = self._http.get(BASE_URL + path, headers=headers)
            except httpx.TimeoutException, httpx.NetworkError:
                if attempt == self._attempts - 1:
                    raise ChessComError(
                        "TRANSPORT_FAILURE", "Retry synchronization later."
                    ) from None
            else:
                status = response.status_code
                if status in (200, 304):
                    return response
                if status not in (429,) and not 500 <= status <= 599:
                    code = "UNAVAILABLE" if status in (404, 410) else "HTTP_ERROR"
                    raise ChessComError(
                        code,
                        f"Chess.com returned HTTP {status}. Check the source and retry.",
                        unavailable=status in (404, 410),
                    )
                if attempt == self._attempts - 1:
                    raise ChessComError(
                        "RETRY_EXHAUSTED", f"HTTP {status}; retry later."
                    )
                if status == 429 and (retry := response.headers.get("Retry-After")):
                    try:
                        delay = float(int(retry))
                    except ValueError:
                        try:
                            delay = (
                                parsedate_to_datetime(retry) - self._clock()
                            ).total_seconds()
                        except ValueError, TypeError, OverflowError:
                            pass
                    if delay > 30:
                        raise ChessComError(
                            "RATE_LIMITED",
                            "Retry-After exceeds 30 seconds; retry later.",
                        )
                    delay = max(0, delay)
            self._sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _json(response: httpx.Response, field: str, expected: type) -> object:
        try:
            data = response.json()
        except ValueError:
            raise ChessComError("INVALID_JSON", "Expected a JSON response.") from None
        if not isinstance(data, dict) or not isinstance(data.get(field), expected):
            raise ChessComError("INVALID_SCHEMA", f"Missing or invalid {field}.")
        return data[field]

    def get_player(self, username: str) -> str:
        username = normalize_username(username)
        try:
            response = self._get(f"/player/{username}")
        except ChessComError as exc:
            if exc.unavailable:
                raise ChessComError(
                    "PLAYER_NOT_FOUND", "Check the Chess.com username."
                ) from None
            raise
        name = self._json(response, "username", str)
        try:
            matches = isinstance(name, str) and normalize_username(name) == username
        except ValueError:
            matches = False
        if not matches:
            raise ChessComError(
                "PLAYER_MISMATCH", "Profile identity does not match the request."
            )
        return username

    def get_archives(self, username: str) -> list[Archive]:
        username = normalize_username(username)
        response = self._get(f"/player/{username}/games/archives")
        values = self._json(response, "archives", list)
        assert isinstance(values, list)
        archives = set()
        for value in values:
            match = (
                re.fullmatch(
                    rf"https://api\.chess\.com/pub/player/{re.escape(username)}/games/(\d{{4}})/(\d{{2}})",
                    value,
                    re.IGNORECASE,
                )
                if isinstance(value, str)
                else None
            )
            if not match:
                raise ChessComError(
                    "INVALID_ARCHIVE_URL", "Archive host, player or path is invalid."
                )
            try:
                archive = Archive(int(match[1]), int(match[2]))
                now = self._clock()
                if (archive.year, archive.month) > (now.year, now.month):
                    raise ValueError("future archive")
                archives.add(archive)
            except ValueError:
                raise ChessComError(
                    "INVALID_ARCHIVE_DATE", "Archive date is invalid."
                ) from None
        return sorted(archives)

    def get_month_games(
        self, username: str, archive: Archive, checkpoint: Checkpoint | None = None
    ) -> MonthResult:
        username = normalize_username(username)
        headers = {}
        if checkpoint and checkpoint.status == "complete":
            if checkpoint.etag:
                headers["If-None-Match"] = checkpoint.etag
            elif checkpoint.last_modified:
                headers["If-Modified-Since"] = checkpoint.last_modified
        path = f"/player/{username}/games/{archive.key}"
        response = self._get(path, headers)
        if response.status_code == 304:
            if headers:
                return MonthResult(unchanged=True)
            response = self._get(path)
            if response.status_code == 304:
                raise ChessComError(
                    "INVALID_304", "No committed conditional checkpoint; retry later."
                )
        raw_games = self._json(response, "games", list)
        assert isinstance(raw_games, list)
        games, rejections = [], []
        for index, raw in enumerate(raw_games):
            game = normalize_game(raw, username, index, self._clock())
            if isinstance(game, ExternalGame):
                games.append(game)
            else:
                rejections.append(game)
        return MonthResult(
            games,
            rejections,
            len(raw_games),
            False,
            response.headers.get("ETag"),
            response.headers.get("Last-Modified"),
        )
