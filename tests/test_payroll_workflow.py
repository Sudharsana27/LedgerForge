from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    ChartOfAccount,
    Department,
    Employee,
    JournalEntry,
    JournalLine,
    PayrollItem,
    PayrollRun,
    Role,
    User,
)
from app.payroll_workflow_service import (
    PayrollRunItemInput,
    PayrollWorkflowError,
    create_payroll_run,
)
from app.payroll_workflow_service import (
    approve_payroll_run,
    pay_payroll_run,
    reverse_payroll_run,
)


def _employee(employee_id: str, department_id: str) -> Employee:
    return Employee(
        employee_id=employee_id,
        first_name=employee_id,
        last_name="Test",
        full_name=f"{employee_id} Test",
        work_email=f"{employee_id.lower()}@example.test",
        hire_date=date(2020, 1, 1),
        employment_status="ACTIVE",
        employment_type="FULL_TIME",
        department_id=department_id,
        role_id="R01",
        manager_id=None,
        work_location="Chennai",
        work_mode="OFFICE",
        pf_applicable="Y",
        esi_applicable="N",
        notice_period_days=0,
    )


def test_payroll_post_payment_and_reversal_are_atomic_and_idempotent(
    tmp_path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'payroll-workflow.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
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
        db.add_all(
            [_employee(f"EMP-{index}", "D01") for index in range(1, 4)]
        )
        db.flush()
        db.add_all(
            [
                User(
                    user_id=f"U-{index}",
                    employee_id=f"EMP-{index}",
                    username=f"user-{index}@example.test",
                    role="HR",
                    is_active="Y",
                    mfa_enabled="N",
                )
                for index in range(1, 4)
            ]
        )
        db.add_all(
            [
                ChartOfAccount(
                    account_code=code,
                    account_name=name,
                    account_type=kind,
                    normal_balance=normal,
                    parent_code=None,
                    is_group="N",
                    statement=statement,
                    is_active="Y",
                )
                for code, name, kind, normal, statement in (
                    ("1001", "Bank", "ASSET", "DEBIT", "BALANCE_SHEET"),
                    (
                        "2100",
                        "Net salaries payable",
                        "LIABILITY",
                        "CREDIT",
                        "BALANCE_SHEET",
                    ),
                    (
                        "2110",
                        "PF payable",
                        "LIABILITY",
                        "CREDIT",
                        "BALANCE_SHEET",
                    ),
                    (
                        "5001",
                        "Salary expense",
                        "EXPENSE",
                        "DEBIT",
                        "INCOME_STATEMENT",
                    ),
                    (
                        "5004",
                        "Employer PF expense",
                        "EXPENSE",
                        "DEBIT",
                        "INCOME_STATEMENT",
                    ),
                )
            ]
        )
        db.flush()
        db.add(
            PayrollRun(
                run_id="PR-2025-04",
                period_start=date(2025, 4, 1),
                period_end=date(2025, 4, 30),
                pay_date=date(2025, 5, 1),
                employees_paid=1,
                total_gross=Decimal("1000.00"),
                total_deductions=Decimal("100.00"),
                total_net=Decimal("900.00"),
                total_employer_contributions=Decimal("100.00"),
                total_employer_cost=Decimal("1100.00"),
                status="APPROVED",
                run_by="U-1",
                approved_by="U-2",
                created_at=datetime(2025, 5, 1),
                approved_at=datetime(2025, 5, 1),
            )
        )
        db.flush()
        db.add(
            PayrollItem(
                payroll_item_id="PI-1",
                run_id="PR-2025-04",
                employee_id="EMP-1",
                period_start=date(2025, 4, 1),
                period_end=date(2025, 4, 30),
                department_id="D01",
                role_id="R01",
                calendar_days=30,
                days_employed=30,
                lop_days=Decimal("0"),
                payable_days=Decimal("30"),
                monthly_fixed_gross=Decimal("1000"),
                basic=Decimal("1000"),
                hra=Decimal("0"),
                conveyance=Decimal("0"),
                medical=Decimal("0"),
                special_allowance=Decimal("0"),
                earned_fixed_pay=Decimal("1000"),
                overtime_hours_paid=Decimal("0"),
                overtime_pay=Decimal("0"),
                variable_pay=Decimal("0"),
                variable_pay_type=None,
                gross_pay=Decimal("1000"),
                pf_employee=Decimal("100"),
                esi_employee=Decimal("0"),
                professional_tax=Decimal("0"),
                tds=Decimal("0"),
                other_deductions=Decimal("0"),
                total_deductions=Decimal("100"),
                net_pay=Decimal("900"),
                pf_employer=Decimal("100"),
                esi_employer=Decimal("0"),
                employer_cost=Decimal("1100"),
            )
        )
        db.commit()

        run, posting = approve_payroll_run(
            db, "PR-2025-04", approved_by="U-2"
        )
        assert run.status == "APPROVED"
        assert posting.source_type == "PAYROLL_RUN"
        assert approve_payroll_run(
            db, "PR-2025-04", approved_by="U-2"
        )[1].entry_id == posting.entry_id

        run, payment = pay_payroll_run(
            db,
            "PR-2025-04",
            paid_by="U-2",
            paid_at=datetime(2025, 5, 2),
        )
        assert run.status == "PAID"
        assert payment.source_type == "SALARY_PAYMENT"
        assert pay_payroll_run(
            db, "PR-2025-04", paid_by="U-2"
        )[1].entry_id == payment.entry_id

        run, reversal = reverse_payroll_run(
            db,
            "PR-2025-04",
            reversed_by="U-3",
            reversed_at=datetime(2025, 5, 3),
        )
        assert run.status == "REVERSED"
        assert reversal.source_type == "PAYROLL_RUN_REVERSAL"
        assert reverse_payroll_run(
            db, "PR-2025-04", reversed_by="U-3"
        )[1].entry_id == reversal.entry_id
        assert db.scalar(
            select(JournalEntry.entry_id).where(
                JournalEntry.source_type == "SALARY_PAYMENT_REVERSAL",
                JournalEntry.source_id == "PR-2025-04",
            )
        )
        account_totals = db.execute(
            select(
                JournalLine.account_code,
                JournalLine.debit,
                JournalLine.credit,
            )
        ).all()
        aggregate: dict[str, Decimal] = {}
        for account, debit, credit in account_totals:
            aggregate[account] = aggregate.get(account, Decimal("0")) + (
                Decimal(str(debit)) - Decimal(str(credit))
            )
        assert all(amount == 0 for amount in aggregate.values())
    engine.dispose()


def test_create_payroll_run_saves_calculation_and_validates_idempotency(
    tmp_path,
    monkeypatch,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'payroll-create.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
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
        db.add(_employee("EMP-1", "D01"))
        db.flush()
        db.add(
            User(
                user_id="U-1",
                employee_id="EMP-1",
                username="user-1@example.test",
                role="HR",
                is_active="Y",
                mfa_enabled="N",
            )
        )
        db.commit()

        def calculate(_db, **kwargs):
            return {
                **kwargs,
                "department_id": "D01",
                "role_id": "R01",
                "calendar_days": 30,
                "days_employed": 30,
                "lop_days": Decimal("0"),
                "payable_days": Decimal("30"),
                "monthly_fixed_gross": Decimal("1000.00"),
                "basic": Decimal("1000.00"),
                "hra": Decimal("0.00"),
                "conveyance": Decimal("0.00"),
                "medical": Decimal("0.00"),
                "special_allowance": Decimal("0.00"),
                "earned_fixed_pay": Decimal("1000.00"),
                "overtime_hours_paid": Decimal("0.00"),
                "overtime_pay": Decimal("0.00"),
                "gross_pay": Decimal("1000.00"),
                "pf_employee": Decimal("0.00"),
                "esi_employee": Decimal("0.00"),
                "professional_tax": Decimal("0.00"),
                "total_deductions": Decimal("0.00"),
                "net_pay": Decimal("1000.00"),
                "pf_employer": Decimal("0.00"),
                "esi_employer": Decimal("0.00"),
                "employer_cost": Decimal("1000.00"),
            }

        monkeypatch.setattr(
            "app.payroll_workflow_service.calculate_payroll", calculate
        )
        item = PayrollRunItemInput(
            employee_id="EMP-1",
            variable_pay=Decimal("0.00"),
            variable_pay_type=None,
            tds=Decimal("0.00"),
            other_deductions=Decimal("0.00"),
        )
        values = {
            "period_start": date(2025, 4, 1),
            "period_end": date(2025, 4, 30),
            "pay_date": date(2025, 5, 1),
            "items": [item],
            "run_by": "U-1",
            "idempotency_key": "apr-2025-create",
        }
        run = create_payroll_run(db, **values)
        assert run.status == "DRAFT"
        assert run.total_gross == Decimal("1000.00")
        repeated = create_payroll_run(db, **values)
        assert repeated.run_id == run.run_id
        changed = PayrollRunItemInput(
            employee_id="EMP-1",
            variable_pay=Decimal("10.00"),
            variable_pay_type="Performance Bonus",
            tds=Decimal("0.00"),
            other_deductions=Decimal("0.00"),
        )
        try:
            create_payroll_run(db, **{**values, "items": [changed]})
        except PayrollWorkflowError as exc:
            assert "Idempotency key conflicts" in str(exc)
        else:
            raise AssertionError("A changed request reused an idempotency key.")
    engine.dispose()
