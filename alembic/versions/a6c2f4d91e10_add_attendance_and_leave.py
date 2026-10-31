"""Add typed attendance and leave tables.

Revision ID: a6c2f4d91e10
Revises: 081f56311621
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6c2f4d91e10"
down_revision: Union[str, Sequence[str], None] = "081f56311621"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = [
    {
        "name": "leave_types",
        "columns": [
            sa.Column("leave_type_code", sa.String(10), nullable=False),
            sa.Column("leave_type_name", sa.String(100), nullable=False),
            sa.Column("pay_type", sa.String(20), nullable=False),
            sa.Column("annual_quota_days", sa.Integer(), nullable=False),
            sa.Column("prorated_for_joiners", sa.String(1), nullable=False),
            sa.Column("carry_forward_allowed", sa.String(1), nullable=False),
            sa.Column("max_carry_forward_days", sa.Integer(), nullable=False),
            sa.Column("policy_note", sa.String(300), nullable=False),
        ],
        "primary_key": ["leave_type_code"],
        "foreign_keys": [],
    },
    {
        "name": "holidays",
        "columns": [
            sa.Column("holiday_date", sa.Date(), nullable=False),
            sa.Column("holiday_name", sa.String(150), nullable=False),
            sa.Column("holiday_type", sa.String(30), nullable=False),
            sa.Column("weekday", sa.String(15), nullable=False),
            sa.Column("falls_on_weekend", sa.String(1), nullable=False),
            sa.Column("calendar_note", sa.String(300), nullable=False),
        ],
        "primary_key": ["holiday_date"],
        "foreign_keys": [],
    },
    {
        "name": "attendance",
        "columns": [
            sa.Column("attendance_id", sa.String(20), nullable=False),
            sa.Column("employee_id", sa.String(20), nullable=False),
            sa.Column("attendance_date", sa.Date(), nullable=False),
            sa.Column("weekday", sa.String(10), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("leave_type_code", sa.String(10), nullable=True),
            sa.Column("check_in", sa.String(5), nullable=True),
            sa.Column("check_out", sa.String(5), nullable=True),
            sa.Column("hours_worked", sa.Numeric(7, 2), nullable=True),
            sa.Column("overtime_hours", sa.Numeric(7, 2), nullable=True),
            sa.Column("late_flag", sa.String(1), nullable=True),
            sa.Column("source", sa.String(100), nullable=False),
            sa.Column("data_quality_flag", sa.String(50), nullable=True),
            sa.Column("department_id", sa.String(10), nullable=False),
        ],
        "primary_key": ["attendance_id"],
        "foreign_keys": [
            ("employee_id", "employees", "employee_id"),
            ("leave_type_code", "leave_types", "leave_type_code"),
            ("department_id", "departments", "department_id"),
        ],
    },
    {
        "name": "leave_balances",
        "columns": [
            sa.Column("employee_id", sa.String(20), nullable=False),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("financial_year", sa.String(20), nullable=False),
            sa.Column("cl_entitlement", sa.Numeric(7, 2), nullable=False),
            sa.Column("cl_used", sa.Numeric(7, 2), nullable=False),
            sa.Column("cl_balance", sa.Numeric(7, 2), nullable=False),
            sa.Column("sl_entitlement", sa.Numeric(7, 2), nullable=False),
            sa.Column("sl_used", sa.Numeric(7, 2), nullable=False),
            sa.Column("sl_balance", sa.Numeric(7, 2), nullable=False),
            sa.Column("el_used_fy", sa.Numeric(7, 2), nullable=False),
            sa.Column("el_balance", sa.Numeric(7, 2), nullable=False),
            sa.Column("pending_days", sa.Numeric(7, 2), nullable=False),
        ],
        "primary_key": ["employee_id", "financial_year"],
        "foreign_keys": [("employee_id", "employees", "employee_id")],
    },
    {
        "name": "leave_requests",
        "columns": [
            sa.Column("leave_request_id", sa.String(20), nullable=False),
            sa.Column("employee_id", sa.String(20), nullable=False),
            sa.Column("leave_type_code", sa.String(10), nullable=False),
            sa.Column("entitlement_reference", sa.String(100), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("days", sa.Numeric(7, 2), nullable=False),
            sa.Column("reason", sa.String(300), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("applied_on", sa.Date(), nullable=False),
            sa.Column("approver_id", sa.String(20), nullable=True),
            sa.Column("decided_on", sa.Date(), nullable=True),
        ],
        "primary_key": ["leave_request_id"],
        "foreign_keys": [
            ("employee_id", "employees", "employee_id"),
            ("leave_type_code", "leave_types", "leave_type_code"),
            ("approver_id", "employees", "employee_id"),
        ],
        "checks": [("end_date >= start_date", "ck_leave_request_date_range")],
    },
]


INDEXES = [
    ("ix_attendance_employee_date", "attendance", ["employee_id", "attendance_date"]),
    (
        "ix_leave_requests_employee_dates",
        "leave_requests",
        ["employee_id", "start_date", "end_date"],
    ),
    ("ix_leave_requests_status", "leave_requests", ["status"]),
]


def _validate_legacy_table(definition, bind):
    name = definition["name"]
    key_columns = definition["primary_key"]
    key_sql = ", ".join(f'"{column}"' for column in key_columns)
    duplicate = bind.execute(
        sa.text(
            f'SELECT 1 FROM "{name}" GROUP BY {key_sql} '
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            f"Cannot safely add the primary key to {name}: duplicate keys exist"
        )

    required = [
        column.name
        for column in definition["columns"]
        if not column.nullable
    ]
    for column in required:
        null_row = bind.execute(
            sa.text(
                f'SELECT 1 FROM "{name}" WHERE "{column}" IS NULL LIMIT 1'
            )
        ).first()
        if null_row is not None:
            raise RuntimeError(
                f"Cannot safely make {name}.{column} required: NULL values exist"
            )

    for column, parent, parent_column in definition["foreign_keys"]:
        orphan = bind.execute(
            sa.text(
                f'SELECT 1 FROM "{name}" child '
                f'LEFT JOIN "{parent}" parent '
                f'ON child."{column}" = parent."{parent_column}" '
                f'WHERE child."{column}" IS NOT NULL '
                f'AND parent."{parent_column}" IS NULL LIMIT 1'
            )
        ).first()
        if orphan is not None:
            raise RuntimeError(
                f"Cannot safely add the {name}.{column} foreign key: "
                "orphan references exist"
            )


def _upgrade_existing_table(definition, bind):
    name = definition["name"]
    inspector = sa.inspect(bind)
    actual_columns = {
        column["name"]: column
        for column in inspector.get_columns(name)
    }
    expected_names = {column.name for column in definition["columns"]}
    optional_names = (
        {"entitlement_reference"} if name == "leave_requests" else set()
    )
    if not expected_names - optional_names <= set(actual_columns):
        raise RuntimeError(
            f"Existing {name} schema does not match the LF-06 source columns"
        )
    if set(actual_columns) - expected_names:
        raise RuntimeError(
            f"Existing {name} schema does not match the LF-06 source columns"
        )

    actual_pk = inspector.get_pk_constraint(name).get("constrained_columns") or []
    actual_fks = {
        (fk["constrained_columns"][0], fk["referred_table"], fk["referred_columns"][0])
        for fk in inspector.get_foreign_keys(name)
        if len(fk["constrained_columns"]) == 1
        and len(fk["referred_columns"]) == 1
    }
    expected_fks = set(definition["foreign_keys"])
    actual_checks = {
        check["name"]
        for check in inspector.get_check_constraints(name)
    }
    expected_checks = {
        constraint_name
        for _, constraint_name in definition.get("checks", [])
    }
    needs_rebuild = actual_pk != definition["primary_key"]
    needs_rebuild = needs_rebuild or set(actual_columns) != expected_names
    needs_rebuild = needs_rebuild or not expected_fks.issubset(actual_fks)
    needs_rebuild = needs_rebuild or not expected_checks.issubset(actual_checks)
    for column in definition["columns"]:
        if column.name not in actual_columns:
            needs_rebuild = True
            continue
        actual = actual_columns[column.name]
        needs_rebuild = needs_rebuild or type(actual["type"]) is not type(column.type)
        needs_rebuild = needs_rebuild or (
            actual["nullable"] != column.nullable
        )

    if not needs_rebuild:
        return

    _validate_legacy_table(definition, bind)
    with op.batch_alter_table(name, recreate="always") as batch:
        for column in definition["columns"]:
            if column.name not in actual_columns:
                batch.add_column(column.copy())
                continue
            actual = actual_columns[column.name]
            batch.alter_column(
                column.name,
                existing_type=actual["type"],
                type_=column.type,
                existing_nullable=actual["nullable"],
                nullable=column.nullable,
            )
        if actual_pk != definition["primary_key"]:
            batch.create_primary_key(
                f"pk_{name}", definition["primary_key"]
            )
        for column, parent, parent_column in definition["foreign_keys"]:
            if (column, parent, parent_column) not in actual_fks:
                batch.create_foreign_key(
                    f"fk_{name}_{column}_{parent}",
                    parent,
                    [column],
                    [parent_column],
                )
        for condition, constraint_name in definition.get("checks", []):
            if constraint_name not in actual_checks:
                batch.create_check_constraint(constraint_name, condition)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for definition in TABLES:
        name = definition["name"]
        columns = list(definition["columns"])
        constraints = [
            sa.PrimaryKeyConstraint(
                *definition["primary_key"],
                name=f"pk_{name}",
            )
        ]
        constraints.extend(
            sa.ForeignKeyConstraint(
                [column],
                [f"{parent}.{parent_column}"],
                name=f"fk_{name}_{column}_{parent}",
            )
            for column, parent, parent_column in definition["foreign_keys"]
        )
        constraints.extend(
            sa.CheckConstraint(condition, name=constraint_name)
            for condition, constraint_name in definition.get("checks", [])
        )

        if name not in existing:
            op.create_table(name, *columns, *constraints)
        else:
            _upgrade_existing_table(definition, bind)

    existing_indexes = {
        (table, index["name"])
        for table in (definition["name"] for definition in TABLES)
        for index in sa.inspect(bind).get_indexes(table)
    }
    for index_name, table, columns in INDEXES:
        if (table, index_name) not in existing_indexes:
            op.create_index(index_name, table, columns, unique=False)


def downgrade() -> None:
    raise RuntimeError(
        "LF-06 downgrade is disabled to prevent deleting attendance and leave data"
    )
