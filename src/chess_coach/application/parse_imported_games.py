"""Resumable per-game validation; persistence and parser are injected adapters."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from chess_coach.domain.game_records import (
    ParsedGame,
    ParseStatus,
    ParseSummary,
    PGNParseError,
)
from chess_coach.domain.game_records import (
    ReasonCode as R,
)
from chess_coach.domain.sync import archive_result

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParseInput:
    game_id: int
    raw_pgn: str
    username: str
    platform: str
    white_username: str
    black_username: str
    source_evidence: dict[str, object] | None


class GameParser(Protocol):
    def __call__(
        self,
        raw_pgn: str,
        tracked_username: str,
        *,
        max_bytes: int,
        source_final_fen: str | None,
    ) -> ParsedGame: ...


class ParseStore(Protocol):
    def guard(self) -> AbstractContextManager[None]: ...
    def recover(self, username: str) -> int: ...
    def candidates(self, username: str, retry: bool) -> list[int]: ...
    def begin(self, game_id: int, now: datetime) -> ParseInput: ...
    def finish(self, game_id: int, outcome: ParsedGame | PGNParseError) -> None: ...


def _source_result(record: ParseInput) -> tuple[str | None, str | None]:
    if record.platform == "pgn":
        return None, None
    evidence = record.source_evidence
    if record.platform != "chess.com" or not evidence:
        raise PGNParseError(R.SOURCE_EVIDENCE_MISSING)
    end = evidence.get("end_time")
    if not isinstance(end, int) or isinstance(end, bool) or end <= 0:
        raise PGNParseError(R.SOURCE_EVIDENCE_MISSING)
    if evidence.get("rules") != "chess":
        raise PGNParseError(R.UNSUPPORTED_VARIANT)
    white, black = evidence.get("white_result"), evidence.get("black_result")
    if not isinstance(white, str) or not isinstance(black, str):
        raise PGNParseError(R.SOURCE_EVIDENCE_MISSING)
    expected = archive_result(white, black)
    if expected is None:
        raise PGNParseError(R.SOURCE_EVIDENCE_MISSING)
    if evidence.get("result") != expected:
        raise PGNParseError(R.RESULT_MISMATCH)
    fen = evidence.get("final_fen")
    if fen is not None and not isinstance(fen, str):
        raise PGNParseError(R.FINAL_POSITION_MISMATCH)
    return expected, fen


def parse_game_with_source(
    record: ParseInput, parser: GameParser, *, max_bytes: int = 1_000_000
) -> tuple[ParsedGame, str | None]:
    expected, final_fen = _source_result(record)
    return parser(
        record.raw_pgn, record.username, max_bytes=max_bytes, source_final_fen=final_fen
    ), expected


class ParseImportedGames:
    def __init__(
        self,
        store: ParseStore,
        parser: GameParser,
        *,
        max_bytes: int = 1_000_000,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.store, self.parser, self.max_bytes, self.clock = (
            store,
            parser,
            max_bytes,
            clock,
        )

    def run(self, username: str, *, retry: bool = False) -> ParseSummary:
        username = username.strip().casefold()
        if not username:
            raise ValueError("Supply the tracked player's username.")
        summary = ParseSummary()
        with self.store.guard():
            summary.recovered = self.store.recover(username)
            try:
                for game_id in self.store.candidates(username, retry):
                    record = self.store.begin(game_id, self.clock())
                    summary.games_attempted += 1
                    outcome: ParsedGame | PGNParseError
                    try:
                        parsed, expected = parse_game_with_source(
                            record, self.parser, max_bytes=self.max_bytes
                        )
                        if expected is not None and parsed.source_result != expected:
                            raise PGNParseError(R.RESULT_MISMATCH)
                        if (
                            parsed.white_username.casefold(),
                            parsed.black_username.casefold(),
                        ) != (
                            record.white_username.strip().casefold(),
                            record.black_username.strip().casefold(),
                        ):
                            raise PGNParseError(R.SOURCE_METADATA_MISMATCH)
                        outcome = (
                            replace(parsed, completion_provenance="chesscom_archive")
                            if expected
                            else parsed
                        )
                    except PGNParseError as exc:
                        outcome = exc
                    except Exception:
                        summary.unexpected_errors += 1
                        logger.exception(
                            "unexpected_parse_error", extra={"game_id": game_id}
                        )
                        self.store.finish(
                            game_id, PGNParseError(R.UNEXPECTED_PARSE_ERROR)
                        )
                        summary.parse_failed += 1
                        summary.reasons[R.UNEXPECTED_PARSE_ERROR] = 1
                        raise
                    self.store.finish(game_id, outcome)
                    if isinstance(outcome, PGNParseError):
                        status = outcome.status
                        summary.reasons[outcome.reason_code] = (
                            summary.reasons.get(outcome.reason_code, 0) + 1
                        )
                        summary.source_position_mismatches += (
                            outcome.reason_code == R.FINAL_POSITION_MISMATCH
                        )
                    else:
                        status = ParseStatus.READY
                        summary.clock_coverage_games += any(
                            m.clock_after_seconds is not None for m in outcome.moves
                        )
                    setattr(summary, status.value, getattr(summary, status.value) + 1)
                    logger.info(
                        "game_parsed",
                        extra={"game_id": game_id, "parse_status": status.value},
                    )
            finally:
                logger.info(
                    "pgn_validation_summary", extra={"summary": asdict(summary)}
                )
        return summary
