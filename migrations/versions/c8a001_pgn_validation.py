"""Versioned parsing outcomes and retained source evidence on existing games."""

import sqlalchemy as sa
from alembic import op

revision = "c8a001"
down_revision = "c7a001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("source_evidence", sa.JSON(), nullable=True),
        sa.Column(
            "parse_status", sa.String(16), nullable=False, server_default="pending"
        ),
        sa.Column("parse_reason", sa.String(64), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.Integer(), nullable=True),
        sa.Column("chess_library_version", sa.String(32), nullable=True),
        sa.Column("parse_attempted_at", sa.DateTime(), nullable=True),
        sa.Column("parsed_metadata", sa.JSON(), nullable=True),
    ):
        op.add_column("games", column)
    op.create_index("ix_games_parse_status", "games", ["parse_status"])


def downgrade() -> None:
    op.drop_index("ix_games_parse_status", table_name="games")
    for name in (
        "parsed_metadata",
        "parse_attempted_at",
        "chess_library_version",
        "parser_version",
        "parse_error",
        "parse_reason",
        "parse_status",
        "source_evidence",
    ):
        op.drop_column("games", name)
