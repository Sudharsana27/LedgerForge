import csv
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import (
    Column,
    Date,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
)
from sqlalchemy.orm import sessionmaker

from app.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.database import Base, get_db
from app.main import app
from app.models import (
    Attendance,
    Department,
    Employee,
    EmployeeAssignment,
    Role,
    SalaryComponent,
    SalaryRevision,
    SalaryStructure,
)
from app.payslip_service import (
    PayslipResult,
    build_payslip_result,
    format_inr,
)


SOURCE_CASES = (
    ("PI-000151", "PR-2025-04", "EMP-0294"),
    ("PI-000193", "PR-2025-04", "EMP-0365"),
    ("PI-000014", "PR-2025-04", "EMP-0031"),
)
PERIOD_START = date(2025, 4, 1)
PERIOD_END = date(2025, 4, 30)


@lru_cache(maxsize=12)
def _read_csv(data_dir: Path, name: str) -> list[dict[str, str]]:
    with (data_dir / f"{name}.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as source:
        return list(csv.DictReader(source))


def _as_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _decimal(value: str) -> Decimal | None:
    return Decimal(value) if value else None


def _source_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "03_Data" / "csv"


@pytest.fixture
def payslip_client(tmp_path):
    data_dir = _source_data_dir()
    required_files = (
        "employees.csv",
        "employee_assignments.csv",
        "salary_components.csv",
        "salary_revisions.csv",
        "salary_structures.csv",
        "attendance.csv",
        "statutory_rates.csv",
        "payroll_runs.csv",
        "payroll_items.csv",
        "roles.csv",
        "departments.csv",
    )
    if not all((data_dir / name).is_file() for name in required_files):
        pytest.skip("LF-08 source CSV files are unavailable")

    employee_ids = {case[2] for case in SOURCE_CASES}
    source_employees = {
        row["employee_id"]: row
        for row in _read_csv(data_dir, "employees")
        if row["employee_id"] in employee_ids
    }
    source_assignments = [
        row
        for row in _read_csv(data_dir, "employee_assignments")
        if row["employee_id"] in employee_ids
        and _as_date(row["effective_from"]) <= PERIOD_END
        and (
            _as_date(row["effective_to"]) is None
            or _as_date(row["effective_to"]) >= PERIOD_END
        )
    ]
    source_revisions = [
        row
        for row in _read_csv(data_dir, "salary_revisions")
        if row["employee_id"] in employee_ids
        and _as_date(row["effective_from"]) <= PERIOD_END
    ]
    latest_revision = {}
    for row in source_revisions:
        previous = latest_revision.get(row["employee_id"])
        if previous is None or (
            _as_date(row["effective_from"]),
            row["revision_id"],
        ) > (
            _as_date(previous["effective_from"]),
            previous["revision_id"],
        ):
            latest_revision[row["employee_id"]] = row
    active_revisions = {
        row["revision_id"] for row in latest_revision.values()
    }
    source_structures = [
        row
        for row in _read_csv(data_dir, "salary_structures")
        if row["employee_id"] in employee_ids
        and row["revision_id"] in active_revisions
        and _as_date(row["effective_from"]) <= PERIOD_END
        and (
            _as_date(row["effective_to"]) is None
            or _as_date(row["effective_to"]) >= PERIOD_END
        )
    ]
    source_attendance = [
        row
        for row in _read_csv(data_dir, "attendance")
        if row["employee_id"] in employee_ids
        and PERIOD_START
        <= _as_date(row["attendance_date"])
        <= PERIOD_END
    ]
    source_roles = {
        row["role_id"]: row
        for row in _read_csv(data_dir, "roles")
    }
    role_ids = {
        role_id
        for employee in source_employees.values()
        if (role_id := employee["role_id"])
    }
    role_ids.update(row["role_id"] for row in source_assignments)
    role_ids.update(
        row["role_id_after"] for row in latest_revision.values()
    )
    role_records = {
        role_id: source_roles[role_id] for role_id in role_ids
    }
    department_ids = {
        employee["department_id"] for employee in source_employees.values()
    }
    department_ids.update(row["department_id"] for row in source_assignments)
    department_ids.update(
        row["department_id"] for row in source_attendance
    )
    department_ids.update(
        role["department_id"] for role in role_records.values()
    )
    departments = {
        row["department_id"]: row
        for row in _read_csv(data_dir, "departments")
        if row["department_id"] in department_ids
    }
    source_components = {
        row["component_id"]: row
        for row in _read_csv(data_dir, "salary_components")
    }
    component_ids = {row["component_id"] for row in source_structures}
    source_run = next(
        row
        for row in _read_csv(data_dir, "payroll_runs")
        if row["run_id"] == "PR-2025-04"
    )
    source_items = {
        row["employee_id"]: row
        for row in _read_csv(data_dir, "payroll_items")
        if row["run_id"] == "PR-2025-04"
        and row["employee_id"] in employee_ids
    }

    engine = create_engine(f"sqlite:///{tmp_path / 'payslips.db'}")
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(engine)

    runs = Table(
        "payroll_runs",
        MetaData(),
        Column("run_id", String, primary_key=True),
        Column("period_start", Date, nullable=False),
        Column("period_end", Date, nullable=False),
    )
    items = Table(
        "payroll_items",
        MetaData(),
        Column("payroll_item_id", String, primary_key=True),
        Column("run_id", String, nullable=False),
        Column("employee_id", String, nullable=False),
        Column("variable_pay", Numeric(14, 2), nullable=False),
        Column("variable_pay_type", String, nullable=True),
        Column("tds", Numeric(14, 2), nullable=False),
        Column("other_deductions", Numeric(14, 2), nullable=False),
    )
    rates = Table(
        "statutory_rates",
        MetaData(),
        Column("parameter", String, primary_key=True),
        Column("value", Numeric(12, 4), nullable=False),
        Column("unit", String, nullable=False),
        Column("note", String, nullable=False),
        Column("effective_from", Date, primary_key=True),
    )
    runs.create(engine)
    items.create(engine)
    rates.create(engine)

    with session_factory() as db:
        db.add_all(
            Department(
                department_id=row["department_id"],
                department_name=row["department_name"],
                cost_center=row["cost_center"],
                description=row["description"] or None,
            )
            for row in departments.values()
        )
        db.flush()
        db.add_all(
            Role(
                role_id=row["role_id"],
                department_id=row["department_id"],
                role_title=row["role_title"],
                level=int(row["level"]),
                grade=row["grade"],
                band_min_annual=int(row["band_min_annual"]),
                band_mid_annual=int(row["band_mid_annual"]),
                band_max_annual=int(row["band_max_annual"]),
                overtime_eligible=row["overtime_eligible"],
                band_year=int(row["band_year"]),
            )
            for row in role_records.values()
        )
        db.flush()
        for row in source_employees.values():
            db.add(
                Employee(
                    employee_id=row["employee_id"],
                    first_name=row["first_name"],
                    last_name=row["last_name"],
                    full_name=row["full_name"],
                    work_email=row["work_email"],
                    gender=row["gender"] or None,
                    date_of_birth=_as_date(row["date_of_birth"]),
                    hire_date=_as_date(row["hire_date"]),
                    exit_date=_as_date(row["exit_date"]),
                    employment_status=row["employment_status"],
                    employment_type=row["employment_type"],
                    department_id=row["department_id"],
                    role_id=row["role_id"],
                    manager_id=None,
                    work_location=row["work_location"],
                    work_mode=row["work_mode"],
                    highest_education=row["highest_education"] or None,
                    prior_experience_years=_decimal(
                        row["prior_experience_years"]
                    ),
                    career_gap_months=int(row["career_gap_months"])
                    if row["career_gap_months"]
                    else None,
                    commute_distance_km=_decimal(
                        row["commute_distance_km"]
                    ),
                    pf_applicable=row["pf_applicable"],
                    esi_applicable=row["esi_applicable"],
                    notice_period_days=int(row["notice_period_days"]),
                    resignation_date=_as_date(row["resignation_date"]),
                    exit_type=row["exit_type"] or None,
                    exit_reason=row["exit_reason"] or None,
                    created_at=_as_date(row["created_at"]),
                )
            )
        db.flush()
        db.add_all(
            SalaryComponent(
                component_id=row["component_id"],
                component_name=row["component_name"],
                component_type=row["component_type"],
                taxable=row["taxable"],
                calculation_rule=row["calculation_rule"],
                is_fixed=row["is_fixed"],
            )
            for key, row in source_components.items()
            if key in component_ids
        )
        db.flush()
        db.add_all(
            SalaryRevision(
                revision_id=row["revision_id"],
                employee_id=row["employee_id"],
                effective_from=_as_date(row["effective_from"]),
                revision_reason=row["revision_reason"],
                previous_annual_fixed=_decimal(
                    row["previous_annual_fixed"]
                ),
                new_annual_fixed=Decimal(row["new_annual_fixed"]),
                pct_change=_decimal(row["pct_change"]),
                role_id_after=row["role_id_after"],
                approved_by=row["approved_by"] or None,
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in latest_revision.values()
        )
        db.flush()
        db.add_all(
            SalaryStructure(
                structure_id=row["structure_id"],
                employee_id=row["employee_id"],
                component_id=row["component_id"],
                component_name=row["component_name"],
                component_type=row["component_type"],
                monthly_amount=Decimal(row["monthly_amount"]),
                effective_from=_as_date(row["effective_from"]),
                effective_to=_as_date(row["effective_to"]),
                revision_id=row["revision_id"],
            )
            for row in source_structures
        )
        db.add_all(
            EmployeeAssignment(
                assignment_id=row["assignment_id"],
                employee_id=row["employee_id"],
                effective_from=_as_date(row["effective_from"]),
                effective_to=_as_date(row["effective_to"]),
                department_id=row["department_id"],
                role_id=row["role_id"],
                job_level=int(row["job_level"]),
                manager_id=None,
                change_reason=row["change_reason"],
            )
            for row in source_assignments
        )
        db.add_all(
            Attendance(
                attendance_id=row["attendance_id"],
                employee_id=row["employee_id"],
                attendance_date=_as_date(row["attendance_date"]),
                weekday=row["weekday"],
                status=row["status"],
                leave_type_code=None,
                check_in=row["check_in"] or None,
                check_out=row["check_out"] or None,
                hours_worked=_decimal(row["hours_worked"]),
                overtime_hours=_decimal(row["overtime_hours"]),
                late_flag=row["late_flag"] or None,
                source=row["source"],
                data_quality_flag=row["data_quality_flag"] or None,
                department_id=row["department_id"],
            )
            for row in source_attendance
        )
        db.commit()

    with engine.begin() as connection:
        connection.execute(
            runs.insert().values(
                run_id=source_run["run_id"],
                period_start=_as_date(source_run["period_start"]),
                period_end=_as_date(source_run["period_end"]),
            )
        )
        connection.execute(
            rates.insert(),
            [
                {
                    "parameter": row["parameter"],
                    "value": Decimal(row["value"]),
                    "unit": row["unit"],
                    "note": row["note"],
                    "effective_from": _as_date(row["effective_from"]),
                }
                for row in _read_csv(data_dir, "statutory_rates")
            ],
        )
        connection.execute(
            items.insert(),
            [
                {
                    "payroll_item_id": item["payroll_item_id"],
                    "run_id": item["run_id"],
                    "employee_id": item["employee_id"],
                    "variable_pay": Decimal(item["variable_pay"] or "0"),
                    "variable_pay_type": item["variable_pay_type"] or None,
                    "tds": Decimal(item["tds"] or "0"),
                    "other_deductions": Decimal(
                        item["other_deductions"] or "0"
                    ),
                }
                for item in source_items.values()
            ],
        )

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), session_factory, source_items
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        runs.drop(engine)
        items.drop(engine)
        rates.drop(engine)
        engine.dispose()


def _authorize_as(client: TestClient, principal: AuthenticatedPrincipal):
    app.dependency_overrides[get_authenticated_principal] = lambda: principal
    return client


def test_format_inr_uses_indian_grouping():
    assert format_inr(Decimal("123456.00")) == "₹1,23,456.00"
    assert format_inr(Decimal("1234.5")) == "₹1,234.50"
    assert format_inr(Decimal("0.005")) == "₹0.01"
    assert format_inr(Decimal("-1234567.89")) == "-₹12,34,567.89"


def test_payslip_data_is_typed_and_uses_calculation_totals(payslip_client):
    _, session_factory, _ = payslip_client
    with session_factory() as db:
        result = build_payslip_result(
            db,
            employee_id="EMP-0294",
            run_id="PR-2025-04",
        )

    assert isinstance(result, PayslipResult)
    assert result.run_id == "PR-2025-04"
    assert result.period_start == PERIOD_START
    assert result.period_end == PERIOD_END
    assert sum(line.amount for line in result.earnings) == (
        result.figures.gross_pay
    )
    assert sum(line.amount for line in result.deductions) == (
        result.figures.total_deductions
    )
    assert result.figures.net_pay == (
        result.figures.gross_pay - result.figures.total_deductions
    )


@pytest.mark.parametrize(
    ("item_id", "run_id", "employee_id"),
    SOURCE_CASES,
)
def test_owner_can_get_valid_pdf_with_engine_totals(
    payslip_client,
    item_id,
    run_id,
    employee_id,
):
    client, session_factory, source_items = payslip_client
    reference = source_items[employee_id]
    assert Decimal(reference["variable_pay"] or "0") == Decimal("0")
    assert Decimal(reference["tds"] or "0") == Decimal("0")
    assert Decimal(reference["other_deductions"] or "0") == Decimal("0")
    assert reference["variable_pay_type"] in ("", None)

    client = _authorize_as(
        client,
        AuthenticatedPrincipal(employee_id=employee_id, role="EMPLOYEE"),
    )
    response = client.get(f"/payslips/{employee_id}/{run_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert item_id.encode() not in response.content

    from pypdf import PdfReader

    from io import BytesIO

    pdf = PdfReader(BytesIO(response.content))
    assert len(pdf.pages) == 1
    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    with session_factory() as db:
        employee = db.get(Employee, employee_id)

    assert "Zenith Nova Technologies" in text
    assert employee_id in text
    assert employee.full_name in text
    assert "".join(employee.work_email.split()) in "".join(text.split())
    assert employee.work_location in text
    assert "Earnings" in text
    assert "Deductions" in text
    assert "Gross salary" in text
    assert "Total deductions" in text
    assert "NET PAY" in text
    for field in (
        "basic",
        "hra",
        "conveyance",
        "medical",
        "special_allowance",
        "overtime_pay",
        "variable_pay",
        "gross_pay",
        "pf_employee",
        "esi_employee",
        "professional_tax",
        "tds",
        "other_deductions",
        "total_deductions",
        "net_pay",
    ):
        assert format_inr(Decimal(reference[field] or "0")) in text

    net_font_sizes = []

    def collect_net_font_size(text_piece, *callback_data):
        if format_inr(Decimal(reference["net_pay"])) in text_piece:
            net_font_sizes.append(callback_data[-1])

    pdf.pages[0].extract_text(visitor_text=collect_net_font_size)
    assert net_font_sizes
    assert max(net_font_sizes) >= 20


def test_hr_can_get_employee_payslip(payslip_client):
    client, _, _ = payslip_client
    client = _authorize_as(
        client,
        AuthenticatedPrincipal(employee_id="EMP-0999", role="HR"),
    )
    response = client.get("/payslips/EMP-0294/PR-2025-04")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")


def test_stranger_is_refused(payslip_client):
    client, _, _ = payslip_client
    client = _authorize_as(
        client,
        AuthenticatedPrincipal(employee_id="EMP-0999", role="EMPLOYEE"),
    )
    response = client.get("/payslips/EMP-0294/PR-2025-04")
    assert response.status_code == 403


def test_admin_is_not_implicitly_hr(payslip_client):
    client, _, _ = payslip_client
    client = _authorize_as(
        client,
        AuthenticatedPrincipal(employee_id="EMP-0999", role="ADMIN"),
    )
    response = client.get("/payslips/EMP-0294/PR-2025-04")
    assert response.status_code == 403


def test_unauthenticated_request_is_refused(payslip_client):
    client, _, _ = payslip_client
    response = client.get(
        "/payslips/EMP-0294/PR-2025-04",
        headers={"X-Employee-ID": "EMP-0294", "X-Role": "HR"},
    )
    assert response.status_code == 401


def test_employee_not_in_run_is_not_found(payslip_client):
    client, _, _ = payslip_client
    client = _authorize_as(
        client,
        AuthenticatedPrincipal(employee_id="EMP-0001", role="EMPLOYEE"),
    )
    response = client.get("/payslips/EMP-0001/PR-2025-04")
    assert response.status_code == 404


def test_run_without_independent_payroll_inputs_is_unavailable(
    payslip_client,
):
    client, session_factory, _ = payslip_client
    with session_factory() as db:
        bind = db.get_bind()
        runs = Table("payroll_runs", MetaData(), autoload_with=bind)
        items = Table("payroll_items", MetaData(), autoload_with=bind)
        with bind.begin() as connection:
            connection.execute(
                runs.insert().values(
                    run_id="PR-2025-05",
                    period_start=date(2025, 5, 1),
                    period_end=date(2025, 5, 31),
                )
            )
            connection.execute(
                items.insert().values(
                    payroll_item_id="PI-TEST-MISSING-INPUTS",
                    run_id="PR-2025-05",
                    employee_id="EMP-0294",
                    variable_pay=Decimal("100"),
                    variable_pay_type="Performance Bonus",
                    tds=Decimal("0"),
                    other_deductions=Decimal("0"),
                )
            )
    client = _authorize_as(
        client,
        AuthenticatedPrincipal(employee_id="EMP-0294", role="EMPLOYEE"),
    )
    response = client.get("/payslips/EMP-0294/PR-2025-05")
    assert response.status_code == 503
    assert "Independent variable-pay" in response.json()["detail"]
