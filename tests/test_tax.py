from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
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
    StatutoryRate,
    StatutoryRateAudit,
    TaxParameter,
    TaxParameterAudit,
    TaxSlab,
    TaxSlabAudit,
    User,
)
from app.tax_service import (
    TaxConfigurationError,
    build_statutory_report,
    calculate_annual_tds,
    update_statutory_rate,
    update_tax_parameter,
    update_tax_slab,
)
from app.payroll_service import _load_statutory_rates


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
            StatutoryRate(
                parameter="PF_EMPLOYEE_RATE",
                value=Decimal("12"),
                unit="percent of basic",
                note="Test setting",
                effective_from=date(2025, 4, 1),
            )
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
        with pytest.raises(TaxConfigurationError, match="between 0 and 100"):
            update_tax_slab(
                db,
                slab_id="TS-2",
                rate_percent=Decimal("-1"),
                effective_from=effective_change,
                changed_by="U-ADMIN",
            )
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

        changed_cess = update_tax_parameter(
            db,
            parameter="health_education_cess_percent",
            value=Decimal("5"),
            effective_from=effective_change,
            changed_by="U-ADMIN",
        )
        cess_restore_date = changed_cess.effective_from + timedelta(days=1)
        db.rollback()
        changed_cess_result = calculate_annual_tds(
            db,
            annual_gross_income=Decimal("1000000"),
            financial_year="FY2025-26",
            regime="NEW",
            on_date=effective_change,
        )
        assert changed_cess_result["annual_tax"] > changed_result["annual_tax"]
        db.rollback()
        update_tax_parameter(
            db,
            parameter="health_education_cess_percent",
            value=Decimal("4"),
            effective_from=cess_restore_date,
            changed_by="U-ADMIN",
        )
        db.rollback()
        restored_cess_result = calculate_annual_tds(
            db,
            annual_gross_income=Decimal("1000000"),
            financial_year="FY2025-26",
            regime="NEW",
            on_date=cess_restore_date,
        )
        assert restored_cess_result["annual_tax"] == changed_result["annual_tax"]
        db.rollback()

        rate_change_date = effective_change + timedelta(days=2)
        changed_rate = update_statutory_rate(
            db,
            parameter="PF_EMPLOYEE_RATE",
            value=Decimal("10"),
            effective_from=rate_change_date,
            source_note="Test rate change",
            changed_by="U-ADMIN",
        )
        changed_rate_id = changed_rate.id
        db.rollback()
        assert _load_statutory_rates(
            db,
            rate_change_date,
            {"PF_EMPLOYEE_RATE"},
        ) == {"PF_EMPLOYEE_RATE": Decimal("10.0000")}
        db.rollback()
        restored_rate = update_statutory_rate(
            db,
            parameter="PF_EMPLOYEE_RATE",
            value=Decimal("12"),
            effective_from=rate_change_date + timedelta(days=1),
            source_note="Test rate restoration",
            changed_by="U-ADMIN",
        )
        db.rollback()
        assert _load_statutory_rates(
            db,
            rate_change_date + timedelta(days=1),
            {"PF_EMPLOYEE_RATE"},
        ) == {"PF_EMPLOYEE_RATE": Decimal("12.0000")}
        db.rollback()

        restored = update_tax_slab(
            db,
            slab_id=changed_slab_id,
            rate_percent=Decimal("10"),
            effective_from=effective_change + timedelta(days=4),
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
        assert len(db.scalars(select(TaxParameterAudit.audit_id)).all()) == 2
        assert len(db.scalars(select(StatutoryRateAudit.audit_id)).all()) == 2
        assert db.get(StatutoryRate, changed_rate_id).value == Decimal("10.0000")
        assert restored_rate.value == Decimal("12.0000")
        assert db.get(PayrollItem, "PI-TAX").tds == saved_tds
    engine.dispose()


def test_tax_calculation_rejects_overlapping_slab_ranges(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tax-overlap.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                TaxSlab(
                    slab_id="TS-LOW",
                    regime="NEW",
                    financial_year="FY2025-26",
                    income_from=Decimal("0"),
                    income_to=Decimal("100000"),
                    rate_percent=Decimal("0"),
                    effective_from=date(2025, 4, 1),
                ),
                TaxSlab(
                    slab_id="TS-HIGH",
                    regime="NEW",
                    financial_year="FY2025-26",
                    income_from=Decimal("90000"),
                    income_to=None,
                    rate_percent=Decimal("10"),
                    effective_from=date(2025, 4, 1),
                ),
            ]
        )
        db.commit()
        with pytest.raises(TaxConfigurationError, match="gap or overlap"):
            calculate_annual_tds(
                db,
                annual_gross_income=Decimal("1000000"),
                financial_year="FY2025-26",
                regime="NEW",
                on_date=date(2025, 4, 1),
            )
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
