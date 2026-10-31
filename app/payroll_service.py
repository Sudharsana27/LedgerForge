import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.orm import Session

from .models import (
    Attendance,
    Employee,
    EmployeeAssignment,
    Role,
    SalaryComponent,
    SalaryRevision,
    SalaryStructure,
)


class PayrollError(ValueError):
    pass


class PayrollNotFoundError(LookupError):
    pass


MONEY_ZERO = Decimal("0")
MONEY_QUANTUM = Decimal("0.01")
FIXED_COMPONENTS = {
    "BASIC",
    "HRA",
    "CONV",
    "MED",
    "SPECIAL",
}
VARIABLE_PAY_TYPES = {
    "Performance Bonus",
    "Festival Bonus",
    "Sales Incentive",
    "Spot Award",
}
ATTENDANCE_LOP = {
    "ABSENT_LOP": Decimal("1"),
    "HALF_DAY_UNPAID": Decimal("0.5"),
    "UNPAID_LEAVE": Decimal("1"),
}
SUPPORTED_ATTENDANCE_STATUSES = {
    "PRESENT",
    "WFH",
    "PAID_LEAVE",
    *ATTENDANCE_LOP,
}


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _validate_period(period_start: date, period_end: date) -> int:
    if period_start > period_end:
        raise PayrollError("period_start must be on or before period_end")
    if (
        period_start.year != period_end.year
        or period_start.month != period_end.month
    ):
        raise PayrollError("Payroll periods must cover one calendar month")
    calendar_days = calendar.monthrange(
        period_start.year, period_start.month
    )[1]
    if period_start.day != 1 or period_end.day != calendar_days:
        raise PayrollError("Payroll periods must cover a full calendar month")
    return calendar_days


def _load_statutory_rates(
    db: Session,
    period_end: date,
    required_parameters: set[str],
) -> dict[str, Decimal]:
    bind = db.get_bind()
    if not inspect(bind).has_table("statutory_rates"):
        raise PayrollError(
            "Required statutory_rates source table is unavailable"
        )

    table = Table(
        "statutory_rates",
        MetaData(),
        autoload_with=bind,
    )
    rows = db.execute(
        select(
            table.c.parameter,
            table.c.value,
            table.c.effective_from,
        ).where(table.c.effective_from <= period_end)
    ).all()

    latest: dict[str, tuple[date, Decimal]] = {}
    for parameter, value, effective_from in rows:
        if parameter not in required_parameters:
            continue
        amount = Decimal(str(value))
        existing = latest.get(parameter)
        if existing is None or effective_from > existing[0]:
            latest[parameter] = (effective_from, amount)
        elif effective_from == existing[0] and amount != existing[1]:
            raise PayrollError(
                f"Conflicting statutory rates for {parameter} "
                f"effective {effective_from}"
            )

    missing = required_parameters - set(latest)
    if missing:
        raise PayrollError(
            "Missing effective statutory rate(s): "
            + ", ".join(sorted(missing))
        )
    invalid = sorted(
        parameter
        for parameter, (_, value) in latest.items()
        if value < 0
    )
    if invalid:
        raise PayrollError(
            "Statutory rate(s) cannot be negative: "
            + ", ".join(invalid)
        )
    return {parameter: value for parameter, (_, value) in latest.items()}


