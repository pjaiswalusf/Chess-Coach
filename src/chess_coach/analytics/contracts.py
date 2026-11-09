"""Read-only longitudinal evidence and report contracts (UTC, half-open windows)."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from chess_coach.domain.analysis import ANALYSIS_VERSION, fingerprint
from chess_coach.domain.feature_models import EvidenceModel, GamePhase
from chess_coach.domain.game_records import GameResult, PlayerColor


class WindowType(StrEnum):
    LAST_20 = "last_20"
    LAST_50 = "last_50"
    LAST_100 = "last_100"
    ALL = "all"
    DATE_RANGE = "date_range"


class AnalyticsRequest(EvidenceModel):
    player_id: int = Field(gt=0, strict=True)
    window: WindowType = WindowType.ALL
    # An explicit profile prevents accidental engine/configuration mixing.
    profile_hash: str = Field(min_length=1)
    analysis_version: str = ANALYSIS_VERSION
    start_date: datetime | None = None
    end_date: datetime | None = None
    color: PlayerColor | None = None
    time_class: str | None = None

    @model_validator(mode="after")
    def dates(self) -> AnalyticsRequest:
        if self.window == WindowType.DATE_RANGE:
            if self.start_date is None or self.end_date is None:
                raise ValueError("Date range requires both UTC boundaries")
            if any(
                d.tzinfo is None or d.utcoffset() is None
                for d in (self.start_date, self.end_date)
            ):
                raise ValueError("Date boundaries must be timezone-aware")
            if self.end_date <= self.start_date:
                raise ValueError("End must be later than start")
            object.__setattr__(self, "start_date", self.start_date.astimezone(UTC))
            object.__setattr__(self, "end_date", self.end_date.astimezone(UTC))
        elif self.start_date is not None or self.end_date is not None:
            raise ValueError("Date boundaries require date_range")
        return self


class EvidenceStatus(StrEnum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"


class ReportStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    DATA_ERROR = "DATA_ERROR"
    NO_GAMES = "NO_GAMES"


class Severity(StrEnum):
    NORMAL = "normal"
    MINOR = "minor"
    SIGNIFICANT = "significant"
    CRITICAL = "critical"


class MoveEvidence(EvidenceModel):
    game_id: int = Field(gt=0)
    ply: int = Field(gt=0)
    move_number: int = Field(gt=0)
    mover: PlayerColor
    phase: GamePhase = GamePhase.UNCLASSIFIED
    loss_cp: float | None = Field(default=None, ge=0)
    severity: Severity | None = None
    # CP is tracked-player perspective. Mate remains separately represented.
    before_cp: int | None = None
    after_cp: int | None = None
    # Mate distances and winner colors retain White POV, never CP conversions.
    mate_before: int | None = None
    mate_after: int | None = None
    mate_before_winner: bool | None = None
    mate_after_winner: bool | None = None
    loss_exclusion: Literal["mate_transition", "missing_score"] | None = None
    in_check: bool | None = None
    after_capture: bool | None = None
    under_time_pressure: bool | None = None
    castled: bool | None = None

    @model_validator(mode="after")
    def score_states(self) -> MoveEvidence:
        if (self.before_cp is not None and self.mate_before is not None) or (
            self.after_cp is not None and self.mate_after is not None
        ):
            raise ValueError("Conflicting CP/mate score")
        if self.loss_cp is not None and (
            self.before_cp is None or self.after_cp is None
        ):
            raise ValueError("Numeric loss requires two CP scores")
        expected = (
            None
            if self.loss_cp is not None
            else (
                "mate_transition"
                if self.mate_before is not None or self.mate_after is not None
                else "missing_score"
            )
        )
        if self.loss_exclusion is not None and self.loss_exclusion != expected:
            raise ValueError("Loss exclusion contradicts scores")
        object.__setattr__(self, "loss_exclusion", expected)
        return self


class AnalysisStatus(StrEnum):
    NOT_ANALYZED = "not_analyzed"
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    INCOMPATIBLE = "incompatible"


class GameEvidence(EvidenceModel):
    game_id: int = Field(gt=0)
    played_at: datetime
    color: PlayerColor
    result: GameResult
    time_class: str = "UNKNOWN"
    time_control: str = "UNKNOWN"
    eco: str = "UNKNOWN"
    opening_name: str | None = None
    provenance: str
    history_before_start_unknown: bool = False
    analysis_status: AnalysisStatus
    expected_player_moves: int = Field(ge=0)
    moves: tuple[MoveEvidence, ...] = ()
    evaluation_path: tuple[int | None, ...] = ()
    features_available: bool = False

    @model_validator(mode="after")
    def valid_game(self) -> GameEvidence:
        if self.result == GameResult.UNKNOWN:
            raise ValueError("Analytics requires completed game outcomes")
        if self.played_at.tzinfo is None or self.played_at.utcoffset() is None:
            raise ValueError("Game timestamps must be timezone-aware")
        return self

    # Unknown custom-start history is ineligible for historical castling frequency.
    castling_history_known: bool = True


class Diagnostic(EvidenceModel):
    code: str
    game_id: int | None = None


class EvidenceDataset(EvidenceModel):
    games: tuple[GameEvidence, ...] = ()
    errors: tuple[Diagnostic, ...] = ()
    warnings: tuple[Diagnostic, ...] = ()
    database_integrity: bool = True
    foreign_keys: bool = True
    retrieval_seconds: float = Field(default=0, ge=0, exclude=True)
    validation_seconds: float = Field(default=0, ge=0, exclude=True)


class Rate(EvidenceModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    per_100: float | None

    @model_validator(mode="after")
    def consistent(self) -> Rate:
        expected = 100 * self.numerator / self.denominator if self.denominator else None
        if self.numerator > self.denominator or self.per_100 != expected:
            raise ValueError("Rate does not reconcile")
        return self


class MoveMetrics(EvidenceModel):
    player_moves: int = Field(ge=0)
    games_represented: int = Field(ge=0)
    comparable_moves: int = Field(ge=0)
    excluded_losses: int = Field(ge=0)
    classifiable_moves: int = Field(ge=0)
    total_loss_cp: float = Field(ge=0)
    mean_loss_cp: float | None
    median_loss_cp: float | None
    significant: Rate
    critical: Rate

    @model_validator(mode="after")
    def counts(self) -> MoveMetrics:
        if (
            self.comparable_moves + self.excluded_losses != self.player_moves
            or self.classifiable_moves > self.player_moves
        ):
            raise ValueError("Move populations do not reconcile")
        if (
            self.significant.denominator != self.classifiable_moves
            or self.critical.denominator != self.classifiable_moves
            or self.significant.numerator + self.critical.numerator
            > self.classifiable_moves
        ):
            raise ValueError("Severity populations do not reconcile")
        if self.mean_loss_cp != (
            self.total_loss_cp / self.comparable_moves
            if self.comparable_moves
            else None
        ):
            raise ValueError("Mean loss does not reconcile")
        if (self.median_loss_cp is None) != (self.comparable_moves == 0):
            raise ValueError("Median availability does not reconcile")
        return self


class Summary(EvidenceModel):
    games_played: int = Field(ge=0)
    wins: int = Field(ge=0)
    draws: int = Field(ge=0)
    losses: int = Field(ge=0)
    score_percentage: float | None
    win_rate: Rate
    moves: MoveMetrics

    @model_validator(mode="after")
    def outcomes(self) -> Summary:
        if (
            self.wins + self.draws + self.losses != self.games_played
            or self.win_rate
            != Rate(
                numerator=self.wins,
                denominator=self.games_played,
                per_100=100 * self.wins / self.games_played
                if self.games_played
                else None,
            )
        ):
            raise ValueError("Game outcomes do not reconcile")
        if self.score_percentage != (
            100 * (self.wins + 0.5 * self.draws) / self.games_played
            if self.games_played
            else None
        ):
            raise ValueError("Game score does not reconcile")
        return self


class Segment(EvidenceModel):
    key: str
    summary: Summary
    evidence_status: EvidenceStatus
    time_class_games: dict[str, int]
    color_games: dict[str, int]
    opening_names: tuple[str, ...] = ()
    opening_family: str | None = None
    opening_moves: MoveMetrics | None = None
    early_errors: Rate | None = None
    median_first_error_move: float | None = None


class ContextMetric(EvidenceModel):
    key: str
    opportunities: MoveMetrics
    comparison: MoveMetrics
    unknown_moves: int = Field(ge=0)
    evidence_status: EvidenceStatus
    # Descriptive strata preserve confounding rather than claiming causation.
    strata: dict[str, MoveMetrics]


class OutcomeMetric(EvidenceModel):
    eligible_game_ids: tuple[int, ...]
    excluded_game_ids: tuple[int, ...]
    wins: Rate
    draws: Rate
    losses: Rate
    nonloss: Rate
    collapsed_game_ids: tuple[int, ...] = ()
    evidence_status: EvidenceStatus

    @model_validator(mode="after")
    def outcomes(self) -> OutcomeMetric:
        n = len(self.eligible_game_ids)
        if len(set(self.eligible_game_ids)) != n or set(self.eligible_game_ids) & set(
            self.excluded_game_ids
        ):
            raise ValueError("Advantage game populations overlap")
        if (
            any(
                r.denominator != n
                for r in (self.wins, self.draws, self.losses, self.nonloss)
            )
            or self.wins.numerator + self.draws.numerator + self.losses.numerator != n
        ):
            raise ValueError("Advantage outcomes do not reconcile")
        if (
            self.nonloss.numerator != self.wins.numerator + self.draws.numerator
            or not set(self.collapsed_game_ids) <= set(self.eligible_game_ids)
        ):
            raise ValueError("Advantage recovery/collapse does not reconcile")
        return self


class AdvantageMetrics(EvidenceModel):
    conversion: OutcomeMetric
    recovery: OutcomeMetric


class CastlingMetrics(EvidenceModel):
    all_games: Rate
    by_move_15: Rate
    excluded_games: int = Field(ge=0)


class Weakness(EvidenceModel):
    candidate_key: str
    category: Literal["phase", "opening", "context"]
    opportunities: int = Field(gt=0)
    significant_errors: int = Field(ge=0)
    critical_errors: int = Field(ge=0)
    distinct_games: int = Field(gt=0)
    priority_score: float = Field(ge=0)
    recency_weight: float = Field(default=1.0, ge=1.0, le=1.0)
    evidence_status: Literal[EvidenceStatus.SUFFICIENT] = EvidenceStatus.SUFFICIENT
    source_moves: tuple[tuple[int, int], ...]


class AnalyticsHealthReport(EvidenceModel):
    integrity: Literal["PASS", "FAIL"]
    database_integrity: bool
    foreign_keys: bool
    selected_games: int = Field(ge=0)
    analyzed_games: int = Field(ge=0)
    analysis_coverage: float | None
    statuses: dict[str, int]
    selected_player_moves: int = Field(ge=0)
    analyzed_player_moves: int = Field(ge=0)
    move_evidence_coverage: float | None
    clock_data_coverage: float | None
    opening_data_coverage: float | None
    errors: tuple[Diagnostic, ...]
    warnings: tuple[Diagnostic, ...]


class TrendPeriod(EvidenceModel):
    first_game_at: datetime
    last_game_at: datetime
    game_ids: tuple[int, ...]
    critical: Rate


class RecentTrend(EvidenceModel):
    color: PlayerColor
    time_class: str
    time_control: str
    earlier: TrendPeriod
    recent: TrendPeriod
    direction: Literal["lower", "higher", "unchanged"]


class AnalyticsReport(EvidenceModel):
    analytics_version: Literal["longitudinal-v1"] = "longitudinal-v1"
    policy_version: Literal["support-v1"] = "support-v1"
    severity_version: Literal["cp-severity-v1"] = "cp-severity-v1"
    ranker_version: Literal["weakness-ranker-v1"] = "weakness-ranker-v1"
    request: AnalyticsRequest
    status: ReportStatus
    selected_game_ids: tuple[int, ...]
    health: AnalyticsHealthReport
    analyzed_move_refs: tuple[tuple[int, int], ...] = ()
    overall: Summary | None = None
    phase_metrics: tuple[Segment, ...] = ()
    color_metrics: tuple[Segment, ...] = ()
    time_control_metrics: tuple[Segment, ...] = ()
    opening_metrics: tuple[Segment, ...] = ()
    behavioral_metrics: tuple[ContextMetric, ...] = ()
    advantage_metrics: AdvantageMetrics | None = None
    castling_metrics: CastlingMetrics | None = None
    recent_trends: tuple[RecentTrend, ...] = ()
    # Category-specific rankings: scores across different populations are not comparable.
    ranked_weaknesses: dict[str, tuple[Weakness, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reconciliation(self) -> AnalyticsReport:
        if self.status != ReportStatus.DATA_ERROR and len(
            set(self.selected_game_ids)
        ) != len(self.selected_game_ids):
            raise ValueError("Duplicate selected game")
        if self.health.selected_games != len(self.selected_game_ids):
            raise ValueError("Cohort does not reconcile")
        if self.health.analyzed_games > self.health.selected_games:
            raise ValueError("Invalid coverage")
        if self.overall is not None:
            total = self.overall
            if (
                total.games_played != len(self.selected_game_ids)
                or total.wins + total.draws + total.losses != total.games_played
            ):
                raise ValueError("Outcomes do not reconcile")
            for partitions in (
                self.color_metrics,
                self.time_control_metrics,
                self.opening_metrics,
            ):
                if (
                    sum(s.summary.games_played for s in partitions)
                    != total.games_played
                ):
                    raise ValueError("Game partitions do not reconcile")
                if (
                    sum(s.summary.moves.player_moves for s in partitions)
                    != total.moves.player_moves
                ):
                    raise ValueError("Move partitions do not reconcile")
            if (
                sum(s.summary.moves.player_moves for s in self.phase_metrics)
                != total.moves.player_moves
            ):
                raise ValueError("Phase partition does not reconcile")
        allowed = set(self.selected_game_ids)
        move_refs = set(self.analyzed_move_refs)
        for category, weaknesses in self.ranked_weaknesses.items():
            if self.status != ReportStatus.COMPLETE and weaknesses:
                raise ValueError("Unsupported report cannot rank weaknesses")
            for w in weaknesses:
                if (
                    w.category != category
                    or not w.source_moves
                    or any(
                        g not in allowed or p < 1 or (g, p) not in move_refs
                        for g, p in w.source_moves
                    )
                ):
                    raise ValueError("Invalid weakness provenance")
        return self


def coaching_report_hash(report: AnalyticsReport) -> str:
    """Stable identity for historical coaching, excluding display-only comparisons."""
    return fingerprint(report.model_dump(mode="json", exclude={"recent_trends"}))
