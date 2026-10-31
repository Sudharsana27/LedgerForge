import calendar
import hashlib
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import MetaData, Table, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ledger_service import (
    JournalEntryInput,
    JournalLineInput,
    LedgerError,
    create_journal_entry_in_transaction,
)
from .models import ChartOfAccount, JournalEntry


ZERO = Decimal("0.00")
CENT = Decimal("0.01")
RUN_COLUMNS = {
    "run_id",
    "period_start",
    "period_end",
    "pay_date",
    "status",
    "total_gross",
    "total_deductions",
    "total_net",
    "total_employer_contributions",
    "total_employer_cost",
    "journal_entry_id",
}
ITEM_COLUMNS = {
    "run_id",
    "employee_id",
    "department_id",
    "gross_pay",
    "total_deductions",
    "earned_fixed_pay",
    "overtime_pay",
    "variable_pay",
    "pf_employee",
    "esi_employee",
    "professional_tax",
    "tds",
    "other_deductions",
    "net_pay",
    "pf_employer",
    "esi_employer",
}
EXPENSE_ACCOUNTS = {
    "earned_fixed_pay": ("5001", "Salaries & Wages"),
    "overtime_pay": ("5002", "Overtime Expense"),
    "variable_pay": ("5003", "Incentives & Bonus"),
    "pf_employer": ("5004", "Employer PF Contribution"),
    "esi_employer": ("5005", "Employer ESI Contribution"),
}
LIABILITY_ACCOUNTS = {
    "net_pay": ("2100", "Net salaries payable"),
    "pf_payable": ("2110", "PF payable (employee + employer)"),
    "esi_payable": ("2120", "ESI payable (employee + employer)"),
    "tds": ("2130", "TDS on salary payable"),
    "professional_tax": ("2140", "Professional tax payable"),
    "other_deductions": ("1300", "Recovery of employee advances"),
}
EXPECTED_ACCOUNT_TYPES = {
    **{str(code): "EXPENSE" for code, _label in EXPENSE_ACCOUNTS.values()},
    **{
        str(code): ("ASSET" if code == "1300" else "LIABILITY")
        for code, _label in LIABILITY_ACCOUNTS.values()
    },
}


def _raw_table(db: Session, name: str, required: set[str]) -> Table:
    bind = db.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(name):
        raise LedgerError(f"Required payroll source table {name} is unavailable.")
    table = Table(name, MetaData(), autoload_with=bind)
    missing = required - set(table.c.keys())
    if missing:
        raise LedgerError(
            f"Payroll source table {name} is missing required column(s): "
            + ", ".join(sorted(missing))
        )
    return table


