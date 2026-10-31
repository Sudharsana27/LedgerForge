import calendar
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import (
    Column,
    Date,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
    text,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    Attendance,
    Department,
    Employee,
    EmployeeAssignment,
    LeaveRequest,
    LeaveType,
    Role,
    SalaryComponent,
    SalaryRevision,
    SalaryStructure,
)
from app.payroll_batch import run_batch_validation


PERIOD_START = date(2025, 4, 1)
PERIOD_END = date(2025, 4, 30)


@pytest.fixture
def payroll_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(engine)
    rates = Table(
        "statutory_rates",
        MetaData(),
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("parameter", String, nullable=False),
        Column("value", Numeric(12, 4), nullable=False),
        Column("unit", String, nullable=False),
        Column("note", String, nullable=False),
        Column("effective_from", Date, nullable=False),
    )
    rates.create(engine)

    with engine.begin() as connection:
        for parameter, value in {
            "PF_EMPLOYEE_RATE": "12",
            "PF_EMPLOYER_RATE": "12",
            "PF_WAGE_CEILING": "15000",
            "ESI_EMPLOYEE_RATE": "0.75",
            "ESI_EMPLOYER_RATE": "3.25",
            "ESI_WAGE_LIMIT": "21000",
            "PT_MONTHLY": "200",
            "PT_GROSS_THRESHOLD": "25000",
            "OT_MULTIPLIER": "2",
            "OT_MONTHLY_CAP_HOURS": "50",
            "WORKING_HOURS_PER_MONTH": "208",
        }.items():
            connection.execute(
                rates.insert().values(
                    parameter=parameter,
                    value=Decimal(value),
                    unit="test",
                    note="test",
                    effective_from=date(2025, 4, 1),
                )
            )

    with testing_session() as db:
        db.add(
            Department(
                department_id="D01",
                department_name="Engineering",
                cost_center="CC01",
                description=None,
            )
        )
        db.add(
            Role(
                role_id="R01",
                department_id="D01",
                role_title="Developer",
                level=1,
                grade="G1",
                band_min_annual=300000,
                band_mid_annual=500000,
                band_max_annual=700000,
                overtime_eligible="Y",
                band_year=2025,
            )
        )
        db.add(
            Role(
                role_id="R02",
                department_id="D01",
                role_title="Non-overtime role",
                level=1,
                grade="G1",
                band_min_annual=300000,
                band_mid_annual=500000,
                band_max_annual=700000,
                overtime_eligible="N",
                band_year=2025,
            )
        )
        for employee_id, pf, esi in [
            ("T1", "Y", "N"),
            ("T2", "N", "Y"),
            ("T3", "Y", "N"),
        ]:
            db.add(
                Employee(
                    employee_id=employee_id,
                    first_name="Test",
                    last_name=employee_id,
                    full_name=f"Test {employee_id}",
                    work_email=f"{employee_id.lower()}@example.com",
                    hire_date=date(2024, 1, 1),
                    exit_date=None,
                    employment_status="ACTIVE",
                    employment_type="FULL_TIME",
                    department_id="D01",
                    role_id="R01",
                    manager_id=None,
                    work_location="Chennai",
                    work_mode="OFFICE",
                    pf_applicable=pf,
                    esi_applicable=esi,
                    notice_period_days=30,
                )
            )
        for component_id, name in [
            ("BASIC", "Basic Salary"),
            ("HRA", "House Rent Allowance"),
            ("CONV", "Conveyance Allowance"),
            ("MED", "Medical Allowance"),
            ("SPECIAL", "Special Allowance"),
        ]:
            db.add(
                SalaryComponent(
                    component_id=component_id,
                    component_name=name,
                    component_type="EARNING",
                    taxable="Y",
                    calculation_rule="Source-defined fixed amount",
                    is_fixed="Y",
                )
            )
        db.flush()
        for employee_id in ("T1", "T2", "T3"):
            revision_id = f"SR-{employee_id}"
            db.add(
                SalaryRevision(
                    revision_id=revision_id,
                    employee_id=employee_id,
                    effective_from=date(2024, 1, 1),
                    revision_reason="Joining",
                    previous_annual_fixed=None,
                    new_annual_fixed=Decimal("360000"),
                    pct_change=None,
                    role_id_after="R01",
                    approved_by=None,
                    created_at=datetime(2024, 1, 1),
                )
            )
            for component_id, amount in [
                ("BASIC", "12000"),
                ("HRA", "6000"),
                ("CONV", "1600"),
                ("MED", "1250"),
                ("SPECIAL", "9150"),
            ]:
                db.add(
                    SalaryStructure(
                        structure_id=f"SS-{employee_id}-{component_id}",
                        employee_id=employee_id,
                        component_id=component_id,
                        component_name=component_id,
                        component_type="EARNING",
                        monthly_amount=Decimal(amount),
                        effective_from=date(2024, 1, 1),
                        effective_to=None,
                        revision_id=revision_id,
                    )
                )
            db.add(
                EmployeeAssignment(
                    assignment_id=f"AS-{employee_id}",
                    employee_id=employee_id,
                    effective_from=date(2024, 1, 1),
                    effective_to=None,
                    department_id="D01",
                    role_id="R01",
                    job_level=1,
                    manager_id=None,
                    change_reason="Joining",
                )
            )
            for day in range(1, calendar.monthrange(2025, 4)[1] + 1):
                db.add(
                    Attendance(
                        attendance_id=f"A-{employee_id}-{day:02}",
                        employee_id=employee_id,
                        attendance_date=date(2025, 4, day),
                        weekday=date(2025, 4, day).strftime("%a"),
                        status="PRESENT",
                        leave_type_code=None,
                        check_in=None,
                        check_out=None,
                        hours_worked=Decimal("8"),
                        overtime_hours=Decimal("0"),
                        late_flag="N",
                        source="test",
                        data_quality_flag=None,
                        department_id="D01",
                    )
                )
        db.commit()

    def override_get_db():
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), testing_session
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        rates.drop(engine)
        engine.dispose()


