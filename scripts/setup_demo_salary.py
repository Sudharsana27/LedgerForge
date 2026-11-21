import argparse
import os
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.config import normalize_database_url
from app.models import (
    Attendance,
    Employee,
    EmployeeAssignment,
    PayrollItem,
    PayrollRun,
    Role,
    SalaryComponent,
    SalaryRevision,
    SalaryStructure,
    StatutoryRate,
)


DATABASE_HOST = "127.0.0.1"
DATABASE_PORT = 55432
DATABASE_NAME = "ledgerforge_demo_test"
HOSTED_DATABASE_NAME = "ledgerforge_wirm"
EMPLOYEE_ID = "DEMOEMP001"
DEPARTMENT_ID = "DEMO01"
ROLE_ID = "DEMO01"
REVISION_ID = "SR-DEMO-2026-11"

COMPONENTS = (
    ("BASIC", "Basic", "EARNING", "Y", "Y"),
    ("HRA", "House Rent Allowance", "EARNING", "Y", "Y"),
    ("CONV", "Conveyance Allowance", "EARNING", "Y", "Y"),
    ("MED", "Medical Allowance", "EARNING", "Y", "Y"),
    ("SPECIAL", "Special Allowance", "EARNING", "Y", "Y"),
)

MONTHLY_COMPONENTS = {
    "BASIC": Decimal("12000"),
    "HRA": Decimal("6000"),
    "CONV": Decimal("1600"),
    "MED": Decimal("1250"),
    "SPECIAL": Decimal("9000"),
}

STATUTORY_RATES = {
    "PF_EMPLOYEE_RATE": ("12", "synthetic local demo"),
    "PF_EMPLOYER_RATE": ("12", "synthetic local demo"),
    "PF_WAGE_CEILING": ("15000", "synthetic local demo"),
    "ESI_EMPLOYEE_RATE": ("0.75", "synthetic local demo"),
    "ESI_EMPLOYER_RATE": ("3.25", "synthetic local demo"),
    "ESI_WAGE_LIMIT": ("21000", "synthetic local demo"),
    "PT_MONTHLY": ("200", "synthetic local demo"),
    "PT_GROSS_THRESHOLD": ("25000", "synthetic local demo"),
}


def validate_target(db: Session) -> None:
    url = engine.url
    if (
        url.drivername != "postgresql+psycopg2"
        or url.host != DATABASE_HOST
        or url.port != DATABASE_PORT
        or url.database != DATABASE_NAME
    ):
        raise RuntimeError(
            "Refusing to run: DATABASE_URL must target the approved "
            "disposable local PostgreSQL database."
        )
    if db.scalar(text("SELECT current_database()")) != DATABASE_NAME:
        raise RuntimeError("Connected database does not match the approved target.")


def validate_hosted_target(db: Session, expected_host: str) -> None:
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        raise RuntimeError(
            "Refusing to run: set the private DATABASE_URL in the process environment."
        )
    url = make_url(normalize_database_url(raw_url))
    if (
        url.drivername != "postgresql+psycopg2"
        or not expected_host
        or url.host != expected_host
        or url.database != HOSTED_DATABASE_NAME
        or url.host in {"localhost", "127.0.0.1", "::1"}
    ):
        raise RuntimeError(
            "Refusing to run: use the exact private hosted PostgreSQL host "
            f"and database {HOSTED_DATABASE_NAME}."
        )
    if url != engine.url:
        raise RuntimeError("DATABASE_URL does not match the application target.")
    if db.scalar(text("SELECT current_database()")) != HOSTED_DATABASE_NAME:
        raise RuntimeError("Connected database name does not match the hosted target.")


