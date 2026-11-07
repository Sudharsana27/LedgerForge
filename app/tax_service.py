from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    PayrollItem,
    PayrollRun,
    StatutoryRate,
    StatutoryRateAudit,
    TaxParameter,
    TaxParameterAudit,
    TaxSlab,
    TaxSlabAudit,
)


CENT = Decimal("0.01")
ZERO = Decimal("0")
STATUTORY_FIELDS = {
    "pf": ("pf_employee", "pf_employer"),
    "esi": ("esi_employee", "esi_employer"),
    "tds": ("tds", None),
}


class TaxConfigurationError(ValueError):
    pass


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _valid_config_amount(value: Decimal, *, max_integer_digits: int) -> bool:
    if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO:
        return False
    try:
        return (
            value.quantize(Decimal("0.0001")) == value
            and value < Decimal(10) ** max_integer_digits
        )
    except InvalidOperation:
        return False


def _effective_parameters(
    db: Session,
    *,
    on_date: date,
) -> dict[str, TaxParameter]:
    rows = db.scalars(
        select(TaxParameter).where(
            or_(
                TaxParameter.effective_from.is_(None),
                TaxParameter.effective_from <= on_date,
            )
        )
    ).all()
    latest: dict[str, TaxParameter] = {}
    for row in rows:
        current = latest.get(row.parameter)
        if current is None or (
            row.effective_from is not None
            and (
                current.effective_from is None
                or row.effective_from > current.effective_from
            )
        ):
            latest[row.parameter] = row
        elif (
            row.effective_from == current.effective_from
            and row.value != current.value
        ):
            raise TaxConfigurationError(
                f"Conflicting tax parameter values for {row.parameter}."
            )
    return latest


def calculate_annual_tds(
    db: Session,
    *,
    annual_gross_income: Decimal,
    financial_year: str,
    regime: str,
    on_date: date,
) -> dict[str, object]:
    if not annual_gross_income.is_finite() or annual_gross_income < ZERO:
        raise TaxConfigurationError(
            "Annual gross income must be finite and non-negative."
        )
    slabs = db.scalars(
        select(TaxSlab)
        .where(
            TaxSlab.regime == regime,
            TaxSlab.financial_year == financial_year,
            TaxSlab.effective_from <= on_date,
        )
        .order_by(
            TaxSlab.income_from,
            TaxSlab.effective_from.desc(),
            TaxSlab.slab_id,
        )
    ).all()
    effective_slabs: dict[Decimal, TaxSlab] = {}
    for slab in slabs:
        existing = effective_slabs.get(slab.income_from)
        if existing is None:
            effective_slabs[slab.income_from] = slab
        elif (
            existing.effective_from == slab.effective_from
            and existing.rate_percent != slab.rate_percent
        ):
            raise TaxConfigurationError(
                f"Conflicting tax slabs for income from {slab.income_from}."
            )

    ordered_slabs = sorted(
        effective_slabs.values(),
        key=lambda item: item.income_from,
    )
    if not ordered_slabs:
        raise TaxConfigurationError(
            f"No effective {regime} tax slabs exist for {financial_year}."
        )
    cursor = ZERO
    for slab in ordered_slabs:
        if slab.income_from != cursor:
            raise TaxConfigurationError(
                "Tax slab schedule contains a gap or overlap."
            )
        if slab.income_to is None:
            cursor = slab.income_from
        else:
            cursor = slab.income_to
    if ordered_slabs[-1].income_to is not None:
        raise TaxConfigurationError(
            "Tax slab schedule has no final open-ended slab."
        )

    parameters = _effective_parameters(db, on_date=on_date)
    required = {
        "standard_deduction",
        "rebate_threshold_taxable",
        "health_education_cess_percent",
    }
    missing = required - set(parameters)
    if missing:
        raise TaxConfigurationError(
            "Missing tax parameter(s): " + ", ".join(sorted(missing))
        )
    deduction = parameters["standard_deduction"].value
    rebate_threshold = parameters["rebate_threshold_taxable"].value
    cess_percent = parameters["health_education_cess_percent"].value
    if min(deduction, rebate_threshold, cess_percent) < ZERO:
        raise TaxConfigurationError("Tax parameters cannot be negative.")

    taxable_income = max(annual_gross_income - deduction, ZERO)
    tax_before_rebate = ZERO
    for slab in ordered_slabs:
        upper = slab.income_to or taxable_income
        taxable_in_slab = max(
            min(taxable_income, upper) - slab.income_from,
            ZERO,
        )
        tax_before_rebate += (
            taxable_in_slab * slab.rate_percent / Decimal("100")
        )
    if taxable_income <= rebate_threshold:
        tax_after_rebate = ZERO
    else:
        tax_after_rebate = min(
            tax_before_rebate,
            taxable_income - rebate_threshold,
        )
    cess = tax_after_rebate * cess_percent / Decimal("100")
    annual_tax = _money(tax_after_rebate + cess)
    monthly_tds = _money(annual_tax / Decimal("12"))
    sample_data = any(
        "sample" in (slab.note or "").lower()
        or "training" in (slab.note or "").lower()
        for slab in ordered_slabs
    ) or any(
        "sample" in (parameters[name].note or "").lower()
        or "training" in (parameters[name].note or "").lower()
        for name in required
    )
    return {
        "financial_year": financial_year,
        "regime": regime,
        "on_date": on_date,
        "annual_gross_income": annual_gross_income,
        "standard_deduction": deduction,
        "taxable_income": taxable_income,
        "tax_before_rebate": _money(tax_before_rebate),
        "rebate_threshold": rebate_threshold,
        "tax_after_rebate": _money(tax_after_rebate),
        "cess": _money(cess),
        "annual_tax": annual_tax,
        "monthly_tds": monthly_tds,
        "training_sample_configuration": sample_data,
    }


