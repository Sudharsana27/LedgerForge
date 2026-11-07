"""Add Phase 3 workflows, credentials, and audit-ready finance models.

Revision ID: a390f1b6d2e8
Revises: e7c2d10f4b39
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from app.database import Base
from app import models


revision: str = "a390f1b6d2e8"
down_revision: Union[str, Sequence[str], None] = "e7c2d10f4b39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PHASE3_TABLES = (
    "vendors",
    "expenses",
    "users",
    "payroll_runs",
    "payroll_items",
    "tax_slabs",
    "tax_parameters",
    "statutory_rates",
    "tax_slab_audits",
)


def _add_missing_columns() -> None:
    additions = {
        "expenses": (
            ("submitted_at", sa.Column("submitted_at", sa.DateTime())),
            ("approved_at", sa.Column("approved_at", sa.DateTime())),
            ("paid_at", sa.Column("paid_at", sa.DateTime())),
            ("duplicate_key", sa.Column("duplicate_key", sa.String(64))),
        ),
        "users": (
            ("password_hash", sa.Column("password_hash", sa.String(255))),
        ),
        "tax_parameters": (
            ("effective_from", sa.Column("effective_from", sa.Date())),
        ),
        "payroll_runs": (
            (
                "processed_by",
                sa.Column(
                    "processed_by",
                    sa.String(20),
                    sa.ForeignKey(
                        "users.user_id",
                        name="fk_payroll_runs_processed_by_users",
                    ),
                ),
            ),
            ("processed_at", sa.Column("processed_at", sa.DateTime())),
            (
                "payment_journal_entry_id",
                sa.Column(
                    "payment_journal_entry_id",
                    sa.String(30),
                    sa.ForeignKey(
                        "journal_entries.entry_id",
                        name="fk_payroll_runs_payment_entry_journal_entries",
                    ),
                ),
            ),
            (
                "paid_by",
                sa.Column(
                    "paid_by",
                    sa.String(20),
                    sa.ForeignKey(
                        "users.user_id",
                        name="fk_payroll_runs_paid_by_users",
                    ),
                ),
            ),
            ("paid_at", sa.Column("paid_at", sa.DateTime())),
            (
                "reversal_journal_entry_id",
                sa.Column(
                    "reversal_journal_entry_id",
                    sa.String(30),
                    sa.ForeignKey(
                        "journal_entries.entry_id",
                        name="fk_payroll_runs_reversal_entry_journal_entries",
                    ),
                ),
            ),
            (
                "reversed_by",
                sa.Column(
                    "reversed_by",
                    sa.String(20),
                    sa.ForeignKey(
                        "users.user_id",
                        name="fk_payroll_runs_reversed_by_users",
                    ),
                ),
            ),
            ("reversed_at", sa.Column("reversed_at", sa.DateTime())),
        ),
    }
    bind = op.get_bind()
    inspector = inspect(bind)
    for table_name, columns in additions.items():
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        missing = [
            column
            for column_name, column in columns
            if column_name not in existing
        ]
        if missing:
            recreate = (
                "always"
                if bind.dialect.name == "sqlite"
                and any(column.foreign_keys for column in missing)
                else "auto"
            )
            with op.batch_alter_table(
                table_name,
                recreate=recreate,
            ) as batch_op:
                for column in missing:
                    batch_op.add_column(column)


def _ensure_unique_index(
    index_name: str,
    table_name: str,
    columns: tuple[str, ...],
) -> None:
    inspector = inspect(op.get_bind())
    target = list(columns)
    if any(
        index.get("unique") and index.get("column_names") == target
        for index in inspector.get_indexes(table_name)
    ):
        return
    if any(
        constraint.get("column_names") == target
        for constraint in inspector.get_unique_constraints(table_name)
    ):
        return
    op.create_index(index_name, table_name, list(columns), unique=True)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind,
        tables=[Base.metadata.tables[name] for name in PHASE3_TABLES],
        checkfirst=True,
    )
    _add_missing_columns()
    for index_name, table_name, columns in (
        ("uq_vendors_vendor_id", "vendors", ("vendor_id",)),
        ("uq_expenses_expense_id", "expenses", ("expense_id",)),
        ("uq_expenses_duplicate_key", "expenses", ("duplicate_key",)),
        ("uq_expenses_ledger_entry", "expenses", ("ledger_entry_id",)),
        (
            "uq_expenses_payment_ledger_entry",
            "expenses",
            ("payment_ledger_entry_id",),
        ),
        ("uq_users_user_id", "users", ("user_id",)),
        ("uq_users_username", "users", ("username",)),
        ("uq_users_employee_id", "users", ("employee_id",)),
        ("uq_payroll_runs_run_id", "payroll_runs", ("run_id",)),
        (
            "uq_payroll_runs_idempotency_key",
            "payroll_runs",
            ("idempotency_key",),
        ),
        (
            "uq_payroll_runs_journal_entry",
            "payroll_runs",
            ("journal_entry_id",),
        ),
        (
            "uq_payroll_runs_payment_entry",
            "payroll_runs",
            ("payment_journal_entry_id",),
        ),
        (
            "uq_payroll_runs_reversal_entry",
            "payroll_runs",
            ("reversal_journal_entry_id",),
        ),
        (
            "uq_payroll_items_run_employee",
            "payroll_items",
            ("run_id", "employee_id"),
        ),
        (
            "uq_statutory_rates_parameter_effective",
            "statutory_rates",
            ("parameter", "effective_from"),
        ),
        (
            "uq_tax_parameters_effective",
            "tax_parameters",
            ("parameter", "effective_from"),
        ),
        (
            "uq_tax_slabs_version",
            "tax_slabs",
            ("regime", "financial_year", "income_from", "effective_from"),
        ),
    ):
        _ensure_unique_index(index_name, table_name, columns)

    op.create_index(
        "uq_journal_payroll_source",
        "journal_entries",
        ["source_id"],
        unique=True,
        sqlite_where=sa.text("source_type = 'PAYROLL_RUN'"),
        postgresql_where=sa.text("source_type = 'PAYROLL_RUN'"),
    )
    op.create_index(
        "uq_journal_payroll_reversal_source",
        "journal_entries",
        ["source_id"],
        unique=True,
        sqlite_where=sa.text("source_type = 'PAYROLL_RUN_REVERSAL'"),
        postgresql_where=sa.text("source_type = 'PAYROLL_RUN_REVERSAL'"),
    )
    op.create_index(
        "uq_journal_expense_source",
        "journal_entries",
        ["source_id"],
        unique=True,
        sqlite_where=sa.text("source_type = 'EXPENSE_BILL'"),
        postgresql_where=sa.text("source_type = 'EXPENSE_BILL'"),
    )
    op.create_index(
        "uq_journal_expense_payment_source",
        "journal_entries",
        ["source_id"],
        unique=True,
        sqlite_where=sa.text("source_type = 'EXPENSE_BILL_PAYMENT'"),
        postgresql_where=sa.text("source_type = 'EXPENSE_BILL_PAYMENT'"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Phase 3 tables contain financial history and credentials; "
        "downgrade is intentionally blocked to prevent data loss."
    )
