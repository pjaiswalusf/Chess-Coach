"""Phase 6 storage models. No import, engine, or coaching logic lives here."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, validates

from chess_coach.infrastructure.persistence.base import Base, UTCDateTime


class Platform(StrEnum):
    CHESS_COM = "chess.com"
    PGN = "pgn"


class PlayerColor(StrEnum):
    WHITE = "white"
    BLACK = "black"


class GameResult(StrEnum):
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"
    UNKNOWN = "unknown"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class GameAnalysisStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Phase(StrEnum):
    OPENING = "opening"
    MIDDLEGAME = "middlegame"
    ENDGAME = "endgame"


class Severity(StrEnum):
    NORMAL = "normal"
    MINOR = "minor"
    SIGNIFICANT = "significant"
    CRITICAL = "critical"


def string_enum(enum: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
    )


def utc_now() -> datetime:
    return datetime.now(UTC)


class TrackedPlayer(Base):
    __tablename__ = "tracked_players"
    __table_args__ = (UniqueConstraint("platform", "username"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[Platform] = mapped_column(string_enum(Platform, "platform"))
    username: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    @validates("username")
    def normalize_username(self, key: str, value: str) -> str:
        return value.casefold()


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        UniqueConstraint("platform", "external_id"),
        UniqueConstraint("canonical_hash"),
        Index("ix_games_tracked_player_id_played_at", "tracked_player_id", "played_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_player_id: Mapped[int] = mapped_column(ForeignKey("tracked_players.id"))
    platform: Mapped[Platform] = mapped_column(string_enum(Platform, "platform"))
    external_id: Mapped[str | None] = mapped_column(String(128))
    canonical_hash: Mapped[str] = mapped_column(String(64))
    raw_pgn: Mapped[str] = mapped_column(Text)
    played_at: Mapped[datetime] = mapped_column(UTCDateTime())
    white_username: Mapped[str] = mapped_column(String(100))
    black_username: Mapped[str] = mapped_column(String(100))
    white_rating: Mapped[int | None]
    black_rating: Mapped[int | None]
    player_color: Mapped[PlayerColor] = mapped_column(
        string_enum(PlayerColor, "player_color")
    )
    result: Mapped[GameResult] = mapped_column(string_enum(GameResult, "result"))
    time_control: Mapped[str | None] = mapped_column(String(100))
    time_class: Mapped[str | None] = mapped_column(String(32))
    eco_code: Mapped[str | None] = mapped_column(String(3))
    eco_url: Mapped[str | None] = mapped_column(Text)
    opening_name: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ImportRun(Base):
    __tablename__ = "import_runs"
    __table_args__ = tuple(
        CheckConstraint(f"{field} >= 0", name=f"{field}_nonnegative")
        for field in (
            "archives_requested",
            "games_seen",
            "games_inserted",
            "games_existing",
            "games_skipped",
            "games_failed",
        )
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_player_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_players.id"), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[RunStatus] = mapped_column(
        string_enum(RunStatus, "status"), default=RunStatus.PENDING
    )
    archives_requested: Mapped[int] = mapped_column(default=0)
    games_seen: Mapped[int] = mapped_column(default=0)
    games_inserted: Mapped[int] = mapped_column(default=0)
    games_existing: Mapped[int] = mapped_column(default=0)
    games_skipped: Mapped[int] = mapped_column(default=0)
    games_failed: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = tuple(
        CheckConstraint(f"{field} >= 0", name=f"{field}_nonnegative")
        for field in (
            "games_total",
            "games_completed",
            "games_failed",
            "positions_analyzed",
            "cache_hits",
            "cache_misses",
            "error_count",
        )
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_player_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_players.id"), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[RunStatus] = mapped_column(
        string_enum(RunStatus, "status"), default=RunStatus.PENDING
    )
    engine_version: Mapped[str] = mapped_column(String(100))
    analysis_version: Mapped[str] = mapped_column(String(32))
    engine_config_hash: Mapped[str] = mapped_column(String(64))
    # The hash alone cannot reconstruct the engine settings or analysis budget.
    engine_config_json: Mapped[dict[str, int | float | str]] = mapped_column(JSON)
    draw_policy_version: Mapped[str] = mapped_column(String(32))
    games_total: Mapped[int] = mapped_column(default=0)
    games_completed: Mapped[int] = mapped_column(default=0)
    games_failed: Mapped[int] = mapped_column(default=0)
    positions_analyzed: Mapped[int] = mapped_column(default=0)
    cache_hits: Mapped[int] = mapped_column(default=0)
    cache_misses: Mapped[int] = mapped_column(default=0)
    error_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class GameAnalysisState(Base):
    __tablename__ = "game_analysis_states"
    __table_args__ = (UniqueConstraint("game_id", "analysis_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    analysis_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[GameAnalysisStatus] = mapped_column(
        string_enum(GameAnalysisStatus, "status"), default=GameAnalysisStatus.PENDING
    )
    analysis_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_runs.id"), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error_message: Mapped[str | None] = mapped_column(Text)


class PositionCache(Base):
    __tablename__ = "position_cache"
    __table_args__ = (
        UniqueConstraint(
            "fen",
            "history_hash",
            "history_before_start_unknown",
            "engine_version",
            "analysis_version",
            "config_hash",
            "draw_policy_version",
            name="uq_position_cache_compatible_history",
        ),
        CheckConstraint(
            "(score_cp_white IS NULL) != (mate_distance_white IS NULL)",
            name="exactly_one_score",
        ),
        CheckConstraint("depth >= 0", name="depth_nonnegative"),
        CheckConstraint("nodes >= 0", name="nodes_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fen: Mapped[str] = mapped_column(Text)
    initial_fen: Mapped[str] = mapped_column(Text)
    moves_uci_json: Mapped[list[str]] = mapped_column(JSON)
    history_hash: Mapped[str] = mapped_column(String(64))
    history_before_start_unknown: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="history_unknown_boolean")
    )
    engine_version: Mapped[str] = mapped_column(String(100))
    analysis_version: Mapped[str] = mapped_column(String(32))
    config_hash: Mapped[str] = mapped_column(String(64))
    draw_policy_version: Mapped[str] = mapped_column(String(32))
    score_cp_white: Mapped[int | None]
    mate_distance_white: Mapped[int | None]
    best_move_uci: Mapped[str | None] = mapped_column(String(5))
    pv_json: Mapped[list[str]] = mapped_column(JSON)
    depth: Mapped[int] = mapped_column(Integer)
    nodes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class MoveAnalysis(Base):
    __tablename__ = "move_analyses"
    __table_args__ = (
        UniqueConstraint("game_id", "ply", "analysis_version"),
        CheckConstraint("ply >= 1", name="ply_positive"),
        CheckConstraint("move_number >= 1", name="move_number_positive"),
        CheckConstraint("loss_cp >= 0", name="loss_nonnegative"),
        CheckConstraint(
            "(eval_before_cp_white IS NULL) != (mate_before_white IS NULL)",
            name="exactly_one_before_score",
        ),
        CheckConstraint(
            "(eval_after_cp_white IS NULL) != (mate_after_white IS NULL)",
            name="exactly_one_after_score",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    analysis_run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_runs.id"), index=True
    )
    ply: Mapped[int]
    move_number: Mapped[int]
    mover: Mapped[PlayerColor] = mapped_column(string_enum(PlayerColor, "mover"))
    fen_before: Mapped[str] = mapped_column(Text)
    played_move_uci: Mapped[str] = mapped_column(String(5))
    played_move_san: Mapped[str] = mapped_column(String(32))
    best_move_uci: Mapped[str | None] = mapped_column(String(5))
    eval_before_cp_white: Mapped[int | None]
    eval_after_cp_white: Mapped[int | None]
    mate_before_white: Mapped[int | None]
    mate_after_white: Mapped[int | None]
    loss_cp: Mapped[int | None]
    phase: Mapped[Phase | None] = mapped_column(string_enum(Phase, "phase"))
    severity: Mapped[Severity | None] = mapped_column(string_enum(Severity, "severity"))
    pv_json: Mapped[list[str]] = mapped_column(JSON)
    analysis_version: Mapped[str] = mapped_column(String(32))