def update_tax_slab(
    db: Session,
    *,
    slab_id: str,
    rate_percent: Decimal,
    effective_from: date,
    changed_by: str,
    changed_at: datetime | None = None,
) -> TaxSlab:
    if db.in_transaction():
        raise TaxConfigurationError(
            "Tax changes require a Session without an active transaction."
        )
    if (
        not _valid_config_amount(rate_percent, max_integer_digits=3)
        or rate_percent > 100
    ):
        raise TaxConfigurationError(
            "Tax slab rate must be finite and between 0 and 100."
        )
    if effective_from <= date.today():
        raise TaxConfigurationError(
            "Tax changes must take effect on a future date."
        )
    try:
        with db.begin():
            source = db.get(TaxSlab, slab_id)
            if source is None:
                raise TaxConfigurationError("Tax slab does not exist.")
            versions = db.scalars(
                select(TaxSlab)
                .where(
                    TaxSlab.regime == source.regime,
                    TaxSlab.financial_year == source.financial_year,
                    TaxSlab.income_from == source.income_from,
                )
                .order_by(TaxSlab.effective_from.desc())
            ).all()
            latest = versions[0]
            if effective_from <= latest.effective_from:
                raise TaxConfigurationError(
                    "A tax slab version must take effect after its latest version."
                )
            updated = TaxSlab(
                slab_id=f"TSV-{uuid4().hex[:16].upper()}",
                regime=source.regime,
                financial_year=source.financial_year,
                income_from=source.income_from,
                income_to=source.income_to,
                rate_percent=rate_percent,
                effective_from=effective_from,
                note=source.note,
            )
            db.add(updated)
            db.add(
                TaxSlabAudit(
                    audit_id=uuid4().hex,
                    slab_id=source.slab_id,
                    previous_rate_percent=latest.rate_percent,
                    new_rate_percent=rate_percent,
                    effective_from=effective_from,
                    changed_by=changed_by,
                    changed_at=changed_at or datetime.now(),
                )
            )
            db.flush()
            return updated
    except IntegrityError as exc:
        raise TaxConfigurationError(
            "Tax slab version conflicts with an existing configuration."
        ) from exc


def update_tax_parameter(
    db: Session,
    *,
    parameter: str,
    value: Decimal,
    effective_from: date,
    changed_by: str,
    changed_at: datetime | None = None,
) -> TaxParameter:
    if db.in_transaction():
        raise TaxConfigurationError(
            "Tax changes require a Session without an active transaction."
        )
    if not _valid_config_amount(value, max_integer_digits=14):
        raise TaxConfigurationError(
            "Tax parameter value must be finite, non-negative, and fit four decimal places."
        )
    if parameter == "health_education_cess_percent" and value > 100:
        raise TaxConfigurationError(
            "Tax cess percent must be between 0 and 100."
        )
    if effective_from <= date.today():
        raise TaxConfigurationError(
            "Tax changes must take effect on a future date."
        )
    try:
        with db.begin():
            versions = db.scalars(
                select(TaxParameter).where(
                    TaxParameter.parameter == parameter
                )
            ).all()
            if not versions:
                raise TaxConfigurationError(
                    "Tax parameter does not exist."
                )
            latest = max(
                versions,
                key=lambda row: row.effective_from or date.min,
            )
            latest_date = latest.effective_from or date.min
            if effective_from <= latest_date:
                raise TaxConfigurationError(
                    "A tax parameter version must take effect after its latest version."
                )
            updated = TaxParameter(
                parameter=parameter,
                effective_from=effective_from,
                value=value,
                note=latest.note,
            )
            db.add(updated)
            db.add(
                TaxParameterAudit(
                    audit_id=uuid4().hex,
                    parameter=parameter,
                    previous_value=latest.value,
                    new_value=value,
                    effective_from=effective_from,
                    changed_by=changed_by,
                    changed_at=changed_at or datetime.now(),
                )
            )
            db.flush()
            return updated
    except IntegrityError as exc:
        raise TaxConfigurationError(
            "Tax parameter version conflicts with an existing configuration."
        ) from exc


