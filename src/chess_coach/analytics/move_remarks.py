"""Conversational remarks from observable changes in the played position."""

import chess

from chess_coach.domain.coaching_models import MoveCoachingEvidence

_CENTER = chess.SquareSet([chess.D4, chess.E4, chess.D5, chess.E5])


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
    if evidence.played_move_uci == evidence.best_move_uci:
        parts.append("Nice choice — this is Stockfish’s top move.")
    elif evidence.loss_cp is not None and evidence.loss_cp >= 80:
        parts.append(
            "But there’s a stronger continuation to consider. Watch the engine’s reply below."
        )
    return " ".join(parts)
