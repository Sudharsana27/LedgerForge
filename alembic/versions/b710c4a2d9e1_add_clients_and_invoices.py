"""Add clients, invoices, invoice items, and invoice payments.

Revision ID: b710c4a2d9e1
Revises: f09a6b27c431
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b710c4a2d9e1"
down_revision: Union[str, Sequence[str], None] = "f09a6b27c431"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("client_id", sa.String(length=20), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=False),
        sa.Column("industry", sa.String(length=100), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("state_or_region", sa.String(length=100), nullable=False),
        sa.Column("country", sa.String(length=3), nullable=False),
        sa.Column("client_type", sa.String(length=20), nullable=False),
        sa.Column("gst_registration", sa.String(length=30), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False),
        sa.Column("payment_behaviour", sa.String(length=30), nullable=False),
        sa.Column("primary_service_line", sa.String(length=20), nullable=False),
        sa.Column("contact_email", sa.String(length=255), nullable=False),
        sa.Column("onboarded_on", sa.Date(), nullable=False),
        sa.Column("is_active", sa.String(length=1), nullable=False),
        sa.CheckConstraint(
            "client_type IN ('DOMESTIC', 'EXPORT')",
            name="ck_clients_client_type",
        ),
        sa.CheckConstraint(
            "payment_terms_days >= 0",
            name="ck_clients_nonnegative_payment_terms",
        ),
        sa.CheckConstraint(
            "is_active IN ('Y', 'N')",
            name="ck_clients_is_active",
        ),
        sa.ForeignKeyConstraint(
            ["primary_service_line"],
            ["chart_of_accounts.account_code"],
            name="fk_clients_primary_service_line_chart_of_accounts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("client_id"),
    )
    op.create_index("ix_clients_client_name", "clients", ["client_name"])
    op.create_index("ix_clients_is_active", "clients", ["is_active"])

    op.create_table(
        "invoices",
        sa.Column("invoice_id", sa.String(length=30), nullable=False),
        sa.Column("invoice_number", sa.String(length=40), nullable=False),
        sa.Column("client_id", sa.String(length=20), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("service_line_account", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "gst_rate_percent", sa.Numeric(precision=7, scale=4), nullable=False
        ),
        sa.Column("gst_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "total_amount", sa.Numeric(precision=18, scale=2), nullable=False
        ),
        sa.Column("amount_paid", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("balance_due", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_payment_date", sa.Date(), nullable=True),
        sa.Column("po_number", sa.String(length=50), nullable=True),
        sa.Column(
            "carried_in_from_prior_period", sa.String(length=1), nullable=False
        ),
        sa.Column("created_by", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ledger_entry_id", sa.String(length=30), nullable=True),
        sa.CheckConstraint(
            "status IN "
            "('DRAFT', 'SENT', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', "
            "'CANCELLED')",
            name="ck_invoices_status",
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND gst_amount >= 0 AND total_amount >= 0 "
            "AND amount_paid >= 0 AND balance_due >= 0",
            name="ck_invoices_nonnegative_amounts",
        ),
        sa.CheckConstraint(
            "gst_rate_percent >= 0",
            name="ck_invoices_nonnegative_gst_rate",
        ),
        sa.CheckConstraint(
            "total_amount = subtotal + gst_amount",
            name="ck_invoices_total_matches_components",
        ),
        sa.CheckConstraint(
            "amount_paid <= total_amount AND balance_due <= total_amount",
            name="ck_invoices_paid_and_balance_within_total",
        ),
        sa.CheckConstraint(
            "carried_in_from_prior_period IN ('Y', 'N')",
            name="ck_invoices_carried_in_flag",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.client_id"],
            name="fk_invoices_client_id_clients",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ledger_entry_id"],
            ["journal_entries.entry_id"],
            name="fk_invoices_ledger_entry_id_journal_entries",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_line_account"],
            ["chart_of_accounts.account_code"],
            name="fk_invoices_service_line_account_chart_of_accounts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("invoice_id"),
        sa.UniqueConstraint("invoice_number", name="uq_invoices_invoice_number"),
        sa.UniqueConstraint(
            "ledger_entry_id", name="uq_invoices_ledger_entry_id"
        ),
    )
    op.create_index("ix_invoices_client_id", "invoices", ["client_id"])
    op.create_index(
        "ix_invoices_status_due_date", "invoices", ["status", "due_date"]
    )
    op.create_index("ix_invoices_invoice_date", "invoices", ["invoice_date"])

    op.create_table(
        "invoice_items",
        sa.Column("invoice_item_id", sa.String(length=30), nullable=False),
        sa.Column("invoice_id", sa.String(length=30), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("revenue_account", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "line_no > 0", name="ck_invoice_items_positive_line_number"
        ),
        sa.CheckConstraint(
            "quantity > 0 AND unit_price >= 0 AND amount >= 0",
            name="ck_invoice_items_nonnegative_values",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.invoice_id"],
            name="fk_invoice_items_invoice_id_invoices",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revenue_account"],
            ["chart_of_accounts.account_code"],
            name="fk_invoice_items_revenue_account_chart_of_accounts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("invoice_item_id"),
        sa.UniqueConstraint(
            "invoice_id",
            "line_no",
            name="uq_invoice_items_invoice_line_no",
        ),
    )
    op.create_index(
        "ix_invoice_items_invoice_id", "invoice_items", ["invoice_id"]
    )
    op.create_index(
        "ix_invoice_items_revenue_account",
        "invoice_items",
        ["revenue_account"],
    )

    op.create_table(
        "invoice_payments",
        sa.Column("payment_id", sa.String(length=30), nullable=False),
        sa.Column("invoice_id", sa.String(length=30), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("payment_mode", sa.String(length=30), nullable=False),
        sa.Column("reference_no", sa.String(length=50), nullable=False),
        sa.Column("received_by", sa.String(length=30), nullable=False),
        sa.Column("ledger_entry_id", sa.String(length=30), nullable=False),
        sa.CheckConstraint(
            "amount > 0", name="ck_invoice_payments_positive_amount"
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.invoice_id"],
            name="fk_invoice_payments_invoice_id_invoices",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ledger_entry_id"],
            ["journal_entries.entry_id"],
            name="fk_invoice_payments_ledger_entry_id_journal_entries",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("payment_id"),
        sa.UniqueConstraint(
            "ledger_entry_id", name="uq_invoice_payments_ledger_entry_id"
        ),
    )
    op.create_index(
        "ix_invoice_payments_invoice_date",
        "invoice_payments",
        ["invoice_id", "payment_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_invoice_payments_invoice_date", table_name="invoice_payments"
    )
    op.drop_table("invoice_payments")
    op.drop_index(
        "ix_invoice_items_revenue_account", table_name="invoice_items"
    )
    op.drop_index("ix_invoice_items_invoice_id", table_name="invoice_items")
    op.drop_table("invoice_items")
    op.drop_index("ix_invoices_invoice_date", table_name="invoices")
    op.drop_index("ix_invoices_status_due_date", table_name="invoices")
    op.drop_index("ix_invoices_client_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_clients_is_active", table_name="clients")
    op.drop_index("ix_clients_client_name", table_name="clients")
    op.drop_table("clients")