def payload(**updates):
    values = {
        "employee_id": "T1",
        "period_start": "2025-04-01",
        "period_end": "2025-04-30",
        "variable_pay": "200",
        "variable_pay_type": "Performance Bonus",
        "tds": "100",
        "other_deductions": "50",
    }
    values.update(updates)
    return values


def test_payroll_calculates_gross_deductions_and_net(payroll_client):
    client, _ = payroll_client
    response = client.post("/payroll/calculate", json=payload())
    repeated = client.post("/payroll/calculate", json=payload())

    assert response.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json() == response.json()
    result = response.json()
    assert Decimal(result["monthly_fixed_gross"]) == Decimal("30000")
    assert Decimal(result["earned_fixed_pay"]) == Decimal("30000")
    assert Decimal(result["overtime_pay"]) == 0
    assert Decimal(result["gross_pay"]) == Decimal("30200")
    assert Decimal(result["pf_employee"]) == Decimal("1440")
    assert Decimal(result["professional_tax"]) == Decimal("200")
    assert Decimal(result["tds"]) == Decimal("100")
    assert Decimal(result["other_deductions"]) == Decimal("50")
    assert Decimal(result["total_deductions"]) == Decimal("1790")
    assert Decimal(result["net_pay"]) == Decimal("28410")
    assert Decimal(result["employer_cost"]) == Decimal("31640")


def test_half_day_and_full_day_unpaid_attendance_reduce_payroll(
    payroll_client,
):
    client, sessions = payroll_client
    with sessions() as db:
        db.query(Attendance).filter_by(
            employee_id="T1", attendance_date=date(2025, 4, 2)
        ).one().status = "HALF_DAY_UNPAID"
        db.query(Attendance).filter_by(
            employee_id="T1", attendance_date=date(2025, 4, 3)
        ).one().status = "ABSENT_LOP"
        db.commit()

    result = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    ).json()
    assert Decimal(result["lop_days"]) == Decimal("1.5")
    assert Decimal(result["payable_days"]) == Decimal("28.5")
    assert Decimal(result["earned_fixed_pay"]) == Decimal("28500")


