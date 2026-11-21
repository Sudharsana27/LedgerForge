from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Department,
    Employee,
    PayrollItem,
    PayrollRun,
    Role,
    User,
)
from app.payroll_service import calculate_payroll
from app.payslip_service import build_payslip_result, render_payslip_pdf
from scripts.setup_demo_salary import setup_demo_salary


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    with session.begin() as db:
        db.add(
            Department(
                department_id="DEMO01",
                department_name="Demonstration Department",
                cost_center="DEMO",
                description="Synthetic demonstration data",
            )
        )
        db.add(
            Role(
                role_id="DEMO01",
                department_id="DEMO01",
                role_title="Demo Administrator",
                level=1,
                grade="DEMO",
                band_min_annual=0,
                band_mid_annual=0,
                band_max_annual=0,
                overtime_eligible="N",
                band_year=2026,
            )
        )
        db.add(
            Employee(
                employee_id="DEMOEMP001",
                first_name="Demo",
                last_name="Administrator",
                full_name="Demo Administrator",
                work_email="demo-admin@example.invalid",
                hire_date=date(2026, 1, 1),
                employment_status="ACTIVE",
                employment_type="FULL_TIME",
                department_id="DEMO01",
                role_id="DEMO01",
                work_location="Demo",
                work_mode="REMOTE",
                pf_applicable="N",
                esi_applicable="N",
                notice_period_days=0,
                created_at=date(2026, 1, 1),
            )
        )
        db.add(
            User(
                user_id="DEMOUSER001",
                employee_id="DEMOEMP001",
                username="demo_admin",
                role="ADMIN",
                is_active="Y",
                mfa_enabled="N",
                password_hash="synthetic-test-only",
            )
        )
    return engine, session


def test_demo_salary_setup_is_idempotent_and_payroll_preview_calculates():
    engine, session = _database()
    with session.begin() as db:
        first = setup_demo_salary(db)
    assert sum(first.values()) > 0

    with session.begin() as db:
        second = setup_demo_salary(db)
    assert sum(second.values()) == 0

    with session() as db:
        result = calculate_payroll(
            db,
            employee_id="DEMOEMP001",
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 30),
            variable_pay=Decimal("0"),
            variable_pay_type=None,
            tds=Decimal("0"),
            other_deductions=Decimal("0"),
        )
    assert result["gross_pay"] == Decimal("29850.00")
    assert result["net_pay"] == Decimal("29650.00")
    engine.dispose()


def test_synthetic_demo_payslip_pdf_is_supported():
    engine, session = _database()
    with session.begin() as db:
        setup_demo_salary(db)
        db.add(
            PayrollRun(
                run_id="PR-DEMO-2026-11",
                period_start=date(2026, 11, 1),
                period_end=date(2026, 11, 30),
                pay_date=date(2026, 12, 1),
                employees_paid=1,
                total_gross=Decimal("29850"),
                total_deductions=Decimal("200"),
                total_net=Decimal("29650"),
                total_employer_contributions=Decimal("0"),
                total_employer_cost=Decimal("29850"),
                status="PAID",
                run_by="DEMOUSER001",
                created_at=datetime(2026, 11, 30),
            )
        )
        db.flush()
        db.add(
            PayrollItem(
                payroll_item_id="PI-DEMO-2026-11",
                run_id="PR-DEMO-2026-11",
                employee_id="DEMOEMP001",
                period_start=date(2026, 11, 1),
                period_end=date(2026, 11, 30),
                department_id="DEMO01",
                role_id="DEMO01",
                calendar_days=30,
                days_employed=30,
                lop_days=Decimal("0"),
                payable_days=Decimal("30"),
                monthly_fixed_gross=Decimal("29850"),
                basic=Decimal("12000"),
                hra=Decimal("6000"),
                conveyance=Decimal("1600"),
                medical=Decimal("1250"),
                special_allowance=Decimal("9000"),
                earned_fixed_pay=Decimal("29850"),
                overtime_hours_paid=Decimal("0"),
                overtime_pay=Decimal("0"),
                variable_pay=Decimal("0"),
                variable_pay_type=None,
                gross_pay=Decimal("29850"),
                pf_employee=Decimal("0"),
                esi_employee=Decimal("0"),
                professional_tax=Decimal("200"),
                tds=Decimal("0"),
                other_deductions=Decimal("0"),
                total_deductions=Decimal("200"),
                net_pay=Decimal("29650"),
                pf_employer=Decimal("0"),
                esi_employer=Decimal("0"),
                employer_cost=Decimal("29850"),
            )
        )

    with session() as db:
        payslip = build_payslip_result(
            db,
            employee_id="DEMOEMP001",
            run_id="PR-DEMO-2026-11",
        )
        pdf = render_payslip_pdf(payslip)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
    engine.dispose()