def hosted_salary_preflight(db: Session) -> dict[str, int | str]:
    employee = db.get(Employee, EMPLOYEE_ID)
    if employee is None:
        raise RuntimeError("Preflight blocked: DEMOEMP001 does not exist.")
    if employee.department_id != DEPARTMENT_ID or employee.role_id != ROLE_ID:
        raise RuntimeError(
            "Preflight blocked: DEMOEMP001 department/role does not match "
            "the synthetic demo account."
        )
    payroll_item_count = db.scalar(
        select(func.count()).select_from(PayrollItem).where(
            PayrollItem.employee_id == EMPLOYEE_ID
        )
    )
    if payroll_item_count:
        raise RuntimeError(
            "Preflight blocked: DEMOEMP001 already has payroll history."
        )
    revision_count = db.scalar(
        select(func.count()).select_from(SalaryRevision).where(
            SalaryRevision.employee_id == EMPLOYEE_ID
        )
    )
    structure_count = db.scalar(
        select(func.count()).select_from(SalaryStructure).where(
            SalaryStructure.employee_id == EMPLOYEE_ID
        )
    )
    assignment_count = db.scalar(
        select(func.count()).select_from(EmployeeAssignment).where(
            EmployeeAssignment.employee_id == EMPLOYEE_ID
        )
    )
    attendance_count = db.scalar(
        select(func.count()).select_from(Attendance).where(
            Attendance.employee_id == EMPLOYEE_ID,
            Attendance.attendance_date >= date(2026, 11, 1),
            Attendance.attendance_date <= date(2026, 11, 30),
        )
    )
    return {
        "employee": EMPLOYEE_ID,
        "payroll_items": payroll_item_count,
        "salary_revisions": revision_count,
        "salary_structures": structure_count,
        "employee_assignments": assignment_count,
        "november_attendance": attendance_count,
    }


