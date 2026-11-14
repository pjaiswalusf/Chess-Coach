"""Persist playable puzzle length and complete player attempts."""

import sqlalchemy as sa
from alembic import op

revision = "c26a001"
down_revision = "c25a001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "puzzles",
        sa.Column("solve_plies", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "puzzle_attempts", sa.Column("submitted_line_json", sa.JSON(), nullable=True)
    )
    # The existing worker can backfill newly eligible positions in bounded batches.
    op.execute(
        "UPDATE analysis_runs SET puzzle_cursor = 0 "
        "WHERE puzzle_cursor IS NULL AND games_completed > 0"
    )


def downgrade() -> None:
    op.drop_column("puzzle_attempts", "submitted_line_json")
    op.drop_column("puzzles", "solve_plies")
