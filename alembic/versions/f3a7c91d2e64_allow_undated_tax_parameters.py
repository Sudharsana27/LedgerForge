"""Allow undated base tax parameters while retaining version identity."""
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "f3a7c91d2e64"
down_revision: Union[str, Sequence[str], None] = "d1e4a6b8c0f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "tax_parameters" not in inspector.get_table_names():
        return

    columns = {
        column["name"]: column
        for column in inspector.get_columns("tax_parameters")
    }
    if "tax_parameter_id" not in columns:
        op.add_column(
            "tax_parameters",
            sa.Column("tax_parameter_id", sa.String(36), nullable=True),
        )
        if bind.dialect.name == "sqlite":
            row_ids = bind.execute(
                sa.text("SELECT rowid FROM tax_parameters")
            ).scalars().all()
            for row_id in row_ids:
                bind.execute(
                    sa.text(
                        "UPDATE tax_parameters "
                        "SET tax_parameter_id = :parameter_id "
                        "WHERE rowid = :row_id"
                    ),
                    {
                        "parameter_id": str(uuid4()),
                        "row_id": row_id,
                    },
                )
        else:
            primary_key = inspect(bind).get_pk_constraint("tax_parameters")
            primary_key_columns = primary_key.get("constrained_columns") or []
            if not primary_key_columns:
                raise RuntimeError(
                    "Cannot safely assign tax parameter identities without "
                    "a primary key."
                )
            table = sa.table(
                "tax_parameters",
                *(
                    sa.column(name, columns[name]["type"])
                    for name in primary_key_columns
                ),
                sa.column("tax_parameter_id", sa.String(36)),
            )
            rows = bind.execute(
                sa.select(
                    *(table.c[name] for name in primary_key_columns)
                )
            ).all()
            for primary_key_values in rows:
                condition = sa.and_(
                    *(
                        table.c[name].is_(value)
                        if value is None
                        else table.c[name] == value
                        for name, value in zip(
                            primary_key_columns, primary_key_values
                        )
                    )
                )
                bind.execute(
                    table.update()
                    .where(condition)
                    .values(tax_parameter_id=str(uuid4()))
                )

    primary_key = inspect(bind).get_pk_constraint("tax_parameters")
    primary_key_columns = primary_key.get("constrained_columns") or []
    effective_from_column = next(
        column
        for column in inspect(bind).get_columns("tax_parameters")
        if column["name"] == "effective_from"
    )
    if (
        primary_key_columns != ["tax_parameter_id"]
        or not effective_from_column["nullable"]
    ):
        with op.batch_alter_table(
            "tax_parameters",
            recreate="always",
            naming_convention={"pk": "pk_%(table_name)s"},
        ) as batch:
            if primary_key_columns:
                batch.drop_constraint(
                    primary_key.get("name") or "pk_tax_parameters",
                    type_="primary",
                )
            batch.alter_column(
                "tax_parameter_id",
                existing_type=sa.String(36),
                nullable=False,
            )
            batch.alter_column(
                "effective_from",
                existing_type=sa.Date(),
                nullable=True,
            )
            if primary_key_columns != ["tax_parameter_id"]:
                batch.create_primary_key(
                    "pk_tax_parameters",
                    ["tax_parameter_id"],
                )

    inspector = inspect(bind)
    unique_pair = ["parameter", "effective_from"]
    has_unique_pair = any(
        index["unique"] and index["column_names"] == unique_pair
        for index in inspector.get_indexes("tax_parameters")
    ) or any(
        constraint["column_names"] == unique_pair
        for constraint in inspector.get_unique_constraints("tax_parameters")
    )
    if not has_unique_pair:
        op.create_index(
            "uq_tax_parameters_effective",
            "tax_parameters",
            unique_pair,
            unique=True,
        )


def downgrade() -> None:
    raise RuntimeError(
        "Undated tax parameter values are valid source data; "
        "this migration is intentionally irreversible."
    )
