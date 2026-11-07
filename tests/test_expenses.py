from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.database import Base
from app.expense_service import (
    ExpenseServiceError,
    approve_expense_bill,
    build_spend_report,
    pay_expense_bill,
    submit_expense_bill,
)
from app.models import (
    ChartOfAccount,
    Department,
    Employee,
    ExpenseBill,
    JournalEntry,
    JournalLine,
    Role,
    Vendor,
)


@pytest.fixture
def expense_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'expense-test.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Department(
                department_id="D01",
                department_name="Finance",
                cost_center="CC01",
                description=None,
            )
        )
        db.flush()
        db.add(
            Role(
                role_id="R01",
                department_id="D01",
                role_title="Finance Associate",
                level=1,
                grade="G1",
                band_min_annual=1,
                band_mid_annual=2,
                band_max_annual=3,
                overtime_eligible="N",
                band_year=2025,
            )
        )
        db.flush()
        db.add_all(
            [
                Employee(
                    employee_id=employee_id,
                    first_name=employee_id,
                    last_name="Test",
                    full_name=f"{employee_id} Test",
                    work_email=f"{employee_id.lower()}@example.test",
                    gender=None,
                    date_of_birth=None,
                    hire_date=date(2020, 1, 1),
                    exit_date=None,
                    employment_status="ACTIVE",
                    employment_type="FULL_TIME",
                    department_id="D01",
                    role_id="R01",
                    manager_id=None,
                    work_location="Chennai",
                    work_mode="OFFICE",
                    highest_education=None,
                    prior_experience_years=None,
                    career_gap_months=None,
                    commute_distance_km=None,
                    pf_applicable="Y",
                    esi_applicable="N",
                    notice_period_days=0,
                    resignation_date=None,
                    exit_type=None,
                    exit_reason=None,
                    created_at=None,
                )
                for employee_id in ("EMP-CREATOR", "EMP-APPROVER")
            ]
        )
        db.add_all(
            [
                ChartOfAccount(
                    account_code=code,
                    account_name=name,
                    account_type=kind,
                    normal_balance=normal,
                    parent_code=None,
                    is_group="N",
                    statement=statement,
                    is_active="Y",
                )
                for code, name, kind, normal, statement in (
                    ("1001", "Bank", "ASSET", "DEBIT", "BALANCE_SHEET"),
                    ("1200", "GST input", "ASSET", "DEBIT", "BALANCE_SHEET"),
                    ("2001", "Accounts payable", "LIABILITY", "CREDIT", "BALANCE_SHEET"),
                    ("5101", "Rent", "EXPENSE", "DEBIT", "INCOME_STATEMENT"),
                )
            ]
        )
        db.add(
            Vendor(
                vendor_id="V-01",
                vendor_name="Office Vendor",
                primary_expense_account="5101",
                payment_terms_days=30,
                city="Chennai",
                gst_registration=None,
                is_active="Y",
            )
        )
        db.commit()
        yield db
    engine.dispose()


def _submit(db, reference="BILL-1", expense_id="EXP-1"):
    return submit_expense_bill(
        db,
        expense_id=expense_id,
        vendor_id="V-01",
        bill_reference=reference,
        expense_date=date(2025, 4, 1),
        due_date=date(2025, 5, 1),
        description="Office rent",
        department_id="D01",
        amount_excl_gst=Decimal("100.00"),
        gst_rate_percent=Decimal("18.00"),
        submitted_by="EMP-CREATOR",
    )


def test_bill_workflow_enforces_separation_and_posts_once(expense_db):
    bill = _submit(expense_db)
    expense_id = bill.expense_id
    expense_db.rollback()

    with pytest.raises(ExpenseServiceError, match="Only approved bills"):
        pay_expense_bill(
            expense_db,
            expense_id,
            payment_date=date(2025, 4, 2),
            payment_mode="NEFT",
            paid_by="EMP-PAYER",
        )
    expense_db.rollback()

    with pytest.raises(ExpenseServiceError, match="cannot approve"):
        approve_expense_bill(
            expense_db,
            expense_id,
            approved_by="EMP-CREATOR",
        )
    expense_db.rollback()

    approved = approve_expense_bill(
        expense_db,
        expense_id,
        approved_by="EMP-APPROVER",
    )
    journal_entry_id = approved.ledger_entry_id
    expense_db.rollback()
    assert journal_entry_id is not None
    lines = expense_db.scalars(
        select(JournalLine)
        .where(JournalLine.entry_id == journal_entry_id)
        .order_by(JournalLine.line_no)
    ).all()
    assert [(line.account_code, line.debit, line.credit) for line in lines] == [
        ("5101", Decimal("100.00"), Decimal("0.00")),
        ("1200", Decimal("18.00"), Decimal("0.00")),
        ("2001", Decimal("0.00"), Decimal("118.00")),
    ]
    expense_db.rollback()

    paid = pay_expense_bill(
        expense_db,
        expense_id,
        payment_date=date(2025, 4, 5),
        payment_mode="NEFT",
        paid_by="EMP-PAYER",
    )
    payment_entry_id = paid.payment_ledger_entry_id
    expense_db.rollback()
    payment_lines = expense_db.scalars(
        select(JournalLine)
        .where(JournalLine.entry_id == payment_entry_id)
        .order_by(JournalLine.line_no)
    ).all()
    assert [(line.account_code, line.debit, line.credit) for line in payment_lines] == [
        ("2001", Decimal("118.00"), Decimal("0.00")),
        ("1001", Decimal("0.00"), Decimal("118.00")),
    ]
    assert expense_db.scalar(
        select(JournalEntry.entry_id).where(
            JournalEntry.source_type == "EXPENSE_BILL",
            JournalEntry.source_id == expense_id,
        )
    ) == journal_entry_id
    expense_db.rollback()
    with pytest.raises(ExpenseServiceError, match="Only submitted bills"):
        approve_expense_bill(
            expense_db,
            expense_id,
            approved_by="EMP-OTHER",
        )


def test_duplicate_bill_identity_is_rejected_without_new_record(expense_db):
    _submit(expense_db)
    expense_db.rollback()
    with pytest.raises(ExpenseServiceError, match="already exists"):
        _submit(
            expense_db,
            reference=" bill-1 ",
            expense_id="EXP-2",
        )
    expense_db.rollback()
    assert expense_db.scalar(
        select(ExpenseBill.expense_id).where(
            ExpenseBill.expense_id.in_(["EXP-1", "EXP-2"])
        )
    ) == "EXP-1"
    expense_db.rollback()


def test_spend_report_uses_posted_expenses_and_vendor_month_totals(expense_db):
    bill = _submit(expense_db)
    expense_id = bill.expense_id
    expense_db.rollback()
    approve_expense_bill(
        expense_db,
        expense_id,
        approved_by="EMP-APPROVER",
    )
    expense_db.rollback()
    report = build_spend_report(
        expense_db,
        start_date=date(2025, 4, 1),
        end_date=date(2025, 4, 30),
    )
    assert report["bill_count"] == 1
    assert report["total_spend"] == Decimal("118.00")
    assert report["monthly"] == [
        {"month": "2025-04", "total": Decimal("118.00")}
    ]
    assert report["vendor_month"][0]["vendor_id"] == "V-01"
