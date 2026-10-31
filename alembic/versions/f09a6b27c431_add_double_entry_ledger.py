"""Add chart of accounts and double-entry journal tables.

Revision ID: f09a6b27c431
Revises: c3f4a8d1027b
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f09a6b27c431"
down_revision: Union[str, Sequence[str], None] = "c3f4a8d1027b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chart_of_accounts",
        sa.Column("account_code", sa.String(length=20), nullable=False),
        sa.Column("account_name", sa.String(length=200), nullable=False),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("normal_balance", sa.String(length=10), nullable=False),
        sa.Column("parent_code", sa.String(length=20), nullable=True),
        sa.Column("is_group", sa.String(length=1), nullable=False),
        sa.Column("statement", sa.String(length=30), nullable=False),
        sa.Column("is_active", sa.String(length=1), nullable=False),
        sa.CheckConstraint(
            "account_type IN "
            "('ASSET', 'LIABILITY', 'EQUITY', 'INCOME', 'EXPENSE')",
            name="ck_chart_of_accounts_type",
        ),
        sa.CheckConstraint(
            "normal_balance IN ('DEBIT', 'CREDIT')",
            name="ck_chart_of_accounts_normal_balance",
        ),
        sa.CheckConstraint(
            "is_group IN ('Y', 'N')",
            name="ck_chart_of_accounts_is_group",
        ),
        sa.CheckConstraint(
            "is_active IN ('Y', 'N')",
            name="ck_chart_of_accounts_is_active",
        ),
        sa.ForeignKeyConstraint(
            ["parent_code"],
            ["chart_of_accounts.account_code"],
            name="fk_chart_of_accounts_parent_code_chart_of_accounts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("account_code"),
    )
    op.create_index(
        "ix_chart_of_accounts_parent_code",
        "chart_of_accounts",
        ["parent_code"],
    )
    op.create_table(
        "journal_entries",
        sa.Column("entry_id", sa.String(length=30), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("posting_period", sa.String(length=20), nullable=False),
        sa.Column("financial_year", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_debit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total_credit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("reversal_of_source_id", sa.String(length=100), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "total_debit = total_credit",
            name="ck_journal_entries_balanced_totals",
        ),
        sa.PrimaryKeyConstraint("entry_id"),
    )
    op.create_index(
        "ix_journal_entries_entry_date", "journal_entries", ["entry_date"]
    )
    op.create_table(
        "journal_lines",
        sa.Column("line_id", sa.String(length=30), nullable=False),
        sa.Column("entry_id", sa.String(length=30), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("account_code", sa.String(length=20), nullable=False),
        sa.Column("debit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("credit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "cost_center_department_id", sa.String(length=10), nullable=True
        ),
        sa.Column("line_description", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "line_no > 0", name="ck_journal_lines_positive_number"
        ),
        sa.CheckConstraint(
            "debit >= 0 AND credit >= 0",
            name="ck_journal_lines_nonnegative_amounts",
        ),
        sa.CheckConstraint(
            "(debit > 0 AND credit = 0) OR "
            "(credit > 0 AND debit = 0)",
            name="ck_journal_lines_one_sided_amount",
        ),
        sa.ForeignKeyConstraint(
            ["account_code"],
            ["chart_of_accounts.account_code"],
            name="fk_journal_lines_account_code_chart_of_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cost_center_department_id"],
            ["departments.department_id"],
            name="fk_journal_lines_cost_center_department_id_departments",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["journal_entries.entry_id"],
            name="fk_journal_lines_entry_id_journal_entries",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("line_id"),
        sa.UniqueConstraint(
            "entry_id",
            "line_no",
            name="uq_journal_lines_entry_line_no",
        ),
    )
    op.create_index(
        "ix_journal_lines_entry_id", "journal_lines", ["entry_id"]
    )
    op.create_index(
        "ix_journal_lines_account_code", "journal_lines", ["account_code"]
    )


def downgrade() -> None:
    op.drop_index("ix_journal_lines_account_code", table_name="journal_lines")
    op.drop_index("ix_journal_lines_entry_id", table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_index("ix_journal_entries_entry_date", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index(
        "ix_chart_of_accounts_parent_code", table_name="chart_of_accounts"
    )
    op.drop_table("chart_of_accounts")
