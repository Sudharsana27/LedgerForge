from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    Department,
    Employee,
    JournalEntry,
    PayrollItem,
    PayrollRun,
    Role,
    TaxParameter,
    TaxSlab,
    TaxSlabAudit,
    User,
)
from app.tax_service import (
    build_statutory_report,
    calculate_annual_tds,
    update_tax_slab,
)


def test_tax_slab_versions_recalculate_without_changing_saved_payroll(
    tmp_path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'tax-test.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Department(
                department_id="D01",
                department_name="Finance",
                cost_center="CC01",
            )
        )
        db.flush()
        db.add(
            Role(
                role_id="R01",
                department_id="D01",
                role_title="Finance Associate",
                level=1,
                grade="G1",
                band_min_annual=1,
                band_mid_annual=2,
                band_max_annual=3,
                overtime_eligible="N",
                band_year=2025,
            )
        )
        db.flush()
        db.add(
            Employee(
                employee_id="EMP-1",
                first_name="Tax",
                last_name="Test",
                full_name="Tax Test",
                work_email="tax-test@example.test",
                hire_date=date(2020, 1, 1),
                employment_status="ACTIVE",
                employment_type="FULL_TIME",
                department_id="D01",
                role_id="R01",
                manager_id=None,
                work_location="Chennai",
                work_mode="OFFICE",
                pf_applicable="Y",
                esi_applicable="N",
                notice_period_days=0,
            )
        )
        db.flush()
        db.add(
            User(
                user_id="U-ADMIN",
                employee_id="EMP-1",
                username="admin@example.test",
                role="ADMIN",
                is_active="Y",
                mfa_enabled="N",
                password_hash="not-used-by-this-service-test",
            )
        )
        db.flush()
        db.add_all(
            [
                TaxParameter(
                    parameter="standard_deduction",
                    effective_from=None,
                    value=Decimal("0"),
                    note="Test value",
                ),
                TaxParameter(
                    parameter="rebate_threshold_taxable",
                    effective_from=None,
                    value=Decimal("100000"),
                    note="Test value",
                ),
                TaxParameter(
                    parameter="health_education_cess_percent",
                    effective_from=None,
                    value=Decimal("4"),
                    note="Test value",
                ),
            ]
        )
        db.add_all(
            [
                TaxSlab(
                    slab_id="TS-1",
                    regime="NEW",
                    financial_year="FY2025-26",
                    income_from=Decimal("0"),
                    income_to=Decimal("100000"),
                    rate_percent=Decimal("0"),
                    effective_from=date(2025, 4, 1),
                    note="Test value",
                ),
                TaxSlab(
                    slab_id="TS-2",
                    regime="NEW",
                    financial_year="FY2025-26",
                    income_from=Decimal("100000"),
                    income_to=None,
                    rate_percent=Decimal("10"),
                    effective_from=date(2025, 4, 1),
                    note="Test value",
                ),
            ]
        )
        db.add(
            PayrollRun(
                run_id="PR-TAX",
                period_start=date(2025, 4, 1),
                period_end=date(2025, 4, 30),
                pay_date=date(2025, 5, 1),
                employees_paid=1,
                total_gross=Decimal("1000000.00"),
                total_deductions=Decimal("7800.00"),
                total_net=Decimal("992200.00"),
                total_employer_contributions=Decimal("0.00"),
                total_employer_cost=Decimal("1000000.00"),
                status="PAID",
                run_by="U-ADMIN",
                approved_by="U-ADMIN",
                created_at=datetime(2025, 5, 1),
                approved_at=datetime(2025, 5, 1),
                calculation_version="test",
            )
        )
        db.flush()
        db.add(
            PayrollItem(
                payroll_item_id="PI-TAX",
                run_id="PR-TAX",
                employee_id="EMP-1",
                period_start=date(2025, 4, 1),
                period_end=date(2025, 4, 30),
                department_id="D01",
                role_id="R01",
                calendar_days=30,
                days_employed=30,
                lop_days=Decimal("0"),
                payable_days=Decimal("30"),
                monthly_fixed_gross=Decimal("1000000.00"),
                basic=Decimal("1000000.00"),
                hra=Decimal("0.00"),
                conveyance=Decimal("0.00"),
                medical=Decimal("0.00"),
                special_allowance=Decimal("0.00"),
                earned_fixed_pay=Decimal("1000000.00"),
                overtime_hours_paid=Decimal("0"),
                overtime_pay=Decimal("0.00"),
                variable_pay=Decimal("0.00"),
                variable_pay_type=None,
                gross_pay=Decimal("1000000.00"),
                pf_employee=Decimal("0.00"),
                esi_employee=Decimal("0.00"),
                professional_tax=Decimal("0.00"),
                tds=Decimal("7800.00"),
                other_deductions=Decimal("0.00"),
                total_deductions=Decimal("7800.00"),
                net_pay=Decimal("992200.00"),
                pf_employer=Decimal("0.00"),
                esi_employer=Decimal("0.00"),
                employer_cost=Decimal("1000000.00"),
            )
        )
        db.commit()
        saved_tds = Decimal("7800.00")
        original = calculate_annual_tds(
            db,
            annual_gross_income=Decimal("1000000"),
            financial_year="FY2025-26",
            regime="NEW",
            on_date=date(2025, 4, 1),
        )
        assert original["annual_tax"] == Decimal("93600.00")
        db.rollback()

        effective_change = date.today() + timedelta(days=2)
        changed = update_tax_slab(
            db,
            slab_id="TS-2",
            rate_percent=Decimal("15"),
            effective_from=effective_change,
            changed_by="U-ADMIN",
        )
        changed_slab_id = changed.slab_id
        db.rollback()
        changed_result = calculate_annual_tds(
            db,
            annual_gross_income=Decimal("1000000"),
            financial_year="FY2025-26",
            regime="NEW",
            on_date=effective_change,
        )
        assert changed_result["annual_tax"] == Decimal("140400.00")
        db.rollback()

        restored = update_tax_slab(
            db,
            slab_id=changed_slab_id,
            rate_percent=Decimal("10"),
            effective_from=effective_change + timedelta(days=2),
            changed_by="U-ADMIN",
        )
        db.rollback()
        restored_result = calculate_annual_tds(
            db,
            annual_gross_income=Decimal("1000000"),
            financial_year="FY2025-26",
            regime="NEW",
            on_date=restored.effective_from,
        )
        assert restored_result["annual_tax"] == original["annual_tax"]
        assert db.scalar(select(TaxSlabAudit.audit_id)) is not None
        assert db.get(PayrollItem, "PI-TAX").tds == saved_tds
    engine.dispose()


