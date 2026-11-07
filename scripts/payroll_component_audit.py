import csv
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


STATUS_LABEL = "PARTIAL RECONCILIATION — NOT A COMPLETE CHECK 2 PASS"
CENT = Decimal("0.01")
ZERO = Decimal("0")
FIXED_COMPONENTS = ("BASIC", "HRA", "CONV", "MED", "SPECIAL")
COMPONENT_COLUMNS = {
    "BASIC": "basic",
    "HRA": "hra",
    "CONV": "conveyance",
    "MED": "medical",
    "SPECIAL": "special_allowance",
}
LOP_BY_STATUS = {
    "ABSENT_LOP": Decimal("1"),
    "UNPAID_LEAVE": Decimal("1"),
    "HALF_DAY_UNPAID": Decimal("0.5"),
}
SUPPORTED_ATTENDANCE_STATUSES = {
    "PRESENT",
    "WFH",
    "PAID_LEAVE",
    *LOP_BY_STATUS,
}
RATE_PARAMETERS = (
    "PF_EMPLOYEE_RATE",
    "PF_EMPLOYER_RATE",
    "PF_WAGE_CEILING",
    "OT_MULTIPLIER",
    "OT_MONTHLY_CAP_HOURS",
    "WORKING_HOURS_PER_MONTH",
)
OUTPUT_COLUMNS = (
    "report_status",
    "employee_id",
    "run_id",
    "comparison_reference_payroll_item_id",
    "period_start",
    "period_end",
    "attendance_status",
    "fixed_salary_status",
    "monthly_fixed_gross",
    "basic",
    "hra",
    "conveyance",
    "medical",
    "special_allowance",
    "earned_fixed_pay",
    "lop_days",
    "lop_comparison_status",
    "overtime_hours_paid",
    "overtime_hours_comparison_status",
    "overtime_pay_unrounded",
    "overtime_pay_calculated",
    "comparison_reference_overtime_pay",
    "overtime_pay_comparison_status",
    "pf_employee_calculated",
    "comparison_reference_pf_employee",
    "pf_employee_comparison_status",
    "pf_employer_calculated",
    "comparison_reference_pf_employer",
    "pf_employer_comparison_status",
    "esi_status",
    "comparison_reference_esi_employee",
    "comparison_reference_esi_employer",
    "notes",
)


def _read_csv(
    path: Path,
    required_columns: tuple[str, ...],
) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise ValueError(f"{path.name} has no header row")
            missing = set(required_columns) - set(reader.fieldnames)
            if missing:
                raise ValueError(
                    f"{path.name} is missing required column(s): "
                    + ", ".join(sorted(missing))
                )
            return list(reader)
    except OSError as exc:
        raise ValueError(f"Unable to read {path}: {exc}") from exc


def _decimal(value: str | None, *, field: str) -> Decimal:
    try:
        amount = Decimal((value or "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal amount") from exc
    if not amount.is_finite():
        raise ValueError(f"{field} must be finite")
    return amount


def _date(value: str | None, *, field: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _money(value: Decimal) -> str:
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), ".2f")


