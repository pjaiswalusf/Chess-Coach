"""Pure, bounded single-game validation. Never logs source text."""

import io
import math
import re
from collections.abc import Callable

import chess
import chess.pgn

from chess_coach.domain.game_records import (
    GameResult,
    ParsedGame,
    ParsedMove,
    PGNParseError,
    PlayerColor,
    TimeControl,
)
from chess_coach.domain.game_records import (
    ReasonCode as R,
)

RESULTS = {"1-0", "0-1", "1/2-1/2"}
MOVE_NUMBER = re.compile(r"[0-9]+\.(?:\.\.)?")


class _Builder(chess.pgn.GameBuilder):
    def handle_error(self, error: Exception) -> None:
        # Retain errors, but suppress python-chess's default raw-position logging.
        self.game.errors.append(error)

    def end_headers(self) -> None:
        headers = self.game.headers
        if headers.get("Variant", "standard").strip().casefold() not in {
            "standard",
            "chess",
        }:
            raise PGNParseError(R.UNSUPPORTED_VARIANT)
        if headers.get("Result") not in RESULTS:
            raise PGNParseError(R.UNKNOWN_RESULT)
        if headers.get("SetUp") not in (None, "0", "1"):
            raise PGNParseError(R.INVALID_START_POSITION)
        if (headers.get("SetUp") == "1") != ("FEN" in headers):
            raise PGNParseError(R.INVALID_START_POSITION)
        try:
            board = self.game.board()
        except ValueError:
            raise PGNParseError(R.INVALID_START_POSITION) from None
        if board.chess960 or board.has_chess960_castling_rights():
            raise PGNParseError(R.UNSUPPORTED_VARIANT)
        if not board.is_valid():
            raise PGNParseError(R.INVALID_START_POSITION)


def _audit_text(text: str) -> tuple[dict[str, str], str | None]:
    """Audit lexical coverage, not SAN semantics (owned by python-chess).

    The library intentionally skips unknown text. Require each token to be a
    library move token, annotation, move number, or structural delimiter. Track
    comments/variations so a result inside either cannot declare completion.
    """
    headers: dict[str, str] = {}
    body: list[str] = []
    in_headers = True
    for line in text.lstrip("\ufeff").splitlines(keepends=True):
        if in_headers and (not line.strip() or line.startswith(("%", ";"))):
            continue
        if in_headers and line.startswith("["):
            match = chess.pgn.TAG_REGEX.fullmatch(line)
            if not match or match[1] in headers:
                raise PGNParseError(R.INVALID_MOVES)
            headers[match[1]] = match[2]
        else:
            in_headers = False
            body.append(line)
    movetext = "".join(body)
    i, depth = 0, 0
    variation_has_move = [False]
    result = None
    while i < len(movetext):
        char = movetext[i]
        if char.isspace():
            i += 1
            continue
        if char == ";" or (char == "%" and (i == 0 or movetext[i - 1] == "\n")):
            end = movetext.find("\n", i)
            i = len(movetext) if end < 0 else end + 1
            continue
        if char == "{":
            end = movetext.find("}", i + 1)
            if end < 0:
                raise PGNParseError(R.INVALID_MOVES)
            i = end + 1
            continue
        if result is not None:
            raise PGNParseError(R.INVALID_MOVES)
        number = MOVE_NUMBER.match(movetext, i)
        if number:
            i = number.end()
            continue
        token_match = chess.pgn.MOVETEXT_REGEX.match(movetext, i)
        if not token_match:
            raise PGNParseError(R.INVALID_MOVES)
        token = token_match[0]
        i = token_match.end()
        if token == "(":
            if not variation_has_move[-1]:
                raise PGNParseError(R.INVALID_MOVES)
            variation_has_move.append(False)
            depth += 1
        elif token == ")":
            if depth == 0 or not variation_has_move[-1]:
                raise PGNParseError(R.INVALID_MOVES)
            variation_has_move.pop()
            depth -= 1
        elif token in RESULTS | {"*"}:
            if depth == 0:
                result = token
        elif token_match[1] is not None:
            variation_has_move[-1] = True
            # The library's tokenizer leaves check/mate suffixes outside SAN.
            if i < len(movetext) and movetext[i] in "+#":
                i += 1
            if i < len(movetext) and not (
                movetext[i].isspace() or movetext[i] in "{}();$!?"
            ):
                raise PGNParseError(R.INVALID_MOVES)
    if depth:
        raise PGNParseError(R.INVALID_MOVES)
    return headers, result


def _optional(value: str | None) -> str | None:
    return value.strip() if value and value.strip() not in {"", "?", "-"} else None


def _time_control(raw: str | None) -> TimeControl:
    if raw and re.fullmatch(r"[0-9]{1,9}(?:\+[0-9]{1,9})?", raw):
        base, _, increment = raw.partition("+")
        if int(base) > 0:
            return TimeControl(raw, float(base), float(increment or 0))
    return TimeControl(raw)


def _seconds(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) and value >= 0 else None


def _annotation_seconds(read: Callable[[], float | None]) -> float | None:
    try:
        return _seconds(read())
    except ValueError, OverflowError:
        # Corrupt optional timing metadata cannot invalidate legal chess moves.
        return None