def setup_demo_salary(db: Session) -> dict[str, int]:
    employee = db.get(Employee, EMPLOYEE_ID)
    if employee is None:
        raise RuntimeError("DEMOEMP001 is unavailable; run create_demo_user.py first.")
    if employee.department_id != DEPARTMENT_ID or employee.role_id != ROLE_ID:
        raise RuntimeError("DEMOEMP001 does not match the synthetic demo references.")

    payroll_history = db.scalar(
        select(func.count()).select_from(PayrollItem).where(
            PayrollItem.employee_id == EMPLOYEE_ID
        )
    )
    if payroll_history:
        raise RuntimeError(
            "Refusing to change salary data for an employee with payroll history."
        )

    counts = {"components": 0, "revision": 0, "structures": 0,
              "assignment": 0, "attendance": 0, "rates": 0}

    for component_id, name, component_type, taxable, is_fixed in COMPONENTS:
        component = db.get(SalaryComponent, component_id)
        if component is None:
            db.add(
                SalaryComponent(
                    component_id=component_id,
                    component_name=name,
                    component_type=component_type,
                    taxable=taxable,
                    calculation_rule="monthly fixed amount",
                    is_fixed=is_fixed,
                )
            )
            counts["components"] += 1
        elif (
            component.component_name != name
            or component.component_type != component_type
            or component.taxable != taxable
            or component.is_fixed != is_fixed
        ):
            raise RuntimeError(
                f"Refusing to modify existing salary component {component_id} "
                "because it does not match the synthetic demo definition."
            )

    if db.get(SalaryRevision, REVISION_ID) is None:
        db.add(
            SalaryRevision(
                revision_id=REVISION_ID,
                employee_id=EMPLOYEE_ID,
                effective_from=date(2026, 1, 1),
                revision_reason="Synthetic local demo setup",
                previous_annual_fixed=None,
                new_annual_fixed=Decimal("360000"),
                pct_change=None,
                role_id_after=ROLE_ID,
                approved_by=None,
                created_at=datetime.now(timezone.utc),
            )
        )
        counts["revision"] += 1
    else:
        revision = db.get(SalaryRevision, REVISION_ID)
        if (
            revision.employee_id != EMPLOYEE_ID
            or revision.effective_from != date(2026, 1, 1)
            or revision.new_annual_fixed != Decimal("360000")
            or revision.role_id_after != ROLE_ID
        ):
            raise RuntimeError(
                "Refusing to modify an existing DEMO salary revision "
                "that does not match the synthetic definition."
            )

    for component_id, amount in MONTHLY_COMPONENTS.items():
        existing = db.scalars(
            select(SalaryStructure).where(
                SalaryStructure.employee_id == EMPLOYEE_ID,
                SalaryStructure.component_id == component_id,
                SalaryStructure.revision_id == REVISION_ID,
            )
        ).first()
        if existing is None:
            db.add(
                SalaryStructure(
                    structure_id=f"SS-DEMO-{component_id}",
                    employee_id=EMPLOYEE_ID,
                    component_id=component_id,
                    component_name=dict(
                        (row[0], row[1]) for row in COMPONENTS
                    )[component_id],
                    component_type="EARNING",
                    monthly_amount=amount,
                    effective_from=date(2026, 1, 1),
                    effective_to=None,
                    revision_id=REVISION_ID,
                )
            )
            counts["structures"] += 1

    assignment = db.scalars(
        select(EmployeeAssignment).where(
            EmployeeAssignment.assignment_id == "EA-DEMO-2026-11"
        )
    ).first()
    if assignment is None:
        db.add(
            EmployeeAssignment(
                assignment_id="EA-DEMO-2026-11",
                employee_id=EMPLOYEE_ID,
                effective_from=date(2026, 1, 1),
                effective_to=None,
                department_id=DEPARTMENT_ID,
                role_id=ROLE_ID,
                job_level=1,
                manager_id=None,
                change_reason="Synthetic local demo setup",
            )
        )
        counts["assignment"] += 1

    for day in range(1, 31):
        attendance_date = date(2026, 11, day)
        existing = db.scalars(
            select(Attendance).where(
                Attendance.attendance_id == f"AT-DEMO-202611-{day:02d}"
            )
        ).first()
        if existing is None:
            db.add(
                Attendance(
                    attendance_id=f"AT-DEMO-202611-{day:02d}",
                    employee_id=EMPLOYEE_ID,
                    attendance_date=attendance_date,
                    weekday=attendance_date.strftime("%A").upper(),
                    status="PRESENT",
                    leave_type_code=None,
                    check_in="09:00",
                    check_out="18:00",
                    hours_worked=Decimal("8"),
                    overtime_hours=Decimal("0"),
                    late_flag="N",
                    source="synthetic local demo",
                    data_quality_flag="VERIFIED",
                    department_id=DEPARTMENT_ID,
                )
            )
            counts["attendance"] += 1

    for parameter, (value, note) in STATUTORY_RATES.items():
        existing = db.scalars(
            select(StatutoryRate).where(
                StatutoryRate.parameter == parameter,
                StatutoryRate.effective_from == date(2026, 1, 1),
            )
        ).first()
        if existing is None:
            db.add(
                StatutoryRate(
                    parameter=parameter,
                    value=Decimal(value),
                    unit="synthetic",
                    note=note,
                    effective_from=date(2026, 1, 1),
                )
            )
            counts["rates"] += 1

    db.flush()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up synthetic November 2026 salary data for DEMOEMP001."
    )
    parser.add_argument("--confirm-demo", action="store_true")
    parser.add_argument(
        "--hosted",
        action="store_true",
        help="allow only the explicitly guarded hosted ledgerforge_wirm target",
    )
    parser.add_argument("--expected-host")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="inspect the hosted demo employee without modifying data",
    )
    args = parser.parse_args()

    if args.hosted:
        if not args.expected_host:
            raise SystemExit("Pass --expected-host for hosted mode.")
        with SessionLocal() as db:
            validate_hosted_target(db, args.expected_host)
            preflight = hosted_salary_preflight(db)
        print(
            "Hosted salary preflight: "
            + ", ".join(f"{key}={value}" for key, value in preflight.items())
        )
        if args.preflight_only:
            return
        if not args.confirm_demo:
            raise SystemExit("Pass --confirm-demo to proceed.")
        expected = (
            f"SETUP-DEMO-SALARY {HOSTED_DATABASE_NAME}@{args.expected_host}"
        )
        confirmation = input(
            f"Type {expected} to authorize synthetic salary data for "
            "DEMOEMP001 only: "
        )
        if confirmation != expected:
            raise SystemExit("Cancelled; no hosted changes made.")
        with SessionLocal.begin() as db:
            validate_hosted_target(db, args.expected_host)
            preflight = hosted_salary_preflight(db)
            counts = setup_demo_salary(db)
        print(
            "Hosted synthetic DEMOEMP001 salary setup complete: "
            + ", ".join(f"{key}={value}" for key, value in counts.items())
        )
        return

    if not args.confirm_demo:
        raise SystemExit("Pass --confirm-demo to proceed.")

    with SessionLocal.begin() as db:
        validate_target(db)
        counts = setup_demo_salary(db)
    print(
        "Synthetic DEMOEMP001 salary setup complete: "
        + ", ".join(f"{key}={value}" for key, value in counts.items())
    )


if __name__ == "__main__":
    main()
