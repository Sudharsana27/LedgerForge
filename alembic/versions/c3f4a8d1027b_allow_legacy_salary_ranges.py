"""Allow historical salary rows with reversed effective ranges.

Revision ID: c3f4a8d1027b
Revises: d24e7a91c630
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f4a8d1027b"
down_revision: Union[str, Sequence[str], None] = "d24e7a91c630"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "salary_structures" not in inspector.get_table_names():
        return
    constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("salary_structures")
    }
    if "ck_salary_structure_date_range" in constraints:
        with op.batch_alter_table(
            "salary_structures", recreate="auto"
        ) as batch:
            batch.drop_constraint(
                "ck_salary_structure_date_range",
                type_="check",
            )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade is disabled because historical salary rows may violate "
        "the former date-range check"
    )
