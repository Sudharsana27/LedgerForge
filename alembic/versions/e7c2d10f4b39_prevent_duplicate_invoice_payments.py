"""Prevent duplicate payment references for an invoice.

Revision ID: e7c2d10f4b39
Revises: b710c4a2d9e1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7c2d10f4b39"
down_revision: Union[str, Sequence[str], None] = "b710c4a2d9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT invoice_id, reference_no "
            "FROM invoice_payments "
            "GROUP BY invoice_id, reference_no "
            "HAVING COUNT(*) > 1 "
            "LIMIT 1"
        )
    ).first()
    if duplicates is not None:
        raise RuntimeError(
            "Cannot prevent duplicate invoice payment references until "
            f"duplicate data is reconciled for invoice {duplicates.invoice_id}."
        )
    op.create_index(
        "uq_invoice_payments_invoice_reference",
        "invoice_payments",
        ["invoice_id", "reference_no"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_invoice_payments_invoice_reference",
        table_name="invoice_payments",
    )
