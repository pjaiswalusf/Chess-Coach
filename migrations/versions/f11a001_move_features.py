"""Versioned offline move feature snapshots.

Revision ID: f11a001
Revises: 2f6cd65e0963
"""

import sqlalchemy as sa
from alembic import op

revision = "f11a001"
down_revision = "2f6cd65e0963"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "move_features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ply", sa.Integer(), nullable=False),
        sa.Column("feature_version", sa.Integer(), nullable=False),
        sa.Column("phase_classifier_version", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("played_is_capture", sa.Boolean(), nullable=False),
        sa.Column("played_gives_check", sa.Boolean(), nullable=False),
        sa.Column("played_is_castling", sa.Boolean(), nullable=False),
        sa.Column("material_balance_before", sa.Integer(), nullable=False),
        sa.Column("material_balance_after", sa.Integer(), nullable=False),
        sa.Column("engine_advantage_before", sa.String(32)),
        sa.Column("advantage_lost", sa.Boolean()),
        sa.Column("time_used_seconds", sa.Float()),
        sa.Column("under_time_pressure", sa.Boolean()),
        sa.Column("features_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("game_id", "ply", "feature_version", "input_hash"),
        sa.CheckConstraint("ply >= 1", name="ply_positive"),
        sa.CheckConstraint("feature_version >= 1", name="version_positive"),
    )
    op.create_index(
        "ix_move_features_snapshot",
        "move_features",
        ["game_id", "feature_version", "input_hash"],
    )


def downgrade() -> None:
    op.drop_table("move_features")
