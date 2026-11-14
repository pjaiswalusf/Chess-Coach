"""Compare completed games before and after practice began."""

from collections import defaultdict
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select

from chess_coach.analytics.sample_policy import CRITICAL_LOSS_CP
from chess_coach.domain.analysis import AnalysisProfile
from chess_coach.domain.game_records import PlayerColor
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
    profile_of,
)
from chess_coach.infrastructure.persistence.models import Puzzle, PuzzleAttempt
from chess_coach.infrastructure.persistence.training_repository import (
    TrainingRepository,
)

MIN_TRANSFER_GAMES = 10
MIN_TRANSFER_MOVES = 100


class PeriodEvidence(BaseModel):
    game_ids: list[int]
    moves: int
    critical_errors: int
    errors_per_100: float | None


class TransferComparison(BaseModel):
    time_class: str
    time_control: str
    color: PlayerColor
    profile_hash: str
    analysis_version: str
    before: PeriodEvidence
    after: PeriodEvidence
    change_per_100: float | None
    relative_change_percent: float | None


class TransferReport(BaseModel):
    first_attempt_at: datetime | None = None
    min_games_per_period: int = MIN_TRANSFER_GAMES
    min_moves_per_period: int = MIN_TRANSFER_MOVES
    critical_loss_cp: int = CRITICAL_LOSS_CP
    cohorts: list[TransferComparison]


def build_transfer_report(
    store: TrainingRepository, player_id: int | None
) -> TransferReport:
    if player_id is None:
        return TransferReport(cohorts=[])
    with store.sessions() as session:
        first = session.scalar(
            select(PuzzleAttempt.attempted_at)
            .join(Puzzle)
            .where(Puzzle.tracked_player_id == player_id)
            .order_by(PuzzleAttempt.attempted_at)
            .limit(1)
        )
        if first is None:
            return TransferReport(cohorts=[])
        evidence = session.execute(store.evidence(player_id))
        # Each game appears once per compatible profile. Track only scored
        # CP moves, with a denominator identical in both periods.
        by_cohort: dict[
            tuple[str, str, PlayerColor, str, str],
            dict[bool, dict[int, list[int]]],
        ] = defaultdict(lambda: defaultdict(dict))
        valid_games: dict[tuple[int, str], bool] = {}
        profiles: dict[int, AnalysisProfile] = {}
        for game, move, _, run in evidence:
            if (
                not game.time_class
                or not game.time_control
                or move.loss_cp is None
                or game.played_at == first
            ):
                continue
            key = (game.id, move.profile_hash)
            if key not in valid_games:
                if run.id not in profiles:
                    profiles[run.id] = profile_of(run)
                profile = profiles[run.id]
                valid_games[key] = (
                    profile.hash == move.profile_hash
                    and AnalysisRepository.compatible(session, game, profile)
                )
            if not valid_games[key]:
                continue
            cohort = (
                game.time_class,
                game.time_control,
                game.player_color,
                move.profile_hash,
                move.analysis_version,
            )
            counts = by_cohort[cohort][game.played_at > first].setdefault(
                game.id, [0, 0]
            )
            counts[0] += 1
            counts[1] += move.loss_cp >= CRITICAL_LOSS_CP
    return TransferReport(
        first_attempt_at=first,
        cohorts=[_compare(key, periods) for key, periods in sorted(by_cohort.items())],
    )


def _compare(
    cohort: tuple[str, str, PlayerColor, str, str],
    periods: dict[bool, dict[int, list[int]]],
) -> TransferComparison:
    def period(games: dict[int, list[int]]) -> PeriodEvidence:
        moves = sum(counts[0] for counts in games.values())
        errors = sum(counts[1] for counts in games.values())
        sufficient = len(games) >= MIN_TRANSFER_GAMES and moves >= MIN_TRANSFER_MOVES
        return PeriodEvidence(
            game_ids=sorted(games),
            moves=moves,
            critical_errors=errors,
            errors_per_100=100 * errors / moves if sufficient else None,
        )

    before, after = period(periods.get(False, {})), period(periods.get(True, {}))
    baseline, subsequent = before.errors_per_100, after.errors_per_100
    change = (
        subsequent - baseline
        if baseline is not None and subsequent is not None
        else None
    )
    time_class, time_control, color, profile, version = cohort
    return TransferComparison(
        time_class=time_class,
        time_control=time_control,
        color=color,
        profile_hash=profile,
        analysis_version=version,
        before=before,
        after=after,
        change_per_100=change,
        relative_change_percent=100 * change / baseline
        if change is not None and baseline
        else None,
    )