def test_unpaid_leave_reduces_payable_days_by_one(payroll_client):
    client, sessions = payroll_client
    with sessions() as db:
        db.query(Attendance).filter_by(
            employee_id="T1", attendance_date=date(2025, 4, 2)
        ).one().status = "UNPAID_LEAVE"
        db.commit()

    result = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    ).json()
    assert Decimal(result["lop_days"]) == Decimal("1")
    assert Decimal(result["payable_days"]) == Decimal("29")
    assert Decimal(result["earned_fixed_pay"]) == Decimal("29000")


@pytest.mark.parametrize(
    ("request_status", "attendance_day"),
    [
        ("PENDING", 2),
        ("REJECTED", 3),
        ("CANCELLED", 4),
    ],
)
def test_paid_leave_attendance_is_not_reinterpreted_from_request_status(
    payroll_client,
    request_status,
    attendance_day,
):
    client, sessions = payroll_client
    leave_date = date(2025, 4, attendance_day)
    with sessions() as db:
        db.add(
            LeaveType(
                leave_type_code="CL",
                leave_type_name="Casual Leave",
                pay_type="PAID",
                annual_quota_days=12,
                prorated_for_joiners="Y",
                carry_forward_allowed="N",
                max_carry_forward_days=0,
                policy_note="Test leave type",
            )
        )
        db.add(
            LeaveRequest(
                leave_request_id=f"LR-{request_status}",
                employee_id="T1",
                leave_type_code="CL",
                entitlement_reference=None,
                start_date=leave_date,
                end_date=leave_date,
                days=Decimal("1"),
                reason="Test payroll attendance handling",
                status=request_status,
                applied_on=date(2025, 3, 30),
                approver_id=None,
                decided_on=None,
            )
        )
        db.query(Attendance).filter_by(
            employee_id="T1",
            attendance_date=leave_date,
        ).one().status = "PAID_LEAVE"
        db.commit()

    result = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    ).json()
    assert Decimal(result["lop_days"]) == Decimal("0")
    assert Decimal(result["payable_days"]) == Decimal("30")
    assert Decimal(result["earned_fixed_pay"]) == Decimal("30000")


def test_fixed_component_proration_uses_source_currency_rounding(
    payroll_client,
):
    client, sessions = payroll_client
    with sessions() as db:
        db.query(SalaryStructure).filter_by(
            employee_id="T1",
            component_id="SPECIAL",
        ).one().monthly_amount = Decimal("0.01")
        for day in range(1, 16):
            db.query(Attendance).filter_by(
                employee_id="T1",
                attendance_date=date(2025, 4, day),
            ).one().status = "ABSENT_LOP"
        db.commit()
    result = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    ).json()
    assert Decimal(result["payable_days"]) == Decimal("15")
    assert Decimal(result["special_allowance"]) == Decimal("0.01")


def test_overtime_is_calculated_and_capped_from_attendance(payroll_client):
    client, sessions = payroll_client
    with sessions() as db:
        for row in db.query(Attendance).filter_by(employee_id="T1"):
            row.overtime_hours = Decimal("2")
        db.commit()

    result = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    ).json()
    assert Decimal(result["overtime_hours_paid"]) == Decimal("50")
    assert Decimal(result["overtime_pay"]) == (
        (
            Decimal("30000") * Decimal("2") * Decimal("50")
            / Decimal("208")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


@pytest.mark.parametrize(
    ("special_amount", "expected_gross", "expected_tax"),
    [
        ("4149.99", Decimal("24999.99"), Decimal("0")),
        ("4150", Decimal("25000"), Decimal("200")),
    ],
)
def test_professional_tax_threshold_is_inclusive(
    payroll_client,
    special_amount,
    expected_gross,
    expected_tax,
):
    client, sessions = payroll_client
    monthly_amounts = {
        "BASIC": "12000",
        "HRA": "6000",
        "CONV": "1600",
        "MED": "1250",
        "SPECIAL": special_amount,
    }
    with sessions() as db:
        for component_id, amount in monthly_amounts.items():
            db.query(SalaryStructure).filter_by(
                employee_id="T1",
                component_id=component_id,
            ).one().monthly_amount = Decimal(amount)
        db.commit()

    result = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    ).json()
    assert Decimal(result["gross_pay"]) == expected_gross
    assert Decimal(result["professional_tax"]) == expected_tax


def test_effective_statutory_rates_use_latest_rate_not_after_period(
    payroll_client,
):
    client, sessions = payroll_client
    with sessions() as db:
        db.execute(
            text(
                "INSERT INTO statutory_rates "
                "(parameter, value, unit, note, effective_from) "
                "VALUES ('PT_MONTHLY', 250, 'test', 'effective in period', "
                "'2025-04-15')"
            )
        )
        db.execute(
            text(
                "INSERT INTO statutory_rates "
                "(parameter, value, unit, note, effective_from) "
                "VALUES ('PT_MONTHLY', 500, 'test', 'future rate', "
                "'2025-05-01')"
            )
        )
        db.commit()

    response = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    )
    assert response.status_code == 200
    assert Decimal(response.json()["professional_tax"]) == Decimal("250")


