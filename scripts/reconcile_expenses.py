import argparse
import csv
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import ExpenseBill


CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile approved bill spend against expenses.csv."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(settings.data_dir),
    )
    parser.add_argument(
        "--output-file",
        required=True,
        type=Path,
        help="New CSV output path; existing files are not overwritten.",
    )
    args = parser.parse_args()
    source_path = args.data_dir / "expenses.csv"
    if not source_path.is_file():
        raise FileNotFoundError(f"Official expense dataset not found: {source_path}")
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    if args.output_file.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output_file}")

    source_monthly: dict[str, Decimal] = defaultdict(Decimal)
    source_count: dict[str, int] = defaultdict(int)
    source_vendor_monthly: dict[tuple[str, str], Decimal] = defaultdict(
        Decimal
    )
    source_vendor_count: dict[tuple[str, str], int] = defaultdict(int)
    with source_path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            month = row["expense_date"][:7]
            source_monthly[month] += Decimal(row["total_amount"])
            source_count[month] += 1
            vendor_month = (row["vendor_id"], month)
            source_vendor_monthly[vendor_month] += Decimal(row["total_amount"])
            source_vendor_count[vendor_month] += 1

    with SessionLocal() as db:
        bills = db.scalars(
            select(ExpenseBill).where(
                ExpenseBill.ledger_entry_id.is_not(None)
            )
        ).all()

    ledger_monthly: dict[str, Decimal] = defaultdict(Decimal)
    ledger_count: dict[str, int] = defaultdict(int)
    ledger_vendor_monthly: dict[tuple[str, str], Decimal] = defaultdict(
        Decimal
    )
    ledger_vendor_count: dict[tuple[str, str], int] = defaultdict(int)
    for bill in bills:
        month = bill.expense_date.strftime("%Y-%m")
        ledger_monthly[month] += Decimal(str(bill.total_amount))
        ledger_count[month] += 1
        vendor_month = (bill.vendor_id, month)
        ledger_vendor_monthly[vendor_month] += Decimal(str(bill.total_amount))
        ledger_vendor_count[vendor_month] += 1

    months = sorted(set(source_monthly) | set(ledger_monthly))
    rows = [
        {
            "scope": "MONTH",
            "vendor_id": "",
            "month": month,
            "source_bill_count": source_count[month],
            "ledger_bill_count": ledger_count[month],
            "source_total": source_monthly[month].quantize(CENT),
            "ledger_total": ledger_monthly[month].quantize(CENT),
            "difference": (
                ledger_monthly[month] - source_monthly[month]
            ).quantize(CENT),
        }
        for month in months
    ]
    vendor_months = sorted(
        set(source_vendor_monthly) | set(ledger_vendor_monthly)
    )
    rows.extend(
        {
            "scope": "VENDOR_MONTH",
            "vendor_id": vendor_id,
            "month": month,
            "source_bill_count": source_vendor_count[(vendor_id, month)],
            "ledger_bill_count": ledger_vendor_count[(vendor_id, month)],
            "source_total": source_vendor_monthly[
                (vendor_id, month)
            ].quantize(CENT),
            "ledger_total": ledger_vendor_monthly[
                (vendor_id, month)
            ].quantize(CENT),
            "difference": (
                ledger_vendor_monthly[(vendor_id, month)]
                - source_vendor_monthly[(vendor_id, month)]
            ).quantize(CENT),
        }
        for vendor_id, month in vendor_months
    )
    with args.output_file.open("x", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    mismatches = [row for row in rows if row["difference"] != ZERO]
    print(
        f"Reconciled {sum(source_count.values())} source bills across "
        f"{len(months)} months; monthly mismatches={len(mismatches)}."
    )
    for row in rows:
        print(
            f'{row["month"]}: source={row["source_total"]} '
            f'ledger={row["ledger_total"]} diff={row["difference"]}'
        )
    if mismatches:
        sys.exit(1)


if __name__ == "__main__":
    main()
