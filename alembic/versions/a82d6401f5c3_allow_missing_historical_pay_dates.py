"""Allow missing pay dates on imported historical payroll runs."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a82d6401f5c3"
down_revision: Union[str, Sequence[str], None] = "f3a7c91d2e64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table(
        "payroll_runs",
        recreate="auto",
    ) as batch:
        batch.alter_column(
            "pay_date",
            existing_type=sa.Date(),
            nullable=True,
        )


def downgrade() -> None:
    raise RuntimeError(
        "Imported historical payroll runs may not have a source pay date; "
        "this migration is intentionally irreversible."
    )