def test_conflicting_statutory_rates_on_same_effective_date_fail(
    payroll_client,
):
    client, sessions = payroll_client
    with sessions() as db:
        db.execute(
            text(
                "INSERT INTO statutory_rates "
                "(parameter, value, unit, note, effective_from) "
                "VALUES ('PT_MONTHLY', 201, 'test', 'conflicting rate', "
                "'2025-04-01')"
            )
        )
        db.commit()

    response = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    )
    assert response.status_code == 422
    assert "Conflicting statutory rates for PT_MONTHLY" in response.json()[
        "detail"
    ]


@pytest.mark.parametrize(
    (
        "source_item_id",
        "monthly_fixed_gross",
        "overtime_hours",
        "lop_statuses",
        "exact_overtime",
        "source_overtime",
    ),
    [
        (
            "PI-002908",
            Decimal("39189"),
            Decimal("13"),
            (),
            Decimal("4898.625"),
            Decimal("4898.62"),
        ),
        (
            "PI-006310",
            Decimal("33926"),
            Decimal("19.5"),
            ("ABSENT_LOP", "HALF_DAY_UNPAID"),
            Decimal("6361.125"),
            Decimal("6361.12"),
        ),
    ],
)
def test_source_overtime_half_cent_cases_preserve_half_up_rounding(
    payroll_client,
    source_item_id,
    monthly_fixed_gross,
    overtime_hours,
    lop_statuses,
    exact_overtime,
    source_overtime,
):
    client, sessions = payroll_client
    monthly_amounts = {
        "BASIC": monthly_fixed_gross / Decimal("2"),
        "HRA": monthly_fixed_gross / Decimal("4"),
        "CONV": Decimal("1600"),
        "MED": Decimal("1250"),
        "SPECIAL": (
            monthly_fixed_gross
            - monthly_fixed_gross / Decimal("2")
            - monthly_fixed_gross / Decimal("4")
            - Decimal("2850")
        ),
    }
    with sessions() as db:
        for component_id, amount in monthly_amounts.items():
            db.query(SalaryStructure).filter_by(
                employee_id="T1",
                component_id=component_id,
            ).one().monthly_amount = amount
        for day, status in enumerate(lop_statuses, start=1):
            db.query(Attendance).filter_by(
                employee_id="T1",
                attendance_date=date(2025, 4, day),
            ).one().status = status
        db.query(Attendance).filter_by(
            employee_id="T1",
            attendance_date=date(2025, 4, 5),
        ).one().overtime_hours = overtime_hours
        db.commit()

    result = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    )
    assert result.status_code == 200, (source_item_id, result.text)
    overtime = Decimal(result.json()["overtime_pay"])
    assert overtime == exact_overtime.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    assert overtime - source_overtime == Decimal("0.01")


