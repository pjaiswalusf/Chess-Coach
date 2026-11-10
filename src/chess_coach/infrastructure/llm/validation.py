"""Conservative detectable-claim checks; these do not prove prose factuality."""

import re

from chess_coach.application.errors import OperationError
from chess_coach.domain.coaching_models import (
    HistoricalExplanation,
    MoveCoachingEvidence,
    MoveExplanation,
)


def validate_text(output: MoveExplanation | HistoricalExplanation) -> None:
    payload = output.model_dump(exclude={"status", "priorities"})
    texts = list(payload.values())
    if isinstance(output, HistoricalExplanation):
        texts += [s for p in output.priorities for s in (p.explanation, p.practice_tip)]
    text = " ".join(str(s) for s in texts)
    # Prohibit numbers (including spelled-out numeric claims), notation and markup.
    if re.search(
        r"\d|[%<>]|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
        r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
        r"hundreds?|thousands?|millions?|billions?|dozens?|percent|twice|thrice|half)\b|"
        r"\b[Oo0]-[Oo0]|\b[KQRBN]?[a-h][1-8]",
        text,
        re.IGNORECASE,
    ):
        raise OperationError(
            "UNSUPPORTED_CLAIM", "The model included prohibited claims. Retry coaching."
        )


def validate_chess_claims(
    output: MoveExplanation, evidence: MoveCoachingEvidence
) -> None:
    """Veto selected detectable contradictions; never claim full semantic verification."""
    import chess

    if (
        output.status == "explained"
        and evidence.played_move_uci == evidence.best_move_uci
    ):
        raise OperationError(
            "FACT_CONTRADICTION",
            "The played move and engine preference are the same move; abstain from explaining a mistake.",
        )

    text = " ".join(
        str(v) for k, v in output.model_dump().items() if k != "status"
    ).lower()
    board = chess.Board(evidence.fen_before)
    board.push_uci(evidence.played_move_uci)
    # Present-tense terminal claims refer to the actual played position, not a PV.
    if (
        re.search(r"(?:is|are|was|were|been|got) checkmated|(?:is|was) checkmate", text)
        and not board.is_checkmate()
    ):
        raise OperationError(
            "FACT_CONTRADICTION", "The model contradicted the recorded board state."
        )
    if re.search(
        r"(?:lost|lose|loses|losing|hangs?|hung|sacrific\w*)\b.{0,30}\b(?:queen|rook|bishop|knight|pawn)\b",
        text,
    ):
        # Material-loss prose needs a verified motif, not just a short legal PV.
        raise OperationError(
            "UNSUPPORTED_CLAIM",
            "The model asserted an unverified material consequence.",
        )
    if re.search(
        r"\b(?:fork|forked|pin|pinned|skewer|skewered|undefended|unprotected|exposes?|exposed)\b",
        text,
    ):
        raise OperationError(
            "UNSUPPORTED_CLAIM", "The model asserted an unverified tactical motif."
        )
