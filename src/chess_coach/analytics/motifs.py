"""Conservative chess events from legal, compatible completed-game snapshots."""

import chess

from chess_coach.analytics.features import calculate_material
from chess_coach.analytics.sample_policy import ADVANTAGE_CP, COLLAPSE_CP
from chess_coach.domain.analysis import fingerprint
from chess_coach.domain.coaching_models import MoveCoachingEvidence
from chess_coach.domain.motif_models import (
    ChessEvent,
    ChessEventType,
    FactId,
    MotifEvidence,
)


def _material_loss(move: MoveCoachingEvidence) -> int | None:
    """Only detect immediate, unrecapturable non-pawn losses on a quiet move."""
    if (
        move.loss_cp is None
        or move.loss_cp < ADVANTAGE_CP
        or move.after.cp_white is None
        or move.played_move_uci == move.best_move_uci
        or not move.played_refutation_uci
        or len(move.best_line_uci) < 2
    ):
        return None
    board = chess.Board(move.fen_before)
    played = chess.Move.from_uci(move.played_move_uci)
    mover = board.turn
    sign = 1 if mover else -1
    if sign * move.after.cp_white >= COLLAPSE_CP:
        return None

    def balance(position: chess.Board) -> int:
        white, black = calculate_material(position)
        return sign * (white - black)

    initial = balance(board)
    if board.is_capture(played) or board.gives_check(played) or played.promotion:
        return None
    best = board.copy()
    for uci in move.best_line_uci:
        best.push_uci(uci)
        if balance(best) < initial and best.turn == mover:
            return None

    board.push(played)
    reply = chess.Move.from_uci(move.played_refutation_uci[0])
    target = board.piece_type_at(reply.to_square)
    if not board.is_capture(reply) or target in (None, chess.PAWN):
        return None
    board.push(reply)
    if any(board.is_capture(m) for m in board.legal_moves):
        # Even an unrelated countercapture can make this short line ambiguous.
        return None
    immediate = initial - balance(board)
    for uci in move.played_refutation_uci[1:]:
        board.push_uci(uci)
        if initial - balance(board) < immediate:
            return None
    return immediate if immediate >= 3 else None


def detect_events(
    move: MoveCoachingEvidence, previous_before_cp_white: int | None = None
) -> MotifEvidence:
    mover = move.player_color == "white"
    before, after = move.before, move.after
    events = []
    # Scope references to the complete engine snapshot, including history and profile.
    identity = fingerprint([move.model_dump(mode="json"), previous_before_cp_white])

    def event(
        kind: ChessEventType, facts: tuple[FactId, ...], material: int | None = None
    ) -> ChessEvent:
        return ChessEvent(
            id=f"{identity[:16]}:{kind.value}",
            type=kind,
            game_id=move.game_id,
            ply=move.ply,
            supporting_facts=facts,
            material_lost=material,
        )

    # A different legal best move must exist. Independent searches can disagree
    # even when the played move is the best move; don't label those transitions.
    if move.played_move_uci != move.best_move_uci:
        if (
            after.mate_winner is not None
            and after.mate_winner != mover
            and (before.mate_winner is None or before.mate_winner == mover)
        ):
            events.append(
                event(ChessEventType.MATE_ALLOWED, ("before", "after", "played_line"))
            )
        if before.mate_winner == mover and after.mate_winner != mover:
            events.append(
                event(ChessEventType.MATE_MISSED, ("before", "after", "best_line"))
            )
        material = _material_loss(move)
        if material is not None:
            events.append(
                event(
                    ChessEventType.MATERIAL_LOSS,
                    ("before", "after", "best_line", "played_line"),
                    material,
                )
            )
        sign = 1 if mover else -1
        if (
            move.ply >= 3
            and previous_before_cp_white is not None
            and before.cp_white is not None
            and after.cp_white is not None
            and sign * previous_before_cp_white >= ADVANTAGE_CP
            and sign * before.cp_white >= ADVANTAGE_CP
            and sign * after.cp_white < COLLAPSE_CP
        ):
            events.append(
                event(
                    ChessEventType.WINNING_OPPORTUNITY_LOST,
                    ("previous_before", "before", "after"),
                )
            )

    return MotifEvidence(
        move=move,
        previous_before_cp_white=previous_before_cp_white,
        events=tuple(events),
    )