def test_payroll_uses_employee_pf_esi_flags_and_esi_threshold(payroll_client):
    client, sessions = payroll_client
    above_esi_limit = client.post(
        "/payroll/calculate",
        json=payload(
            employee_id="T2",
            variable_pay="0",
            variable_pay_type=None,
            tds="0",
            other_deductions="0",
        ),
    )
    assert above_esi_limit.status_code == 200
    assert Decimal(above_esi_limit.json()["esi_employee"]) == 0

    with sessions() as db:
        db.query(SalaryStructure).filter_by(employee_id="T2").filter(
            SalaryStructure.component_id == "BASIC"
        ).one().monthly_amount = Decimal("8000")
        db.query(SalaryStructure).filter_by(employee_id="T2").filter(
            SalaryStructure.component_id == "HRA"
        ).one().monthly_amount = Decimal("4000")
        db.query(SalaryStructure).filter_by(employee_id="T2").filter(
            SalaryStructure.component_id == "CONV"
        ).one().monthly_amount = Decimal("1000")
        db.query(SalaryStructure).filter_by(employee_id="T2").filter(
            SalaryStructure.component_id == "MED"
        ).one().monthly_amount = Decimal("1000")
        db.query(SalaryStructure).filter_by(employee_id="T2").filter(
            SalaryStructure.component_id == "SPECIAL"
        ).one().monthly_amount = Decimal("6000")
        db.commit()
    esi_response = client.post(
        "/payroll/calculate",
        json=payload(
            employee_id="T2",
            variable_pay="0",
            variable_pay_type=None,
            tds="0",
            other_deductions="0",
        ),
    )
    assert esi_response.status_code == 200
    assert Decimal(esi_response.json()["pf_employee"]) == 0
    assert Decimal(esi_response.json()["esi_employee"]) == Decimal("150")
    assert Decimal(esi_response.json()["esi_employer"]) == Decimal("650")


def test_esi_flag_n_remains_zero_below_threshold_despite_source_conflicts(
    payroll_client,
):
    client, sessions = payroll_client
    monthly_amounts = {
        "BASIC": "8000",
        "HRA": "4000",
        "CONV": "1000",
        "MED": "1000",
        "SPECIAL": "6000",
    }
    with sessions() as db:
        for component_id, amount in monthly_amounts.items():
            db.query(SalaryStructure).filter_by(
                employee_id="T1",
                component_id=component_id,
            ).one().monthly_amount = Decimal(amount)
        db.commit()

    response = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    )
    assert response.status_code == 200
    assert Decimal(response.json()["monthly_fixed_gross"]) == Decimal(
        "20000"
    )
    assert Decimal(response.json()["esi_employee"]) == Decimal("0")
    assert Decimal(response.json()["esi_employer"]) == Decimal("0")


def test_positive_variable_pay_requires_type(payroll_client):
    client, _ = payroll_client
    response = client.post(
        "/payroll/calculate",
        json=payload(variable_pay_type=None),
    )
    assert response.status_code == 422


def test_variable_pay_type_must_use_a_source_category(payroll_client):
    client, _ = payroll_client
    response = client.post(
        "/payroll/calculate",
        json=payload(variable_pay_type="Unlisted bonus"),
    )
    assert response.status_code == 422


def test_tds_and_other_deductions_must_be_explicit(payroll_client):
    client, _ = payroll_client
    values = payload()
    del values["tds"]
    response = client.post("/payroll/calculate", json=values)
    assert response.status_code == 422


def test_missing_attendance_fails_explicitly(payroll_client):
    client, sessions = payroll_client
    with sessions() as db:
        db.query(Attendance).filter_by(employee_id="T1").delete()
        db.commit()
    response = client.post("/payroll/calculate", json=payload())
    assert response.status_code == 422
    assert "No attendance records" in response.json()["detail"]


