import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ledger_service import (
    JournalEntryInput,
    JournalLineInput,
    LedgerError,
    create_journal_entry_in_transaction,
)
from .models import ChartOfAccount, ExpenseBill, JournalEntry, Vendor


CENT = Decimal("0.01")
ZERO = Decimal("0.00")
GST_INPUT_ACCOUNT = "1200"
ACCOUNTS_PAYABLE_ACCOUNT = "2001"
DEFAULT_CASH_ACCOUNT = "1001"


class ExpenseServiceError(ValueError):
    pass


def _rounded(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _financial_year(value: date) -> str:
    year = value.year if value.month >= 4 else value.year - 1
    return f"{year}-{str(year + 1)[-2:]}"


def _duplicate_key(
    vendor_id: str,
    bill_reference: str,
    expense_date: date,
    total_amount: Decimal,
) -> str:
    identity = (
        vendor_id.strip().casefold(),
        bill_reference.strip().casefold(),
        expense_date.isoformat(),
        format(total_amount, ".2f"),
    )
    return hashlib.sha256(
        json.dumps(identity, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _require_account(
    db: Session,
    account_code: str,
    *,
    account_type: str,
    normal_balance: str,
) -> ChartOfAccount:
    account = db.get(ChartOfAccount, account_code)
    if (
        account is None
        or account.is_active != "Y"
        or account.is_group == "Y"
        or account.account_type != account_type
        or account.normal_balance != normal_balance
    ):
        raise ExpenseServiceError(
            f"Account {account_code} is not a valid active posting account."
        )
    return account


def submit_expense_bill(
    db: Session,
    *,
    expense_id: str,
    vendor_id: str,
    bill_reference: str,
    expense_date: date,
    due_date: date,
    description: str,
    department_id: str,
    amount_excl_gst: Decimal,
    gst_rate_percent: Decimal,
    submitted_by: str,
    category_account: str | None = None,
    submitted_at: datetime | None = None,
) -> ExpenseBill:
    if db.in_transaction():
        raise ExpenseServiceError(
            "Expense submission requires a Session without an active transaction."
        )
    bill_reference = bill_reference.strip()
    if not bill_reference:
        raise ExpenseServiceError("Bill reference cannot be empty.")
    if expense_date > due_date:
        raise ExpenseServiceError("due_date must be on or after expense_date.")
    if amount_excl_gst <= 0 or gst_rate_percent < 0:
        raise ExpenseServiceError(
            "Expense amounts must be positive and rates cannot be negative."
        )
    if not amount_excl_gst.is_finite() or not gst_rate_percent.is_finite():
        raise ExpenseServiceError("Expense amounts and rates must be finite.")

    gst_amount = _rounded(
        amount_excl_gst * gst_rate_percent / Decimal("100")
    )
    total_amount = amount_excl_gst + gst_amount
    duplicate_key = _duplicate_key(
        vendor_id,
        bill_reference,
        expense_date,
        total_amount,
    )
    try:
        with db.begin():
            vendor = db.get(Vendor, vendor_id)
            if vendor is None or vendor.is_active != "Y":
                raise ExpenseServiceError("Active vendor does not exist.")
            account_code = category_account or vendor.primary_expense_account
            _require_account(
                db,
                account_code,
                account_type="EXPENSE",
                normal_balance="DEBIT",
            )
            duplicate = db.scalar(
                select(ExpenseBill.expense_id).where(
                    ExpenseBill.duplicate_key == duplicate_key
                )
            )
            if duplicate is not None:
                raise ExpenseServiceError(
                    "A bill with this vendor, reference, date, and amount already exists."
                )
            bill = ExpenseBill(
                expense_id=expense_id,
                expense_date=expense_date,
                category_account=account_code,
                vendor_id=vendor_id,
                bill_reference=bill_reference,
                description=description.strip(),
                department_id=department_id,
                amount_excl_gst=amount_excl_gst,
                gst_rate_percent=gst_rate_percent,
                gst_amount=gst_amount,
                total_amount=total_amount,
                due_date=due_date,
                paid_date=None,
                status="SUBMITTED",
                payment_mode=None,
                submitted_by=submitted_by,
                approved_by=None,
                ledger_entry_id=None,
                payment_ledger_entry_id=None,
                submitted_at=submitted_at or datetime.now(),
                approved_at=None,
                paid_at=None,
                duplicate_key=duplicate_key,
            )
            db.add(bill)
            db.flush()
            return bill
    except IntegrityError as exc:
        raise ExpenseServiceError(
            "Expense bill conflicts with an existing record or constraint."
        ) from exc


def approve_expense_bill(
    db: Session,
    expense_id: str,
    *,
    approved_by: str,
    approved_at: datetime | None = None,
) -> ExpenseBill:
    if db.in_transaction():
        raise ExpenseServiceError(
            "Expense approval requires a Session without an active transaction."
        )
    try:
        with db.begin():
            bill = db.get(ExpenseBill, expense_id)
            if bill is None:
                raise ExpenseServiceError("Expense bill does not exist.")
            if bill.status != "SUBMITTED":
                raise ExpenseServiceError(
                    f"Only submitted bills can be approved (current status: {bill.status})."
                )
            if bill.submitted_by == approved_by:
                raise ExpenseServiceError(
                    "The bill submitter cannot approve the same bill."
                )
            if bill.ledger_entry_id is not None:
                raise ExpenseServiceError(
                    "Submitted bill already has a ledger posting."
                )

            expense_account = _require_account(
                db,
                bill.category_account,
                account_type="EXPENSE",
                normal_balance="DEBIT",
            )
            _require_account(
                db,
                ACCOUNTS_PAYABLE_ACCOUNT,
                account_type="LIABILITY",
                normal_balance="CREDIT",
            )
            lines = []
            digest = hashlib.sha256(expense_id.encode("utf-8")).hexdigest()[:14].upper()
            line_no = 1
            for account_code, amount, description in (
                (
                    expense_account.account_code,
                    bill.amount_excl_gst,
                    expense_account.account_name,
                ),
                (
                    GST_INPUT_ACCOUNT,
                    bill.gst_amount,
                    "GST input credit",
                ),
            ):
                if amount == 0:
                    continue
                if account_code == GST_INPUT_ACCOUNT:
                    _require_account(
                        db,
                        GST_INPUT_ACCOUNT,
                        account_type="ASSET",
                        normal_balance="DEBIT",
                    )
                lines.append(
                    JournalLineInput(
                        line_id=f"JL-EX-{digest}-{line_no:02}",
                        line_no=line_no,
                        account_code=account_code,
                        debit=amount,
                        credit=ZERO,
                        cost_center_department_id=bill.department_id,
                        line_description=description,
                    )
                )
                line_no += 1
            lines.append(
                JournalLineInput(
                    line_id=f"JL-EX-{digest}-{line_no:02}",
                    line_no=line_no,
                    account_code=ACCOUNTS_PAYABLE_ACCOUNT,
                    debit=ZERO,
                    credit=bill.total_amount,
                    line_description=f"Payable to vendor {bill.vendor_id}",
                )
            )
            entry = create_journal_entry_in_transaction(
                db,
                JournalEntryInput(
                    entry_id=f"JE-EX-{digest}",
                    entry_date=bill.expense_date,
                    posting_period=bill.expense_date.strftime("%Y-%m"),
                    financial_year=_financial_year(bill.expense_date),
                    description=f"Expense bill {bill.bill_reference}",
                    source_type="EXPENSE_BILL",
                    source_id=bill.expense_id,
                    created_by=approved_by,
                    created_at=approved_at or datetime.now(),
                ),
                lines,
            )
            bill.status = "APPROVED"
            bill.approved_by = approved_by
            bill.approved_at = approved_at or datetime.now()
            bill.ledger_entry_id = entry.entry_id
            db.flush()
            return bill
    except IntegrityError as exc:
        raise ExpenseServiceError(
            "Expense approval conflicts with an existing ledger posting."
        ) from exc
    except LedgerError as exc:
        raise ExpenseServiceError(str(exc)) from exc


def pay_expense_bill(
    db: Session,
    expense_id: str,
    *,
    payment_date: date,
    payment_mode: str,
    paid_by: str,
    cash_account: str = DEFAULT_CASH_ACCOUNT,
    paid_at: datetime | None = None,
) -> ExpenseBill:
    if db.in_transaction():
        raise ExpenseServiceError(
            "Expense payment requires a Session without an active transaction."
        )
    try:
        with db.begin():
            bill = db.get(ExpenseBill, expense_id)
            if bill is None:
                raise ExpenseServiceError("Expense bill does not exist.")
            if bill.status != "APPROVED":
                raise ExpenseServiceError(
                    "Only approved bills can be paid."
                )
            if payment_date < bill.expense_date:
                raise ExpenseServiceError(
                    "payment_date cannot be before expense_date."
                )
            if not payment_mode.strip():
                raise ExpenseServiceError("Payment mode cannot be empty.")
            if bill.payment_ledger_entry_id is not None:
                raise ExpenseServiceError(
                    "Expense bill already has a payment posting."
                )
            _require_account(
                db,
                ACCOUNTS_PAYABLE_ACCOUNT,
                account_type="LIABILITY",
                normal_balance="CREDIT",
            )
            _require_account(
                db,
                cash_account,
                account_type="ASSET",
                normal_balance="DEBIT",
            )
            digest = hashlib.sha256(expense_id.encode("utf-8")).hexdigest()[:14].upper()
            entry = create_journal_entry_in_transaction(
                db,
                JournalEntryInput(
                    entry_id=f"JE-EP-{digest}",
                    entry_date=payment_date,
                    posting_period=payment_date.strftime("%Y-%m"),
                    financial_year=_financial_year(payment_date),
                    description=f"Payment for bill {bill.bill_reference}",
                    source_type="EXPENSE_BILL_PAYMENT",
                    source_id=bill.expense_id,
                    created_by=paid_by,
                    created_at=paid_at or datetime.now(),
                ),
                [
                    JournalLineInput(
                        line_id=f"JL-EP-{digest}-01",
                        line_no=1,
                        account_code=ACCOUNTS_PAYABLE_ACCOUNT,
                        debit=bill.total_amount,
                        credit=ZERO,
                        line_description=f"Clear vendor payable {bill.vendor_id}",
                    ),
                    JournalLineInput(
                        line_id=f"JL-EP-{digest}-02",
                        line_no=2,
                        account_code=cash_account,
                        debit=ZERO,
                        credit=bill.total_amount,
                        line_description="Vendor bill payment",
                    ),
                ],
            )
            bill.status = "PAID"
            bill.paid_date = payment_date
            bill.payment_mode = payment_mode.strip()
            bill.payment_ledger_entry_id = entry.entry_id
            bill.paid_at = paid_at or datetime.now()
            db.flush()
            return bill
    except IntegrityError as exc:
        raise ExpenseServiceError(
            "Expense payment conflicts with an existing ledger posting."
        ) from exc
    except LedgerError as exc:
        raise ExpenseServiceError(str(exc)) from exc


def build_spend_report(
    db: Session,
    *,
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    if start_date > end_date:
        raise ExpenseServiceError(
            "start_date must be on or before end_date."
        )
    bills = db.scalars(
        select(ExpenseBill)
        .where(
            ExpenseBill.expense_date >= start_date,
            ExpenseBill.expense_date <= end_date,
            ExpenseBill.ledger_entry_id.is_not(None),
        )
        .order_by(ExpenseBill.expense_date, ExpenseBill.expense_id)
    ).all()
    monthly: dict[str, Decimal] = defaultdict(lambda: ZERO)
    vendor_totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    vendor_month: dict[tuple[str, str], Decimal] = defaultdict(
        lambda: ZERO
    )
    vendor_names: dict[str, str] = {}
    for bill in bills:
        month = bill.expense_date.strftime("%Y-%m")
        amount = Decimal(str(bill.total_amount))
        monthly[month] += amount
        vendor_totals[bill.vendor_id] += amount
        vendor_month[(bill.vendor_id, month)] += amount
        vendor_names[bill.vendor_id] = bill.vendor.vendor_name

    return {
        "start_date": start_date,
        "end_date": end_date,
        "bill_count": len(bills),
        "total_spend": sum(monthly.values(), ZERO),
        "monthly": [
            {"month": month, "total": amount}
            for month, amount in sorted(monthly.items())
        ],
        "vendors": [
            {
                "vendor_id": vendor_id,
                "vendor_name": vendor_names[vendor_id],
                "total": amount,
            }
            for vendor_id, amount in sorted(vendor_totals.items())
        ],
        "vendor_month": [
            {
                "vendor_id": vendor_id,
                "vendor_name": vendor_names[vendor_id],
                "month": month,
                "total": amount,
            }
            for (vendor_id, month), amount in sorted(vendor_month.items())
        ],
    }


def get_expense_bill(db: Session, expense_id: str) -> ExpenseBill | None:
    return db.get(ExpenseBill, expense_id)
