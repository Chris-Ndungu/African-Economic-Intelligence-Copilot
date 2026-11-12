"""Add the run record and the error code and service to investigations

A run saves what it was asked and did (``run``), and a failed run saves why
(``error_code``, ``error_service``, with the message in ``error``), as
``api/openapi.yaml`` describes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("investigations", sa.Column("run", postgresql.JSONB(), nullable=True))
    op.add_column("investigations", sa.Column("error_code", sa.Text(), nullable=True))
    op.add_column("investigations", sa.Column("error_service", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("investigations", "error_service")
    op.drop_column("investigations", "error_code")
    op.drop_column("investigations", "run")