def update_statutory_rate(
    db: Session,
    *,
    parameter: str,
    value: Decimal,
    effective_from: date,
    source_note: str,
    changed_by: str,
    changed_at: datetime | None = None,
) -> StatutoryRate:
    if db.in_transaction():
        raise TaxConfigurationError(
            "Statutory rate changes require a Session without an active transaction."
        )
    if not _valid_config_amount(value, max_integer_digits=14):
        raise TaxConfigurationError(
            "Statutory rate must be finite, non-negative, and fit four decimal places."
        )
    if not source_note.strip():
        raise TaxConfigurationError(
            "A source note is required for statutory rate changes."
        )
    if effective_from <= date.today():
        raise TaxConfigurationError(
            "Statutory rate changes must take effect on a future date."
        )
    try:
        with db.begin():
            versions = db.scalars(
                select(StatutoryRate)
                .where(StatutoryRate.parameter == parameter)
                .order_by(
                    StatutoryRate.effective_from.desc(),
                    StatutoryRate.id.desc(),
                )
            ).all()
            if not versions:
                raise TaxConfigurationError(
                    "Statutory rate parameter does not exist."
                )
            latest = versions[0]
            if "percent" in latest.unit.lower() and value > 100:
                raise TaxConfigurationError(
                    "A percentage statutory rate must be between 0 and 100."
                )
            if effective_from <= latest.effective_from:
                raise TaxConfigurationError(
                    "A statutory rate version must take effect after its latest version."
                )
            updated = StatutoryRate(
                parameter=parameter,
                value=value,
                unit=latest.unit,
                note=source_note.strip(),
                effective_from=effective_from,
            )
            db.add(updated)
            db.flush()
            db.add(
                StatutoryRateAudit(
                    audit_id=uuid4().hex,
                    parameter=parameter,
                    previous_value=latest.value,
                    new_value=value,
                    effective_from=effective_from,
                    changed_by=changed_by,
                    changed_at=changed_at or datetime.now(),
                )
            )
            db.flush()
            return updated
    except IntegrityError as exc:
        raise TaxConfigurationError(
            "Statutory rate version conflicts with an existing configuration."
        ) from exc


def build_statutory_report(
    db: Session,
    *,
    report_type: str,
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    if report_type not in STATUTORY_FIELDS:
        raise TaxConfigurationError("Unsupported statutory report type.")
    if start_date > end_date:
        raise TaxConfigurationError(
            "start_date must be on or before end_date."
        )
    employee_field, employer_field = STATUTORY_FIELDS[report_type]
    query = (
        select(PayrollRun, PayrollItem)
        .join(PayrollItem, PayrollItem.run_id == PayrollRun.run_id)
        .where(
            PayrollRun.period_start >= start_date,
            PayrollRun.period_end <= end_date,
            PayrollRun.journal_entry_id.is_not(None),
            PayrollRun.status.in_(
                {"APPROVED", "PAID", "POSTED - PAYMENT PENDING"}
            ),
        )
        .order_by(
            PayrollRun.period_start,
            PayrollItem.employee_id,
        )
    )
    rows = db.execute(query).all()
    employee_monthly: dict[tuple[str, str], list[Decimal]] = defaultdict(
        lambda: [ZERO, ZERO]
    )
    month_totals: dict[str, list[Decimal]] = defaultdict(
        lambda: [ZERO, ZERO]
    )
    for run, item in rows:
        month = run.period_start.strftime("%Y-%m")
        employee_value = Decimal(str(getattr(item, employee_field)))
        employer_value = (
            Decimal(str(getattr(item, employer_field)))
            if employer_field is not None
            else ZERO
        )
        employee_monthly[(item.employee_id, month)][0] += employee_value
        employee_monthly[(item.employee_id, month)][1] += employer_value
        month_totals[month][0] += employee_value
        month_totals[month][1] += employer_value

    employee_totals = [
        {
            "employee_id": employee_id,
            "month": month,
            "employee_amount": values[0],
            "employer_amount": values[1],
            "total": values[0] + values[1],
        }
        for (employee_id, month), values in sorted(employee_monthly.items())
    ]
    monthly = [
        {
            "month": month,
            "employee_total": values[0],
            "employer_total": values[1],
            "total": values[0] + values[1],
        }
        for month, values in sorted(month_totals.items())
    ]
    employee_total = sum(
        (values[0] for values in month_totals.values()),
        ZERO,
    )
    employer_total = sum(
        (values[1] for values in month_totals.values()),
        ZERO,
    )
    return {
        "report_type": report_type.upper(),
        "start_date": start_date,
        "end_date": end_date,
        "employees": employee_totals,
        "monthly": monthly,
        "employee_total": employee_total,
        "employer_total": employer_total,
        "total": employee_total + employer_total,
        "source_row_count": len(rows),
    }