def test_statutory_reports_sum_posted_payroll_records(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'statutory-test.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Department(
                department_id="D01",
                department_name="Finance",
                cost_center="CC01",
            )
        )
        db.flush()
        db.add(
            Role(
                role_id="R01",
                department_id="D01",
                role_title="Finance Associate",
                level=1,
                grade="G1",
                band_min_annual=1,
                band_mid_annual=2,
                band_max_annual=3,
                overtime_eligible="N",
                band_year=2025,
            )
        )
        db.flush()
        db.add(
            Employee(
                employee_id="EMP-1",
                first_name="Payroll",
                last_name="Test",
                full_name="Payroll Test",
                work_email="payroll-test@example.test",
                hire_date=date(2020, 1, 1),
                employment_status="ACTIVE",
                employment_type="FULL_TIME",
                department_id="D01",
                role_id="R01",
                manager_id=None,
                work_location="Chennai",
                work_mode="OFFICE",
                pf_applicable="Y",
                esi_applicable="N",
                notice_period_days=0,
            )
        )
        db.flush()
        db.add(
            User(
                user_id="U-1",
                employee_id="EMP-1",
                username="payroll@example.test",
                role="HR",
                is_active="Y",
                mfa_enabled="N",
            )
        )
        db.flush()
        db.add(
            JournalEntry(
                entry_id="JE-1",
                entry_date=date(2025, 5, 1),
                posting_period="2025-04",
                financial_year="2025-26",
                description="Payroll test",
                source_type="PAYROLL_RUN",
                source_id="PR-1",
                status="POSTED",
                total_debit=Decimal("100.00"),
                total_credit=Decimal("100.00"),
                reversal_of_source_id=None,
                created_by="test",
                created_at=datetime(2025, 5, 1),
            )
        )
        db.flush()
        db.add(
            PayrollRun(
                run_id="PR-1",
                period_start=date(2025, 4, 1),
                period_end=date(2025, 4, 30),
                pay_date=date(2025, 5, 1),
                employees_paid=1,
                total_gross=Decimal("100.00"),
                total_deductions=Decimal("10.00"),
                total_net=Decimal("90.00"),
                total_employer_contributions=Decimal("20.00"),
                total_employer_cost=Decimal("120.00"),
                status="PAID",
                run_by="U-1",
                approved_by="U-1",
                created_at=datetime(2025, 4, 30),
                approved_at=datetime(2025, 5, 1),
                idempotency_key="payroll-test",
                journal_entry_id="JE-1",
                calculation_version="test",
            )
        )
        db.flush()
        db.add(
            PayrollItem(
                payroll_item_id="PI-1",
                run_id="PR-1",
                employee_id="EMP-1",
                period_start=date(2025, 4, 1),
                period_end=date(2025, 4, 30),
                department_id="D01",
                role_id="R01",
                calendar_days=30,
                days_employed=30,
                lop_days=Decimal("0"),
                payable_days=Decimal("30"),
                monthly_fixed_gross=Decimal("100"),
                basic=Decimal("50"),
                hra=Decimal("20"),
                conveyance=Decimal("10"),
                medical=Decimal("10"),
                special_allowance=Decimal("10"),
                earned_fixed_pay=Decimal("100"),
                overtime_hours_paid=Decimal("0"),
                overtime_pay=Decimal("0"),
                variable_pay=Decimal("0"),
                variable_pay_type=None,
                gross_pay=Decimal("100"),
                pf_employee=Decimal("5"),
                esi_employee=Decimal("1"),
                professional_tax=Decimal("0"),
                tds=Decimal("3"),
                other_deductions=Decimal("1"),
                total_deductions=Decimal("10"),
                net_pay=Decimal("90"),
                pf_employer=Decimal("15"),
                esi_employer=Decimal("5"),
                employer_cost=Decimal("120"),
                calculation_note=None,
            )
        )
        db.commit()

        pf = build_statutory_report(
            db,
            report_type="pf",
            start_date=date(2025, 4, 1),
            end_date=date(2025, 4, 30),
        )
        esi = build_statutory_report(
            db,
            report_type="esi",
            start_date=date(2025, 4, 1),
            end_date=date(2025, 4, 30),
        )
        tds = build_statutory_report(
            db,
            report_type="tds",
            start_date=date(2025, 4, 1),
            end_date=date(2025, 4, 30),
        )
        assert (pf["employee_total"], pf["employer_total"], pf["total"]) == (
            Decimal("5.00"),
            Decimal("15.00"),
            Decimal("20.00"),
        )
        assert (esi["employee_total"], esi["employer_total"], esi["total"]) == (
            Decimal("1.00"),
            Decimal("5.00"),
            Decimal("6.00"),
        )
        assert (tds["employee_total"], tds["employer_total"], tds["total"]) == (
            Decimal("3.00"),
            Decimal("0"),
            Decimal("3.00"),
        )
    engine.dispose()