def test_pi_003864_emp_0566_missing_attendance_fails_without_inference(
    payroll_client,
):
    client, sessions = payroll_client
    with sessions() as db:
        db.add(
            Employee(
                employee_id="EMP-0566",
                first_name="Source",
                last_name="Employee",
                full_name="Source Employee",
                work_email="emp-0566@example.com",
                hire_date=date(2026, 1, 1),
                exit_date=None,
                employment_status="ACTIVE",
                employment_type="FULL_TIME",
                department_id="D01",
                role_id="R02",
                manager_id=None,
                work_location="Chennai",
                work_mode="OFFICE",
                pf_applicable="N",
                esi_applicable="N",
                notice_period_days=30,
            )
        )
        db.add(
            SalaryRevision(
                revision_id="SR-EMP-0566",
                employee_id="EMP-0566",
                effective_from=date(2024, 1, 1),
                revision_reason="Source payroll test",
                previous_annual_fixed=None,
                new_annual_fixed=Decimal("285732"),
                pct_change=None,
                role_id_after="R02",
                approved_by=None,
                created_at=datetime(2024, 1, 1),
            )
        )
        source_components = {
            "BASIC": "9524",
            "HRA": "4762",
            "CONV": "1600",
            "MED": "1250",
            "SPECIAL": "6675",
        }
        for component_id, amount in source_components.items():
            db.add(
                SalaryStructure(
                    structure_id=f"SS-EMP-0566-{component_id}",
                    employee_id="EMP-0566",
                    component_id=component_id,
                    component_name=component_id,
                    component_type="EARNING",
                    monthly_amount=Decimal(amount),
                    effective_from=date(2024, 1, 1),
                    effective_to=None,
                    revision_id="SR-EMP-0566",
                )
            )
        db.add(
            EmployeeAssignment(
                assignment_id="AS-EMP-0566",
                employee_id="EMP-0566",
                effective_from=date(2024, 1, 1),
                effective_to=None,
                department_id="D01",
                role_id="R02",
                job_level=1,
                manager_id=None,
                change_reason="Source payroll test",
            )
        )
        db.commit()

    response = client.post(
        "/payroll/calculate",
        json=payload(
            employee_id="EMP-0566",
            period_start="2026-01-01",
            period_end="2026-01-31",
            variable_pay="0",
            variable_pay_type=None,
            tds="0",
            other_deductions="0",
        ),
    )
    assert response.status_code == 422
    assert "No attendance records" in response.json()["detail"]


def test_missing_salary_structure_fails_explicitly(payroll_client):
    client, sessions = payroll_client
    with sessions() as db:
        db.query(SalaryStructure).filter_by(employee_id="T1").delete()
        db.commit()
    response = client.post("/payroll/calculate", json=payload())
    assert response.status_code == 422
    assert "No effective fixed salary structure" in response.json()["detail"]


def test_incomplete_fixed_salary_structure_fails_explicitly(payroll_client):
    client, sessions = payroll_client
    with sessions() as db:
        db.query(SalaryStructure).filter_by(
            employee_id="T1",
            component_id="HRA",
        ).delete()
        db.commit()
    response = client.post("/payroll/calculate", json=payload())
    assert response.status_code == 422
    assert "Missing fixed salary component" in response.json()["detail"]


def test_partial_month_employment_is_prorated(payroll_client):
    client, sessions = payroll_client
    with sessions() as db:
        db.get(Employee, "T3").hire_date = date(2025, 4, 15)
        db.commit()
    result = client.post(
        "/payroll/calculate",
        json=payload(
            employee_id="T3",
            variable_pay="0",
            variable_pay_type=None,
            tds="0",
            other_deductions="0",
        ),
    ).json()
    assert result["days_employed"] == 16
    assert Decimal(result["earned_fixed_pay"]) == Decimal("16000")


def test_partial_month_leaver_uses_salary_and_assignment_on_exit_date(
    payroll_client,
):
    client, sessions = payroll_client
    with sessions() as db:
        employee = db.get(Employee, "T3")
        employee.exit_date = date(2025, 4, 15)
        assignment = db.query(EmployeeAssignment).filter_by(
            employee_id="T3"
        ).one()
        assignment.effective_to = date(2025, 4, 15)
        for structure in db.query(SalaryStructure).filter_by(
            employee_id="T3"
        ):
            structure.effective_to = date(2025, 4, 15)
        db.commit()
    result = client.post(
        "/payroll/calculate",
        json=payload(
            employee_id="T3",
            variable_pay="0",
            variable_pay_type=None,
            tds="0",
            other_deductions="0",
        ),
    ).json()
    assert result["days_employed"] == 15
    assert result["department_id"] == "D01"
    assert Decimal(result["earned_fixed_pay"]) == Decimal("15000")


