"""Conservative detectable-claim checks; these do not prove prose factuality."""

import re

from chess_coach.application.errors import OperationError
from chess_coach.domain.coaching_models import HistoricalExplanation


def validate_text(output: HistoricalExplanation) -> None:
    payload = output.model_dump(exclude={"status", "priorities"})
    texts = list(payload.values())
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
