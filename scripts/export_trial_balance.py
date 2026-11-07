import argparse
import csv
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from app.database import SessionLocal
from app.financial_reports import export_trial_balance_totals
from app.models import JournalEntry


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export posted ledger activity for the official checker."
    )
    parser.add_argument(
        "--output-file",
        required=True,
        type=Path,
        help="New CSV path; existing files are not overwritten.",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        help="Last included journal date; defaults to the latest posted date.",
    )
    args = parser.parse_args()
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    if args.output_file.exists():
        raise FileExistsError(
            f"Refusing to overwrite {args.output_file}"
        )

    with SessionLocal() as db:
        end_date = args.end_date or db.scalar(
            select(func.max(JournalEntry.entry_date)).where(
                JournalEntry.status == "POSTED"
            )
        )
        if end_date is None:
            raise ValueError("No posted journal entries are available")
        rows = export_trial_balance_totals(db, end_date=end_date)

    with args.output_file.open("x", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=("account_code", "debit", "credit"),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "debit": format(row["debit"], ".2f"),
                    "credit": format(row["credit"], ".2f"),
                }
            )
    print(f"Trial-balance export through {end_date}: {args.output_file}")


if __name__ == "__main__":
    main()