def test_duplicate_attendance_date_fails_explicitly(payroll_client):
    client, sessions = payroll_client
    with sessions() as db:
        original = db.query(Attendance).filter_by(
            employee_id="T1",
            attendance_date=date(2025, 4, 1),
        ).one()
        db.add(
            Attendance(
                attendance_id="A-DUPLICATE",
                employee_id="T1",
                attendance_date=original.attendance_date,
                weekday=original.weekday,
                status="PRESENT",
                leave_type_code=None,
                check_in=None,
                check_out=None,
                hours_worked=Decimal("8"),
                overtime_hours=Decimal("0"),
                late_flag="N",
                source="test",
                data_quality_flag=None,
                department_id="D01",
            )
        )
        db.commit()
    response = client.post("/payroll/calculate", json=payload())
    assert response.status_code == 422
    assert "Duplicate attendance" in response.json()["detail"]


def test_invalid_period_and_unknown_employee_are_rejected(payroll_client):
    client, _ = payroll_client
    invalid_period = client.post(
        "/payroll/calculate",
        json=payload(period_end="2025-05-01"),
    )
    unknown_employee = client.post(
        "/payroll/calculate",
        json=payload(employee_id="UNKNOWN"),
    )
    assert invalid_period.status_code == 422
    assert unknown_employee.status_code == 404


def test_salary_revision_effective_on_period_end_is_selected(payroll_client):
    client, sessions = payroll_client
    with sessions() as db:
        for attendance in db.query(Attendance).filter_by(employee_id="T1"):
            attendance.overtime_hours = Decimal("1")
        db.add(
            SalaryRevision(
                revision_id="SR-T1-NEW",
                employee_id="T1",
                effective_from=date(2025, 4, 1),
                revision_reason="Annual Increment",
                previous_annual_fixed=Decimal("360000"),
                new_annual_fixed=Decimal("480000"),
                pct_change=Decimal("33.333"),
                role_id_after="R02",
                approved_by=None,
                created_at=datetime(2025, 4, 1),
            )
        )
        for component_id, amount in [
            ("BASIC", "16000"),
            ("HRA", "8000"),
            ("CONV", "1600"),
            ("MED", "1250"),
            ("SPECIAL", "13150"),
        ]:
            db.add(
                SalaryStructure(
                    structure_id=f"SS-T1-NEW-{component_id}",
                    employee_id="T1",
                    component_id=component_id,
                    component_name=component_id,
                    component_type="EARNING",
                    monthly_amount=Decimal(amount),
                    effective_from=date(2025, 4, 1),
                    effective_to=None,
                    revision_id="SR-T1-NEW",
                )
            )
        db.query(EmployeeAssignment).filter_by(
            employee_id="T1"
        ).one().role_id = "R02"
        db.commit()

    result = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    ).json()
    assert Decimal(result["monthly_fixed_gross"]) == Decimal("40000")
    assert Decimal(result["basic"]) == Decimal("16000")
    assert Decimal(result["pf_employee"]) == Decimal("1800")
    assert Decimal(result["overtime_pay"]) == 0


def test_effective_assignment_controls_payroll_role(payroll_client):
    client, sessions = payroll_client
    with sessions() as db:
        db.query(EmployeeAssignment).filter_by(
            employee_id="T1"
        ).one().role_id = "R02"
        for attendance in db.query(Attendance).filter_by(employee_id="T1"):
            attendance.overtime_hours = Decimal("1")
        db.commit()
    result = client.post(
        "/payroll/calculate",
        json=payload(variable_pay="0", variable_pay_type=None),
    ).json()
    assert result["role_id"] == "R02"
    assert Decimal(result["overtime_pay"]) == 0


def test_mid_period_salary_revision_is_not_silently_prorated(payroll_client):
    client, sessions = payroll_client
    with sessions() as db:
        db.add(
            SalaryRevision(
                revision_id="SR-T1-MID",
                employee_id="T1",
                effective_from=date(2025, 4, 15),
                revision_reason="Mid-month change",
                previous_annual_fixed=Decimal("360000"),
                new_annual_fixed=Decimal("420000"),
                pct_change=Decimal("16.667"),
                role_id_after="R01",
                approved_by=None,
                created_at=datetime(2025, 4, 15),
            )
        )
        db.commit()

    response = client.post("/payroll/calculate", json=payload())
    assert response.status_code == 422
    assert "starts mid-period" in response.json()["detail"]