def calculate_payroll(
    db: Session,
    *,
    employee_id: str,
    period_start: date,
    period_end: date,
    variable_pay: Decimal,
    variable_pay_type: str | None,
    tds: Decimal,
    other_deductions: Decimal,
) -> dict:
    """Calculate one monthly payroll result from effective source records."""
    calendar_days = _validate_period(period_start, period_end)
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise PayrollNotFoundError("Employee not found")
    if employee.pf_applicable not in {"Y", "N"}:
        raise PayrollError("Employee PF applicability must be Y or N")
    if employee.esi_applicable not in {"Y", "N"}:
        raise PayrollError("Employee ESI applicability must be Y or N")

    if variable_pay < 0 or tds < 0 or other_deductions < 0:
        raise PayrollError("Payroll input amounts cannot be negative")
    if variable_pay > 0 and not variable_pay_type:
        raise PayrollError(
            "variable_pay_type is required when variable_pay is positive"
        )
    if variable_pay_type and variable_pay_type not in VARIABLE_PAY_TYPES:
        raise PayrollError(
            "Unsupported variable_pay_type; use a supplied source category"
        )
    if variable_pay_type and variable_pay <= 0:
        raise PayrollError(
            "variable_pay_type is only valid when variable_pay is positive"
        )

    employment_start = max(period_start, employee.hire_date)
    employment_end = min(
        period_end,
        employee.exit_date or period_end,
    )
    if employment_start > employment_end:
        raise PayrollError(
            "Employee was not employed during the requested payroll period"
        )
    days_employed = (employment_end - employment_start).days + 1

    revisions = db.scalars(
        select(SalaryRevision)
        .where(
            SalaryRevision.employee_id == employee_id,
            SalaryRevision.effective_from <= employment_end,
        )
        .order_by(
            SalaryRevision.effective_from.desc(),
            SalaryRevision.revision_id.desc(),
        )
    ).all()
    if not revisions:
        raise PayrollError(
            "No salary revision is effective during the payroll period"
        )
    revision = revisions[0]
    if (
        revision.effective_from > period_start
        and revision.effective_from != employee.hire_date
    ):
        raise PayrollError(
            "A salary revision starts mid-period; split-period salary "
            "changes are not supported"
        )

    structure_rows = db.execute(
        select(SalaryStructure, SalaryComponent)
        .join(
            SalaryComponent,
            SalaryComponent.component_id == SalaryStructure.component_id,
        )
        .where(
            SalaryStructure.employee_id == employee_id,
            SalaryStructure.revision_id == revision.revision_id,
            SalaryStructure.effective_from <= employment_end,
            (
                SalaryStructure.effective_to.is_(None)
                | (SalaryStructure.effective_to >= employment_end)
            ),
            SalaryComponent.component_type == "EARNING",
            SalaryComponent.is_fixed == "Y",
        )
        .order_by(SalaryStructure.component_id)
    ).all()
    if not structure_rows:
        raise PayrollError(
            "No effective fixed salary structure is available"
        )

    component_amounts: dict[str, Decimal] = {}
    for structure, _component in structure_rows:
        if structure.component_id not in FIXED_COMPONENTS:
            raise PayrollError(
                "Unsupported fixed salary component: "
                f"{structure.component_id}"
            )
        if structure.component_id in component_amounts:
            raise PayrollError(
                "Multiple effective salary rows found for component "
                f"{structure.component_id}"
            )
        if structure.effective_from > employment_start:
            raise PayrollError(
                "Salary structure does not cover every employed day "
                "in the payroll period"
            )
        component_amounts[structure.component_id] = Decimal(
            str(structure.monthly_amount)
        )

    if "BASIC" not in component_amounts:
        raise PayrollError("The effective salary structure has no BASIC")
    missing_components = FIXED_COMPONENTS - set(component_amounts)
    if missing_components:
        raise PayrollError(
            "Missing fixed salary component(s): "
            + ", ".join(sorted(missing_components))
        )
    if any(amount < 0 for amount in component_amounts.values()):
        raise PayrollError("Fixed salary components cannot be negative")

    monthly_fixed_gross = sum(component_amounts.values(), MONEY_ZERO)
    if monthly_fixed_gross <= 0:
        raise PayrollError("Monthly fixed gross must be positive")

    attendance_rows = db.scalars(
        select(Attendance)
        .where(
            Attendance.employee_id == employee_id,
            Attendance.attendance_date >= employment_start,
            Attendance.attendance_date <= employment_end,
        )
        .order_by(Attendance.attendance_date, Attendance.attendance_id)
    ).all()
    if not attendance_rows:
        raise PayrollError(
            "No attendance records are available for the employed period"
        )

    seen_dates: set[date] = set()
    lop_days = MONEY_ZERO
    overtime_hours = MONEY_ZERO
    for row in attendance_rows:
        if row.attendance_date in seen_dates:
            raise PayrollError(
                "Duplicate attendance records found for "
                f"{employee_id} on {row.attendance_date}"
            )
        seen_dates.add(row.attendance_date)
        if row.status not in SUPPORTED_ATTENDANCE_STATUSES:
            raise PayrollError(
                f"Unsupported attendance status: {row.status}"
            )
        lop_days += ATTENDANCE_LOP.get(row.status, MONEY_ZERO)
        if row.overtime_hours is not None:
            hours = Decimal(str(row.overtime_hours))
            if hours < 0:
                raise PayrollError(
                    "Attendance overtime hours cannot be negative"
                )
            overtime_hours += hours

    payable_days = Decimal(days_employed) - lop_days
    if payable_days < 0:
        raise PayrollError("Loss-of-pay days exceed days employed")

    proration = payable_days / Decimal(calendar_days)
    earned_components = {
        component_id: _round_money(amount * proration)
        for component_id, amount in component_amounts.items()
    }
    earned_fixed_pay = sum(earned_components.values(), MONEY_ZERO)
    basic = earned_components["BASIC"]

    assignment_rows = db.scalars(
        select(EmployeeAssignment)
        .where(
            EmployeeAssignment.employee_id == employee_id,
            EmployeeAssignment.effective_from <= employment_end,
            (
                EmployeeAssignment.effective_to.is_(None)
                | (EmployeeAssignment.effective_to >= employment_end)
            ),
        )
        .order_by(
            EmployeeAssignment.effective_from.desc(),
            EmployeeAssignment.assignment_id.desc(),
        )
    ).all()
    if len(assignment_rows) > 1:
        raise PayrollError(
            "Multiple employee assignments are effective on the last "
            "employed day"
        )
    if not assignment_rows:
        raise PayrollError(
            "No employee assignment is effective on the last employed day"
        )
    assignment = assignment_rows[0]

    role = db.get(Role, assignment.role_id)
    if role is None:
        raise PayrollError(
            f"Effective assignment role {assignment.role_id} is unavailable"
        )
    if role.overtime_eligible not in {"Y", "N"}:
        raise PayrollError("Role overtime eligibility must be Y or N")
    overtime_eligible = role.overtime_eligible == "Y"
    paid_overtime_hours = MONEY_ZERO
    overtime_pay = MONEY_ZERO
    required_rates = {
        "PF_EMPLOYEE_RATE",
        "PF_EMPLOYER_RATE",
        "PF_WAGE_CEILING",
        "ESI_EMPLOYEE_RATE",
        "ESI_EMPLOYER_RATE",
        "ESI_WAGE_LIMIT",
        "PT_MONTHLY",
        "PT_GROSS_THRESHOLD",
    }
    if overtime_eligible:
        required_rates.update(
            {
                "OT_MULTIPLIER",
                "OT_MONTHLY_CAP_HOURS",
                "WORKING_HOURS_PER_MONTH",
            }
        )
    rates = _load_statutory_rates(db, period_end, required_rates)
    if overtime_eligible:
        if rates["WORKING_HOURS_PER_MONTH"] <= 0:
            raise PayrollError(
                "WORKING_HOURS_PER_MONTH must be greater than zero"
            )
        paid_overtime_hours = min(
            overtime_hours,
            rates["OT_MONTHLY_CAP_HOURS"],
        )
        overtime_pay = _round_money(
            monthly_fixed_gross
            * rates["OT_MULTIPLIER"]
            * paid_overtime_hours
            / rates["WORKING_HOURS_PER_MONTH"]
        )

    gross_pay = earned_fixed_pay + overtime_pay + variable_pay
    pf_employee = MONEY_ZERO
    pf_employer = MONEY_ZERO
    if employee.pf_applicable == "Y":
        pf_basis = min(basic, rates["PF_WAGE_CEILING"])
        pf_employee = _round_money(
            pf_basis * rates["PF_EMPLOYEE_RATE"] / Decimal("100")
        )
        pf_employer = _round_money(
            pf_basis * rates["PF_EMPLOYER_RATE"] / Decimal("100")
        )

    esi_employee = MONEY_ZERO
    esi_employer = MONEY_ZERO
    if (
        employee.esi_applicable == "Y"
        and monthly_fixed_gross <= rates["ESI_WAGE_LIMIT"]
    ):
        esi_employee = _round_money(
            gross_pay * rates["ESI_EMPLOYEE_RATE"] / Decimal("100")
        )
        esi_employer = _round_money(
            gross_pay * rates["ESI_EMPLOYER_RATE"] / Decimal("100")
        )

    professional_tax = (
        rates["PT_MONTHLY"]
        if gross_pay >= rates["PT_GROSS_THRESHOLD"]
        else MONEY_ZERO
    )
    total_deductions = (
        pf_employee
        + esi_employee
        + professional_tax
        + tds
        + other_deductions
    )
    net_pay = gross_pay - total_deductions

    return {
        "employee_id": employee_id,
        "period_start": period_start,
        "period_end": period_end,
        "department_id": assignment.department_id,
        "role_id": assignment.role_id,
        "calendar_days": calendar_days,
        "days_employed": days_employed,
        "lop_days": lop_days,
        "payable_days": payable_days,
        "monthly_fixed_gross": monthly_fixed_gross,
        "basic": earned_components.get("BASIC", MONEY_ZERO),
        "hra": earned_components.get("HRA", MONEY_ZERO),
        "conveyance": earned_components.get("CONV", MONEY_ZERO),
        "medical": earned_components.get("MED", MONEY_ZERO),
        "special_allowance": earned_components.get(
            "SPECIAL", MONEY_ZERO
        ),
        "earned_fixed_pay": earned_fixed_pay,
        "overtime_hours_paid": paid_overtime_hours,
        "overtime_pay": overtime_pay,
        "variable_pay": variable_pay,
        "variable_pay_type": variable_pay_type,
        "gross_pay": gross_pay,
        "pf_employee": pf_employee,
        "esi_employee": esi_employee,
        "professional_tax": professional_tax,
        "tds": tds,
        "other_deductions": other_deductions,
        "total_deductions": total_deductions,
        "net_pay": net_pay,
        "pf_employer": pf_employer,
        "esi_employer": esi_employer,
        "employer_cost": gross_pay + pf_employer + esi_employer,
    }
