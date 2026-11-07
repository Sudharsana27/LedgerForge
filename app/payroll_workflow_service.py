import calendar
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .ledger_service import (
    JournalEntryInput,
    JournalLineInput,
    LedgerError,
    create_journal_entry_in_transaction,
    reverse_journal_entry_in_transaction,
)
from .models import (
    ChartOfAccount,
    JournalEntry,
    PayrollItem,
    PayrollRun,
)
from .payroll_ledger_service import post_payroll_run_in_transaction
from .payroll_service import PayrollError, calculate_payroll


class PayrollWorkflowError(ValueError):
    pass


@dataclass(frozen=True)
class PayrollRunItemInput:
    employee_id: str
    variable_pay: Decimal
    variable_pay_type: str | None
    tds: Decimal
    other_deductions: Decimal


def _require_idle_session(db: Session) -> None:
    if db.in_transaction():
        raise PayrollWorkflowError(
            "Payroll workflow operations require a Session without an active transaction."
        )


def _digest(run_id: str, purpose: str) -> str:
    return hashlib.sha256(f"{purpose}:{run_id}".encode("utf-8")).hexdigest()[
        :16
    ].upper()


def _financial_year(day: date) -> str:
    start_year = day.year if day.month >= 4 else day.year - 1
    return f"FY{start_year}-{str(start_year + 1)[-2:]}"


def _amount(value: Decimal, field: str) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise PayrollWorkflowError(f"{field} must be a finite nonnegative amount.")
    return result.quantize(Decimal("0.01"))


def _required_account(
    db: Session,
    account_code: str,
    *,
    account_type: str,
    normal_balance: str,
) -> None:
    account = db.get(ChartOfAccount, account_code)
    if (
        account is None
        or account.is_active != "Y"
        or account.is_group == "Y"
        or account.account_type != account_type
        or account.normal_balance != normal_balance
    ):
        raise PayrollWorkflowError(
            f"Account {account_code} is not a valid active posting account."
        )


