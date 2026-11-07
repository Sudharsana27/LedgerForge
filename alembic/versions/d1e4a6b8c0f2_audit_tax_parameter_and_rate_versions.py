"""Audit effective-dated tax parameter and statutory rate changes."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e4a6b8c0f2"
down_revision: Union[str, Sequence[str], None] = "a390f1b6d2e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tax_parameter_audits",
        sa.Column("audit_id", sa.String(length=36), primary_key=True),
        sa.Column("parameter", sa.String(length=100), nullable=False),
        sa.Column("previous_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("new_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column(
            "changed_by",
            sa.String(length=20),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_tax_parameter_audits_parameter_effective",
        "tax_parameter_audits",
        ["parameter", "effective_from"],
    )
    op.create_table(
        "statutory_rate_audits",
        sa.Column("audit_id", sa.String(length=36), primary_key=True),
        sa.Column("parameter", sa.String(length=100), nullable=False),
        sa.Column("previous_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("new_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column(
            "changed_by",
            sa.String(length=20),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_statutory_rate_audits_parameter_effective",
        "statutory_rate_audits",
        ["parameter", "effective_from"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Tax configuration audit history is append-only; "
        "downgrade is intentionally blocked."
    )
