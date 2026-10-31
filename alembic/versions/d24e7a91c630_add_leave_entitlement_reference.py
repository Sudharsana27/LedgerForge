"""Add leave entitlement references.

Revision ID: d24e7a91c630
Revises: a6c2f4d91e10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d24e7a91c630"
down_revision: Union[str, Sequence[str], None] = "a6c2f4d91e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("leave_requests")
    }
    if "entitlement_reference" not in columns:
        op.add_column(
            "leave_requests",
            sa.Column("entitlement_reference", sa.String(100), nullable=True),
        )


def downgrade() -> None:
    raise RuntimeError(
        "Leave entitlement references are retained to prevent data loss"
    )