def _unique(
    rows: list[dict[str, str]],
    key: str,
    *,
    file_name: str,
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row[key].strip()
        if not value or value in result:
            raise ValueError(f"{file_name} has an empty or duplicate {key}")
        result[value] = row
    return result


def _unique_pair(
    rows: list[dict[str, str]],
    *,
    file_name: str,
) -> dict[tuple[str, str], dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row["employee_id"].strip(), row["run_id"].strip())
        if not all(key) or key in result:
            raise ValueError(
                f"{file_name} has an empty or duplicate employee/run key"
            )
        result[key] = row
    return result


def _effective_rates(
    rows: list[dict[str, str]],
    *,
    period_end: date,
) -> dict[str, Decimal]:
    latest: dict[str, tuple[date, Decimal]] = {}
    for row in rows:
        effective_from = _date(
            row["effective_from"],
            field="statutory_rates.effective_from",
        )
        parameter = row["parameter"].strip()
        if effective_from > period_end or parameter not in RATE_PARAMETERS:
            continue
        value = _decimal(row["value"], field=f"statutory_rates.{parameter}")
        current = latest.get(parameter)
        if current is None or effective_from > current[0]:
            latest[parameter] = (effective_from, value)
        elif effective_from == current[0] and value != current[1]:
            raise ValueError(
                f"Conflicting statutory rates for {parameter} "
                f"effective {effective_from}"
            )
    missing = set(RATE_PARAMETERS) - set(latest)
    if missing:
        raise ValueError(
            "Missing effective statutory rate(s): "
            + ", ".join(sorted(missing))
        )
    return {name: value for name, (_, value) in latest.items()}


def _reference_status(
    calculated: Decimal,
    reference: dict[str, str] | None,
    field: str,
) -> str:
    if reference is None:
        return "REFERENCE_MISSING"
    expected = _decimal(reference[field], field=f"payroll_items.{field}")
    return "MATCH" if calculated == expected else "MISMATCH"


def _fixed_salary(
    employee_id: str,
    employment_start: date,
    employment_end: date,
    revisions: list[dict[str, str]],
    structures: list[dict[str, str]],
    components: dict[str, dict[str, str]],
    period_start: date,
) -> tuple[dict[str, Decimal] | None, Decimal | None, str]:
    effective_revisions = [
        row
        for row in revisions
        if row["employee_id"] == employee_id
        and _date(row["effective_from"], field="salary_revisions.effective_from")
        <= employment_end
    ]
    if not effective_revisions:
        return None, None, "UNAVAILABLE_NO_EFFECTIVE_SALARY_REVISION"
    revision = max(
        effective_revisions,
        key=lambda row: (
            _date(row["effective_from"], field="salary_revisions.effective_from"),
            row["revision_id"],
        ),
    )
    revision_start = _date(
        revision["effective_from"],
        field="salary_revisions.effective_from",
    )
    if revision_start > period_start and revision_start != employment_start:
        return None, None, "UNAVAILABLE_MID_PERIOD_SALARY_REVISION"

    active_rows = [
        row
        for row in structures
        if row["employee_id"] == employee_id
        and row["revision_id"] == revision["revision_id"]
        and row["component_id"] in FIXED_COMPONENTS
        and row["component_id"] in components
        and components[row["component_id"]]["component_type"] == "EARNING"
        and components[row["component_id"]]["is_fixed"] == "Y"
        and _date(
            row["effective_from"],
            field="salary_structures.effective_from",
        )
        <= employment_end
        and (
            not row["effective_to"].strip()
            or _date(
                row["effective_to"],
                field="salary_structures.effective_to",
            )
            >= employment_end
        )
    ]
    amounts: dict[str, Decimal] = {}
    for row in active_rows:
        component_id = row["component_id"]
        if component_id in amounts:
            return None, None, "UNAVAILABLE_MULTIPLE_EFFECTIVE_COMPONENT_ROWS"
        structure_start = _date(
            row["effective_from"],
            field="salary_structures.effective_from",
        )
        if structure_start > employment_start:
            return None, None, "UNAVAILABLE_SALARY_STRUCTURE_GAP"
        amount = _decimal(
            row["monthly_amount"],
            field=f"salary_structures.{component_id}.monthly_amount",
        )
        if amount < ZERO:
            return None, None, "UNAVAILABLE_NEGATIVE_FIXED_COMPONENT"
        amounts[component_id] = amount

    missing = set(FIXED_COMPONENTS) - set(amounts)
    if missing:
        return None, None, "UNAVAILABLE_MISSING_FIXED_COMPONENTS"
    if sum(amounts.values(), ZERO) <= ZERO:
        return None, None, "UNAVAILABLE_NONPOSITIVE_FIXED_GROSS"
    return amounts, sum(amounts.values(), ZERO), "AVAILABLE"


def _format_optional(value: Decimal | None) -> str:
    return "" if value is None else _money(value)


def audit_payroll_components(data_dir: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Reconstruct source-supported payroll components; reference values compare only."""
    data_dir = Path(data_dir)
    employees = _unique(
        _read_csv(
            data_dir / "employees.csv",
            (
                "employee_id",
                "hire_date",
                "exit_date",
                "pf_applicable",
                "esi_applicable",
            ),
        ),
        "employee_id",
        file_name="employees.csv",
    )
    runs = _unique(
        _read_csv(
            data_dir / "payroll_runs.csv",
            ("run_id", "period_start", "period_end"),
        ),
        "run_id",
        file_name="payroll_runs.csv",
    )
    revisions = _read_csv(
        data_dir / "salary_revisions.csv",
        ("revision_id", "employee_id", "effective_from"),
    )
    structures = _read_csv(
        data_dir / "salary_structures.csv",
        (
            "employee_id",
            "revision_id",
            "component_id",
            "monthly_amount",
            "effective_from",
            "effective_to",
        ),
    )
    components = _unique(
        _read_csv(
            data_dir / "salary_components.csv",
            ("component_id", "component_type", "is_fixed"),
        ),
        "component_id",
        file_name="salary_components.csv",
    )
    assignments: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(
        data_dir / "employee_assignments.csv",
        ("employee_id", "assignment_id", "effective_from", "effective_to", "role_id"),
    ):
        assignments[row["employee_id"]].append(row)
    roles = _unique(
        _read_csv(
            data_dir / "roles.csv",
            ("role_id", "overtime_eligible"),
        ),
        "role_id",
        file_name="roles.csv",
    )
    attendance: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(
        data_dir / "attendance.csv",
        ("employee_id", "attendance_date", "status", "overtime_hours"),
    ):
        attendance[row["employee_id"]].append(row)
    statutory_rates = _read_csv(
        data_dir / "statutory_rates.csv",
        ("parameter", "value", "effective_from"),
    )

    reference_items = _unique_pair(
        _read_csv(
            data_dir / "payroll_items.csv",
            (
                "payroll_item_id",
                "employee_id",
                "run_id",
                "basic",
                "hra",
                "conveyance",
                "medical",
                "special_allowance",
                "earned_fixed_pay",
                "lop_days",
                "overtime_hours_paid",
                "overtime_pay",
                "pf_employee",
                "pf_employer",
                "esi_employee",
                "esi_employer",
            ),
        ),
        file_name="payroll_items.csv comparison reference",
    )

    result_rows: list[dict[str, str]] = []
    calculated_keys: set[tuple[str, str]] = set()
    for run_id, run in runs.items():
        period_start = _date(run["period_start"], field="payroll_runs.period_start")
        period_end = _date(run["period_end"], field="payroll_runs.period_end")
        rates = _effective_rates(statutory_rates, period_end=period_end)
        for employee_id, employee in employees.items():
            hire_date = _date(employee["hire_date"], field="employees.hire_date")
            exit_date = (
                _date(employee["exit_date"], field="employees.exit_date")
                if employee["exit_date"].strip()
                else None
            )
            if hire_date > period_end or (
                exit_date is not None and exit_date < period_start
            ):
                continue
            key = (employee_id, run_id)
            calculated_keys.add(key)
            employed_start = max(period_start, hire_date)
            employed_end = min(period_end, exit_date or period_end)
            fixed_amounts, monthly_fixed_gross, fixed_status = _fixed_salary(
                employee_id,
                employed_start,
                employed_end,
                revisions,
                structures,
                components,
                period_start,
            )
            reference = reference_items.get(key)
            notes: list[str] = []
            if reference is None:
                notes.append("No matching payroll_items comparison row")
            attendance_rows = [
                row
                for row in attendance[employee_id]
                if employed_start
                <= _date(row["attendance_date"], field="attendance.attendance_date")
                <= employed_end
            ]
            dates = [
                _date(row["attendance_date"], field="attendance.attendance_date")
                for row in attendance_rows
            ]
            if len(dates) != len(set(dates)):
                raise ValueError(
                    f"Duplicate attendance dates for {employee_id}/{run_id}"
                )
            attendance_status = "AVAILABLE"
            lop_days: Decimal | None = ZERO
            overtime_hours: Decimal | None = ZERO
            if not attendance_rows:
                attendance_status = "UNAVAILABLE_MISSING_ATTENDANCE"
                lop_days = None
                overtime_hours = None
                notes.append(
                    "No attendance row; LOP, earned fixed pay, and overtime "
                    "are unavailable, not assumed zero"
                )
            else:
                for row in attendance_rows:
                    if row["status"] not in SUPPORTED_ATTENDANCE_STATUSES:
                        attendance_status = "UNAVAILABLE_UNSUPPORTED_ATTENDANCE_STATUS"
                        lop_days = None
                        overtime_hours = None
                        notes.append(f"Unsupported attendance status: {row['status']}")
                        break
                    hours = _decimal(
                        row["overtime_hours"],
                        field="attendance.overtime_hours",
                    )
                    if hours < ZERO:
                        raise ValueError("Attendance overtime cannot be negative")
                    assert lop_days is not None and overtime_hours is not None
                    lop_days += LOP_BY_STATUS.get(row["status"], ZERO)
                    overtime_hours += hours

            earned_components: dict[str, Decimal] | None = None
            earned_fixed_pay: Decimal | None = None
            if fixed_amounts is None:
                notes.append(fixed_status)
            elif attendance_status == "AVAILABLE":
                calendar_days = Decimal((period_end - period_start).days + 1)
                days_employed = Decimal((employed_end - employed_start).days + 1)
                assert lop_days is not None
                payable_days = days_employed - lop_days
                if payable_days < ZERO:
                    raise ValueError(f"LOP exceeds days employed for {employee_id}/{run_id}")
                earned_components = {
                    component_id: (amount * payable_days / calendar_days).quantize(
                        CENT,
                        rounding=ROUND_HALF_UP,
                    )
                    for component_id, amount in fixed_amounts.items()
                }
                earned_fixed_pay = sum(earned_components.values(), ZERO)

            assignment_rows = [
                row
                for row in assignments[employee_id]
                if _date(
                    row["effective_from"],
                    field="employee_assignments.effective_from",
                )
                <= employed_end
                and (
                    not row["effective_to"].strip()
                    or _date(
                        row["effective_to"],
                        field="employee_assignments.effective_to",
                    )
                    >= employed_end
                )
            ]
            if len(assignment_rows) != 1:
                overtime_eligible: bool | None = None
                notes.append("Overtime eligibility unavailable: assignment is not unique")
            else:
                role = roles.get(assignment_rows[0]["role_id"])
                if role is None or role["overtime_eligible"] not in {"Y", "N"}:
                    overtime_eligible = None
                    notes.append("Overtime eligibility unavailable: role is missing or invalid")
                else:
                    overtime_eligible = role["overtime_eligible"] == "Y"

            overtime_unrounded: Decimal | None = None
            overtime_calculated: Decimal | None = None
            overtime_hours_paid: Decimal | None = None
            if overtime_hours is not None and overtime_eligible is True:
                overtime_hours_paid = min(
                    overtime_hours,
                    rates["OT_MONTHLY_CAP_HOURS"],
                )
            elif overtime_hours is not None and overtime_eligible is False:
                overtime_hours_paid = ZERO
            if (
                attendance_status == "AVAILABLE"
                and overtime_hours is not None
                and overtime_eligible is not None
                and monthly_fixed_gross is not None
            ):
                if overtime_eligible:
                    if rates["WORKING_HOURS_PER_MONTH"] <= ZERO:
                        raise ValueError("WORKING_HOURS_PER_MONTH must be positive")
                    assert overtime_hours_paid is not None
                    overtime_unrounded = (
                        monthly_fixed_gross
                        * rates["OT_MULTIPLIER"]
                        * overtime_hours_paid
                        / rates["WORKING_HOURS_PER_MONTH"]
                    )
                    overtime_calculated = overtime_unrounded.quantize(
                        CENT,
                        rounding=ROUND_HALF_UP,
                    )
                else:
                    overtime_unrounded = ZERO
                    overtime_calculated = ZERO

            pf_employee: Decimal | None = None
            pf_employer: Decimal | None = None
            pf_flag = employee["pf_applicable"]
            if pf_flag not in {"Y", "N"}:
                notes.append("PF unavailable: employee PF flag is invalid")
            elif pf_flag == "N":
                pf_employee = ZERO
                pf_employer = ZERO
            elif earned_components is not None:
                pf_basis = min(
                    earned_components["BASIC"],
                    rates["PF_WAGE_CEILING"],
                )
                pf_employee = (
                    pf_basis * rates["PF_EMPLOYEE_RATE"] / Decimal("100")
                ).quantize(CENT, rounding=ROUND_HALF_UP)
                pf_employer = (
                    pf_basis * rates["PF_EMPLOYER_RATE"] / Decimal("100")
                ).quantize(CENT, rounding=ROUND_HALF_UP)

            fixed_comparison = "UNAVAILABLE"
            if reference is not None and earned_components is not None:
                fixed_comparison = (
                    "MATCH"
                    if all(
                        earned_components[component_id]
                        == _decimal(
                            reference[column],
                            field=f"payroll_items.{column}",
                        )
                        for component_id, column in COMPONENT_COLUMNS.items()
                    )
                    and earned_fixed_pay
                    == _decimal(
                        reference["earned_fixed_pay"],
                        field="payroll_items.earned_fixed_pay",
                    )
                    else "MISMATCH"
                )
            if fixed_status != "AVAILABLE":
                fixed_comparison = fixed_status
            elif attendance_status != "AVAILABLE":
                fixed_comparison = attendance_status

            def compare_attendance(field: str, calculated: Decimal | None) -> str:
                if calculated is None:
                    return "UNAVAILABLE_MISSING_ATTENDANCE"
                if reference is None:
                    return "REFERENCE_MISSING"
                return _reference_status(calculated, reference, field)

            overtime_comparison = "UNAVAILABLE"
            if overtime_calculated is not None:
                if reference is None:
                    overtime_comparison = "REFERENCE_MISSING"
                else:
                    reference_overtime = _decimal(
                        reference["overtime_pay"],
                        field="payroll_items.overtime_pay",
                    )
                    if overtime_calculated == reference_overtime:
                        overtime_comparison = "MATCH"
                    elif (
                        abs(overtime_calculated - reference_overtime) == CENT
                        and overtime_unrounded is not None
                        and overtime_unrounded % CENT == Decimal("0.005")
                    ):
                        overtime_comparison = (
                            "ROUNDING_DIFFERENCE_HALF_UP_VS_REFERENCE"
                        )
                    else:
                        overtime_comparison = "MISMATCH"

            def pf_comparison(
                field: str,
                calculated: Decimal | None,
            ) -> str:
                if calculated is None:
                    return "UNAVAILABLE_ATTENDANCE_OR_INPUT"
                if reference is None:
                    return "REFERENCE_MISSING"
                return _reference_status(calculated, reference, field)

            esi_status = "NOT_INDEPENDENTLY_CALCULATED"
            if reference is not None and employee["esi_applicable"] == "N":
                reference_esi = _decimal(
                    reference["esi_employee"],
                    field="payroll_items.esi_employee",
                )
                reference_employer_esi = _decimal(
                    reference["esi_employer"],
                    field="payroll_items.esi_employer",
                )
                if reference_esi != ZERO or reference_employer_esi != ZERO:
                    esi_status = "UNRESOLVED_SOURCE_DATA_CONFLICT"
                else:
                    esi_status = "NO_FLAG_CONFLICT_IN_REFERENCE"
            elif reference is None:
                esi_status = "REFERENCE_MISSING"

            row = {
                "report_status": STATUS_LABEL,
                "employee_id": employee_id,
                "run_id": run_id,
                "comparison_reference_payroll_item_id": (
                    reference["payroll_item_id"] if reference else ""
                ),
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "attendance_status": attendance_status,
                "fixed_salary_status": fixed_comparison,
                "monthly_fixed_gross": _format_optional(monthly_fixed_gross),
                "basic": _format_optional(
                    earned_components.get("BASIC") if earned_components else None
                ),
                "hra": _format_optional(
                    earned_components.get("HRA") if earned_components else None
                ),
                "conveyance": _format_optional(
                    earned_components.get("CONV") if earned_components else None
                ),
                "medical": _format_optional(
                    earned_components.get("MED") if earned_components else None
                ),
                "special_allowance": _format_optional(
                    earned_components.get("SPECIAL") if earned_components else None
                ),
                "earned_fixed_pay": _format_optional(earned_fixed_pay),
                "lop_days": _format_optional(lop_days),
                "lop_comparison_status": compare_attendance("lop_days", lop_days),
                "overtime_hours_paid": _format_optional(overtime_hours_paid),
                "overtime_hours_comparison_status": compare_attendance(
                    "overtime_hours_paid",
                    overtime_hours_paid,
                ),
                "overtime_pay_unrounded": (
                    "" if overtime_unrounded is None else str(overtime_unrounded)
                ),
                "overtime_pay_calculated": _format_optional(overtime_calculated),
                "comparison_reference_overtime_pay": (
                    reference["overtime_pay"] if reference else ""
                ),
                "overtime_pay_comparison_status": overtime_comparison,
                "pf_employee_calculated": _format_optional(pf_employee),
                "comparison_reference_pf_employee": (
                    reference["pf_employee"] if reference else ""
                ),
                "pf_employee_comparison_status": pf_comparison(
                    "pf_employee",
                    pf_employee,
                ),
                "pf_employer_calculated": _format_optional(pf_employer),
                "comparison_reference_pf_employer": (
                    reference["pf_employer"] if reference else ""
                ),
                "pf_employer_comparison_status": pf_comparison(
                    "pf_employer",
                    pf_employer,
                ),
                "esi_status": esi_status,
                "comparison_reference_esi_employee": (
                    reference["esi_employee"] if reference else ""
                ),
                "comparison_reference_esi_employer": (
                    reference["esi_employer"] if reference else ""
                ),
                "notes": "; ".join(notes),
            }
            result_rows.append(row)

    unmatched_reference_keys = set(reference_items) - calculated_keys
    status_counts = Counter(row["fixed_salary_status"] for row in result_rows)
    summary: dict[str, Any] = {
        "status": STATUS_LABEL,
        "complete_check_2_pass": False,
        "payroll_items_used_as_calculation_input": False,
        "source_files": [
            "employees.csv",
            "payroll_runs.csv",
            "salary_revisions.csv",
            "salary_structures.csv",
            "salary_components.csv",
            "attendance.csv",
            "employee_assignments.csv",
            "roles.csv",
            "statutory_rates.csv",
        ],
        "comparison_only_file": "payroll_items.csv",
        "source_employee_run_rows": len(result_rows),
        "comparison_reference_rows": len(reference_items),
        "reference_rows_without_source_employee_run": len(unmatched_reference_keys),
        "fixed_component_rows_calculated": sum(
            row["fixed_salary_status"] in {"MATCH", "MISMATCH"}
            for row in result_rows
        ),
        "fixed_component_reference_matches": status_counts["MATCH"],
        "attendance_unavailable_rows": sum(
            row["attendance_status"] != "AVAILABLE" for row in result_rows
        ),
        "lop_source_rows_calculated": sum(
            row["lop_comparison_status"] in {"MATCH", "MISMATCH"}
            for row in result_rows
        ),
        "lop_reference_matches": sum(
            row["lop_comparison_status"] == "MATCH" for row in result_rows
        ),
        "overtime_hours_source_rows_calculated": sum(
            row["overtime_hours_comparison_status"] in {"MATCH", "MISMATCH"}
            for row in result_rows
        ),
        "overtime_hours_reference_matches": sum(
            row["overtime_hours_comparison_status"] == "MATCH"
            for row in result_rows
        ),
        "overtime_pay_calculated_rows": sum(
            row["overtime_pay_calculated"] != "" for row in result_rows
        ),
        "overtime_pay_reference_matches": sum(
            row["overtime_pay_comparison_status"] == "MATCH"
            for row in result_rows
        ),
        "overtime_rounding_difference_rows": [
            {
                "employee_id": row["employee_id"],
                "run_id": row["run_id"],
                "calculated": row["overtime_pay_calculated"],
                "reference": row["comparison_reference_overtime_pay"],
                "unrounded": row["overtime_pay_unrounded"],
            }
            for row in result_rows
            if row["overtime_pay_comparison_status"]
            == "ROUNDING_DIFFERENCE_HALF_UP_VS_REFERENCE"
        ],
        "pf_employee_calculated_rows": sum(
            row["pf_employee_calculated"] != "" for row in result_rows
        ),
        "pf_employee_reference_matches": sum(
            row["pf_employee_comparison_status"] == "MATCH"
            for row in result_rows
        ),
        "pf_employer_calculated_rows": sum(
            row["pf_employer_calculated"] != "" for row in result_rows
        ),
        "pf_employer_reference_matches": sum(
            row["pf_employer_comparison_status"] == "MATCH"
            for row in result_rows
        ),
        "unresolved_esi_conflict_rows": sum(
            row["esi_status"] == "UNRESOLVED_SOURCE_DATA_CONFLICT"
            for row in result_rows
        ),
        "unresolved_esi_conflict_employee_runs": [
            {
                "employee_id": row["employee_id"],
                "run_id": row["run_id"],
            }
            for row in result_rows
            if row["esi_status"] == "UNRESOLVED_SOURCE_DATA_CONFLICT"
        ],
        "not_independently_reconciled": [
            "variable pay",
            "TDS",
            "other deductions",
            "complete gross pay",
            "complete total deductions",
            "net pay",
            "legal correctness of sample statutory rates",
        ],
    }
    return result_rows, summary


def run_payroll_component_audit(
    *,
    data_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "payroll_component_audit.csv"
    summary_path = output_dir / "payroll_component_audit_summary.json"
    existing = [str(path) for path in (csv_path, summary_path) if path.exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite existing output file(s): "
            + ", ".join(existing)
        )
    rows, summary = audit_payroll_components(Path(data_dir))
    with csv_path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    summary["outputs"] = {
        "component_audit_csv": str(csv_path),
        "summary_json": str(summary_path),
    }
    with summary_path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(summary, output, indent=2, ensure_ascii=False)
        output.write("\n")
    return summary


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Create a partial source-based payroll component audit. "
            "This is not a complete Check 2 result."
        )
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        type=Path,
        help="Directory containing the official source CSV files.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory for new payroll_component_audit outputs.",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run_payroll_component_audit(
                data_dir=args.data_dir,
                output_dir=args.output_dir,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
