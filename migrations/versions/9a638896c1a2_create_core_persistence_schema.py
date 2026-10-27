"""create core persistence schema

Revision ID: 9a638896c1a2
Revises:
Create Date: 2026-10-28 00:52:48.280172

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a638896c1a2"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "position_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fen", sa.Text(), nullable=False),
        sa.Column("initial_fen", sa.Text(), nullable=False),
        sa.Column("moves_uci_json", sa.JSON(), nullable=False),
        sa.Column("history_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "history_before_start_unknown",
            sa.Boolean(create_constraint=True, name="history_unknown_boolean"),
            nullable=False,
        ),
        sa.Column("engine_version", sa.String(length=100), nullable=False),
        sa.Column("analysis_version", sa.String(length=32), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("draw_policy_version", sa.String(length=32), nullable=False),
        sa.Column("score_cp_white", sa.Integer(), nullable=True),
        sa.Column("mate_distance_white", sa.Integer(), nullable=True),
        sa.Column("best_move_uci", sa.String(length=5), nullable=True),
        sa.Column("pv_json", sa.JSON(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("nodes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(score_cp_white IS NULL) != (mate_distance_white IS NULL)",
            name=op.f("ck_position_cache_exactly_one_score"),
        ),
        sa.CheckConstraint(
            "depth >= 0", name=op.f("ck_position_cache_depth_nonnegative")
        ),
        sa.CheckConstraint(
            "nodes >= 0", name=op.f("ck_position_cache_nodes_nonnegative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_position_cache")),
        sa.UniqueConstraint(
            "fen",
            "history_hash",
            "history_before_start_unknown",
            "engine_version",
            "analysis_version",
            "config_hash",
            "draw_policy_version",
            name="uq_position_cache_compatible_history",
        ),
    )
    op.create_table(
        "tracked_players",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum(
                "chess.com",
                "pgn",
                name="platform",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tracked_players")),
        sa.UniqueConstraint(
            "platform", "username", name=op.f("uq_tracked_players_platform")
        ),
    )
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracked_player_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "partial",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("engine_version", sa.String(length=100), nullable=False),
        sa.Column("analysis_version", sa.String(length=32), nullable=False),
        sa.Column("engine_config_hash", sa.String(length=64), nullable=False),
        sa.Column("engine_config_json", sa.JSON(), nullable=False),
        sa.Column("draw_policy_version", sa.String(length=32), nullable=False),
        sa.Column("games_total", sa.Integer(), nullable=False),
        sa.Column("games_completed", sa.Integer(), nullable=False),
        sa.Column("games_failed", sa.Integer(), nullable=False),
        sa.Column("positions_analyzed", sa.Integer(), nullable=False),
        sa.Column("cache_hits", sa.Integer(), nullable=False),
        sa.Column("cache_misses", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "cache_hits >= 0", name=op.f("ck_analysis_runs_cache_hits_nonnegative")
        ),
        sa.CheckConstraint(
            "cache_misses >= 0", name=op.f("ck_analysis_runs_cache_misses_nonnegative")
        ),
        sa.CheckConstraint(
            "error_count >= 0", name=op.f("ck_analysis_runs_error_count_nonnegative")
        ),
        sa.CheckConstraint(
            "games_completed >= 0",
            name=op.f("ck_analysis_runs_games_completed_nonnegative"),
        ),
        sa.CheckConstraint(
            "games_failed >= 0", name=op.f("ck_analysis_runs_games_failed_nonnegative")
        ),
        sa.CheckConstraint(
            "games_total >= 0", name=op.f("ck_analysis_runs_games_total_nonnegative")
        ),
        sa.CheckConstraint(
            "positions_analyzed >= 0",
            name=op.f("ck_analysis_runs_positions_analyzed_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["tracked_player_id"],
            ["tracked_players.id"],
            name=op.f("fk_analysis_runs_tracked_player_id_tracked_players"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_runs")),
    )
    with op.batch_alter_table("analysis_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_analysis_runs_tracked_player_id"),
            ["tracked_player_id"],
            unique=False,
        )

    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracked_player_id", sa.Integer(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum(
                "chess.com",
                "pgn",
                name="platform",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("canonical_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_pgn", sa.Text(), nullable=False),
        sa.Column("played_at", sa.DateTime(), nullable=False),
        sa.Column("white_username", sa.String(length=100), nullable=False),
        sa.Column("black_username", sa.String(length=100), nullable=False),
        sa.Column("white_rating", sa.Integer(), nullable=True),
        sa.Column("black_rating", sa.Integer(), nullable=True),
        sa.Column(
            "player_color",
            sa.Enum(
                "white",
                "black",
                name="player_color",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "result",
            sa.Enum(
                "win",
                "loss",
                "draw",
                "unknown",
                name="result",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("time_control", sa.String(length=100), nullable=True),
        sa.Column("time_class", sa.String(length=32), nullable=True),
        sa.Column("eco_code", sa.String(length=3), nullable=True),
        sa.Column("eco_url", sa.Text(), nullable=True),
        sa.Column("opening_name", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tracked_player_id"],
            ["tracked_players.id"],
            name=op.f("fk_games_tracked_player_id_tracked_players"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_games")),
        sa.UniqueConstraint("canonical_hash", name=op.f("uq_games_canonical_hash")),
        sa.UniqueConstraint("platform", "external_id", name=op.f("uq_games_platform")),
    )
    with op.batch_alter_table("games", schema=None) as batch_op:
        batch_op.create_index(
            "ix_games_tracked_player_id_played_at",
            ["tracked_player_id", "played_at"],
            unique=False,
        )

    op.create_table(
        "import_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracked_player_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "partial",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("archives_requested", sa.Integer(), nullable=False),
        sa.Column("games_seen", sa.Integer(), nullable=False),
        sa.Column("games_inserted", sa.Integer(), nullable=False),
        sa.Column("games_existing", sa.Integer(), nullable=False),
        sa.Column("games_skipped", sa.Integer(), nullable=False),
        sa.Column("games_failed", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "archives_requested >= 0",
            name=op.f("ck_import_runs_archives_requested_nonnegative"),
        ),
        sa.CheckConstraint(
            "games_existing >= 0",
            name=op.f("ck_import_runs_games_existing_nonnegative"),
        ),
        sa.CheckConstraint(
            "games_failed >= 0", name=op.f("ck_import_runs_games_failed_nonnegative")
        ),
        sa.CheckConstraint(
            "games_inserted >= 0",
            name=op.f("ck_import_runs_games_inserted_nonnegative"),
        ),
        sa.CheckConstraint(
            "games_seen >= 0", name=op.f("ck_import_runs_games_seen_nonnegative")
        ),
        sa.CheckConstraint(
            "games_skipped >= 0", name=op.f("ck_import_runs_games_skipped_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["tracked_player_id"],
            ["tracked_players.id"],
            name=op.f("fk_import_runs_tracked_player_id_tracked_players"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_runs")),
    )
    with op.batch_alter_table("import_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_import_runs_tracked_player_id"),
            ["tracked_player_id"],
            unique=False,
        )

    op.create_table(
        "game_analysis_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("analysis_version", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "done",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("analysis_run_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_game_analysis_states_analysis_run_id_analysis_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["games.id"],
            name=op.f("fk_game_analysis_states_game_id_games"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_game_analysis_states")),
        sa.UniqueConstraint(
            "game_id", "analysis_version", name=op.f("uq_game_analysis_states_game_id")
        ),
    )
    with op.batch_alter_table("game_analysis_states", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_game_analysis_states_analysis_run_id"),
            ["analysis_run_id"],
            unique=False,
        )

    op.create_table(
        "move_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("analysis_run_id", sa.Integer(), nullable=False),
        sa.Column("ply", sa.Integer(), nullable=False),
        sa.Column("move_number", sa.Integer(), nullable=False),
        sa.Column(
            "mover",
            sa.Enum(
                "white",
                "black",
                name="mover",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("fen_before", sa.Text(), nullable=False),
        sa.Column("played_move_uci", sa.String(length=5), nullable=False),
        sa.Column("played_move_san", sa.String(length=32), nullable=False),
        sa.Column("best_move_uci", sa.String(length=5), nullable=True),
        sa.Column("eval_before_cp_white", sa.Integer(), nullable=True),
        sa.Column("eval_after_cp_white", sa.Integer(), nullable=True),
        sa.Column("mate_before_white", sa.Integer(), nullable=True),
        sa.Column("mate_after_white", sa.Integer(), nullable=True),
        sa.Column("loss_cp", sa.Integer(), nullable=True),
        sa.Column(
            "phase",
            sa.Enum(
                "opening",
                "middlegame",
                "endgame",
                name="phase",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "normal",
                "minor",
                "significant",
                "critical",
                name="severity",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("pv_json", sa.JSON(), nullable=False),
        sa.Column("analysis_version", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "(eval_after_cp_white IS NULL) != (mate_after_white IS NULL)",
            name=op.f("ck_move_analyses_exactly_one_after_score"),
        ),
        sa.CheckConstraint(
            "(eval_before_cp_white IS NULL) != (mate_before_white IS NULL)",
            name=op.f("ck_move_analyses_exactly_one_before_score"),
        ),
        sa.CheckConstraint(
            "loss_cp >= 0", name=op.f("ck_move_analyses_loss_nonnegative")
        ),
        sa.CheckConstraint(
            "move_number >= 1", name=op.f("ck_move_analyses_move_number_positive")
        ),
        sa.CheckConstraint("ply >= 1", name=op.f("ck_move_analyses_ply_positive")),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_move_analyses_analysis_run_id_analysis_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["games.id"],
            name=op.f("fk_move_analyses_game_id_games"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_move_analyses")),
        sa.UniqueConstraint(
            "game_id", "ply", "analysis_version", name=op.f("uq_move_analyses_game_id")
        ),
    )
    with op.batch_alter_table("move_analyses", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_move_analyses_analysis_run_id"),
            ["analysis_run_id"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("move_analyses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_move_analyses_analysis_run_id"))

    op.drop_table("move_analyses")
    with op.batch_alter_table("game_analysis_states", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_game_analysis_states_analysis_run_id"))

    op.drop_table("game_analysis_states")
    with op.batch_alter_table("import_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_import_runs_tracked_player_id"))

    op.drop_table("import_runs")
    with op.batch_alter_table("games", schema=None) as batch_op:
        batch_op.drop_index("ix_games_tracked_player_id_played_at")

    op.drop_table("games")
    with op.batch_alter_table("analysis_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_analysis_runs_tracked_player_id"))

    op.drop_table("analysis_runs")
    op.drop_table("tracked_players")
    op.drop_table("position_cache")
