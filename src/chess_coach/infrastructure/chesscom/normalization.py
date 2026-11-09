"""Validate archived source records; PGN replay belongs to Phase 8."""

import hashlib
import re
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chess_coach.domain.sync import ExternalGame, Rejection, normalize_username

LOSSES = {"checkmated", "timeout", "resigned", "lose", "abandoned"}
DRAWS = {
    "agreed",
    "repetition",
    "stalemate",
    "insufficient",
    "50move",
    "timevsinsufficient",
}


class Player(BaseModel):
    model_config = ConfigDict(strict=True)
    username: str = Field(min_length=1, max_length=100)
    result: str
    rating: int | None = Field(default=None, ge=0)


class SourceGame(BaseModel):
    model_config = ConfigDict(strict=True)
    rules: str
    pgn: str
    uuid: str | None = None
    url: str
    end_time: int = Field(gt=0)
    white: Player
    black: Player
    time_control: str | None = None
    time_class: str | None = None
    eco: str | None = None
    fen: str | None = None


def normalize_game(
    raw: object, username: str, index: int, now: datetime
) -> ExternalGame | Rejection:
    pgn = raw.get("pgn") if isinstance(raw, dict) else None
    pgn = pgn if isinstance(pgn, str) else None
    if (
        isinstance(raw, dict)
        and isinstance(raw.get("rules"), str)
        and raw["rules"] != "chess"
    ):
        return Rejection(index, "UNSUPPORTED_VARIANT", pgn, True)
    try:
        source = SourceGame.model_validate(raw)
        white = normalize_username(source.white.username)
        black = normalize_username(source.black.username)
        if username not in (white, black) or white == black:
            raise ValueError("PLAYER_MISMATCH")
        played = datetime.fromtimestamp(source.end_time, UTC)
        if played > now:
            raise ValueError("INVALID_END_TIME")
        wr, br = source.white.result, source.black.result
        if wr == "win" and br in LOSSES:
            winner = "white"
        elif br == "win" and wr in LOSSES:
            winner = "black"
        elif wr in DRAWS and br in DRAWS:
            winner = "draw"
        else:
            raise ValueError("INVALID_COMPLETION_RESULTS")
        expected = {"white": "1-0", "black": "0-1", "draw": "1/2-1/2"}[winner]
        # Refuse an explicitly conflicting variant even if the envelope says chess.
        variant = re.search(r'^\[Variant\s+"([^"]+)"\]', source.pgn, re.MULTILINE)
        if variant and variant[1].lower() not in {"standard", "chess"}:
            return Rejection(index, "UNSUPPORTED_PGN_VARIANT", pgn, True)
        url = source.url
        if not re.fullmatch(
            r"https://www\.chess\.com/game/(live|daily)/[1-9][0-9]*", url
        ):
            raise ValueError("INVALID_GAME_URL")
        if source.uuid:
            identity = f"uuid:{UUID(source.uuid)}"
        else:
            identity = f"url:{url}"
        if not source.pgn.strip():
            return Rejection(index, "EMPTY_PGN", pgn, quarantined=True)
        declared = re.search(
            r'^\[Result\s+"(1-0|0-1|1/2-1/2)"\]\s*$', source.pgn, re.MULTILINE
        )
        if declared is None or declared[1] != expected:
            return Rejection(index, "INVALID_PGN_RESULT", pgn, quarantined=True)
        # Prefer URL for the secondary identity so UUID presence/absence is stable.
        fingerprint = hashlib.sha256(
            f"chesscom-source-v1:{url or identity}".encode()
        ).hexdigest()
        color = "white" if username == white else "black"
        result = "draw" if winner == "draw" else "win" if color == winner else "loss"
        return ExternalGame(
            identity,
            fingerprint,
            source.pgn,
            played,
            source.white.username,
            source.black.username,
            source.white.rating,
            source.black.rating,
            color,
            result,
            source.time_control,
            source.time_class,
            source.eco,
            url,
            {
                "end_time": source.end_time,
                "white_result": wr,
                "black_result": br,
                "result": expected,
                "final_fen": source.fen,
                "rules": source.rules,
            },
        )
    except ValidationError:
        return Rejection(index, "INVALID_SOURCE_SCHEMA", pgn)
    except OverflowError, OSError:
        return Rejection(index, "INVALID_END_TIME", pgn)
    except ValueError as exc:
        code = str(exc)
        known = {
            "PLAYER_MISMATCH",
            "INVALID_END_TIME",
            "INVALID_COMPLETION_RESULTS",
            "INVALID_GAME_URL",
        }
        return Rejection(index, code if code in known else "INVALID_SOURCE_RECORD", pgn)
