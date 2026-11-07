from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ChartOfAccount, JournalEntry, JournalLine


ZERO = Decimal("0.00")


class FinancialReportError(ValueError):
    pass


def _validate_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise FinancialReportError("start_date must be on or before end_date")


def _account_totals(
    db: Session,
    *,
    end_date: date,
    start_date: date | None = None,
) -> dict[str, tuple[Decimal, Decimal]]:
    conditions = [
        JournalEntry.status == "POSTED",
        JournalEntry.entry_date <= end_date,
    ]
    if start_date is not None:
        conditions.append(JournalEntry.entry_date >= start_date)

    rows = db.execute(
        select(
            JournalLine.account_code,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalEntry, JournalEntry.entry_id == JournalLine.entry_id)
        .where(*conditions)
        .group_by(JournalLine.account_code)
    ).all()
    return {
        account_code: (Decimal(str(debit)), Decimal(str(credit)))
        for account_code, debit, credit in rows
    }


def _leaf_accounts(db: Session) -> list[ChartOfAccount]:
    return list(
        db.scalars(
            select(ChartOfAccount)
            .where(ChartOfAccount.is_group == "N")
            .order_by(ChartOfAccount.account_code)
        ).all()
    )


def _balances(
    debit: Decimal,
    credit: Decimal,
    normal_balance: str,
) -> tuple[Decimal, Decimal, Decimal]:
    raw = debit - credit
    if normal_balance == "DEBIT":
        normal = raw
    elif normal_balance == "CREDIT":
        normal = -raw
    else:
        raise FinancialReportError("Account has an invalid normal balance")
    return (
        max(raw, ZERO),
        max(-raw, ZERO),
        normal,
    )


def trial_balance(
    db: Session,
    *,
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    _validate_range(start_date, end_date)
    opening = _account_totals(
        db,
        start_date=date.min,
        end_date=date.fromordinal(start_date.toordinal() - 1),
    ) if start_date > date.min else {}
    activity = _account_totals(
        db,
        start_date=start_date,
        end_date=end_date,
    )
    accounts = _leaf_accounts(db)
    rows = []
    opening_debit_total = ZERO
    opening_credit_total = ZERO
    debit_total = ZERO
    credit_total = ZERO
    closing_debit_total = ZERO
    closing_credit_total = ZERO

    for account in accounts:
        opening_debit, opening_credit = opening.get(
            account.account_code, (ZERO, ZERO)
        )
        period_debit, period_credit = activity.get(
            account.account_code, (ZERO, ZERO)
        )
        opening_debit_balance, opening_credit_balance, _ = _balances(
            opening_debit,
            opening_credit,
            account.normal_balance,
        )
        closing_debit_balance, closing_credit_balance, _ = _balances(
            opening_debit + period_debit,
            opening_credit + period_credit,
            account.normal_balance,
        )
        rows.append(
            {
                "account_code": account.account_code,
                "account_name": account.account_name,
                "account_type": account.account_type,
                "opening_debit": opening_debit_balance,
                "opening_credit": opening_credit_balance,
                "period_debit": period_debit,
                "period_credit": period_credit,
                "closing_debit": closing_debit_balance,
                "closing_credit": closing_credit_balance,
            }
        )
        opening_debit_total += opening_debit_balance
        opening_credit_total += opening_credit_balance
        debit_total += period_debit
        credit_total += period_credit
        closing_debit_total += closing_debit_balance
        closing_credit_total += closing_credit_balance

    return {
        "start_date": start_date,
        "end_date": end_date,
        "accounts": rows,
        "opening_debit_total": opening_debit_total,
        "opening_credit_total": opening_credit_total,
        "period_debit_total": debit_total,
        "period_credit_total": credit_total,
        "closing_debit_total": closing_debit_total,
        "closing_credit_total": closing_credit_total,
    }


def profit_and_loss(
    db: Session,
    *,
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    _validate_range(start_date, end_date)
    totals = _account_totals(
        db,
        start_date=start_date,
        end_date=end_date,
    )
    revenue_rows = []
    expense_rows = []
    revenue_total = ZERO
    expense_total = ZERO

    for account in _leaf_accounts(db):
        debit, credit = totals.get(account.account_code, (ZERO, ZERO))
        if account.account_type == "INCOME":
            amount = credit - debit
            revenue_total += amount
            revenue_rows.append(
                {
                    "account_code": account.account_code,
                    "account_name": account.account_name,
                    "amount": amount,
                }
            )
        elif account.account_type == "EXPENSE":
            amount = debit - credit
            expense_total += amount
            expense_rows.append(
                {
                    "account_code": account.account_code,
                    "account_name": account.account_name,
                    "amount": amount,
                }
            )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "revenue": revenue_rows,
        "expenses": expense_rows,
        "revenue_total": revenue_total,
        "expense_total": expense_total,
        "net_profit": revenue_total - expense_total,
    }


def balance_sheet(
    db: Session,
    *,
    as_of_date: date,
) -> dict[str, object]:
    balances = _account_totals(db, end_date=as_of_date)
    account_rows: dict[str, list[dict[str, object]]] = {
        "assets": [],
        "liabilities": [],
        "equity": [],
    }
    totals = {
        "assets": ZERO,
        "liabilities": ZERO,
        "equity": ZERO,
    }
    statement_names = {
        "ASSET": "assets",
        "LIABILITY": "liabilities",
        "EQUITY": "equity",
    }
    for account in _leaf_accounts(db):
        statement_name = statement_names.get(account.account_type)
        if statement_name is None:
            continue
        debit, credit = balances.get(account.account_code, (ZERO, ZERO))
        amount = (
            debit - credit
            if account.account_type == "ASSET"
            else credit - debit
        )
        account_rows[statement_name].append(
            {
                "account_code": account.account_code,
                "account_name": account.account_name,
                "balance": amount,
            }
        )
        totals[statement_name] += amount

    current_activity = _account_totals(db, end_date=as_of_date)
    current_profit = ZERO
    for account in _leaf_accounts(db):
        debit, credit = current_activity.get(
            account.account_code, (ZERO, ZERO)
        )
        if account.account_type == "INCOME":
            current_profit += credit - debit
        elif account.account_type == "EXPENSE":
            current_profit -= debit - credit

    liabilities_and_equity = (
        totals["liabilities"] + totals["equity"] + current_profit
    )
    return {
        "as_of_date": as_of_date,
        **account_rows,
        "assets_total": totals["assets"],
        "liabilities_total": totals["liabilities"],
        "equity_total": totals["equity"],
        "current_period_profit": current_profit,
        "liabilities_and_equity_total": liabilities_and_equity,
        "difference": totals["assets"] - liabilities_and_equity,
    }


def export_trial_balance_totals(
    db: Session,
    *,
    end_date: date,
) -> list[dict[str, object]]:
    """Return all posted debit and credit activity for checker-compatible export."""
    totals = _account_totals(db, end_date=end_date)
    accounts = {account.account_code for account in _leaf_accounts(db)}
    return [
        {
            "account_code": account_code,
            "debit": debit,
            "credit": credit,
        }
        for account_code, (debit, credit) in sorted(totals.items())
        if account_code in accounts
    ]
