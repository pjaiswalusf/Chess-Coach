"""Bounded, explicitly dated file imports using the completed-game validator."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from chess_coach.domain.game_records import ParsedGame, PGNParseError
from chess_coach.domain.sync import normalize_username
from chess_coach.infrastructure.persistence.pgn_repository import PGNRepository
from chess_coach.infrastructure.pgn.parser import _audit_text, parse_game


@dataclass(frozen=True)
class FileGame:
    raw: str
    parsed: ParsedGame | None
    identity: str | None
    error: str | None


def import_files(
    store: PGNRepository,
    paths: list[Path],
    username: str,
    played_at: datetime,
    max_bytes: int,
) -> dict[str, int]:
    username = normalize_username(username)
    if played_at.tzinfo is None or played_at > datetime.now(UTC):
        raise ValueError("Supply a past played-at timestamp with an explicit timezone.")
    if not 1 <= len(paths) <= 100:
        raise ValueError("Import between 1 and 100 single-game PGN files per command.")
    played_at = played_at.astimezone(UTC)
    records = []
    for path in paths:
        try:
            with path.open("rb") as source:
                data = source.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError(
                    "PGN file exceeds the configured byte limit; split it first."
                )
            raw = data.decode("utf-8")
        except OSError, UnicodeError:
            raise ValueError(
                "Cannot read a UTF-8 PGN file. Check the path and encoding."
            ) from None
        try:
            parsed = parse_game(raw, username, max_bytes=max_bytes)
            headers, _ = _audit_text(raw)
            # Source discriminators avoid merging different rounds/sites. Engine
            # annotations and export formatting do not define a game identity.
            identity = hashlib.sha256(
                json.dumps(
                    {
                        "version": "pgn-file-v1",
                        "played_at": played_at.isoformat(),
                        "white": parsed.white_username.casefold(),
                        "black": parsed.black_username.casefold(),
                        "initial_fen": parsed.initial_fen,
                        "unknown_history": parsed.history_before_start_unknown,
                        "result": parsed.source_result,
                        "moves": [move.uci for move in parsed.moves],
                        "source": {
                            key: headers.get(key, "").strip()
                            for key in (
                                "Event",
                                "Site",
                                "Date",
                                "Round",
                                "UTCDate",
                                "UTCTime",
                                "Time",
                                "TimeControl",
                            )
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            records.append(FileGame(raw, parsed, identity, None))
        except PGNParseError as exc:
            records.append(FileGame(raw, None, None, exc.reason_code))
    return store.save(username, played_at, records)
