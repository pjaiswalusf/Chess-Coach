"""Persist automatic analysis requests and puzzle scan progress."""

import sqlalchemy as sa
from alembic import op

revision = "c25a001"
down_revision = "c19a001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "games",
        sa.Column(
            "auto_analysis_pending", sa.Boolean(), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "analysis_runs", sa.Column("puzzle_cursor", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "puzzle_cursor")
    op.drop_column("games", "auto_analysis_pending")
