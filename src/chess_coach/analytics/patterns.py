"""Descriptive segments, opportunity populations and deterministic category rankings."""

from collections import Counter, defaultdict
from statistics import median
from typing import Literal, cast

from chess_coach.analytics import sample_policy as policy
from chess_coach.analytics.contracts import (
    AdvantageMetrics,
    CastlingMetrics,
    ContextMetric,
    EvidenceStatus,
    GameEvidence,
    MoveEvidence,
    OutcomeMetric,
    Segment,
    Severity,
    Weakness,
)
from chess_coach.analytics.metrics import move_metrics, player_moves, rate, summarize
from chess_coach.domain.feature_models import GamePhase

ERRORS = {Severity.SIGNIFICANT, Severity.CRITICAL}


def segments(games: tuple[GameEvidence, ...], dimension: str) -> tuple[Segment, ...]:
    groups: dict[str, list[GameEvidence]] = defaultdict(list)
    if dimension == "phase":
        for phase in GamePhase:
            groups[phase.value] = [
                g for g in games if any(m.phase == phase for m in g.moves)
            ]
    else:
        for game in games:
            # Preserve exact clock rules as well as imported time class.
            key = (
                f"{game.time_class}:{game.time_control}"
                if dimension == "time_control"
                else str(getattr(game, dimension))
            )
            groups[key].append(game)
    result = []
    for key, group in sorted(groups.items()):
        cohort = tuple(group)
        moves = player_moves(cohort)
        if dimension == "phase":
            moves = tuple(m for m in moves if m.phase == key)
        usable = tuple(m for m in moves if m.severity is not None)
        support = policy.support(
            len(usable),
            len({m.game_id for m in usable}),
            policy.PHASE_MOVES,
            policy.PHASE_GAMES,
        )
        early = None
        opening = None
        first = []
        if dimension == "eco":
            opening = move_metrics(
                tuple(m for m in moves if m.phase == GamePhase.OPENING)
            )
            analyzed = [
                g
                for g in cohort
                if g.analysis_status == "done"
                and g.features_available
                and all(
                    m.severity is not None
                    for m in g.moves
                    if m.phase == GamePhase.OPENING
                )
            ]
            for g in analyzed:
                errors = [
                    m.move_number
                    for m in g.moves
                    if m.phase == GamePhase.OPENING and m.severity in ERRORS
                ]
                if errors:
                    first.append(min(errors))
            early = rate(len(first), len(analyzed))
            support = policy.support(
                len(analyzed), len(analyzed), policy.OPENING_GAMES, policy.OPENING_GAMES
            )
            if key == "UNKNOWN":
                support = EvidenceStatus.UNAVAILABLE
        if dimension == "phase" and key == GamePhase.UNCLASSIFIED:
            support = EvidenceStatus.UNAVAILABLE
        result.append(
            Segment(
                key=key,
                summary=summarize(cohort, moves),
                evidence_status=support,
                time_class_games=dict(
                    sorted(Counter(g.time_class for g in cohort).items())
                ),
                color_games=dict(
                    sorted(Counter(g.color.value for g in cohort).items())
                ),
                opening_names=tuple(
                    sorted({g.opening_name for g in cohort if g.opening_name})
                )
                if dimension == "eco"
                else (),
                opening_moves=opening,
                early_errors=early,
                median_first_error_move=float(median(first)) if first else None,
            )
        )
    return tuple(result)


def advantage_crossings(
    games: tuple[GameEvidence, ...],
) -> dict[tuple[int, int], bool | None]:
    result: dict[tuple[int, int], bool | None] = {}
    for game in games:
        previous = None
        for move in sorted(game.moves, key=lambda m: m.ply):
            result[(game.game_id, move.ply)] = (
                None
                if previous is None or move.before_cp is None
                else previous < policy.ADVANTAGE_CP <= move.before_cp
            )
            previous = move.before_cp
    return result


def contexts(
    games: tuple[GameEvidence, ...], clock_coverage: float | None
) -> tuple[ContextMetric, ...]:
    moves = player_moves(games)
    crossings = advantage_crossings(games)
    game_by_id = {g.game_id: g for g in games}
    result = []
    for key in (
        "in_check",
        "after_capture",
        "under_time_pressure",
        "advantage_crossing",
    ):

        def value(m: MoveEvidence, key: str = key) -> bool | None:
            return (
                crossings[(m.game_id, m.ply)]
                if key == "advantage_crossing"
                else getattr(m, key)
            )

        yes = tuple(m for m in moves if value(m) is True)
        no = tuple(m for m in moves if value(m) is False)
        classified = [m for m in yes if m.severity is not None]
        status = policy.support(
            len(classified),
            len({m.game_id for m in classified}),
            policy.CONTEXT_MOVES,
            policy.CONTEXT_GAMES,
        )
        if key == "under_time_pressure" and (
            clock_coverage is None or clock_coverage < policy.CLOCK_COVERAGE
        ):
            status = EvidenceStatus.UNAVAILABLE
        strata: dict[str, list[MoveEvidence]] = defaultdict(list)
        for m in yes:
            g = game_by_id[m.game_id]
            strata[f"{m.phase}:{g.time_class}:{g.time_control}:{g.color}"].append(m)
        result.append(
            ContextMetric(
                key=key,
                opportunities=move_metrics(yes),
                comparison=move_metrics(no),
                unknown_moves=sum(value(m) is None for m in moves),
                evidence_status=status,
                strata={k: move_metrics(tuple(v)) for k, v in sorted(strata.items())},
            )
        )
    return tuple(result)


