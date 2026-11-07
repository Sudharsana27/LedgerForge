from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.database import Base
from app.financial_reports import balance_sheet, profit_and_loss, trial_balance
from app.ledger_service import (
    JournalEntryInput,
    JournalLineInput,
    create_journal_entry,
)
from app.models import ChartOfAccount


def _account(code, name, kind, normal, parent=None, group="N"):
    return ChartOfAccount(
        account_code=code,
        account_name=name,
        account_type=kind,
        normal_balance=normal,
        parent_code=parent,
        is_group=group,
        statement=(
            "INCOME_STATEMENT"
            if kind in {"INCOME", "EXPENSE"}
            else "BALANCE_SHEET"
        ),
        is_active="Y",
    )


def _post(db, entry_id, on_date, lines):
    create_journal_entry(
        db,
        JournalEntryInput(
            entry_id=entry_id,
            entry_date=on_date,
            posting_period=on_date.strftime("%Y-%m"),
            financial_year="2025-26",
            description=entry_id,
            source_type="TEST",
            source_id=entry_id,
            created_by="test",
            created_at=datetime.combine(on_date, datetime.min.time()),
        ),
        [
            JournalLineInput(
                line_id=f"{entry_id}-{index}",
                line_no=index,
                account_code=account,
                debit=debit,
                credit=credit,
            )
            for index, (account, debit, credit) in enumerate(lines, start=1)
        ],
    )


def test_trial_balance_profit_loss_and_balance_sheet_reconcile(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reports.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                _account("1000", "Assets", "ASSET", "DEBIT", group="Y"),
                _account("1001", "Bank", "ASSET", "DEBIT", "1000"),
                _account("2001", "Payables", "LIABILITY", "CREDIT"),
                _account("3001", "Capital", "EQUITY", "CREDIT"),
                _account("4001", "Revenue", "INCOME", "CREDIT"),
                _account("5001", "Expense", "EXPENSE", "DEBIT"),
            ]
        )
        db.commit()
        _post(
            db,
            "JE-OPEN",
            date(2025, 4, 1),
            [
                ("1001", Decimal("100.00"), Decimal("0.00")),
                ("3001", Decimal("0.00"), Decimal("100.00")),
            ],
        )
        _post(
            db,
            "JE-REV",
            date(2025, 4, 10),
            [
                ("1001", Decimal("50.00"), Decimal("0.00")),
                ("4001", Decimal("0.00"), Decimal("50.00")),
            ],
        )
        _post(
            db,
            "JE-EXP",
            date(2025, 4, 11),
            [
                ("5001", Decimal("20.00"), Decimal("0.00")),
                ("1001", Decimal("0.00"), Decimal("20.00")),
            ],
        )

        trial = trial_balance(
            db,
            start_date=date(2025, 4, 10),
            end_date=date(2025, 4, 11),
        )
        assert trial["opening_debit_total"] == Decimal("100.00")
        assert trial["period_debit_total"] == Decimal("70.00")
        assert trial["period_credit_total"] == Decimal("70.00")
        assert trial["closing_debit_total"] == Decimal("150.00")
        assert trial["closing_credit_total"] == Decimal("150.00")
        assert len(trial["accounts"]) == 5

        pnl = profit_and_loss(
            db,
            start_date=date(2025, 4, 1),
            end_date=date(2025, 4, 11),
        )
        assert pnl["revenue_total"] == Decimal("50.00")
        assert pnl["expense_total"] == Decimal("20.00")
        assert pnl["net_profit"] == Decimal("30.00")

        sheet = balance_sheet(db, as_of_date=date(2025, 4, 11))
        assert sheet["assets_total"] == Decimal("130.00")
        assert sheet["equity_total"] == Decimal("100.00")
        assert sheet["current_period_profit"] == Decimal("30.00")
        assert sheet["difference"] == Decimal("0.00")
    engine.dispose()
