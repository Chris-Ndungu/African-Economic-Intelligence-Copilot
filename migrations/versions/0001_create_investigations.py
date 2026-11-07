"""Create the investigations table

Revision ID: 0001
Revises:
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Sets updated_at on every UPDATE, whichever client runs it. clock_timestamp()
# rather than now(), so an update in the same transaction as the insert
# still moves updated_at forward.
SET_UPDATED_AT = """
CREATE FUNCTION investigations_set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$
"""

UPDATED_AT_TRIGGER = """
CREATE TRIGGER investigations_set_updated_at
BEFORE UPDATE ON investigations
FOR EACH ROW EXECUTE FUNCTION investigations_set_updated_at()
"""


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("selections", postgresql.JSONB(), nullable=False),
        sa.Column(
            "parameters",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "findings",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("chart_config", postgresql.JSONB(), nullable=True),
        sa.Column(
            "sources",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("data_mode", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "data_mode IN ('demo', 'live')",
            name=op.f("ck_investigations_data_mode"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name=op.f("ck_investigations_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investigations")),
    )
    op.create_index(
        "ix_investigations_created_at_id",
        "investigations",
        [sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )
    op.execute(SET_UPDATED_AT)
    op.execute(UPDATED_AT_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER investigations_set_updated_at ON investigations")
    op.execute("DROP FUNCTION investigations_set_updated_at()")
    op.drop_index("ix_investigations_created_at_id", table_name="investigations")
    op.drop_table("investigations")
