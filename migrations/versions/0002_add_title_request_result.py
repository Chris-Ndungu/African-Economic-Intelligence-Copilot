"""Add title, request and result to investigations

The API saves and returns an investigation's title, its request and its
full result (``api/openapi.yaml``). ``findings``, ``sources`` and
``chart_config`` stay, holding parts of the result for querying.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "investigations",
        sa.Column("title", sa.Text(), server_default=sa.text("''"), nullable=False),
    )
    op.add_column("investigations", sa.Column("request", postgresql.JSONB(), nullable=True))
    op.add_column("investigations", sa.Column("result", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("investigations", "result")
    op.drop_column("investigations", "request")
    op.drop_column("investigations", "title")
