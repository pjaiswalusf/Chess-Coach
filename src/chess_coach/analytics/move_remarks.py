"""Concise move remarks from the position and verified continuations."""

import chess

from chess_coach.analytics.contracts import Severity
from chess_coach.analytics.sample_policy import severity
from chess_coach.domain.coaching_models import MoveCoachingEvidence
from chess_coach.domain.material import PIECE_VALUES, calculate_material

_CENTER = chess.SquareSet([chess.D4, chess.E4, chess.D5, chess.E5])


def _line_consequence(
    start: chess.Board, line: tuple[str, ...], material_baseline: chess.Board
) -> str | None:
    """Describe what the side achieves in this saved line."""
    if not line:
        return None
    side = start.turn
    board = start.copy(stack=False)
    captures: list[tuple[int, int, str, str]] = []
    first_fact = None
    for index, uci in enumerate(line):
        move = chess.Move.from_uci(uci)
        mover = board.turn
        san = board.san(move)
        captured = (
            chess.PAWN
            if board.is_en_passant(move)
            else board.piece_type_at(move.to_square)
        )
        old_attacks = board.attacks(move.from_square)
        board.push(move)
        if mover != side:
            continue
        if board.is_checkmate():
            return (
                f"{san} delivers checkmate"
                if index == 0
                else f"the line ends in mate with {san}"
            )
        if captured:
            captures.append(
                (PIECE_VALUES[captured], index, san, chess.piece_name(captured))
            )
        if index == 0:
            if move.promotion:
                first_fact = f"{san} promotes to a {chess.piece_name(move.promotion)}"
            elif board.is_check():
                first_fact = f"{san} gives check"
            else:
                targets = [
                    (PIECE_VALUES[target], square, target)
                    for square in board.attacks(move.to_square) - old_attacks
                    if (target := board.piece_type_at(square)) not in (None, chess.KING)
                    and board.color_at(square) != mover
                    and not board.is_pinned(mover, move.to_square)
                ]
                if targets:
                    _, square, target = max(targets)
                    first_fact = (
                        f"{san} attacks the {chess.piece_name(target)} on "
                        f"{chess.square_name(square)}"
                    )

    white_before, black_before = calculate_material(material_baseline)
    white_after, black_after = calculate_material(board)
    swing = (white_after - black_after) - (white_before - black_before)
    if captures and (swing if side else -swing) > 0:
        _, index, san, piece = max(captures, key=lambda capture: capture[0])
        capture = f"{san} takes the {piece}"
        if index == 0:
            return capture
        if first_fact:
            return f"{first_fact}, then {capture}"
        return f"{capture} later in the line"
    return first_fact


def _correction(
    evidence: MoveCoachingEvidence,
    before: chess.Board,
    played: chess.Move,
    after: chess.Board,
) -> str | None:
    mover = before.turn
    missed_mate = (
        evidence.before.mate_winner == mover and evidence.after.mate_winner != mover
    )
    opponent = not mover
    allows_mate = (
        evidence.after.mate_winner == opponent
        and evidence.before.mate_winner != opponent
    )
    if evidence.played_move_uci == evidence.best_move_uci or (
        severity(evidence.loss_cp) in (None, Severity.NORMAL)
        and not missed_mate
        and not allows_mate
    ):
        return None

    played_san = before.san(played)
    best_san = before.san(chess.Move.from_uci(evidence.best_move_uci))
    reply = _line_consequence(after, evidence.played_refutation_uci, before)
    if missed_mate:
        problem = f"{played_san} misses a forced mate"
    elif allows_mate:
        problem = f"{played_san} allows forced mate"
    else:
        problem = (
            f"After {played_san}, {reply}"
            if reply
            else "The saved continuation shows no clear tactical reason"
        )
        reply = None
    if reply:
        problem += f", and {reply}"

    if missed_mate:
        improvement = f"Play {best_san} to force mate"
    elif allows_mate:
        improvement = f"Play {best_san} to avoid that forced mate"
    elif alternative := _line_consequence(before, evidence.best_line_uci, before):
        improvement = (
            f"Instead, {alternative}"
            if alternative.startswith(f"{best_san} ")
            else f"Play {best_san}. In that line, {alternative}"
        )
    else:
        improvement = f"Play {best_san} instead"
    return f"{problem}. {improvement}."


def move_remark(evidence: MoveCoachingEvidence) -> str:
    before = chess.Board(evidence.fen_before)
    move = chess.Move.from_uci(evidence.played_move_uci)
    color = before.turn
    piece = before.piece_type_at(move.from_square)
    assert piece is not None
    name = chess.piece_name(move.promotion or piece)
    destination = chess.square_name(move.to_square)
    after = before.copy()
    after.push(move)
    parts: list[str] = []
    if after.is_checkmate():
        return "Checkmate! The king is in check and there’s no legal escape."
    if correction := _correction(evidence, before, move, after):
        return correction
    if before.is_castling(move):
        parts.append(
            "Castling brings the rook into play and takes the king off its starting square."
        )
    elif move.promotion:
        parts.append(
            f"The pawn reaches the back rank and becomes a {chess.piece_name(move.promotion)}."
        )
    elif before.is_capture(move):
        captured = (
            chess.PAWN
            if before.is_en_passant(move)
            else before.piece_type_at(move.to_square)
        )
        assert captured is not None
        capture_square = (
            chess.square(
                chess.square_file(move.to_square), chess.square_rank(move.from_square)
            )
            if before.is_en_passant(move)
            else move.to_square
        )
        parts.append(
            f"Capturing the {chess.piece_name(captured)} on {chess.square_name(capture_square)}."
        )
    elif piece == chess.PAWN and move.to_square in _CENTER:
        parts.append(f"Taking space in the center with the pawn on {destination}.")
    elif (
        piece in (chess.KNIGHT, chess.BISHOP)
        and evidence.initial_fen == chess.STARTING_FEN
        and not evidence.history_before_start_unknown
        and chess.square_rank(move.from_square) == (0 if color else 7)
        and all(
            chess.Move.from_uci(uci).from_square != move.from_square
            for uci in evidence.history_uci
        )
    ):
        parts.append(f"Bringing the {name} off the back rank and into the game.")

    if after.is_check():
        parts.append("Check! The opponent has to deal with the king’s safety first.")
    elif not after.is_pinned(color, move.to_square):
        targets = [
            square
            for square in after.attacks(move.to_square)
            if after.color_at(square) == (not color)
            and after.piece_type_at(square) != chess.KING
        ]
        if targets:
            target = max(targets, key=lambda square: after.piece_type_at(square) or 0)
            parts.append(
                f"The {name} now attacks the {chess.piece_name(after.piece_type_at(target) or chess.PAWN)} on {chess.square_name(target)}."
            )
        elif central := after.attacks(move.to_square) & _CENTER:
            squares = " and ".join(chess.square_name(square) for square in central)
            parts.append(f"The {name} keeps an eye on {squares} in the center.")

    if piece == chess.PAWN:
        for square in before.pieces(chess.BISHOP, color):
            if after.attacks(square) - before.attacks(square):
                parts.append(
                    f"That also opens the diagonal for the bishop on {chess.square_name(square)}."
                )
                break
    if not parts:
        parts.append(f"The {name} repositions to {destination}.")
    return " ".join(parts)
