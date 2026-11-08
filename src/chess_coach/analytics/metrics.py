"""Pure arithmetic; no missing-as-zero, pooled means, explicit denominators."""

from collections import Counter
from statistics import median

from chess_coach.analytics.contracts import (
    GameEvidence,
    MoveEvidence,
    MoveMetrics,
    Rate,
    Severity,
    Summary,
)


def rate(numerator: int, denominator: int) -> Rate:
    return Rate(
        numerator=numerator,
        denominator=denominator,
        per_100=100 * numerator / denominator if denominator else None,
    )


def move_metrics(moves: tuple[MoveEvidence, ...]) -> MoveMetrics:
    losses = [m.loss_cp for m in moves if m.loss_cp is not None]
    classified = sum(m.severity is not None for m in moves)
    return MoveMetrics(
        player_moves=len(moves),
        games_represented=len({m.game_id for m in moves}),
        comparable_moves=len(losses),
        excluded_losses=len(moves) - len(losses),
        classifiable_moves=classified,
        total_loss_cp=sum(losses),
        mean_loss_cp=sum(losses) / len(losses) if losses else None,
        median_loss_cp=float(median(losses)) if losses else None,
        significant=rate(
            sum(m.severity == Severity.SIGNIFICANT for m in moves), classified
        ),
        critical=rate(sum(m.severity == Severity.CRITICAL for m in moves), classified),
    )


def player_moves(games: tuple[GameEvidence, ...]) -> tuple[MoveEvidence, ...]:
    return tuple(m for g in games if g.analysis_status == "done" for m in g.moves)


def summarize(
    games: tuple[GameEvidence, ...], moves: tuple[MoveEvidence, ...] | None = None
) -> Summary:
    outcomes = Counter(g.result.value for g in games)
    n, wins, draws, losses = (
        len(games),
        outcomes["win"],
        outcomes["draw"],
        outcomes["loss"],
    )
    return Summary(
        games_played=n,
        wins=wins,
        draws=draws,
        losses=losses,
        score_percentage=100 * (wins + 0.5 * draws) / n if n else None,
        win_rate=rate(wins, n),
        moves=move_metrics(player_moves(games) if moves is None else moves),
    )
