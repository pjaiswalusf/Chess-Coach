"""Coaching priorities grounded in completed-game engine evidence."""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

import chess
from pydantic import BaseModel

from chess_coach.analytics.sample_policy import (
    ADVANTAGE_CP,
    COLLAPSE_CP,
    CRITICAL_LOSS_CP,
)
from chess_coach.domain.material import calculate_material


class Pattern(StrEnum):
    MISSED_MATE = "missed_mate"
    LOST_PIECE = "lost_piece"
    LOST_ADVANTAGE = "lost_advantage"


COPY = {
    Pattern.MISSED_MATE: (
        "Look for a forced mate",
        "You had a forced mate and played a move that let it slip away.",
        "Before taking material, check whether a forcing check starts a mating sequence.",
    ),
    Pattern.LOST_PIECE: (
        "Check what your move leaves undefended",
        "Your opponent could take a piece immediately and keep the material gain in the saved engine line.",
        "Before moving, scan your opponent’s captures. Check what the piece you move was defending or blocking.",
    ),
    Pattern.LOST_ADVANTAGE: (
        "Protect your advantage",
        "A sustained engine advantage fell below half a pawn on your move.",
        "When you’re ahead, check your opponent’s forcing replies before committing to your plan.",
    ),
}


class CoachExample(BaseModel):
    game_id: int
    ply: int
    move_label: str
    opponent: str
    detail: str


class CoachPriority(BaseModel):
    pattern: Pattern
    title: str
    finding: str
    habit: str
    affected_games: int
    examples: list[CoachExample]
    practice_puzzle_id: int | None


@dataclass(frozen=True)
class Finding:
    pattern: Pattern
    example: CoachExample
    puzzle_id: int | None
    loss: int


def piece_loss(board: chess.Board, played: str, line: list[str]) -> str | None:
    if not line:
        return None
    after = board.copy(stack=False)
    try:
        after.push_uci(played)
        reply = after.parse_uci(line[0])
        captured = after.piece_type_at(reply.to_square)
        if captured in (None, chess.PAWN, chess.KING) or not after.is_capture(reply):
            return None
        reply_san = after.san(reply)
        after.push(reply)
        # Let the solver reply before claiming the piece was lost.
        if len(line) < 2 and not after.is_game_over():
            return None
        if any(
            board_move.to_square == reply.to_square and after.is_capture(board_move)
            for board_move in after.legal_moves
        ):
            return None
        for uci in line[1:]:
            after.push_uci(uci)
    except ValueError:
        return None
    w0, b0 = calculate_material(board)
    w1, b1 = calculate_material(after)
    loss = (w0 - b0 - w1 + b1) * (1 if board.turn else -1)
    if loss < 3:
        return None
    return f"{reply_san} takes your {chess.piece_name(captured)}."


def classify(
    board: chess.Board,
    played: str,
    before_mate: bool | None,
    after_mate: bool | None,
    loss: int,
    previous_cp: int | None,
    before_cp: int | None,
    after_cp: int | None,
    reply: list[str],
) -> tuple[Pattern, str] | None:
    if before_mate == board.turn and after_mate != board.turn:
        return Pattern.MISSED_MATE, "This move gave up the forced mate."
    if loss >= CRITICAL_LOSS_CP and (detail := piece_loss(board, played, reply)):
        return Pattern.LOST_PIECE, detail
    if (
        previous_cp is not None
        and before_cp is not None
        and after_cp is not None
        and min(previous_cp, before_cp) >= ADVANTAGE_CP
        and after_cp < COLLAPSE_CP
        and loss >= CRITICAL_LOSS_CP
    ):
        after = board.copy(stack=False)
        detail = f"Your engine evaluation fell from {before_cp / 100:+.2f} to {after_cp / 100:+.2f}."
        if reply:
            try:
                after.push_uci(played)
                answer = after.parse_uci(reply[0])
                detail += f" The engine’s reply is {after.san(answer)}."
            except ValueError:
                pass
        return Pattern.LOST_ADVANTAGE, detail
    return None


def top_priority(findings: list[Finding]) -> CoachPriority | None:
    """Require three distinct games. Rank by reach, then by tactical specificity."""
    groups: dict[Pattern, dict[int, Finding]] = {pattern: {} for pattern in Pattern}
    practice: dict[Pattern, int] = {}
    for finding in sorted(findings, key=lambda item: -item.loss):
        groups[finding.pattern].setdefault(finding.example.game_id, finding)
        if finding.puzzle_id is not None:
            practice.setdefault(finding.pattern, finding.puzzle_id)
    counts = Counter({key: len(games) for key, games in groups.items()})
    pattern, count = counts.most_common(1)[0]
    if count < 3:
        return None
    title, finding_text, habit = COPY[pattern]
    return CoachPriority(
        pattern=pattern,
        title=title,
        finding=finding_text,
        habit=habit,
        affected_games=count,
        examples=[item.example for item in list(groups[pattern].values())[:2]],
        practice_puzzle_id=practice.get(pattern),
    )
