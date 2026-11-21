"""Add incremental employee tracking and export/query indexes.

Revision ID: 6f2b18d4a731
Revises: a82d6401f5c3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6f2b18d4a731"
down_revision: Union[str, Sequence[str], None] = "a82d6401f5c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "salary_components" not in table_names:
        op.create_table(
            "salary_components",
            sa.Column("component_id", sa.String(20), nullable=False),
            sa.Column("component_name", sa.String(100), nullable=False),
            sa.Column("component_type", sa.String(30), nullable=False),
            sa.Column("taxable", sa.String(1), nullable=False),
            sa.Column("calculation_rule", sa.String(200), nullable=False),
            sa.Column("is_fixed", sa.String(1), nullable=False),
            sa.PrimaryKeyConstraint("component_id"),
        )
    if "salary_revisions" not in table_names:
        op.create_table(
            "salary_revisions",
            sa.Column("revision_id", sa.String(20), nullable=False),
            sa.Column("employee_id", sa.String(20), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("revision_reason", sa.String(100), nullable=False),
            sa.Column("previous_annual_fixed", sa.Numeric(14, 2), nullable=True),
            sa.Column("new_annual_fixed", sa.Numeric(14, 2), nullable=False),
            sa.Column("pct_change", sa.Numeric(7, 3), nullable=True),
            sa.Column("role_id_after", sa.String(10), nullable=False),
            sa.Column("approved_by", sa.String(20), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["employee_id"], ["employees.employee_id"]),
            sa.ForeignKeyConstraint(["role_id_after"], ["roles.role_id"]),
            sa.PrimaryKeyConstraint("revision_id"),
        )
        op.create_index(
            "ix_salary_revisions_employee_effective",
            "salary_revisions",
            ["employee_id", "effective_from"],
        )
    if "salary_structures" not in table_names:
        op.create_table(
            "salary_structures",
            sa.Column("structure_id", sa.String(20), nullable=False),
            sa.Column("employee_id", sa.String(20), nullable=False),
            sa.Column("component_id", sa.String(20), nullable=False),
            sa.Column("component_name", sa.String(100), nullable=False),
            sa.Column("component_type", sa.String(30), nullable=False),
            sa.Column("monthly_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("revision_id", sa.String(20), nullable=False),
            sa.ForeignKeyConstraint(["employee_id"], ["employees.employee_id"]),
            sa.ForeignKeyConstraint(["component_id"], ["salary_components.component_id"]),
            sa.ForeignKeyConstraint(["revision_id"], ["salary_revisions.revision_id"]),
            sa.PrimaryKeyConstraint("structure_id"),
        )
        op.create_index(
            "ix_salary_structure_employee_dates",
            "salary_structures",
            ["employee_id", "effective_from", "effective_to"],
        )
    employee_columns = {
        column["name"] for column in inspector.get_columns("employees")
    }
    if "updated_at" not in employee_columns:
        op.add_column(
            "employees",
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    index_specs = (
        ("employees", "ix_employees_created_at", ["created_at"]),
        ("employees", "ix_employees_updated_at", ["updated_at"]),
        ("journal_entries", "ix_journal_entries_created_at", ["created_at"]),
        ("payroll_runs", "ix_payroll_runs_created_at", ["created_at"]),
        (
            "payroll_items",
            "ix_payroll_items_period_run",
            ["period_start", "period_end", "run_id"],
        ),
    )
    for table_name, index_name, columns in index_specs:
        existing = {
            index["name"] for index in inspector.get_indexes(table_name)
        }
        if index_name not in existing:
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    op.drop_index("ix_payroll_items_period_run", table_name="payroll_items")
    op.drop_index("ix_payroll_runs_created_at", table_name="payroll_runs")
    op.drop_index("ix_journal_entries_created_at", table_name="journal_entries")
    op.drop_index("ix_employees_updated_at", table_name="employees")
    op.drop_index("ix_employees_created_at", table_name="employees")
    op.drop_column("employees", "updated_at")
    if sa.inspect(op.get_bind()).has_table("salary_structures"):
        op.drop_index(
            "ix_salary_structure_employee_dates",
            table_name="salary_structures",
        )
        op.drop_table("salary_structures")
    if sa.inspect(op.get_bind()).has_table("salary_revisions"):
        op.drop_index(
            "ix_salary_revisions_employee_effective",
            table_name="salary_revisions",
        )
        op.drop_table("salary_revisions")
    if sa.inspect(op.get_bind()).has_table("salary_components"):
        op.drop_table("salary_components")
