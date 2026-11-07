"""Archive checkpoints and import diagnostics.

Revision ID: c7a001
Revises: 9a638896c1a2
"""

import sqlalchemy as sa
from alembic import op

revision = "c7a001"
down_revision = "9a638896c1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("import_runs", sa.Column("summary_json", sa.JSON(), nullable=True))
    op.create_table(
        "archive_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tracked_player_id",
            sa.Integer(),
            sa.ForeignKey("tracked_players.id"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("last_successful_game_count", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("tracked_player_id", "year", "month"),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="valid_month"),
        sa.CheckConstraint("year BETWEEN 2007 AND 9999", name="valid_year"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'complete', 'failed', 'unavailable')",
            name="archive_status",
        ),
    )
    op.create_table(
        "import_rejections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "import_run_id",
            sa.Integer(),
            sa.ForeignKey("import_runs.id"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("record_index", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("raw_pgn", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("import_rejections")
    op.drop_table("archive_sync_state")
    op.drop_column("import_runs", "summary_json")
