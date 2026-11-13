"""Create the run attempts table for the rate limits

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_run_attempts"),
    )
    op.create_index(
        "ix_run_attempts_client_hash_created_at", "run_attempts", ["client_hash", "created_at"]
    )
    op.create_index("ix_run_attempts_created_at", "run_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_run_attempts_created_at", table_name="run_attempts")
    op.drop_index("ix_run_attempts_client_hash_created_at", table_name="run_attempts")
    op.drop_table("run_attempts")
