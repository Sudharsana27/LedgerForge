"""create initial organization schema

Revision ID: 081f56311621
Revises: 4f91d6a3d0d5
Create Date: 2026-10-23 10:19:59.320485

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '081f56311621'
down_revision: Union[str, Sequence[str], None] = '4f91d6a3d0d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "departments" not in existing:
        op.create_table(
            "departments",
            sa.Column("department_id", sa.String(10), nullable=False),
            sa.Column("department_name", sa.String(100), nullable=False),
            sa.Column("cost_center", sa.String(20), nullable=False),
            sa.Column("description", sa.String(300), nullable=True),
            sa.PrimaryKeyConstraint("department_id"),
        )
    if "roles" not in existing:
        op.create_table(
            "roles",
            sa.Column("role_id", sa.String(10), nullable=False),
            sa.Column("department_id", sa.String(10), nullable=False),
            sa.Column("role_title", sa.String(150), nullable=False),
            sa.Column("level", sa.Integer(), nullable=False),
            sa.Column("grade", sa.String(50), nullable=False),
            sa.Column("band_min_annual", sa.Integer(), nullable=False),
            sa.Column("band_mid_annual", sa.Integer(), nullable=False),
            sa.Column("band_max_annual", sa.Integer(), nullable=False),
            sa.Column("overtime_eligible", sa.String(1), nullable=False),
            sa.Column("band_year", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["department_id"], ["departments.department_id"]
            ),
            sa.PrimaryKeyConstraint("role_id"),
        )
    if "employees" not in existing:
        op.create_table(
            "employees",
            sa.Column("employee_id", sa.String(20), nullable=False),
            sa.Column("first_name", sa.String(100), nullable=False),
            sa.Column("last_name", sa.String(100), nullable=False),
            sa.Column("full_name", sa.String(200), nullable=False),
            sa.Column("work_email", sa.String(255), nullable=False),
            sa.Column("gender", sa.String(20), nullable=True),
            sa.Column("date_of_birth", sa.Date(), nullable=True),
            sa.Column("hire_date", sa.Date(), nullable=False),
            sa.Column("exit_date", sa.Date(), nullable=True),
            sa.Column("employment_status", sa.String(30), nullable=False),
            sa.Column("employment_type", sa.String(30), nullable=False),
            sa.Column("department_id", sa.String(10), nullable=False),
            sa.Column("role_id", sa.String(10), nullable=False),
            sa.Column("manager_id", sa.String(20), nullable=True),
            sa.Column("work_location", sa.String(100), nullable=False),
            sa.Column("work_mode", sa.String(30), nullable=False),
            sa.Column("highest_education", sa.String(150), nullable=True),
            sa.Column("prior_experience_years", sa.Double(), nullable=True),
            sa.Column("career_gap_months", sa.Integer(), nullable=True),
            sa.Column("commute_distance_km", sa.Double(), nullable=True),
            sa.Column("pf_applicable", sa.String(1), nullable=False),
            sa.Column("esi_applicable", sa.String(1), nullable=False),
            sa.Column("notice_period_days", sa.Integer(), nullable=False),
            sa.Column("resignation_date", sa.Date(), nullable=True),
            sa.Column("exit_type", sa.String(50), nullable=True),
            sa.Column("exit_reason", sa.String(200), nullable=True),
            sa.Column("created_at", sa.Date(), nullable=True),
            sa.ForeignKeyConstraint(
                ["department_id"], ["departments.department_id"]
            ),
            sa.ForeignKeyConstraint(["manager_id"], ["employees.employee_id"]),
            sa.ForeignKeyConstraint(["role_id"], ["roles.role_id"]),
            sa.PrimaryKeyConstraint("employee_id"),
            sa.UniqueConstraint("work_email"),
        )
    if "employees" in set(sa.inspect(op.get_bind()).get_table_names()):
        indexes = {
            index["name"]
            for index in sa.inspect(op.get_bind()).get_indexes("employees")
        }
        for name, column in (
            ("ix_employees_department_id", "department_id"),
            ("ix_employees_manager_id", "manager_id"),
        ):
            if name not in indexes:
                op.create_index(name, "employees", [column], unique=False)
    if "employee_assignments" not in existing:
        op.create_table(
            "employee_assignments",
            sa.Column("assignment_id", sa.String(20), nullable=False),
            sa.Column("employee_id", sa.String(20), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("department_id", sa.String(10), nullable=False),
            sa.Column("role_id", sa.String(10), nullable=False),
            sa.Column("job_level", sa.Integer(), nullable=False),
            sa.Column("manager_id", sa.String(20), nullable=True),
            sa.Column("change_reason", sa.String(100), nullable=False),
            sa.ForeignKeyConstraint(["department_id"], ["departments.department_id"]),
            sa.ForeignKeyConstraint(["employee_id"], ["employees.employee_id"]),
            sa.ForeignKeyConstraint(["manager_id"], ["employees.employee_id"]),
            sa.ForeignKeyConstraint(["role_id"], ["roles.role_id"]),
            sa.PrimaryKeyConstraint("assignment_id"),
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade of the organization schema is disabled because upgrade "
        "may adopt pre-existing tables and cannot safely determine ownership"
    )