def advantages(games: tuple[GameEvidence, ...]) -> AdvantageMetrics:
    eligible: dict[str, list[GameEvidence]] = {"conversion": [], "recovery": []}
    excluded = []
    collapsed = []
    for g in games:
        ordered = sorted(g.moves, key=lambda m: m.ply)
        # Missing/mate anywhere in the player's before/after history excludes the game.
        if (
            g.analysis_status != "done"
            or not ordered
            or any(v is None for v in g.evaluation_path)
            or any(m.before_cp is None or m.after_cp is None for m in ordered)
        ):
            excluded.append(g.game_id)
            continue
        before = [m.before_cp for m in ordered if m.before_cp is not None]
        for category, sign in (("conversion", 1), ("recovery", -1)):
            qualifying = next(
                (
                    i
                    for i in range(1, len(before))
                    if sign * before[i - 1] >= policy.ADVANTAGE_CP
                    and sign * before[i] >= policy.ADVANTAGE_CP
                ),
                None,
            )
            if qualifying is not None:
                eligible[category].append(g)
                later = (
                    [
                        v
                        for i, v in enumerate(g.evaluation_path, start=1)
                        if i >= ordered[qualifying].ply
                    ]
                    if g.evaluation_path
                    else [
                        v
                        for m in ordered[qualifying:]
                        for v in (m.before_cp, m.after_cp)
                    ]
                )
                if category == "conversion" and any(
                    v is not None and v < policy.COLLAPSE_CP for v in later
                ):
                    collapsed.append(g.game_id)

    def outcome(category: str) -> OutcomeMetric:
        group = eligible[category]
        n = len(group)
        counts = Counter(g.result.value for g in group)
        return OutcomeMetric(
            eligible_game_ids=tuple(sorted(g.game_id for g in group)),
            excluded_game_ids=tuple(sorted(excluded)),
            wins=rate(counts["win"], n),
            draws=rate(counts["draw"], n),
            losses=rate(counts["loss"], n),
            nonloss=rate(counts["win"] + counts["draw"], n),
            collapsed_game_ids=tuple(sorted(collapsed))
            if category == "conversion"
            else (),
            evidence_status=policy.support(
                n, n, policy.CONVERSION_GAMES, policy.CONVERSION_GAMES
            ),
        )

    return AdvantageMetrics(
        conversion=outcome("conversion"), recovery=outcome("recovery")
    )


def castling(games: tuple[GameEvidence, ...]) -> CastlingMetrics:
    eligible = [
        g
        for g in games
        if g.analysis_status == "done"
        and g.features_available
        and g.castling_history_known
    ]
    reached = [g for g in eligible if any(m.move_number >= 15 for m in g.moves)]
    return CastlingMetrics(
        all_games=rate(
            sum(any(m.castled for m in g.moves) for g in eligible), len(eligible)
        ),
        by_move_15=rate(
            sum(
                any(m.castled and m.move_number <= 15 for m in g.moves) for g in reached
            ),
            len(reached),
        ),
        excluded_games=len(games) - len(eligible),
    )


def rank_candidates(
    games: tuple[GameEvidence, ...],
    phase: tuple[Segment, ...],
    openings: tuple[Segment, ...],
    behavioral: tuple[ContextMetric, ...],
) -> dict[str, tuple[Weakness, ...]]:
    candidates: dict[str, list[Weakness]] = {"phase": [], "opening": [], "context": []}
    moves = player_moves(games)
    crossings = advantage_crossings(games)
    for category, entries in (
        ("phase", phase),
        ("opening", openings),
        ("context", behavioral),
    ):
        for entry in entries:
            if entry.evidence_status != EvidenceStatus.SUFFICIENT:
                continue
            if category == "phase":
                subset = tuple(m for m in moves if m.phase == entry.key)
            elif category == "opening":
                ids = {g.game_id for g in games if g.eco == entry.key}
                subset = tuple(
                    m
                    for m in moves
                    if m.game_id in ids and m.phase == GamePhase.OPENING
                )
            else:
                subset = tuple(
                    m
                    for m in moves
                    if (
                        crossings[(m.game_id, m.ply)]
                        if entry.key == "advantage_crossing"
                        else getattr(m, entry.key)
                    )
                    is True
                )
            usable = tuple(m for m in subset if m.severity is not None)
            metrics = move_metrics(usable)
            n, s, c = (
                metrics.classifiable_moves,
                metrics.significant.numerator,
                metrics.critical.numerator,
            )
            if not n or not s + c:
                continue
            # Opening ranking additionally needs usable early-error move support.
            if (
                category == "opening"
                and policy.support(
                    n,
                    metrics.games_represented,
                    policy.PHASE_MOVES,
                    policy.OPENING_GAMES,
                )
                != EvidenceStatus.SUFFICIENT
            ):
                continue
            score = (
                100 * (s + 2 * c) / n * min(1.0, n / 50, metrics.games_represented / 10)
            )
            candidates[category].append(
                Weakness(
                    candidate_key=f"{category}:{entry.key}",
                    category=cast(Literal["phase", "opening", "context"], category),
                    opportunities=n,
                    significant_errors=s,
                    critical_errors=c,
                    distinct_games=metrics.games_represented,
                    priority_score=score,
                    source_moves=tuple(
                        sorted(
                            (m.game_id, m.ply) for m in usable if m.severity in ERRORS
                        )
                    ),
                )
            )
    return {
        k: tuple(sorted(v, key=lambda w: (-w.priority_score, w.candidate_key)))
        for k, v in candidates.items()
    }