def test_missing_effective_statutory_rate_fails(payroll_client):
    client, sessions = payroll_client
    with sessions() as db:
        db.execute(
            text(
                "DELETE FROM statutory_rates "
                "WHERE parameter = 'PF_EMPLOYEE_RATE'"
            )
        )
        db.commit()
    response = client.post(
        "/payroll/calculate",
        json=payload(),
    )
    assert response.status_code == 422
    assert "Missing effective statutory rate" in response.json()["detail"]


def _write_batch_inputs(data_dir, *, include_inputs):
    (data_dir / "payroll_runs.csv").write_text(
        "run_id,period_start,period_end\n"
        "RUN-APR-2025,2025-04-01,2025-04-30\n",
        encoding="utf-8",
    )
    (data_dir / "payroll_items.csv").write_text(
        "employee_id,run_id,gross_pay,total_deductions,net_pay\n"
        "T1,RUN-APR-2025,30000.00,1640.00,28360.00\n",
        encoding="utf-8",
    )
    if include_inputs:
        (data_dir / "payroll_inputs.csv").write_text(
            "employee_id,run_id,variable_pay,variable_pay_type,tds,"
            "other_deductions,source_reference\n"
            "T1,RUN-APR-2025,0,,0,0,approved-test-source\n",
            encoding="utf-8",
        )


def test_batch_validation_calculates_only_rows_with_independent_inputs(
    payroll_client,
    tmp_path,
):
    _client, sessions = payroll_client
    data_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    _write_batch_inputs(data_dir, include_inputs=True)

    with sessions() as db:
        summary = run_batch_validation(
            db,
            data_dir=data_dir,
            output_dir=output_dir,
        )

    assert summary["processed"] == 3
    assert summary["successful"] == 1
    assert summary["skipped"] == 2
    assert summary["errors"] == 0
    assert summary["comparison"]["matched"] == 1
    assert (output_dir / "payroll_results.csv").read_text(
        encoding="utf-8"
    ).splitlines() == [
        "employee_id,run_id,gross_pay,total_deductions,net_pay",
        "T1,RUN-APR-2025,30000.00,1640.00,28360.00",
    ]
    exception_rows = (output_dir / "payroll_exceptions.csv").read_text(
        encoding="utf-8"
    ).splitlines()
    assert exception_rows[0] == "employee_id,run_id,reason"
    assert len(exception_rows) == 3
    assert all(
        "Missing independent payroll input record" in row
        for row in exception_rows[1:]
    )
    assert (output_dir / "payroll_comparison.csv").read_text(
        encoding="utf-8"
    ).splitlines()[1].split(",")[3] == "MATCH"


def test_batch_validation_does_not_assume_missing_inputs_are_zero(
    payroll_client,
    tmp_path,
):
    _client, sessions = payroll_client
    data_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    _write_batch_inputs(data_dir, include_inputs=False)

    with sessions() as db:
        summary = run_batch_validation(
            db,
            data_dir=data_dir,
            output_dir=output_dir,
        )

    assert summary["processed"] == 3
    assert summary["successful"] == 0
    assert summary["skipped"] == 3
    assert summary["errors"] == 0
    assert len(
        (output_dir / "payroll_results.csv").read_text(
            encoding="utf-8"
        ).splitlines()
    ) == 1
    reasons = (output_dir / "payroll_exceptions.csv").read_text(
        encoding="utf-8"
    )
    assert "cannot be inferred" in reasons


def test_batch_validation_skips_sample_statutory_policy(
    payroll_client,
    tmp_path,
):
    _client, sessions = payroll_client
    data_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    _write_batch_inputs(data_dir, include_inputs=True)

    with sessions() as db:
        db.execute(
            text(
                "UPDATE statutory_rates SET note = "
                "'SAMPLE training policy' "
                "WHERE parameter = 'PF_EMPLOYEE_RATE'"
            )
        )
        db.commit()
        summary = run_batch_validation(
            db,
            data_dir=data_dir,
            output_dir=output_dir,
        )

    assert summary["processed"] == 3
    assert summary["successful"] == 0
    assert summary["skipped"] == 3
    exceptions = (output_dir / "payroll_exceptions.csv").read_text(
        encoding="utf-8"
    )
    assert "sample/training" in exceptions
