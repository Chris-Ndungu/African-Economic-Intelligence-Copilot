"""Add the owner of an investigation

``owner`` keys an investigation to one visitor: ``anon:<id>`` for the
anonymous ID in the visitor's cookie, or a user identity once live-mode
login exists. Rows saved before this migration have no owner and are not
shown to anyone who is scoped to an owner.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("investigations", sa.Column("owner", sa.Text(), nullable=True))
    op.create_index("ix_investigations_owner_created_at", "investigations", ["owner", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_investigations_owner_created_at", table_name="investigations")
    op.drop_column("investigations", "owner")
