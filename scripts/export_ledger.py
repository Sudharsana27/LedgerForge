import argparse
import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ChartOfAccount, JournalEntry, JournalLine


EXPORT_COLUMNS = {
    "chart_of_accounts": (
        "account_code",
        "account_name",
        "account_type",
        "normal_balance",
        "parent_code",
        "is_group",
        "statement",
        "is_active",
    ),
    "journal_entries": (
        "entry_id",
        "entry_date",
        "posting_period",
        "financial_year",
        "description",
        "source_type",
        "source_id",
        "status",
        "total_debit",
        "total_credit",
        "reversal_of_source_id",
        "created_by",
        "created_at",
    ),
    "journal_lines": (
        "line_id",
        "entry_id",
        "line_no",
        "account_code",
        "debit",
        "credit",
        "cost_center_department_id",
        "line_description",
    ),
}


def _serialize(value):
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        if hasattr(value, "hour"):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value.isoformat()
    if hasattr(value, "as_tuple"):
        return format(value, ".2f")
    return value


def export_ledger_tables(db: Session, output_dir: Path) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = [output_dir / f"{name}.csv" for name in EXPORT_COLUMNS]
    existing = [path for path in paths if path.exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite existing ledger export(s): "
            + ", ".join(str(path) for path in existing)
        )

    queries = (
        select(ChartOfAccount).order_by(ChartOfAccount.account_code),
        select(JournalEntry).order_by(JournalEntry.entry_id),
        select(JournalLine).order_by(JournalLine.entry_id, JournalLine.line_no),
    )
    for (table_name, columns), query, path in zip(
        EXPORT_COLUMNS.items(), queries, paths
    ):
        records = db.scalars(query)
        with path.open("w", newline="", encoding="utf-8-sig") as output:
            writer = csv.DictWriter(output, fieldnames=columns)
            writer.writeheader()
            for record in records:
                writer.writerow(
                    {
                        column: _serialize(getattr(record, column))
                        for column in columns
                    }
                )
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the ledger tables to CSV files."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="New or empty destination directory for the three CSV files.",
    )
    arguments = parser.parse_args()

    with SessionLocal() as db:
        paths = export_ledger_tables(db, arguments.output_dir)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
