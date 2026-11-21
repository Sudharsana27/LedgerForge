import argparse
import calendar
import time
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models import (
    Attendance,
    Department,
    Employee,
    EmployeeAssignment,
    PayrollItem,
    PayrollRun,
    Role,
    SalaryComponent,
    SalaryRevision,
    SalaryStructure,
    StatutoryRate,
    User,
)
from app.payroll_service import calculate_payroll
from app.payroll_workflow_service import process_payroll_run


DATABASE_HOST = "127.0.0.1"
DATABASE_PORT = 55434
DATABASE_NAME = "ledgerforge_phase4_benchmark"


def validate(db: Session) -> None:
    url = engine.url
    if (
        url.drivername != "postgresql+psycopg2"
        or url.host != DATABASE_HOST
        or url.port != DATABASE_PORT
        or url.database != DATABASE_NAME
    ):
        raise RuntimeError("Refusing to run outside the disposable benchmark database.")
    if db.scalar(text("SELECT current_database()")) != DATABASE_NAME:
        raise RuntimeError("Connected database does not match benchmark target.")


def seed(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(PayrollRun)) != 0:
        raise RuntimeError("Benchmark database already has payroll runs.")

    db.add(
        Department(
            department_id="DBENCH",
            department_name="Benchmark Department",
            cost_center="BENCH",
            description="Disposable benchmark",
        )
    )
    db.flush()
    db.add(
        Role(
            role_id="RBENCH",
            department_id="DBENCH",
            role_title="Benchmark",
            level=1,
            grade="BENCH",
            band_min_annual=300000,
            band_mid_annual=360000,
            band_max_annual=420000,
            overtime_eligible="N",
            band_year=2025,
        )
    )
    db.flush()
    db.add(
        Employee(
            employee_id="EBENCH",
            first_name="Benchmark",
            last_name="Employee",
            full_name="Benchmark Employee",
            work_email="benchmark@example.invalid",
            hire_date=date(2025, 1, 1),
            employment_status="ACTIVE",
            employment_type="FULL_TIME",
            department_id="DBENCH",
            role_id="RBENCH",
            work_location="Local",
            work_mode="OFFICE",
            pf_applicable="N",
            esi_applicable="N",
            notice_period_days=0,
            created_at=date(2025, 1, 1),
        )
    )
    db.flush()
    db.add(
        User(
            user_id="UBENCH",
            employee_id="EBENCH",
            username="benchmark",
            role="ADMIN",
            is_active="Y",
            mfa_enabled="N",
            password_hash="benchmark-only",
        )
    )
    db.flush()
    db.add(
        EmployeeAssignment(
            assignment_id="A-BENCH",
            employee_id="EBENCH",
            effective_from=date(2025, 1, 1),
            effective_to=None,
            department_id="DBENCH",
            role_id="RBENCH",
            job_level=1,
            manager_id=None,
            change_reason="Disposable benchmark",
        )
    )

    components = (
        ("BASIC", "Basic", "EARNING", "Y", "Y", "12000"),
        ("HRA", "House Rent Allowance", "EARNING", "Y", "Y", "6000"),
        ("CONV", "Conveyance", "EARNING", "Y", "Y", "1600"),
        ("MED", "Medical", "EARNING", "Y", "Y", "1250"),
        ("SPECIAL", "Special", "EARNING", "Y", "Y", "9000"),
    )
    for component_id, name, kind, taxable, fixed, _amount in components:
        db.add(
            SalaryComponent(
                component_id=component_id,
                component_name=name,
                component_type=kind,
                taxable=taxable,
                calculation_rule="monthly fixed amount",
                is_fixed=fixed,
            )
        )
    db.flush()
    db.add(
        SalaryRevision(
            revision_id="SR-BENCH",
            employee_id="EBENCH",
            effective_from=date(2025, 1, 1),
            revision_reason="Disposable benchmark",
            previous_annual_fixed=None,
            new_annual_fixed=Decimal("358200"),
            pct_change=None,
            role_id_after="RBENCH",
            approved_by=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.flush()
    for component_id, name, _kind, _taxable, _fixed, amount in components:
        db.add(
            SalaryStructure(
                structure_id=f"SS-BENCH-{component_id}",
                employee_id="EBENCH",
                component_id=component_id,
                component_name=name,
                component_type="EARNING",
                monthly_amount=Decimal(amount),
                effective_from=date(2025, 1, 1),
                effective_to=None,
                revision_id="SR-BENCH",
            )
        )

    for parameter, value in {
        "PF_EMPLOYEE_RATE": "12",
        "PF_EMPLOYER_RATE": "12",
        "PF_WAGE_CEILING": "15000",
        "ESI_EMPLOYEE_RATE": "0.75",
        "ESI_EMPLOYER_RATE": "3.25",
        "ESI_WAGE_LIMIT": "21000",
        "PT_MONTHLY": "200",
        "PT_GROSS_THRESHOLD": "25000",
    }.items():
        db.add(
            StatutoryRate(
                parameter=parameter,
                value=Decimal(value),
                unit="synthetic",
                note="Disposable benchmark",
                effective_from=date(2025, 1, 1),
            )
        )

    for month_offset in range(18):
        year = 2025 + (month_offset // 12)
        month = month_offset % 12 + 1
        start = date(year, month, 1)
        days = calendar.monthrange(year, month)[1]
        end = date(year, month, days)
        for day in range(1, days + 1):
            attendance_date = date(year, month, day)
            db.add(
                Attendance(
                    attendance_id=f"AT-BENCH-{year}-{month:02d}-{day:02d}",
                    employee_id="EBENCH",
                    attendance_date=attendance_date,
                    weekday=attendance_date.strftime("%A").upper(),
                    status="PRESENT",
                    leave_type_code=None,
                    check_in="09:00",
                    check_out="18:00",
                    hours_worked=Decimal("8"),
                    overtime_hours=Decimal("0"),
                    late_flag="N",
                    source="Disposable benchmark",
                    data_quality_flag="VERIFIED",
                    department_id="DBENCH",
                )
            )
        run_id = f"PR-BENCH-{year}-{month:02d}"
        db.flush()
        calculated = calculate_payroll(
            db,
            employee_id="EBENCH",
            period_start=start,
            period_end=end,
            variable_pay=Decimal("0"),
            variable_pay_type=None,
            tds=Decimal("0"),
            other_deductions=Decimal("0"),
        )
        db.add(
            PayrollRun(
                run_id=run_id,
                period_start=start,
                period_end=end,
                pay_date=end,
                employees_paid=1,
                total_gross=calculated["gross_pay"],
                total_deductions=calculated["total_deductions"],
                total_net=calculated["net_pay"],
                total_employer_contributions=(
                    calculated["pf_employer"] + calculated["esi_employer"]
                ),
                total_employer_cost=calculated["employer_cost"],
                status="DRAFT",
                run_by="UBENCH",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.flush()
        db.add(
            PayrollItem(
                payroll_item_id=f"PI-BENCH-{year}-{month:02d}",
                run_id=run_id,
                employee_id="EBENCH",
                period_start=start,
                period_end=end,
                department_id=calculated["department_id"],
                role_id=calculated["role_id"],
                calendar_days=calculated["calendar_days"],
                days_employed=calculated["days_employed"],
                lop_days=calculated["lop_days"],
                payable_days=calculated["payable_days"],
                monthly_fixed_gross=calculated["monthly_fixed_gross"],
                basic=calculated["basic"],
                hra=calculated["hra"],
                conveyance=calculated["conveyance"],
                medical=calculated["medical"],
                special_allowance=calculated["special_allowance"],
                earned_fixed_pay=calculated["earned_fixed_pay"],
                overtime_hours_paid=calculated["overtime_hours_paid"],
                overtime_pay=calculated["overtime_pay"],
                variable_pay=Decimal("0"),
                variable_pay_type=None,
                gross_pay=calculated["gross_pay"],
                pf_employee=calculated["pf_employee"],
                esi_employee=calculated["esi_employee"],
                professional_tax=calculated["professional_tax"],
                tds=Decimal("0"),
                other_deductions=Decimal("0"),
                total_deductions=calculated["total_deductions"],
                net_pay=calculated["net_pay"],
                pf_employer=calculated["pf_employer"],
                esi_employer=calculated["esi_employer"],
                employer_cost=calculated["employer_cost"],
            )
        )

    db.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-benchmark", action="store_true")
    args = parser.parse_args()
    if not args.confirm_benchmark:
        raise SystemExit("Pass --confirm-benchmark to proceed.")

    with SessionLocal.begin() as db:
        validate(db)
        seed(db)

    completed = 0
    failed = 0
    first_error = None
    started = time.perf_counter()
    with SessionLocal() as db:
        run_ids = list(db.scalars(
            select(PayrollRun.run_id).where(PayrollRun.status == "DRAFT").order_by(
                PayrollRun.period_start, PayrollRun.run_id
            )
        ).all())
        db.rollback()
        for run_id in run_ids:
            db.rollback()
            try:
                process_payroll_run(db, run_id, processed_by="UBENCH")
                completed += 1
            except Exception as exc:
                failed += 1
                if first_error is None:
                    first_error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    print(
        f"runtime_seconds={elapsed:.6f} periods={len(run_ids)} "
        f"throughput_periods_per_second={len(run_ids)/elapsed:.2f} "
        f"completed={completed} failed={failed}"
        + (f" first_error={first_error}" if first_error else "")
    )


if __name__ == "__main__":
    main()
