"""persist puzzle training and attempts

Revision ID: c18a001
Revises: c15a001
Create Date: 2026-11-09 17:53:42.333567

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c18a001"
down_revision: str | Sequence[str] | None = "c15a001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "puzzles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracked_player_id", sa.Integer(), nullable=False),
        sa.Column("source_game_id", sa.Integer(), nullable=False),
        sa.Column("source_ply", sa.Integer(), nullable=False),
        sa.Column("source_analysis_version", sa.String(length=32), nullable=False),
        sa.Column("source_profile_hash", sa.String(length=64), nullable=False),
        sa.Column("fen", sa.Text(), nullable=False),
        sa.Column(
            "side_to_move",
            sa.Enum(
                "white",
                "black",
                name="side_to_move",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("original_move_uci", sa.String(length=5), nullable=False),
        sa.Column("solution_uci", sa.String(length=5), nullable=False),
        sa.Column("solution_pv_json", sa.JSON(), nullable=False),
        sa.Column("theme", sa.String(length=32), nullable=False),
        sa.Column("difficulty", sa.String(length=8), nullable=False),
        sa.Column("engine_version", sa.String(length=100), nullable=False),
        sa.Column("engine_config_hash", sa.String(length=64), nullable=False),
        sa.Column("verification_json", sa.JSON(), nullable=False),
        sa.Column("generator_version", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=8), server_default="active", nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("correct_streak", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_review_at", sa.DateTime(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')",
            name=op.f("ck_puzzles_valid_difficulty"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retired')", name=op.f("ck_puzzles_valid_status")
        ),
        sa.CheckConstraint(
            "(attempt_count = 0 AND last_attempt_at IS NULL) OR (attempt_count > 0 AND last_attempt_at IS NOT NULL AND next_review_at > last_attempt_at)",
            name=op.f("ck_puzzles_valid_review_state"),
        ),
        sa.CheckConstraint(
            "attempt_count >= correct_streak AND correct_streak >= 0",
            name=op.f("ck_puzzles_valid_counts"),
        ),
        sa.CheckConstraint(
            "original_move_uci != solution_uci",
            name=op.f("ck_puzzles_distinct_solution"),
        ),
        sa.CheckConstraint(
            "source_ply >= 1", name=op.f("ck_puzzles_source_ply_positive")
        ),
        sa.ForeignKeyConstraint(
            ["source_game_id"],
            ["games.id"],
            name=op.f("fk_puzzles_source_game_id_games"),
        ),
        sa.ForeignKeyConstraint(
            ["tracked_player_id"],
            ["tracked_players.id"],
            name=op.f("fk_puzzles_tracked_player_id_tracked_players"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_puzzles")),
        sa.UniqueConstraint(
            "tracked_player_id",
            "source_game_id",
            "source_ply",
            name=op.f("uq_puzzles_tracked_player_id"),
        ),
    )
    with op.batch_alter_table("puzzles", schema=None) as batch_op:
        batch_op.create_index(
            "ix_puzzles_due",
            ["tracked_player_id", "status", "next_review_at"],
            unique=False,
        )

    op.create_table(
        "puzzle_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("puzzle_id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.String(length=36), nullable=False),
        sa.Column("submitted_move_uci", sa.String(length=5), nullable=False),
        sa.Column(
            "is_correct",
            sa.Boolean(create_constraint=True, name="correct_boolean"),
            nullable=False,
        ),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("next_review_at_after", sa.DateTime(), nullable=False),
        sa.Column("scheduler_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "next_review_at_after > attempted_at",
            name=op.f("ck_puzzle_attempts_valid_review_time"),
        ),
        sa.ForeignKeyConstraint(
            ["puzzle_id"],
            ["puzzles.id"],
            name=op.f("fk_puzzle_attempts_puzzle_id_puzzles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_puzzle_attempts")),
        sa.UniqueConstraint(
            "puzzle_id", "submission_id", name=op.f("uq_puzzle_attempts_puzzle_id")
        ),
    )
    with op.batch_alter_table("puzzle_attempts", schema=None) as batch_op:
        batch_op.create_index(
            "ix_puzzle_attempts_history", ["puzzle_id", "attempted_at"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("puzzle_attempts", schema=None) as batch_op:
        batch_op.drop_index("ix_puzzle_attempts_history")

    op.drop_table("puzzle_attempts")
    with op.batch_alter_table("puzzles", schema=None) as batch_op:
        batch_op.drop_index("ix_puzzles_due")

    op.drop_table("puzzles")