def _date(value: object, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise LedgerError(f"Payroll run has an invalid {field}.") from exc


def _amount(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise LedgerError(
            f"Payroll run has an invalid monetary value for {field}."
        ) from exc
    if not result.is_finite() or result < 0:
        raise LedgerError(
            f"Payroll amount {field} must be finite and non-negative."
        )
    if result.quantize(CENT) != result:
        raise LedgerError(
            f"Payroll amount {field} cannot have more than two decimals."
        )
    return result


def _fiscal_year(value: date) -> str:
    start_year = value.year if value.month >= 4 else value.year - 1
    return f"FY{start_year}-{str(start_year + 1)[-2:]}"


def _entry_ids(run_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16].upper()
    return f"JE-PAY-{digest}", digest


def _existing_payroll_entry(db: Session, run_id: str) -> JournalEntry | None:
    entries = db.scalars(
        select(JournalEntry)
        .where(
            JournalEntry.source_type == "PAYROLL_RUN",
            JournalEntry.source_id == run_id,
        )
        .order_by(JournalEntry.entry_id)
        .limit(2)
    ).all()
    if len(entries) > 1:
        raise LedgerError(
            f"Multiple payroll journal entries already exist for run {run_id}."
        )
    if not entries:
        return None
    if entries[0].status != "POSTED":
        raise LedgerError(
            f"Payroll journal entry for run {run_id} exists but is not posted."
        )
    return entries[0]


def _validate_payroll_accounts(
    db: Session,
    lines: list[JournalLineInput],
) -> None:
    account_codes = {line.account_code for line in lines}
    accounts = {
        account.account_code: account
        for account in db.scalars(
            select(ChartOfAccount).where(
                ChartOfAccount.account_code.in_(account_codes)
            )
        )
    }
    for code in sorted(account_codes):
        account = accounts.get(code)
        if account is None:
            raise LedgerError(f"Unknown payroll account code: {code}.")
        expected_type = EXPECTED_ACCOUNT_TYPES[code]
        if (
            account.account_type != expected_type
            or account.normal_balance
            != ("DEBIT" if expected_type in {"ASSET", "EXPENSE"} else "CREDIT")
        ):
            raise LedgerError(
                f"Payroll account {code} has an unexpected account type "
                "or normal balance."
            )


def _run_items(db: Session, table: Table, run_id: str):
    rows = db.execute(
        select(*table.c).where(table.c.run_id == run_id).order_by(
            table.c.employee_id
        )
    ).mappings().all()
    if not rows:
        raise LedgerError(f"Payroll run {run_id} has no payroll items.")
    return rows


def _journal_lines(run_id: str, items) -> list[JournalLineInput]:
    expenses: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    payable_totals: dict[str, Decimal] = defaultdict(lambda: ZERO)

    for row in items:
        department_id = str(row["department_id"] or "").strip()
        if not department_id:
            raise LedgerError(
                f"Payroll item for employee {row['employee_id']} has no "
                "department cost center."
            )
        values = {
            field: _amount(row[field], field=field)
            for field in ITEM_COLUMNS
            if field not in {"run_id", "employee_id", "department_id"}
        }
        for field, (account_code, _description) in EXPENSE_ACCOUNTS.items():
            expenses[(account_code, department_id)] += values[field]

        payable_totals["net_pay"] += values["net_pay"]
        payable_totals["pf_payable"] += (
            values["pf_employee"] + values["pf_employer"]
        )
        payable_totals["esi_payable"] += (
            values["esi_employee"] + values["esi_employer"]
        )
        payable_totals["tds"] += values["tds"]
        payable_totals["professional_tax"] += values["professional_tax"]
        payable_totals["other_deductions"] += values["other_deductions"]

        employee_deductions = sum(
            (
                values["pf_employee"],
                values["esi_employee"],
                values["professional_tax"],
                values["tds"],
                values["other_deductions"],
            ),
            ZERO,
        )
        gross = sum(
            (
                values["earned_fixed_pay"],
                values["overtime_pay"],
                values["variable_pay"],
            ),
            ZERO,
        )
        if values["net_pay"] + employee_deductions != gross:
            raise LedgerError(
                f"Payroll item for employee {row['employee_id']} does not "
                "reconcile gross pay, deductions, and net pay."
            )

    _, digest = _entry_ids(run_id)
    lines: list[JournalLineInput] = []
    next_line = 1

    def add_line(
        account_code: str,
        amount: Decimal,
        *,
        debit: bool,
        department_id: str | None,
        description: str,
    ) -> None:
        nonlocal next_line
        if amount == 0:
            return
        lines.append(
            JournalLineInput(
                line_id=f"JL-PAY-{digest}-{next_line:03}",
                line_no=next_line,
                account_code=account_code,
                debit=amount if debit else ZERO,
                credit=ZERO if debit else amount,
                cost_center_department_id=department_id,
                line_description=description,
            )
        )
        next_line += 1

    account_labels = {
        account: label
        for account, label in EXPENSE_ACCOUNTS.values()
    }
    for (account_code, department_id), amount in sorted(expenses.items()):
        add_line(
            account_code,
            amount,
            debit=True,
            department_id=department_id,
            description=f"{account_labels[account_code]} - {department_id}",
        )

    for field, (account_code, description) in LIABILITY_ACCOUNTS.items():
        amount = payable_totals[field]
        add_line(
            account_code,
            amount,
            debit=False,
            department_id=None,
            description=description,
        )
    return lines


def _verify_run_totals(run, items) -> None:
    totals = {
        "total_gross": ZERO,
        "total_deductions": ZERO,
        "total_net": ZERO,
        "total_employer_contributions": ZERO,
        "total_employer_cost": ZERO,
    }
    for row in items:
        earnings = (
            _amount(row["earned_fixed_pay"], field="earned_fixed_pay")
            + _amount(row["overtime_pay"], field="overtime_pay")
            + _amount(row["variable_pay"], field="variable_pay")
        )
        deductions = sum(
            (
                _amount(row["pf_employee"], field="pf_employee"),
                _amount(row["esi_employee"], field="esi_employee"),
                _amount(row["professional_tax"], field="professional_tax"),
                _amount(row["tds"], field="tds"),
                _amount(row["other_deductions"], field="other_deductions"),
            ),
            ZERO,
        )
        declared_gross = _amount(row["gross_pay"], field="gross_pay")
        declared_deductions = _amount(
            row["total_deductions"],
            field="total_deductions",
        )
        employer = (
            _amount(row["pf_employer"], field="pf_employer")
            + _amount(row["esi_employer"], field="esi_employer")
        )
        net = _amount(row["net_pay"], field="net_pay")
        if (
            earnings != declared_gross
            or deductions != declared_deductions
            or earnings - deductions != net
        ):
            raise LedgerError(
                f"Payroll item for employee {row['employee_id']} does not "
                "reconcile gross pay, deductions, and net pay."
            )
        totals["total_gross"] += earnings
        totals["total_deductions"] += deductions
        totals["total_net"] += net
        totals["total_employer_contributions"] += employer
        totals["total_employer_cost"] += earnings + employer

    for field, calculated in totals.items():
        declared = _amount(run[field], field=field)
        if declared != calculated:
            raise LedgerError(
                f"Payroll run {run['run_id']} {field} ({declared:.2f}) "
                f"does not agree with its payroll items ({calculated:.2f})."
            )


def post_payroll_run(
    db: Session,
    run_id: str,
    *,
    created_by: str,
    created_at: datetime | None = None,
) -> JournalEntry:
    """Post one approved/paid payroll run atomically and idempotently."""
    if db.in_transaction():
        raise LedgerError(
            "post_payroll_run requires a Session with no active transaction."
        )
    if not run_id.strip():
        raise LedgerError("Payroll run ID cannot be empty.")
    if not created_by.strip():
        raise LedgerError("Payroll posting requires a created_by value.")

    try:
        with db.begin():
            runs = _raw_table(db, "payroll_runs", RUN_COLUMNS)
            items_table = _raw_table(db, "payroll_items", ITEM_COLUMNS)
            run_rows = db.execute(
                select(*runs.c).where(runs.c.run_id == run_id).limit(2)
            ).mappings().all()
            if not run_rows:
                raise LedgerError(f"Payroll run {run_id} was not found.")
            if len(run_rows) > 1:
                raise LedgerError(f"Payroll run ID {run_id} is not unique.")
            run = run_rows[0]

            existing = _existing_payroll_entry(db, run_id)
            linked_entry_id = run["journal_entry_id"]
            if linked_entry_id:
                linked = db.get(JournalEntry, linked_entry_id)
                if linked is None:
                    raise LedgerError(
                        f"Payroll run {run_id} references missing journal "
                        f"entry {linked_entry_id}."
                    )
                if (
                    linked.source_type != "PAYROLL_RUN"
                    or linked.source_id != run_id
                    or linked.status != "POSTED"
                ):
                    raise LedgerError(
                        f"Payroll run {run_id} references an unrelated or "
                        "unposted journal entry."
                    )
                if existing is not None and existing.entry_id != linked.entry_id:
                    raise LedgerError(
                        f"Payroll run {run_id} has conflicting journal "
                        "references."
                    )
                return linked
            if existing is not None:
                db.execute(
                    update(runs)
                    .where(runs.c.run_id == run_id)
                    .values(journal_entry_id=existing.entry_id)
                )
                return existing

            if str(run["status"]).upper() not in {"APPROVED", "PAID"}:
                raise LedgerError(
                    f"Payroll run {run_id} is not approved for posting."
                )

            period_start = _date(run["period_start"], field="period_start")
            period_end = _date(run["period_end"], field="period_end")
            pay_date = _date(run["pay_date"], field="pay_date")
            if period_start > period_end or pay_date < period_end:
                raise LedgerError(
                    f"Payroll run {run_id} has an invalid period or pay date."
                )
            if (
                period_start.year != period_end.year
                or period_start.month != period_end.month
                or period_start.day != 1
                or period_end.day
                != calendar.monthrange(period_end.year, period_end.month)[1]
            ):
                raise LedgerError(
                    f"Payroll run {run_id} must cover one full calendar month."
                )

            item_rows = _run_items(db, items_table, run_id)
            _verify_run_totals(run, item_rows)
            lines = _journal_lines(run_id, item_rows)
            _validate_payroll_accounts(db, lines)
            entry_id, _digest = _entry_ids(run_id)
            entry = JournalEntryInput(
                entry_id=entry_id,
                entry_date=pay_date,
                posting_period=f"{period_start:%Y-%m}",
                financial_year=_fiscal_year(pay_date),
                description=f"Payroll posting {run_id}",
                source_type="PAYROLL_RUN",
                source_id=run_id,
                created_by=created_by,
                created_at=created_at or datetime.now(),
            )
            posted = create_journal_entry_in_transaction(
                db,
                entry,
                lines,
            )
            db.execute(
                update(runs)
                .where(runs.c.run_id == run_id)
                .values(journal_entry_id=posted.entry_id)
            )
            db.flush()
            return posted
    except IntegrityError as exc:
        existing = _existing_payroll_entry(db, run_id)
        if existing is not None:
            return existing
        raise LedgerError(
            f"Payroll run {run_id} could not be posted because a database "
            f"constraint was violated: {exc.orig}"
        ) from exc
