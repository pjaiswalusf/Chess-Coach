"""Turn legal saved Stockfish lines into move-specific coaching facts."""

import chess

from chess_coach.analytics.feature_config import PIECE_VALUES
from chess_coach.domain.coaching_models import (
    EngineScore,
    MoveBreakdown,
    MoveCoachingEvidence,
    MoveLine,
)

_LINE_PLIES = 8


def _label(board: chess.Board, move: chess.Move) -> str:
    dots = "." if board.turn == chess.WHITE else "..."
    return f"{board.fullmove_number}{dots} {board.san(move)}"


def _line(board: chess.Board, ucis: tuple[str, ...], focus: chess.Color) -> MoveLine:
    moves = [chess.Move.from_uci(uci) for uci in ucis[:_LINE_PLIES]]
    san = board.variation_san(moves)
    replay = board.copy(stack=False)
    candidates: list[tuple[int, str, str]] = []
    for move in moves:
        mover = replay.turn
        label = _label(replay, move)
        if mover != focus:
            replay.push(move)
            continue

        piece = replay.piece_type_at(move.from_square)
        assert piece is not None
        en_passant = replay.is_en_passant(move)
        captured = chess.PAWN if en_passant else replay.piece_type_at(move.to_square)
        capture_square = move.to_square
        if en_passant:
            capture_square = chess.square(
                chess.square_file(move.to_square), chess.square_rank(move.from_square)
            )
        castles = replay.is_castling(move)
        old_attacks = replay.attacks(move.from_square)
        replay.push(move)
        destination = chess.square_name(move.to_square)
        if replay.is_checkmate():
            candidates.append(
                (100, f"{label} delivers checkmate.", "delivers checkmate")
            )
        elif move.promotion:
            promoted = chess.piece_name(move.promotion)
            candidates.append(
                (
                    90,
                    f"{label} promotes the pawn to a {promoted} on {destination}.",
                    f"promotes a pawn to a {promoted}",
                )
            )
        elif captured:
            target_name = chess.piece_name(captured)
            capture_name = chess.square_name(capture_square)
            check = " and gives check" if replay.is_check() else ""
            candidates.append(
                (
                    60 + PIECE_VALUES[captured],
                    f"{label} captures the {target_name} on {capture_name}{check}.",
                    f"captures the {target_name}{check}",
                )
            )
        elif replay.is_check():
            candidates.append(
                (
                    50,
                    f"{label} gives check, so the opponent has to answer it.",
                    "gives check",
                )
            )
        elif castles:
            candidates.append(
                (30, f"{label} castles, moving the king to {destination}.", "castles")
            )
        else:
            targets = [
                (PIECE_VALUES[target], square, target)
                for square in replay.attacks(move.to_square) - old_attacks
                if (target := replay.piece_type_at(square))
                not in (None, chess.PAWN, chess.KING)
                and replay.color_at(square) != mover
            ]
            if targets and not replay.is_pinned(mover, move.to_square):
                weight, target_square, target_piece = max(targets)
                target_name = chess.piece_name(target_piece)
                candidates.append(
                    (
                        30 + weight,
                        f"{label} attacks the {target_name} on {chess.square_name(target_square)}.",
                        f"attacks the {target_name}",
                    )
                )
            else:
                origin = chess.square_name(move.from_square)
                candidates.append(
                    (
                        0,
                        f"{label} moves the {chess.piece_name(piece)} from {origin} to {destination}.",
                        "quiet move",
                    )
                )

    if not candidates:
        return MoveLine(
            san=san,
            key_fact=f"{_label(board, moves[0])} ends the game.",
            cue="ends the game",
        )
    _, fact, cue = max(candidates, key=lambda item: item[0])
    return MoveLine(san=san, key_fact=fact, cue=cue)


def _score(score: EngineScore) -> str:
    if score.cp_white is not None:
        return f"{score.cp_white / 100:+.2f}"
    winner = "White" if score.mate_winner else "Black"
    assert score.mate_white is not None
    return (
        f"checkmate for {winner}"
        if score.mate_white == 0
        else f"mate in {abs(score.mate_white)} for {winner}"
    )


def build_move_breakdown(evidence: MoveCoachingEvidence) -> MoveBreakdown:
    board = chess.Board(evidence.fen_before)
    mover = board.turn
    same = evidence.played_move_uci == evidence.best_move_uci
    played = chess.Move.from_uci(evidence.played_move_uci)
    best = chess.Move.from_uci(evidence.best_move_uci)
    assessment = (
        f"{_label(board, played)} is Stockfish’s top choice."
        if same
        else (
            f"After {_label(board, played)}, Stockfish’s evaluation goes from "
            f"{_score(evidence.before)} to {_score(evidence.after)} (White perspective). "
            f"Its top move from the original position was {_label(board, best)}."
        )
    )
    return MoveBreakdown(
        assessment=assessment,
        played=_line(
            board,
            (evidence.played_move_uci, *evidence.played_refutation_uci),
            mover if same else not mover,
        ),
        alternative=None if same else _line(board, evidence.best_line_uci, mover),
    )