def _read_mainline(
    game: chess.pgn.Game,
    board: chess.Board,
    control: TimeControl,
    unknown_history: bool,
) -> list[ParsedMove]:
    previous: dict[chess.Color, float | None] = {
        chess.WHITE: None if unknown_history else control.base_seconds,
        chess.BLACK: None if unknown_history else control.base_seconds,
    }
    moves: list[ParsedMove] = []
    for index, node in enumerate(game.mainline(), 1):
        move = node.move
        if move not in board.legal_moves or board.is_game_over(claim_draw=False):
            raise PGNParseError(R.INVALID_MOVES)
        before, number, turn = board.fen(), board.fullmove_number, board.turn
        san = board.san(move)
        clock, elapsed = _annotation_seconds(node.clock), _annotation_seconds(node.emt)
        elapsed_source = "recorded" if elapsed is not None else "unknown"
        prior = previous[turn]
        if (
            elapsed is None
            and clock is not None
            and prior is not None
            and control.increment_seconds is not None
        ):
            elapsed = _seconds(prior + control.increment_seconds - clock)
            elapsed_source = "estimated" if elapsed is not None else "unknown"
        previous[turn] = clock  # A missing move clock breaks the estimation chain.
        board.push(move)
        moves.append(
            ParsedMove(
                index,
                number,
                PlayerColor.WHITE if turn else PlayerColor.BLACK,
                san,
                move.uci(),
                before,
                board.fen(),
                clock,
                elapsed,
                elapsed_source,
            )
        )
    return moves


def parse_game(
    raw_pgn: str,
    tracked_username: str,
    *,
    max_bytes: int = 1_000_000,
    source_final_fen: str | None = None,
) -> ParsedGame:
    if not isinstance(raw_pgn, str) or not raw_pgn.strip():
        raise PGNParseError(R.EMPTY_PGN)
    if (
        len(raw_pgn) > max_bytes
        or len(raw_pgn.encode("utf-8", errors="replace")) > max_bytes
    ):
        raise PGNParseError(R.PGN_TOO_LARGE)
    if not isinstance(tracked_username, str) or not tracked_username.strip():
        raise PGNParseError(R.INVALID_PLAYER_METADATA)
    stream = io.StringIO(raw_pgn)
    try:
        game = chess.pgn.read_game(stream, Visitor=_Builder)
    except PGNParseError:
        raise
    except ValueError, OverflowError:
        # Numeric NAGs and other malformed library input must not abort a batch.
        raise PGNParseError(R.INVALID_MOVES) from None
    if game is None:
        raise PGNParseError(R.EMPTY_PGN)
    if game.errors:
        raise PGNParseError(R.INVALID_MOVES)
    if chess.pgn.read_game(stream, Visitor=chess.pgn.SkipVisitor) is not None:
        raise PGNParseError(R.MULTIPLE_GAMES)
    headers, result = _audit_text(raw_pgn)
    if headers.get("Result") not in RESULTS or result not in RESULTS:
        raise PGNParseError(R.UNKNOWN_RESULT)
    if headers["Result"] != result:
        raise PGNParseError(R.RESULT_MISMATCH)
    white, black = _optional(headers.get("White")), _optional(headers.get("Black"))
    if not white or not black or white.casefold() == black.casefold():
        raise PGNParseError(R.INVALID_PLAYER_METADATA)
    tracked = tracked_username.strip().casefold()
    if tracked not in {white.casefold(), black.casefold()}:
        raise PGNParseError(R.PLAYER_NOT_IN_GAME)
    color = PlayerColor.WHITE if tracked == white.casefold() else PlayerColor.BLACK
    player_result = (
        GameResult.DRAW
        if result == "1/2-1/2"
        else (
            GameResult.WIN
            if (result == "1-0") == (color == PlayerColor.WHITE)
            else GameResult.LOSS
        )
    )
    board = game.board()
    initial_fen = board.fen()
    unknown_history = "FEN" in headers
    control = _time_control(_optional(headers.get("TimeControl")))
    moves = _read_mainline(game, board, control, unknown_history)
    outcome = board.outcome(claim_draw=False)
    if outcome is not None and outcome.result() != result:
        raise PGNParseError(R.RESULT_MISMATCH)
    if source_final_fen is not None:
        try:
            reference = chess.Board(source_final_fen)
        except ValueError:
            raise PGNParseError(R.FINAL_POSITION_MISMATCH) from None
        # Providers differ on EP/counters. Compare placement and side-to-move.
        if not reference.is_valid() or (reference.board_fen(), reference.turn) != (
            board.board_fen(),
            board.turn,
        ):
            raise PGNParseError(R.FINAL_POSITION_MISMATCH)
    return ParsedGame(
        tracked,
        white,
        black,
        color,
        player_result,
        result,
        initial_fen,
        board.fen(),
        unknown_history,
        tuple(moves),
        control,
        _optional(headers.get("ECO")),
        _optional(headers.get("Opening")),
        _optional(headers.get("ECOUrl")),
        _optional(headers.get("Termination")),
    )