def create_payroll_run(
    db: Session,
    *,
    period_start: date,
    period_end: date,
    pay_date: date,
    items: Sequence[PayrollRunItemInput],
    run_by: str,
    idempotency_key: str | None = None,
    created_at: datetime | None = None,
) -> PayrollRun:
    """Calculate and save a draft run using explicit employee inputs."""
    _require_idle_session(db)
    if not items:
        raise PayrollWorkflowError(
            "A payroll run must contain at least one payroll item."
        )
    if (
        period_start.day != 1
        or period_start.year != period_end.year
        or period_start.month != period_end.month
        or period_end.day
        != calendar.monthrange(period_end.year, period_end.month)[1]
    ):
        raise PayrollWorkflowError(
            "Payroll runs must cover one full calendar month."
        )
    if pay_date < period_end:
        raise PayrollWorkflowError(
            "pay_date must be on or after the payroll period end."
        )
    if idempotency_key is not None and not idempotency_key.strip():
        raise PayrollWorkflowError("Idempotency key cannot be blank.")
    employee_ids = [item.employee_id for item in items]
    if len(set(employee_ids)) != len(employee_ids):
        raise PayrollWorkflowError(
            "A payroll run cannot contain duplicate employees."
        )

    try:
        with db.begin():
            if idempotency_key:
                existing = db.scalar(
                    select(PayrollRun).where(
                        PayrollRun.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    saved_items = {
                        item.employee_id: item
                        for item in db.scalars(
                            select(PayrollItem).where(
                                PayrollItem.run_id == existing.run_id
                            )
                        ).all()
                    }
                    same_request = (
                        existing.period_start == period_start
                        and existing.period_end == period_end
                        and existing.pay_date == pay_date
                        and set(saved_items) == set(employee_ids)
                        and all(
                            Decimal(str(saved_items[item.employee_id].variable_pay))
                            == item.variable_pay
                            and saved_items[
                                item.employee_id
                            ].variable_pay_type
                            == item.variable_pay_type
                            and Decimal(
                                str(saved_items[item.employee_id].tds)
                            )
                            == item.tds
                            and Decimal(
                                str(
                                    saved_items[
                                        item.employee_id
                                    ].other_deductions
                                )
                            )
                            == item.other_deductions
                            for item in items
                        )
                    )
                    if not same_request:
                        raise PayrollWorkflowError(
                            "Idempotency key conflicts with a different payroll request."
                        )
                    return existing

            active_run = db.scalar(
                select(PayrollRun.run_id).where(
                    PayrollRun.period_start == period_start,
                    PayrollRun.period_end == period_end,
                    PayrollRun.status != "REVERSED",
                )
            )
            if active_run is not None:
                raise PayrollWorkflowError(
                    "A non-reversed payroll run already exists for this period."
                )

            token = hashlib.sha256(
                (idempotency_key or uuid4().hex).encode("utf-8")
            ).hexdigest()[:12].upper()
            run_id = f"PR-{period_start:%Y%m}-{token}"
            calculated_items = []
            totals = {
                "gross": Decimal("0.00"),
                "deductions": Decimal("0.00"),
                "net": Decimal("0.00"),
                "employer_contributions": Decimal("0.00"),
                "employer_cost": Decimal("0.00"),
            }
            for item in items:
                try:
                    calculated = calculate_payroll(
                        db,
                        employee_id=item.employee_id,
                        period_start=period_start,
                        period_end=period_end,
                        variable_pay=item.variable_pay,
                        variable_pay_type=item.variable_pay_type,
                        tds=item.tds,
                        other_deductions=item.other_deductions,
                    )
                except PayrollError as exc:
                    raise PayrollWorkflowError(
                        f"Employee {item.employee_id} could not be calculated: {exc}"
                    ) from exc
                totals["gross"] += calculated["gross_pay"]
                totals["deductions"] += calculated["total_deductions"]
                totals["net"] += calculated["net_pay"]
                totals["employer_contributions"] += (
                    calculated["pf_employer"]
                    + calculated["esi_employer"]
                )
                totals["employer_cost"] += calculated["employer_cost"]
                item_digest = hashlib.sha256(
                    f"{run_id}:{item.employee_id}".encode("utf-8")
                ).hexdigest()[:20].upper()
                item_values = {
                    key: value
                    for key, value in calculated.items()
                    if key not in {"employee_id"}
                }
                calculated_items.append(
                    PayrollItem(
                        payroll_item_id=f"PI-{item_digest}",
                        run_id=run_id,
                        employee_id=item.employee_id,
                        **item_values,
                    )
                )

            run = PayrollRun(
                run_id=run_id,
                period_start=period_start,
                period_end=period_end,
                pay_date=pay_date,
                employees_paid=len(items),
                total_gross=totals["gross"],
                total_deductions=totals["deductions"],
                total_net=totals["net"],
                total_employer_contributions=totals[
                    "employer_contributions"
                ],
                total_employer_cost=totals["employer_cost"],
                status="DRAFT",
                run_by=run_by,
                approved_by=None,
                created_at=created_at or datetime.now(),
                approved_at=None,
                idempotency_key=idempotency_key,
                journal_entry_id=None,
                calculation_version="phase3-v1",
            )
            db.add(run)
            db.flush()
            db.add_all(calculated_items)
            db.flush()
            return run
    except IntegrityError as exc:
        raise PayrollWorkflowError(
            f"Payroll run could not be created because a database constraint was violated: {exc.orig}"
        ) from exc


def process_payroll_run(
    db: Session,
    run_id: str,
    *,
    processed_by: str,
    processed_at: datetime | None = None,
) -> PayrollRun:
    """Recalculate all saved items before allowing approval."""
    _require_idle_session(db)
    try:
        with db.begin():
            run = db.get(PayrollRun, run_id)
            if run is None:
                raise PayrollWorkflowError("Payroll run does not exist.")
            if run.status != "DRAFT":
                raise PayrollWorkflowError(
                    f"Only draft payroll runs can be processed (current status: {run.status})."
                )
            items = db.scalars(
                select(PayrollItem)
                .where(PayrollItem.run_id == run_id)
                .order_by(PayrollItem.employee_id)
            ).all()
            if not items:
                raise PayrollWorkflowError(
                    "A payroll run must contain at least one payroll item."
                )
            if (
                run.period_start.day != 1
                or run.period_start.year != run.period_end.year
                or run.period_start.month != run.period_end.month
                or run.period_end.day
                != calendar.monthrange(
                    run.period_end.year, run.period_end.month
                )[1]
            ):
                raise PayrollWorkflowError(
                    "Payroll runs must cover one full calendar month."
                )
            if run.pay_date < run.period_end:
                raise PayrollWorkflowError(
                    "Payroll pay date must be on or after the period end."
                )

            totals = {
                "gross_pay": Decimal("0.00"),
                "total_deductions": Decimal("0.00"),
                "net_pay": Decimal("0.00"),
                "employer_contributions": Decimal("0.00"),
                "employer_cost": Decimal("0.00"),
            }
            for item in items:
                try:
                    calculated = calculate_payroll(
                        db,
                        employee_id=item.employee_id,
                        period_start=run.period_start,
                        period_end=run.period_end,
                        variable_pay=Decimal(str(item.variable_pay)),
                        variable_pay_type=item.variable_pay_type,
                        tds=Decimal(str(item.tds)),
                        other_deductions=Decimal(str(item.other_deductions)),
                    )
                except PayrollError as exc:
                    raise PayrollWorkflowError(
                        f"Payroll item {item.employee_id} could not be recalculated: {exc}"
                    ) from exc
                for field, expected in calculated.items():
                    if field in {"employee_id", "period_start", "period_end"}:
                        continue
                    saved = getattr(item, field)
                    if isinstance(expected, Decimal):
                        matches = Decimal(str(saved)) == expected
                    else:
                        matches = saved == expected
                    if not matches:
                        raise PayrollWorkflowError(
                            f"Payroll item {item.employee_id} does not match the current calculation for {field}."
                        )
                totals["gross_pay"] += Decimal(str(item.gross_pay))
                totals["total_deductions"] += Decimal(
                    str(item.total_deductions)
                )
                totals["net_pay"] += Decimal(str(item.net_pay))
                totals["employer_contributions"] += (
                    Decimal(str(item.pf_employer))
                    + Decimal(str(item.esi_employer))
                )
                totals["employer_cost"] += Decimal(
                    str(item.employer_cost)
                )

            run_totals = {
                "total_gross": totals["gross_pay"],
                "total_deductions": totals["total_deductions"],
                "total_net": totals["net_pay"],
                "total_employer_contributions": totals[
                    "employer_contributions"
                ],
                "total_employer_cost": totals["employer_cost"],
            }
            for field, expected in run_totals.items():
                if _amount(getattr(run, field), field) != _amount(
                    expected, field
                ):
                    raise PayrollWorkflowError(
                        f"Payroll run total {field} does not match its items."
                    )
            if run.employees_paid != len(items):
                raise PayrollWorkflowError(
                    "Payroll run employee count does not match its items."
                )
            run.status = "PROCESSED"
            run.processed_by = processed_by
            run.processed_at = processed_at or datetime.now()
            db.flush()
            return run
    except IntegrityError as exc:
        raise PayrollWorkflowError(
            f"Payroll run could not be processed: {exc.orig}"
        ) from exc


def approve_payroll_run(
    db: Session,
    run_id: str,
    *,
    approved_by: str,
    approved_at: datetime | None = None,
) -> tuple[PayrollRun, JournalEntry]:
    """Approve a processed run and post its journal atomically."""
    _require_idle_session(db)
    try:
        with db.begin():
            run = db.get(PayrollRun, run_id)
            if run is None:
                raise PayrollWorkflowError("Payroll run does not exist.")
            if run.status == "PROCESSED":
                if run.run_by == approved_by:
                    raise PayrollWorkflowError(
                        "The payroll run creator cannot approve the same run."
                    )
                run.status = "APPROVED"
                run.approved_by = approved_by
                run.approved_at = approved_at or datetime.now()
            elif run.status not in {
                "APPROVED",
                "PAID",
                "POSTED - PAYMENT PENDING",
            }:
                raise PayrollWorkflowError(
                    f"Only processed payroll runs can be approved (current status: {run.status})."
                )
            db.flush()
            entry = post_payroll_run_in_transaction(
                db,
                run_id,
                created_by=approved_by,
                created_at=approved_at,
            )
            run.journal_entry_id = entry.entry_id
            db.flush()
            return run, entry
    except IntegrityError as exc:
        raise PayrollWorkflowError(
            f"Payroll approval could not be saved: {exc.orig}"
        ) from exc
    except LedgerError as exc:
        raise PayrollWorkflowError(str(exc)) from exc


def pay_payroll_run(
    db: Session,
    run_id: str,
    *,
    paid_by: str,
    paid_at: datetime | None = None,
    cash_account: str = "1001",
) -> tuple[PayrollRun, JournalEntry]:
    """Record the net-pay disbursement after payroll posting."""
    _require_idle_session(db)
    payment_time = paid_at or datetime.now()
    try:
        with db.begin():
            run = db.get(PayrollRun, run_id)
            if run is None:
                raise PayrollWorkflowError("Payroll run does not exist.")
            if run.payment_journal_entry_id:
                entry = db.get(JournalEntry, run.payment_journal_entry_id)
                if entry is None or entry.status != "POSTED":
                    raise PayrollWorkflowError(
                        "Payroll run references a missing or unposted payment journal."
                    )
                return run, entry
            if run.status not in {"APPROVED", "POSTED - PAYMENT PENDING"}:
                raise PayrollWorkflowError(
                    f"Only approved payroll runs can be paid (current status: {run.status})."
                )
            if not run.journal_entry_id:
                raise PayrollWorkflowError(
                    "Payroll run must be posted before payment."
                )
            _required_account(
                db,
                "2100",
                account_type="LIABILITY",
                normal_balance="CREDIT",
            )
            _required_account(
                db,
                cash_account,
                account_type="ASSET",
                normal_balance="DEBIT",
            )
            amount = _amount(run.total_net, "total_net")
            if amount <= 0:
                raise PayrollWorkflowError(
                    "Payroll net pay must be positive to record payment."
                )
            digest = _digest(run_id, "payment")
            entry = create_journal_entry_in_transaction(
                db,
                JournalEntryInput(
                    entry_id=f"JE-PAY-{digest}",
                    entry_date=payment_time.date(),
                    posting_period=f"{payment_time:%Y-%m}",
                    financial_year=_financial_year(payment_time.date()),
                    description=f"Net payroll payment {run_id}",
                    source_type="SALARY_PAYMENT",
                    source_id=run_id,
                    created_by=paid_by,
                    created_at=payment_time,
                ),
                [
                    JournalLineInput(
                        line_id=f"JL-PAY-{digest}-01",
                        line_no=1,
                        account_code="2100",
                        debit=amount,
                        credit=Decimal("0.00"),
                        line_description="Net salaries paid",
                    ),
                    JournalLineInput(
                        line_id=f"JL-PAY-{digest}-02",
                        line_no=2,
                        account_code=cash_account,
                        debit=Decimal("0.00"),
                        credit=amount,
                        line_description="Payroll bank disbursement",
                    ),
                ],
            )
            run.status = "PAID"
            run.payment_journal_entry_id = entry.entry_id
            run.paid_by = paid_by
            run.paid_at = payment_time
            db.flush()
            return run, entry
    except IntegrityError as exc:
        raise PayrollWorkflowError(
            f"Payroll payment could not be saved: {exc.orig}"
        ) from exc
    except LedgerError as exc:
        raise PayrollWorkflowError(str(exc)) from exc


def reverse_payroll_run(
    db: Session,
    run_id: str,
    *,
    reversed_by: str,
    reversed_at: datetime | None = None,
) -> tuple[PayrollRun, JournalEntry]:
    """Reverse a posted payroll run and, if paid, its disbursement."""
    _require_idle_session(db)
    reversal_time = reversed_at or datetime.now()
    try:
        with db.begin():
            run = db.get(PayrollRun, run_id)
            if run is None:
                raise PayrollWorkflowError("Payroll run does not exist.")
            if run.reversal_journal_entry_id:
                entry = db.get(JournalEntry, run.reversal_journal_entry_id)
                if entry is None or entry.status != "POSTED":
                    raise PayrollWorkflowError(
                        "Payroll run references a missing or unposted reversal."
                    )
                return run, entry
            if run.status not in {
                "APPROVED",
                "PAID",
                "POSTED - PAYMENT PENDING",
            } or not run.journal_entry_id:
                raise PayrollWorkflowError(
                    "Only posted payroll runs can be reversed."
                )

            digest = _digest(run_id, "reversal")
            original = db.scalar(
                select(JournalEntry)
                .options(selectinload(JournalEntry.lines))
                .where(JournalEntry.entry_id == run.journal_entry_id)
            )
            if original is None:
                raise PayrollWorkflowError(
                    "Payroll posting journal is missing."
                )
            main_reversal = reverse_journal_entry_in_transaction(
                db,
                run.journal_entry_id,
                JournalEntryInput(
                    entry_id=f"JE-REV-{digest}",
                    entry_date=reversal_time.date(),
                    posting_period=f"{reversal_time:%Y-%m}",
                    financial_year=_financial_year(reversal_time.date()),
                    description=f"Payroll reversal {run_id}",
                    source_type="PAYROLL_RUN_REVERSAL",
                    source_id=run_id,
                    created_by=reversed_by,
                    created_at=reversal_time,
                ),
                [
                    f"JL-REV-{digest}-{line_no:02}"
                    for line_no in range(1, len(original.lines) + 1)
                ],
            )
            if run.payment_journal_entry_id:
                payment = db.get(
                    JournalEntry, run.payment_journal_entry_id
                )
                if payment is None:
                    raise PayrollWorkflowError(
                        "Payroll payment journal is missing."
                    )
                payment_with_lines = db.scalar(
                    select(JournalEntry)
                    .options(selectinload(JournalEntry.lines))
                    .where(JournalEntry.entry_id == payment.entry_id)
                )
                if payment_with_lines is None:
                    raise PayrollWorkflowError(
                        "Payroll payment journal is missing."
                    )
                payment_digest = _digest(run_id, "payment-reversal")
                reverse_journal_entry_in_transaction(
                    db,
                    payment.entry_id,
                    JournalEntryInput(
                        entry_id=f"JE-PREV-{payment_digest}",
                        entry_date=reversal_time.date(),
                        posting_period=f"{reversal_time:%Y-%m}",
                        financial_year=_financial_year(
                            reversal_time.date()
                        ),
                        description=f"Payroll payment reversal {run_id}",
                        source_type="SALARY_PAYMENT_REVERSAL",
                        source_id=run_id,
                        created_by=reversed_by,
                        created_at=reversal_time,
                    ),
                    [
                        f"JL-PREV-{payment_digest}-{line_no:02}"
                        for line_no in range(
                            1, len(payment_with_lines.lines) + 1
                        )
                    ],
                )
            run.status = "REVERSED"
            run.reversal_journal_entry_id = main_reversal.entry_id
            run.reversed_by = reversed_by
            run.reversed_at = reversal_time
            db.flush()
            return run, main_reversal
    except IntegrityError as exc:
        raise PayrollWorkflowError(
            f"Payroll reversal could not be saved: {exc.orig}"
        ) from exc
    except LedgerError as exc:
        raise PayrollWorkflowError(str(exc)) from exc
