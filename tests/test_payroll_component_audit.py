import csv
from decimal import Decimal

from scripts.payroll_component_audit import (
    STATUS_LABEL,
    run_payroll_component_audit,
)


def _write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _audit_source_dir(tmp_path, *, change_reference_basic=False):
    data_dir = tmp_path / "source"
    data_dir.mkdir()
    _write_csv(
        data_dir / "employees.csv",
        ("employee_id", "hire_date", "exit_date", "pf_applicable", "esi_applicable"),
        [
            {
                "employee_id": "EMP-0307",
                "hire_date": "2025-11-01",
                "exit_date": "2025-11-30",
                "pf_applicable": "Y",
                "esi_applicable": "N",
            },
            {
                "employee_id": "EMP-0535",
                "hire_date": "2026-07-01",
                "exit_date": "2026-07-31",
                "pf_applicable": "Y",
                "esi_applicable": "Y",
            },
            {
                "employee_id": "EMP-0566",
                "hire_date": "2026-01-01",
                "exit_date": "2026-01-01",
                "pf_applicable": "N",
                "esi_applicable": "N",
            },
        ],
    )
    _write_csv(
        data_dir / "payroll_runs.csv",
        ("run_id", "period_start", "period_end"),
        [
            {
                "run_id": "PR-2025-11",
                "period_start": "2025-11-01",
                "period_end": "2025-11-30",
            },
            {
                "run_id": "PR-2026-01",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
            {
                "run_id": "PR-2026-07",
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
            },
        ],
    )
    employees = {
        "EMP-0307": ("PR-2025-11", "2025-11-01", "39189", "13", "15000"),
        "EMP-0535": ("PR-2026-07", "2026-07-01", "33926", "19.5", "12000"),
        "EMP-0566": ("PR-2026-01", "2026-01-01", "10000", "0", "5000"),
    }
    component_rows = []
    revision_rows = []
    structure_rows = []
    assignment_rows = []
    attendance_rows = []
    reference_rows = []
    for employee_id, (run_id, effective_from, fixed_gross, hours, basic) in employees.items():
        revision_id = f"REV-{employee_id}"
        revision_rows.append(
            {
                "revision_id": revision_id,
                "employee_id": employee_id,
                "effective_from": effective_from,
            }
        )
        remaining = Decimal(fixed_gross) - Decimal(basic)
        amounts = {
            "BASIC": Decimal(basic),
            "HRA": remaining / 2,
            "CONV": Decimal("0"),
            "MED": Decimal("0"),
            "SPECIAL": remaining / 2,
        }
        for component_id, amount in amounts.items():
            component_rows.append(
                {
                    "component_id": component_id,
                    "component_type": "EARNING",
                    "is_fixed": "Y",
                }
            )
            structure_rows.append(
                {
                    "employee_id": employee_id,
                    "revision_id": revision_id,
                    "component_id": component_id,
                    "monthly_amount": str(amount),
                    "effective_from": effective_from,
                    "effective_to": "",
                }
            )
        assignment_rows.append(
            {
                "employee_id": employee_id,
                "assignment_id": f"ASG-{employee_id}",
                "effective_from": effective_from,
                "effective_to": "",
                "role_id": "R-OT",
            }
        )
        if employee_id != "EMP-0566":
            day = effective_from[:8] + "15"
            attendance_rows.append(
                {
                    "employee_id": employee_id,
                    "attendance_date": day,
                    "status": "PRESENT",
                    "overtime_hours": hours,
                }
            )
        values = {
            "payroll_item_id": f"PI-{employee_id}",
            "employee_id": employee_id,
            "run_id": run_id,
            "basic": basic,
            "hra": str(amounts["HRA"]),
            "conveyance": "0",
            "medical": "0",
            "special_allowance": str(amounts["SPECIAL"]),
            "earned_fixed_pay": fixed_gross,
            "lop_days": "0",
            "overtime_hours_paid": hours,
            "overtime_pay": (
                "4898.62" if employee_id == "EMP-0307"
                else "6361.12" if employee_id == "EMP-0535"
                else "0"
            ),
            "pf_employee": "1800" if employee_id == "EMP-0307" else "1440" if employee_id == "EMP-0535" else "0",
            "pf_employer": "1800" if employee_id == "EMP-0307" else "1440" if employee_id == "EMP-0535" else "0",
            "esi_employee": "236.45" if employee_id == "EMP-0307" else "0",
            "esi_employer": "1024.63" if employee_id == "EMP-0307" else "0",
        }
        if change_reference_basic and employee_id == "EMP-0307":
            values["basic"] = "999999"
        reference_rows.append(values)

    _write_csv(
        data_dir / "salary_revisions.csv",
        ("revision_id", "employee_id", "effective_from"),
        revision_rows,
    )
    _write_csv(
        data_dir / "salary_structures.csv",
        (
            "employee_id",
            "revision_id",
            "component_id",
            "monthly_amount",
            "effective_from",
            "effective_to",
        ),
        structure_rows,
    )
    _write_csv(
        data_dir / "salary_components.csv",
        ("component_id", "component_type", "is_fixed"),
        [
            {"component_id": component_id, "component_type": "EARNING", "is_fixed": "Y"}
            for component_id in ("BASIC", "HRA", "CONV", "MED", "SPECIAL")
        ],
    )
    _write_csv(
        data_dir / "employee_assignments.csv",
        ("employee_id", "assignment_id", "effective_from", "effective_to", "role_id"),
        assignment_rows,
    )
    _write_csv(
        data_dir / "roles.csv",
        ("role_id", "overtime_eligible"),
        [{"role_id": "R-OT", "overtime_eligible": "Y"}],
    )
    _write_csv(
        data_dir / "attendance.csv",
        ("employee_id", "attendance_date", "status", "overtime_hours"),
        attendance_rows,
    )
    _write_csv(
        data_dir / "statutory_rates.csv",
        ("parameter", "value", "effective_from"),
        [
            {"parameter": "PF_EMPLOYEE_RATE", "value": "12", "effective_from": "2025-04-01"},
            {"parameter": "PF_EMPLOYER_RATE", "value": "12", "effective_from": "2025-04-01"},
            {"parameter": "PF_WAGE_CEILING", "value": "15000", "effective_from": "2025-04-01"},
            {"parameter": "OT_MULTIPLIER", "value": "2", "effective_from": "2025-04-01"},
            {"parameter": "OT_MONTHLY_CAP_HOURS", "value": "50", "effective_from": "2025-04-01"},
            {"parameter": "WORKING_HOURS_PER_MONTH", "value": "208", "effective_from": "2025-04-01"},
        ],
    )
    _write_csv(
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
        reference_rows,
    )
    return data_dir


def test_partial_audit_marks_half_cent_rounding_and_esi_conflict(tmp_path):
    data_dir = _audit_source_dir(tmp_path)
    summary = run_payroll_component_audit(
        data_dir=data_dir,
        output_dir=tmp_path / "output",
    )

    assert summary["status"] == STATUS_LABEL
    assert summary["complete_check_2_pass"] is False
    assert summary["source_employee_run_rows"] == 3
    assert summary["overtime_rounding_difference_rows"] == [
        {
            "employee_id": "EMP-0307",
            "run_id": "PR-2025-11",
            "calculated": "4898.63",
            "reference": "4898.62",
            "unrounded": "4898.625",
        },
        {
            "employee_id": "EMP-0535",
            "run_id": "PR-2026-07",
            "calculated": "6361.13",
            "reference": "6361.12",
            "unrounded": "6361.125",
        },
    ]
    assert summary["unresolved_esi_conflict_rows"] == 1
    assert summary["pf_employee_reference_matches"] == 3

    with (tmp_path / "output" / "payroll_component_audit.csv").open(
        encoding="utf-8",
        newline="",
    ) as source:
        rows = {
            (row["employee_id"], row["run_id"]): row
            for row in csv.DictReader(source)
        }
    assert rows[("EMP-0307", "PR-2025-11")]["esi_status"] == (
        "UNRESOLVED_SOURCE_DATA_CONFLICT"
    )
    assert rows[("EMP-0307", "PR-2025-11")]["overtime_pay_comparison_status"] == (
        "ROUNDING_DIFFERENCE_HALF_UP_VS_REFERENCE"
    )


def test_partial_audit_marks_missing_attendance_unavailable(tmp_path):
    data_dir = _audit_source_dir(tmp_path)
    summary = run_payroll_component_audit(
        data_dir=data_dir,
        output_dir=tmp_path / "output",
    )

    with (tmp_path / "output" / "payroll_component_audit.csv").open(
        encoding="utf-8",
        newline="",
    ) as source:
        rows = {
            (row["employee_id"], row["run_id"]): row
            for row in csv.DictReader(source)
        }
    missing = rows[("EMP-0566", "PR-2026-01")]
    assert missing["attendance_status"] == "UNAVAILABLE_MISSING_ATTENDANCE"
    assert missing["fixed_salary_status"] == "UNAVAILABLE_MISSING_ATTENDANCE"
    assert missing["lop_days"] == ""
    assert missing["overtime_hours_paid"] == ""
    assert missing["overtime_pay_calculated"] == ""
    assert missing["pf_employee_calculated"] == "0.00"
    assert summary["attendance_unavailable_rows"] == 1


def test_reference_amounts_are_comparison_only(tmp_path):
    data_dir = _audit_source_dir(tmp_path, change_reference_basic=True)
    summary = run_payroll_component_audit(
        data_dir=data_dir,
        output_dir=tmp_path / "output",
    )
    with (tmp_path / "output" / "payroll_component_audit.csv").open(
        encoding="utf-8",
        newline="",
    ) as source:
        rows = {
            (row["employee_id"], row["run_id"]): row
            for row in csv.DictReader(source)
        }
    row = rows[("EMP-0307", "PR-2025-11")]
    assert row["basic"] == "15000.00"
    assert row["fixed_salary_status"] == "MISMATCH"
    assert summary["payroll_items_used_as_calculation_input"] is False
