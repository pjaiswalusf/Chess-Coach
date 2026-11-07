"""Immutable trusted-game contracts; no persistence or integration dependencies."""

from dataclasses import dataclass, field
from enum import StrEnum

PARSER_VERSION = 1


class ParseStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    READY = "ready"
    PARSE_FAILED = "parse_failed"
    UNSUPPORTED = "unsupported"
    INCOMPLETE = "incomplete"


class PlayerColor(StrEnum):
    WHITE = "white"
    BLACK = "black"


class GameResult(StrEnum):
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"
    UNKNOWN = "unknown"


class ReasonCode(StrEnum):
    EMPTY_PGN = "EMPTY_PGN"
    PGN_TOO_LARGE = "PGN_TOO_LARGE"
    MULTIPLE_GAMES = "MULTIPLE_GAMES"
    INVALID_MOVES = "INVALID_MOVES"
    INVALID_START_POSITION = "INVALID_START_POSITION"
    INVALID_PLAYER_METADATA = "INVALID_PLAYER_METADATA"
    PLAYER_NOT_IN_GAME = "PLAYER_NOT_IN_GAME"
    UNSUPPORTED_VARIANT = "UNSUPPORTED_VARIANT"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"
    RESULT_MISMATCH = "RESULT_MISMATCH"
    FINAL_POSITION_MISMATCH = "FINAL_POSITION_MISMATCH"
    SOURCE_EVIDENCE_MISSING = "SOURCE_EVIDENCE_MISSING"
    SOURCE_METADATA_MISMATCH = "SOURCE_METADATA_MISMATCH"
    UNEXPECTED_PARSE_ERROR = "UNEXPECTED_PARSE_ERROR"


class PGNParseError(ValueError):
    def __init__(self, reason_code: ReasonCode):
        self.reason_code = reason_code
        self.status = (
            ParseStatus.UNSUPPORTED
            if reason_code == ReasonCode.UNSUPPORTED_VARIANT
            else ParseStatus.INCOMPLETE
            if reason_code
            in {ReasonCode.UNKNOWN_RESULT, ReasonCode.SOURCE_EVIDENCE_MISSING}
            else ParseStatus.PARSE_FAILED
        )
        self.safe_error_message = f"{reason_code}: inspect the preserved source and explicitly retry after correction."
        super().__init__(self.safe_error_message)


@dataclass(frozen=True)
class TimeControl:
    raw: str | None
    base_seconds: float | None = None
    increment_seconds: float | None = None


@dataclass(frozen=True)
class ParsedMove:
    ply_index: int
    move_number: int
    mover_color: PlayerColor
    san: str
    uci: str
    fen_before: str
    fen_after: str
    clock_after_seconds: float | None
    elapsed_seconds: float | None
    elapsed_source: str


@dataclass(frozen=True)
class ParsedGame:
    tracked_player: str
    white_username: str
    black_username: str
    player_color: PlayerColor
    player_result: GameResult
    source_result: str
    initial_fen: str
    final_fen: str
    history_before_start_unknown: bool
    moves: tuple[ParsedMove, ...]
    time_control: TimeControl
    eco: str | None
    opening_name: str | None
    eco_url: str | None
    termination: str | None
    completion_provenance: str = "pgn_declaration"

    @property
    def total_plies(self) -> int:
        return len(self.moves)


@dataclass
class ParseSummary:
    parser_version: int = PARSER_VERSION
    games_attempted: int = 0
    ready: int = 0
    parse_failed: int = 0
    unsupported: int = 0
    incomplete: int = 0
    unexpected_errors: int = 0
    source_position_mismatches: int = 0
    clock_coverage_games: int = 0
    recovered: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
